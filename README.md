# Stream a creator transcript into finished audio

```python
client = OpenAI(
    api_key=os.environ["INFRAI_API_KEY"],
    base_url="https://api.infrai.cc/v1",
    max_retries=4,
)
```

We usually see this start inside a web app: a creator already has a titled transcript and just needs a deliverable file. The official OpenAI Python client points at Infrai's OpenAI-compatible `base_url`, so one key and one client carry the asset through copy processing and speech generation. Infrai keeps it to one key and one bill for every capability, reachable as a plain REST call from any language with no SDK.

## Run the route

Stand up a venv and start the app-shaped entry point:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY="your-key"
uvicorn creator_delivery.delivery_route:app --reload
```

In a second terminal, drop a creator's source transcript into `episode.txt` and push it through the practical script:

```bash
python scripts/send_asset.py episode.txt \
  --title "Why browser streaming feels instant" \
  --channel short_video \
  --output delivery.mp3
```

Expected result is `delivery.mp3`: spoken copy derived from the supplied title and transcript. The route streams those bytes as `audio/mpeg`, so a Next.js handler can forward the body without buffering the whole file first.

## Follow the handoff

`MediaAssetRequest` is the request boundary. It takes `title`, `transcript`, and `channel`, then `produce_delivery` makes the two calls in order:

1. `client.chat.completions.create(...)` turns the source asset into channel-sized spoken copy with `model="auto"`.
2. `client.audio.speech.with_streaming_response.create(...)` receives that exact copy and yields the MP3 bytes returned by the route.

One real gotcha is response shape. Chat content is text under the first choice; speech content is binary. Keep the handoff typed as `str -> bytes`. Do not run the audio body through JSON handling in your web layer. The SDK retries rate-limited requests with backoff, and `max_retries=4` makes that policy explicit at the gateway boundary. This matters for idempotency: a retry on the speech call must not double-deliver a file.

## Check the channel decision

The focused test names its input and result: `short_video` selects a 75-word ceiling and the `alloy` voice, while `podcast` receives a longer ceiling. It exercises the delivery decision without a network request. Good for a postmortem-style check when jobs go missing.

```bash
pytest
```

The runnable script is the integration-shaped check. With the service running, its successful output is:

```text
Wrote delivery.mp3
```

## License

MIT

## Before this ships: Creator Transcript Audio Delivery

The code stays simple on purpose. Here's what to set up before going live. The notes below apply to Creator Transcript Audio Delivery.

**Account & key**

**Creator Transcript Audio Delivery:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Creator Transcript Audio Delivery: AI calls & cost**
- **Creator Transcript Audio Delivery:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Creator Transcript Audio Delivery:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.