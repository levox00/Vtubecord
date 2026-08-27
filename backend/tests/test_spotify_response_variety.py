import asyncio

from app.api.routes import (
    _natural_spotify_confirmation,
    _spotify_response_is_repetitive,
    _varied_spotify_status_fallback,
)
from app.llm.base import ChatMessage, LLMResponse


def _status_result(title: str = "Sailor Song") -> dict[str, object]:
    return {
        "is_playing": True,
        "item": {
            "name": title,
            "artists": ["Gigi Perez"],
            "album": "At The Beach, In Every Life",
        },
    }


def test_spotify_variety_guard_rejects_stock_music_filler_and_repeated_openings():
    recent = ["Right now, Spotify has Little Angel by Onokami playing."]

    assert _spotify_response_is_repetitive(
        "Oh, it looks like we're still grooving to Sailor Song by Gigi Perez!",
        recent,
    )
    assert _spotify_response_is_repetitive(
        "Right now, Spotify has Sailor Song by Gigi Perez playing.",
        recent,
    )
    assert not _spotify_response_is_repetitive(
        "On now: Sailor Song — Gigi Perez.",
        recent,
    )


def test_spotify_status_fallback_rotates_away_from_recent_wording():
    first = _varied_spotify_status_fallback([], _status_result(), model="local-model")
    assert first is not None
    second = _varied_spotify_status_fallback(
        [ChatMessage(role="assistant", content=first.content)],
        _status_result("Little Angel"),
        model="local-model",
    )

    assert second is not None
    assert second.content != first.content
    assert "Little Angel" in second.content
    assert "Gigi Perez" in second.content
    assert not _spotify_response_is_repetitive(second.content, [first.content])


class _RetryingLLM:
    model_name = "Mistral-NeMo-test"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    async def generate(self, _messages):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return LLMResponse(content=reply, model=self.model_name, finish_reason="stop")


def test_natural_spotify_confirmation_retries_repetitive_draft():
    llm = _RetryingLLM(
        [
            "Oh, it looks like we're currently enjoying Sailor Song by Gigi Perez!",
            "On now: Sailor Song — Gigi Perez.",
        ]
    )
    response = asyncio.run(
        _natural_spotify_confirmation(
            llm,
            [ChatMessage(role="user", content="What song is playing?")],
            "status",
            {},
            _status_result(),
            None,
        )
    )

    assert llm.calls == 2
    assert response is not None
    assert response.content == "On now: Sailor Song — Gigi Perez."


def test_natural_spotify_confirmation_uses_varied_grounded_fallback_after_two_rejections():
    llm = _RetryingLLM(
        ["Oh, it looks like we're still grooving to Sailor Song by Gigi Perez!"]
    )
    response = asyncio.run(
        _natural_spotify_confirmation(
            llm,
            [
                ChatMessage(role="user", content="What was playing before?"),
                ChatMessage(role="assistant", content="Now playing: Little Angel by Onokami."),
                ChatMessage(role="user", content="And what is playing now?"),
            ],
            "status",
            {},
            _status_result(),
            None,
        )
    )

    assert llm.calls == 2
    assert response is not None
    assert "Sailor Song" in response.content
    assert "Gigi Perez" in response.content
    assert "Oh, it looks like" not in response.content
    assert not response.content.startswith("Now playing:")
