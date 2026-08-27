import asyncio
from pathlib import Path

from app.api import routes
from app.schemas.chat import TTSRequest


def test_openrouter_tts_sends_openai_compatible_speech_request(monkeypatch):
    class FakeResponse:
        status_code = 200
        content = b"ID3-openrouter-audio"
        text = ""

        def json(self):
            return {}

    class FakeClient:
        request = None

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, headers, json):
            FakeClient.request = {"url": url, "headers": headers, "json": json}
            return FakeResponse()

        async def get(self, url, *, headers, params):
            FakeClient.request = {"url": url, "headers": headers, "params": params}
            response = FakeResponse()
            response.json = lambda: {
                "total_count": 1,
                "data": [{
                    "id": "fish-audio/s2.1-pro-free:free",
                    "name": "S2.1 Pro Free",
                    "description": "Fish speech",
                    "architecture": {"output_modalities": ["audio"]},
                    "supported_voices": [],
                    "pricing": {"prompt": "0", "completion": "0"},
                }],
            }
            return response

    async def fake_prepare(_engine: str) -> None:
        return None

    monkeypatch.setattr(routes, "_prepare_tts_engine", fake_prepare)
    monkeypatch.setattr(routes.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(routes.settings.tts, "openrouter_model", "fish-audio/s2.1-pro-free:free")
    monkeypatch.setattr(routes.settings.tts, "openrouter_voice", "")
    monkeypatch.setattr(routes.settings.tts, "openrouter_response_format", "mp3")

    audio = asyncio.run(
        routes._tts_openrouter(
            "hello from the hosted voice",
            TTSRequest(text="hello", engine="openrouter"),
        )
    )

    assert audio.data.startswith(b"ID3")
    assert audio.media_type == "audio/mpeg"
    assert audio.filename == "tts-openrouter.mp3"
    assert FakeClient.request["url"].endswith("/audio/speech")
    assert FakeClient.request["headers"]["Authorization"] == "Bearer test-key"
    assert FakeClient.request["json"] == {
        "input": "hello from the hosted voice",
        "model": "fish-audio/s2.1-pro-free:free",
        "response_format": "mp3",
        "speed": 1.0,
    }


def test_openrouter_tts_requires_configured_api_key(monkeypatch):
    async def fake_prepare(_engine: str) -> None:
        return None

    monkeypatch.setattr(routes, "_prepare_tts_engine", fake_prepare)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(routes.settings.tts, "openrouter_api_key_env", "OPENROUTER_API_KEY")

    try:
        asyncio.run(routes._tts_openrouter("hello", TTSRequest(text="hello", engine="openrouter")))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
    else:
        raise AssertionError("OpenRouter TTS unexpectedly ran without an API key")


def test_openrouter_speech_model_search_uses_speech_filter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(routes.settings.tts, "openrouter_api_key_env", "OPENROUTER_API_KEY")

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "total_count": 1,
                "data": [{
                    "id": "fish-audio/s2.1-pro-free:free",
                    "name": "S2.1 Pro Free",
                    "description": "Fish speech",
                    "architecture": {"output_modalities": ["audio"]},
                    "supported_voices": [],
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
    result = asyncio.run(routes.list_openrouter_tts_models("fish-audio", 25))
    assert result["models"][0]["id"] == "fish-audio/s2.1-pro-free:free"
    assert FakeClient.request["params"] == {"output_modalities": "speech", "limit": 25, "q": "fish-audio"}


def test_openrouter_key_save_writes_env_without_returning_secret(monkeypatch):
    env_path = Path(".test-openrouter-key.env")
    env_path.write_text("# existing\nOTHER=value\n", encoding="utf-8")
    monkeypatch.setattr(routes, "_openrouter_env_file", lambda: env_path)
    monkeypatch.setattr(routes.settings.tts, "openrouter_api_key_env", "OPENROUTER_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    try:
        result = asyncio.run(
            routes.save_openrouter_key(
                routes.OpenRouterKeyUpdate(api_key="sk-or-test-secret", env_name="OPENROUTER_API_KEY")
            )
        )
        assert result["configured"] is True
        assert result["masked"].endswith("cret")
        assert "sk-or-test-secret" in env_path.read_text(encoding="utf-8")
        assert "api_key" not in result
    finally:
        env_path.unlink(missing_ok=True)
