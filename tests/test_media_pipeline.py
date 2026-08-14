from creator_delivery.media_pipeline import plan_delivery


def test_short_video_delivery_stays_brief_and_uses_default_voice() -> None:
    short = plan_delivery("short_video")
    podcast = plan_delivery("podcast")

    assert short.max_words == 75
    assert short.max_words < podcast.max_words
    assert short.voice == "alloy"
