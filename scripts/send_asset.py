import argparse
import os

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a transcript asset for creator delivery")
    parser.add_argument("transcript", help="Path to a UTF-8 transcript")
    parser.add_argument("--title", required=True)
    parser.add_argument("--channel", choices=["short_video", "podcast"], default="short_video")
    parser.add_argument("--output", default="delivery.mp3")
    args = parser.parse_args()

    with open(args.transcript, encoding="utf-8") as source:
        transcript = source.read()

    response = httpx.request(
        method="POST",
        url=os.environ.get("DELIVERY_SERVICE_URL", "http://127.0.0.1:8000/deliveries"),
        json={"title": args.title, "transcript": transcript, "channel": args.channel},
        timeout=120,
    )
    response.raise_for_status()
    with open(args.output, "wb") as target:
        target.write(response.content)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
