import io
import struct
import wave

import numpy as np

from app.api.discord_bridge import _discord_voice_output_allowed
from app.audio_output import (
    AudioOutputError,
    _decode_wav,
    _decode_with_ffmpeg,
    select_output_device,
)


def _wav_bytes() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes((np.zeros(160, dtype="<i2")).tobytes())
    return stream.getvalue()


def _float_wav_bytes() -> bytes:
    samples = np.array([0.0, 0.25, -0.25, 1.0], dtype="<f4").tobytes()
    fmt = struct.pack("<HHIIHH", 3, 1, 16000, 64000, 4, 32)
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def test_wav_tts_audio_is_decoded_to_float_pcm():
    decoded = _decode_wav(_wav_bytes())
    assert decoded.sample_rate == 16000
    assert decoded.samples.shape == (160, 1)
    assert decoded.samples.dtype == np.float32


def test_ieee_float_wav_tts_audio_is_decoded_to_float_pcm():
    decoded = _decode_wav(_float_wav_bytes())
    assert decoded.sample_rate == 16000
    assert decoded.samples.shape == (4, 1)
    np.testing.assert_allclose(decoded.samples[:, 0], [0.0, 0.25, -0.25, 1.0])


def test_mp3_decoder_converts_ffmpeg_float_pcm(monkeypatch):
    class Completed:
        returncode = 0
        stdout = (np.zeros(8, dtype="<f4")).tobytes()
        stderr = b""

    monkeypatch.setattr("app.audio_output.shutil.which", lambda _name: "ffmpeg.exe")
    monkeypatch.setattr("app.audio_output.subprocess.run", lambda *args, **kwargs: Completed())
    decoded = _decode_with_ffmpeg(b"mp3", "audio/mpeg")
    assert decoded.sample_rate == 48000
    assert decoded.samples.shape == (4, 2)


def test_missing_output_device_reports_available_outputs(monkeypatch):
    monkeypatch.setattr("app.audio_output.list_output_devices", lambda: [{"name": "Speakers", "index": 1}])
    try:
        select_output_device("CABLE Input")
    except AudioOutputError as exc:
        assert "CABLE Input" in str(exc)
        assert "Speakers" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Missing device should have raised AudioOutputError")


def test_discord_voice_output_is_desktop_only_and_opt_in():
    assert _discord_voice_output_allowed("client", True, True)
    assert not _discord_voice_output_allowed("client", False, True)
    assert not _discord_voice_output_allowed("client", True, False)
    assert not _discord_voice_output_allowed("bot", True, True)
