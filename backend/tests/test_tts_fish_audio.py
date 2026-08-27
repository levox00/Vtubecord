import asyncio

from app.api import routes


def test_fish_voice_search_uses_title_filter_and_normalizes_ids(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fish-test-key")
    monkeypatch.setattr(routes.settings.tts, "fish_audio_api_key_env", "FISH_AUDIO_API_KEY")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "total": 1,
                "has_more": False,
                "items": [{
                    "_id": "abc123",
                    "title": "Naruto voice",
                    "description": "Anime character voice",
                    "author": {"nickname": "creator"},
                    "tags": ["anime"],
                    "languages": ["en", "ja"],
                    "licensed": True,
                }],
            }

    class FakeClient:
        request = None

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, *, headers, params):
            FakeClient.request = {"url": url, "headers": headers, "params": params}
            return FakeResponse()

    monkeypatch.setattr(routes.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(routes.list_fish_audio_voices("naruto", 1, 20))

    assert result["voices"][0]["id"] == "abc123"
    assert result["voices"][0]["url"].endswith("/abc123")
    assert FakeClient.request["url"].endswith("/model")
    assert FakeClient.request["headers"]["Authorization"] == "Bearer fish-test-key"
    assert FakeClient.request["params"] == {
        "page_number": 1,
        "page_size": 20,
        "sort_by": "score",
        "title": "naruto",
    }


def test_fish_voice_search_requires_fish_key(monkeypatch):
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    monkeypatch.setattr(routes.settings.tts, "fish_audio_api_key_env", "FISH_AUDIO_API_KEY")
    try:
        asyncio.run(routes.list_fish_audio_voices("naruto"))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
    else:
        raise AssertionError("Fish Audio voice search unexpectedly ran without an API key")
