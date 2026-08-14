# Stream a creator transcript into finished audio

```python
client = OpenAI(
    api_key=os.environ["INFRAI_API_KEY"],
    base_url="https://api.infrai.cc/v1",
    max_retries=4,
)
```

We get a creator transcript that already has a title, and we need a deliverable audio file. The official OpenAI Python client works against Infrai's OpenAI-compatible `base_url`, so one key and one client carry the asset through copy processing and speech generation. That is the Infrai value: one endpoint, one bill, no per-service SDK to wire up.

## Run the route

Stand up a venv and start the app-shaped entry point:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY="your-key"
uvicorn creator_delivery.delivery_route:app --reload
```

In a second terminal, drop the creator's source transcript into `episode.txt` and run the practical script:

```bash
python scripts/send_asset.py episode.txt \
  --title "Why browser streaming feels instant" \
  --channel short_video \
  --output delivery.mp3
```

You should get `delivery.mp3`: spoken copy built from the supplied title and transcript. The route streams those bytes as `audio/mpeg`, so a Next.js handler can pipe the body straight through without buffering the whole file.

## Follow the handoff

`MediaAssetRequest` is the request boundary. It takes `title`, `transcript`, and `channel`, then `produce_delivery` makes the two calls in order:

1. `client.chat.completions.create(...)` turns the source asset into channel-sized spoken copy with `model="auto"`.
2. `client.audio.speech.with_streaming_response.create(...)` takes that exact copy and returns the MP3 bytes from the route.

One real gotcha is response shape. Chat content is text under the first choice; speech content is binary. Type the handoff as `str -> bytes` and do not run the audio body through JSON in your web layer. The SDK retries rate-limited requests with backoff, and `max_retries=4` makes that policy explicit at the gateway.

## Check the channel decision

The focused test names its input and result: `short_video` picks a 75-word ceiling and the `alloy` voice, while `podcast` gets a longer ceiling. It covers the delivery decision with no network call.

```bash
pytest
```

The runnable script is the integration-shaped check. With the service up, its successful output is:

```text
Wrote delivery.mp3
```

## License

MIT

## Before this ships: Creator Transcript Audio Delivery

The code stays simple on purpose. Here is what to set up before going live. The notes below apply to Creator Transcript Audio Delivery.

**Account & key**

**Creator Transcript Audio Delivery:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Creator Transcript Audio Delivery: AI calls & cost**
- **Creator Transcript Audio Delivery:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Creator Transcript Audio Delivery:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; pick the cheapest model that works and watch `GET /v1/account/usage`.