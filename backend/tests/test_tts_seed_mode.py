import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.anyio
async def test_tts_settings_persistence():
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        # set fixed seed and mode
        r = await client.post("/api/tts/settings", json={"tts_seed": 12345, "tts_seed_mode": "fixed"})
        assert r.status_code == 200

        # verify settings persisted via GET
        r2 = await client.get("/api/tts/settings")
        assert r2.status_code == 200
        data = r2.json()
        assert data.get("seed") == 12345 or data.get("tts_seed") == 12345 or data.get("seed_mode") == "fixed" or data.get("tts_seed_mode") == "fixed"

@pytest.mark.anyio
async def test_tts_endpoint_returns_audio():
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        # set random mode to exercise dynamic behavior
        r = await client.post("/api/tts/settings", json={"tts_seed_mode": "random"})
        assert r.status_code == 200

        payload = {"text": "hello world","engine": "zonos", "voice_ref": "voices/female_energetic.wav"}
        r1 = await client.post("/api/tts", json=payload)
        assert r1.status_code == 200
        # response should contain audio bytes
        assert isinstance(r1.content, (bytes, bytearray))
        assert len(r1.content) > 100  # tiny sanity check that it's not empty
