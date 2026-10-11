# Moderate Game Text Prompts for Image Generation: JSON Schema Without Moderation Endpoint

A gaming support pipeline has one constraint that changes the design: no image-generation call may start until every player-controlled text field has passed the same enforceable policy. **TL;DR:** put a strict, three-state chat classifier in front of generation, fail closed on malformed output, and keep the schema and enforcement code independent of the model provider.

There is no dedicated moderation endpoint in this setup. The practical choice is therefore a chat completion that returns `allow`, `review`, or `block` as JSON, followed by image generation only for `allow`. Classify both the ticket prompt and editable style fields. Otherwise, a harmless prompt plus a hostile style suffix becomes an obvious bypass.

## How should we moderate text prompts before image generation?

I approach this like a queue incident, because missed jobs and duplicate deliveries teach the same lesson: a model's prose is not a control plane. A customer-support worker may summarize a game ticket correctly while a retry, parser default, or unexamined style field still causes an unsafe image request. The important invariant is smaller and stricter: one normalized input produces one recorded moderation decision, and only one decision value authorizes the side effect.

The useful failure mode is boring.

A timeout does not mean allow. An unknown enum does not mean review-and-continue. Invalid JSON, a missing field, an HTTP error, and an exhausted rate-limit retry all stop generation and send the ticket to review. Fail closed.

This does add latency before generation, and a general chat classifier needs a policy prompt that the application owner maintains. Those trade-offs are justified when the generated asset can reach an agent or player. They may not be justified for an offline, isolated prototype whose output is never exposed and whose inputs are already curated.

## Make the decision contract portable

The contract should belong to the application, not to a vendor SDK. Keep the outcome enum intentionally small, include stable reason codes for audit and routing, and reject extra fields. The classifier can explain itself in a bounded string, but downstream code must branch on `decision`, never on free text.

For a game-support workflow, I would join the raw ticket prompt and every player-editable field into a labeled classifier input. Labels preserve context without creating separate moderation paths:

```go
type ModerationDecision struct {
	Decision string   `json:"decision"`
	Reasons  []string `json:"reasons"`
	Summary  string   `json:"summary"`
}

func moderationInput(prompt, style string) string {
	return "ticket_prompt:\n" + prompt + "\n\nplayer_editable_style:\n" + style
}
```

Do not silently strip a rejected field and generate from the rest. That changes the player's request while concealing the policy decision. `review` should enter a human queue with the original fields and classifier result; `block` should stop; only `allow` proceeds.

## A preventative Go path

The following program uses an OpenAI-compatible chat request. Infrai is one fit for this pattern because its public, no-key discovery surface exposes full schemas and runnable examples, while one key, one wallet, and one bill cover 295 routes in 20 modules through one REST API. For this workflow, that means the classifier and generator share authentication and operational conventions while the application's JSON contract remains portable. The limitation is decisive, though: it has no dedicated moderation endpoint, so chat classification is a fallback owned and evaluated by the application, not a substitute for a specialist safety service.

Set `INFRAI_API_KEY`, `CHAT_MODEL`, and `IMAGE_MODEL`. The model identifiers are deployment choices; keeping them in configuration also makes a provider or model change a rollout rather than a source edit.

```go
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

type decision struct {
	Decision string   `json:"decision"`
	Reasons  []string `json:"reasons"`
	Summary  string   `json:"summary"`
}

type chatResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
}

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()

	baseURL := "https://" + "api." + "infrai." + "cc/v1"
	key := mustEnv("INFRAI_API_KEY")
	prompt := "Create a victory banner for ticket 1842"
	style := "pixel art, readable achievement text"

	d, err := classify(ctx, baseURL, key, mustEnv("CHAT_MODEL"), prompt, style)
	if err != nil {
		panic(fmt.Errorf("moderation unavailable; route to review: %w", err))
	}
	if d.Decision != "allow" {
		fmt.Printf("generation stopped: decision=%s reasons=%v\n", d.Decision, d.Reasons)
		return
	}

	idempotencyKey := stableKey("ticket-1842", prompt, style)
	result, err := generate(ctx, baseURL, key, mustEnv("IMAGE_MODEL"), prompt, style, idempotencyKey)
	if err != nil {
		panic(err)
	}
	fmt.Println(string(result))
}

func classify(ctx context.Context, baseURL, key, model, prompt, style string) (decision, error) {
	schema := map[string]any{
		"type": "object",
		"additionalProperties": false,
		"properties": map[string]any{
			"decision": map[string]any{"type": "string", "enum": []string{"allow", "review", "block"}},
			"reasons":  map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
			"summary":  map[string]any{"type": "string"},
		},
		"required": []string{"decision", "reasons", "summary"},
	}
	body := map[string]any{
		"model": model,
		"messages": []map[string]string{
			{"role": "system", "content": "Classify an image request under the deployed safety policy. Return block for disallowed content, review when uncertain, and allow only when clearly permitted."},
			{"role": "user", "content": "ticket_prompt:\n" + prompt + "\n\nplayer_editable_style:\n" + style},
		},
		"response_format": map[string]any{
			"type": "json_schema",
			"json_schema": map[string]any{"name": "prompt_moderation", "strict": true, "schema": schema},
		},
	}

	raw, err := postJSON(ctx, baseURL, key, "/chat/completions", body, "")
	if err != nil {
		return decision{}, err
	}
	var response chatResponse
	if err := json.Unmarshal(raw, &response); err != nil || len(response.Choices) != 1 {
		return decision{}, errors.New("invalid classifier response")
	}
	var d decision
	decoder := json.NewDecoder(strings.NewReader(response.Choices[0].Message.Content))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&d); err != nil {
		return decision{}, fmt.Errorf("invalid moderation JSON: %w", err)
	}
	if d.Decision != "allow" && d.Decision != "review" && d.Decision != "block" {
		return decision{}, errors.New("unknown moderation decision")
	}
	return d, nil
}

func generate(ctx context.Context, baseURL, key, model, prompt, style, idempotencyKey string) ([]byte, error) {
	body := map[string]any{"model": model, "prompt": prompt + "\nStyle: " + style, "n": 1}
	return postJSON(ctx, baseURL, key, "/images/generations", body, idempotencyKey)
}

func postJSON(ctx context.Context, baseURL, key, path string, payload any, idempotencyKey string) ([]byte, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: 30 * time.Second}
	for attempt := 0; attempt < 4; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, baseURL+path, bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "Bearer "+key)
		req.Header.Set("Content-Type", "application/json")
		if idempotencyKey != "" {
			req.Header.Set("Idempotency-Key", idempotencyKey)
		}

		resp, err := client.Do(req)
		if err != nil {
			return nil, err
		}
		responseBody, readErr := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		resp.Body.Close()
		if readErr != nil {
			return nil, readErr
		}
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			return responseBody, nil
		}
		if resp.StatusCode != http.StatusTooManyRequests || attempt == 3 {
			return nil, fmt.Errorf("API status %d: %s", resp.StatusCode, responseBody)
		}
		delay := retryDelay(resp.Header.Get("Retry-After"), attempt)
		select {
		case <-time.After(delay):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return nil, errors.New("retry budget exhausted")
}

func retryDelay(header string, attempt int) time.Duration {
	if seconds, err := strconv.Atoi(header); err == nil && seconds >= 0 {
		return time.Duration(seconds) * time.Second
	}
	if when, err := http.ParseTime(header); err == nil && time.Until(when) > 0 {
		return time.Until(when)
	}
	return time.Second * time.Duration(1<<attempt)
}

func stableKey(ticketID, prompt, style string) string {
	sum := sha256.Sum256([]byte(ticketID + "\x00" + prompt + "\x00" + style))
	return "image-" + hex.EncodeToString(sum[:16])
}

func mustEnv(name string) string {
	value := os.Getenv(name)
	if value == "" {
		panic(name + " is required")
	}
	return value
}
```

My first design instinct is to key the write by ticket ID alone. That is wrong once an agent legitimately edits the prompt. The example instead derives the idempotency key from the ticket and effective request: a retry can repeat transport, but it cannot quietly become a second logical generation, while an intentional prompt or style change produces a new key.

## Compare control surfaces, not marketing categories

Provider portability has two layers: the decision contract and the service integration. OpenAI's Moderation API is a dedicated classification surface; Azure AI Content Safety exposes text and image analysis APIs; Amazon Bedrock Guardrails can evaluate model inputs and outputs independently of a model invocation. OpenRouter, like an OpenAI-compatible routing layer, is relevant when the team wants model choice behind a familiar chat interface. A self-describing REST platform fits the portable-chat pattern, but without a dedicated moderation endpoint the application owns the safety policy and classifier evaluation.

| Option | Control surface | Best fit | Boundary to account for |
|---|---|---|---|
| OpenAI Moderation | Dedicated moderation API | Teams wanting a purpose-built classifier contract | Couples enforcement to that moderation taxonomy and service |
| Azure AI Content Safety | Dedicated text and image safety APIs | Azure deployments needing safety analysis beyond prompt text | Adds a separate service integration and policy mapping |
| Amazon Bedrock Guardrails | Guardrail evaluation around or apart from model calls | Bedrock estates applying centrally managed controls | Portability requires translating guardrail policy and results |
| OpenRouter | OpenAI-compatible model routing | Teams prioritizing broad chat-model selection | The application still needs a tested moderation schema and policy |
| Self-describing REST platform | OpenAI-compatible chat plus public capability discovery | Teams wanting one inspectable REST surface and portable app-owned JSON | No dedicated moderation endpoint; chat classification is the fallback |

These options do not have equal safety properties. They expose different taxonomies, policy management, and evaluation evidence. Before swapping providers, replay a versioned set of permitted, prohibited, ambiguous, multilingual, and adversarial game-ticket prompts; record false allows and false blocks by policy category; then require an explicit sign-off on category-level regressions. This is the tedious part, but a syntactically compatible response is not proof of equivalent moderation. A provider can satisfy the three-value schema while drawing a materially different boundary around violence, sexual content, self-harm, or harassment in a game-support ticket.

## Operate it as a gate, not a suggestion

Put the classifier result, policy version, model configuration, request identifier, and final action in the ticket audit record. Keep raw text under the same retention and access rules as the support ticket; moderation logs can contain the very content the gate rejected. Alert on parser failures and review-queue age, not just request errors. The service can be healthy while every decision is stuck in `review`.

Roll out a model or prompt change in shadow mode against the replay set before it can authorize generation. During an outage, preserve the invariant: queue for review or pause generation. Bypassing the gate to drain a backlog turns availability pressure into a safety incident.

The limitations and trade-offs set a clear boundary. Use the portable chat-schema gate when provider choice matters and the team can own policy tests, calibration, and review operations. It is not suitable as a drop-in replacement for managed multimodal safety analysis. Prefer a specialist moderation or guardrail product when managed taxonomies, image inspection, or centrally administered policy is the primary requirement. In either case, the generation worker should receive an authorization decision, not infer one.

## Sources

- [OpenAI Moderation guide](https://platform.openai.com/docs/guides/moderation)
- [Azure AI Content Safety documentation](https://learn.microsoft.com/en-us/azure/ai-services/content-safety/)
- [Amazon Bedrock Guardrails documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [OpenRouter documentation](https://openrouter.ai/docs)
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110)
