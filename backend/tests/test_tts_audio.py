import asyncio

from app.api import routes
from app.schemas.chat import TTSRequest


def test_shared_tts_generation_returns_bytes_before_http_wrapping(monkeypatch):
    async def fake_prepare(_engine: str) -> None:
        return None

    async def fake_edge(_text: str, _voice: str | None = None, _req: TTSRequest | None = None):
        return routes.GeneratedAudio(b"RIFF-test", "audio/wav", "tts.wav")

    monkeypatch.setattr(routes, "_prepare_tts_engine", fake_prepare)
    monkeypatch.setattr(routes, "_tts_edge", fake_edge)
    monkeypatch.setattr(routes.settings.tts, "engine", "edge-tts")

    generated = asyncio.run(routes._generate_tts_audio(TTSRequest(text="hello")))
    assert generated.data == b"RIFF-test"
    assert generated.media_type == "audio/wav"
    assert generated.filename == "tts.wav"
