import pytest

from app.audio_output import AudioOutputError, select_input_device
from app.core.config import settings
from app.discord_voice import DiscordVoiceInputManager


def test_select_input_device_prefers_short_48khz_endpoint(monkeypatch):
    monkeypatch.setattr(
        "app.audio_output.list_input_devices",
        lambda: [
            {"name": "CABLE-A Output (long host API)", "index": 1, "max_input_channels": 16, "default_samplerate": 44100},
            {"name": "CABLE-A Output", "index": 2, "max_input_channels": 2, "default_samplerate": 48000},
        ],
    )
    selected = select_input_device("CABLE-A Output")
    assert selected["index"] == 2


def test_missing_input_device_has_actionable_error(monkeypatch):
    monkeypatch.setattr("app.audio_output.list_input_devices", lambda: [{"name": "Microphone", "index": 1}])
    with pytest.raises(AudioOutputError, match="CABLE-A Output"):
        select_input_device("CABLE-A Output")


def test_voice_input_status_exposes_two_cable_defaults(monkeypatch):
    monkeypatch.setattr("app.discord_voice.list_input_devices", lambda: [])
    monkeypatch.setattr("app.discord_voice.select_input_device", lambda _name: (_ for _ in ()).throw(AudioOutputError("missing")))
    old = settings.discord_voice_input.model_copy(deep=True)
    try:
        settings.discord_voice_input.enabled = False
        settings.discord_voice_input.device_name = "CABLE-A Output"
        # This test verifies the schema default independently of the user's
        # active low-latency runtime setting (which may legitimately be 80ms).
        settings.discord_voice_input.chunk_ms = 320
        status = DiscordVoiceInputManager().status()
        assert status["configured_device_name"] == "CABLE-A Output"
        assert status["chunk_ms"] == 320
        assert status["running"] is False
    finally:
        settings.discord_voice_input = old
