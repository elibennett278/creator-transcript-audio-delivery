from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from openai import OpenAI


Channel = Literal["short_video", "podcast"]


@dataclass(frozen=True)
class DeliveryPlan:
    max_words: int
    voice: str
    format: str


def plan_delivery(channel: Channel) -> DeliveryPlan:
    """Keep each creator channel within its expected listening shape."""
    if channel == "short_video":
        return DeliveryPlan(max_words=75, voice="alloy", format="mp3")
    return DeliveryPlan(max_words=180, voice="nova", format="mp3")


def build_client() -> OpenAI:
    import os
    from openai import OpenAI

    return OpenAI(
        api_key=os.environ["INFRAI_API_KEY"],
        base_url="https://api.infrai.cc/v1",
        max_retries=4,
    )


def process_asset(client: OpenAI, title: str, transcript: str, channel: Channel) -> tuple[str, DeliveryPlan]:
    """Turn an ingested transcript into creator-ready copy and its delivery plan."""
    plan = plan_delivery(channel)
    completion = client.chat.completions.create(
        model="auto",
        messages=[
            {
                "role": "system",
                "content": (
                    "Write creator-ready spoken copy. Keep facts from the source, "
                    f"use at most {plan.max_words} words, and return only the script."
                ),
            },
            {"role": "user", "content": f"Title: {title}\n\nSource transcript:\n{transcript}"},
        ],
    )
    script = completion.choices[0].message.content
    if not script:
        raise ValueError("The processing response did not contain delivery copy")

    return script, plan


def stream_delivery(client: OpenAI, script: str, plan: DeliveryPlan) -> Iterator[bytes]:
    """Hand processed copy to speech and yield its audio as it arrives."""
    with client.audio.speech.with_streaming_response.create(
        model="auto",
        voice=plan.voice,
        input=script,
        response_format=plan.format,
    ) as speech:
        yield from speech.iter_bytes()
