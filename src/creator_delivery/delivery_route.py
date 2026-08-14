from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel, Field

from .media_pipeline import build_client, process_asset, stream_delivery


class MediaAssetRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    transcript: str = Field(min_length=1, max_length=20_000)
    channel: Literal["short_video", "podcast"]


@lru_cache
def gateway_client() -> OpenAI:
    return build_client()


app = FastAPI(title="Creator audio delivery")


@app.post("/deliveries", response_class=StreamingResponse)
def create_delivery(
    asset: MediaAssetRequest,
    client: Annotated[OpenAI, Depends(gateway_client)],
) -> StreamingResponse:
    script, plan = process_asset(client, asset.title, asset.transcript, asset.channel)
    return StreamingResponse(
        stream_delivery(client, script, plan),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'attachment; filename="delivery.mp3"'},
    )
