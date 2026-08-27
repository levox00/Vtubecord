"""Windows audio I/O helpers for desktop Discord voice routing.

The playback service writes decoded TTS PCM to the configured VB-CABLE input.
The same module exposes input-device discovery for the companion Discord voice
capture service, which records the other cable's output endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import struct
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _event_log(level: str, message: str) -> None:
    """Mirror cable playback diagnostics into the in-app Discord log view."""

    try:
        from app.debug.events import add_event_log

        add_event_log(level, "discord_voice", message)
    except Exception:
        logger.log(getattr(logging, str(level).upper(), logging.INFO), str(message))


class AudioOutputError(RuntimeError):
    """A user-actionable virtual audio output error."""


@dataclass(frozen=True)
class DecodedAudio:
    samples: np.ndarray
    sample_rate: int


def _sounddevice_module() -> Any | None:
    try:
        import sounddevice as sd

        return sd
    except Exception:
        return None


def list_output_devices() -> list[dict[str, Any]]:
    """List playback-capable devices, including their stable PortAudio index."""

    sd = _sounddevice_module()
    if sd is None:
        return []
    try:
        devices = sd.query_devices()
    except Exception as exc:
        logger.debug("Could not enumerate audio devices: %s", exc)
        return []

    result: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        try:
            channels = int(device.get("max_output_channels", 0))
        except (AttributeError, TypeError, ValueError):
            channels = 0
        if channels <= 0:
            continue
        try:
            sample_rate = int(round(float(device.get("default_samplerate", 48000))))
        except (AttributeError, TypeError, ValueError):
            sample_rate = 48000
        result.append(
            {
                "index": index,
                "name": str(device.get("name") or f"Output device {index}"),
                "max_output_channels": channels,
                "default_samplerate": sample_rate,
                "is_virtual_cable": "cable input" in str(device.get("name") or "").lower(),
            }
        )
    return result


def list_input_devices() -> list[dict[str, Any]]:
    """List recording-capable devices, including virtual-cable endpoints."""

    sd = _sounddevice_module()
    if sd is None:
        return []
    try:
        devices = sd.query_devices()
    except Exception as exc:
        logger.debug("Could not enumerate audio input devices: %s", exc)
        return []

    result: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        try:
            channels = int(device.get("max_input_channels", 0))
        except (AttributeError, TypeError, ValueError):
            channels = 0
        if channels <= 0:
            continue
        try:
            sample_rate = int(round(float(device.get("default_samplerate", 48000))))
        except (AttributeError, TypeError, ValueError):
            sample_rate = 48000
        name = str(device.get("name") or f"Input device {index}")
        result.append(
            {
                "index": index,
                "name": name,
                "max_input_channels": channels,
                "default_samplerate": sample_rate,
                "is_virtual_cable": "cable output" in name.lower(),
            }
        )
    return result


def select_output_device(device_name: str | None = None) -> dict[str, Any]:
    """Select a configured output by exact name, then case-insensitive substring."""

    devices = list_output_devices()
    requested = str(device_name or "CABLE Input").strip().lower()
    if not devices:
        sd = _sounddevice_module()
        if sd is None:
            raise AudioOutputError(
                "Python audio output support is not installed. Install the project's "
                "sounddevice dependency and restart the backend."
            )
        raise AudioOutputError(
            "No playback audio devices were detected. Check Windows sound output permissions."
        )

    def preference(item: dict[str, Any]) -> tuple[int, int, int, int]:
        # Windows exposes the same cable through several host APIs. Prefer a
        # normal two-channel/48 kHz endpoint and then the least truncated name.
        return (
            int(int(item.get("max_output_channels") or 0) <= 2),
            int(int(item.get("default_samplerate") or 0) == 48000),
            len(str(item.get("name") or "")),
            -int(item.get("index") or 0),
        )

    exact = sorted(
        (item for item in devices if item["name"].strip().lower() == requested),
        key=preference,
        reverse=True,
    )
    if exact:
        return exact[0]
    partial = sorted(
        (item for item in devices if requested and requested in item["name"].lower()),
        key=preference,
        reverse=True,
    )
    if partial:
        return partial[0]

    available = ", ".join(item["name"] for item in devices)
    raise AudioOutputError(
        f'Audio device "{device_name or "CABLE Input"}" was not found. Available outputs: {available}'
    )


def select_input_device(device_name: str | None = None) -> dict[str, Any]:
    """Select a configured recording endpoint by exact name, then substring."""

    devices = list_input_devices()
    requested = str(device_name or "CABLE-A Output").strip().lower()
    if not devices:
        sd = _sounddevice_module()
        if sd is None:
            raise AudioOutputError(
                "Python audio input support is not installed. Install the project's "
                "sounddevice dependency and restart the backend."
            )
        raise AudioOutputError(
            "No recording audio devices were detected. Check Windows audio permissions."
        )

    def preference(item: dict[str, Any]) -> tuple[int, int, int, int]:
        return (
            int(int(item.get("max_input_channels") or 0) <= 2),
            int(int(item.get("default_samplerate") or 0) == 48000),
            len(str(item.get("name") or "")),
            -int(item.get("index") or 0),
        )

    exact = sorted(
        (item for item in devices if item["name"].strip().lower() == requested),
        key=preference,
        reverse=True,
    )
    if exact:
        return exact[0]
    partial = sorted(
        (item for item in devices if requested and requested in item["name"].lower()),
        key=preference,
        reverse=True,
    )
    if partial:
        return partial[0]

    available = ", ".join(item["name"] for item in devices)
    raise AudioOutputError(
        f'Audio input device "{device_name or "CABLE-A Output"}" was not found. Available inputs: {available}'
    )


def _decode_wav(audio_bytes: bytes) -> DecodedAudio:
    # ``wave`` rejects IEEE-float WAVs on some Python versions (the error is
    # usually ``unknown format: 3``), while several local TTS engines emit
    # exactly that format. Parse the RIFF chunks directly so PCM, float, and
    # WAVE_FORMAT_EXTENSIBLE files all follow the same path.
    if len(audio_bytes) < 12 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        raise AudioOutputError("Could not decode WAV TTS audio: invalid RIFF/WAVE header")

    format_tag: int | None = None
    channels = 0
    sample_rate = 0
    bits_per_sample = 0
    raw: bytes | None = None
    offset = 12
    while offset + 8 <= len(audio_bytes):
        chunk_id = audio_bytes[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", audio_bytes, offset + 4)[0]
        chunk_start = offset + 8
        chunk_end = min(len(audio_bytes), chunk_start + chunk_size)
        chunk = audio_bytes[chunk_start:chunk_end]
        if chunk_id == b"fmt " and len(chunk) >= 16:
            format_tag, channels, sample_rate, _byte_rate, _block_align, bits_per_sample = struct.unpack_from(
                "<HHIIHH", chunk, 0
            )
            # WAVE_FORMAT_EXTENSIBLE stores the real codec in its SubFormat
            # GUID. The first WORD is PCM (1) or IEEE float (3).
            if format_tag == 0xFFFE and len(chunk) >= 40:
                format_tag = struct.unpack_from("<H", chunk, 24)[0]
        elif chunk_id == b"data":
            raw = chunk
        # RIFF chunks are word aligned.
        offset = chunk_start + chunk_size + (chunk_size & 1)

    if format_tag is None or raw is None:
        raise AudioOutputError("Could not decode WAV TTS audio: missing fmt or data chunk")
    if channels <= 0 or sample_rate <= 0 or bits_per_sample <= 0:
        raise AudioOutputError("WAV TTS audio has an invalid channel count or sample rate")
    sample_width = (bits_per_sample + 7) // 8
    if format_tag == 1:  # PCM integer
        if sample_width == 1:
            samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif sample_width == 2:
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif sample_width == 3:
            usable = len(raw) - (len(raw) % 3)
            packed = np.frombuffer(raw[:usable], dtype=np.uint8).reshape(-1, 3)
            values = (
                packed[:, 0].astype(np.int32)
                | (packed[:, 1].astype(np.int32) << 8)
                | (packed[:, 2].astype(np.int32) << 16)
            )
            values = np.where(values & 0x800000, values - 0x1000000, values)
            samples = values.astype(np.float32) / 8388608.0
        elif sample_width == 4:
            samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            raise AudioOutputError(f"Unsupported PCM WAV sample width: {sample_width} bytes")
    elif format_tag == 3:  # IEEE float
        if sample_width == 4:
            samples = np.frombuffer(raw, dtype="<f4").astype(np.float32)
        elif sample_width == 8:
            samples = np.frombuffer(raw, dtype="<f8").astype(np.float32)
        else:
            raise AudioOutputError(f"Unsupported IEEE-float WAV sample width: {sample_width} bytes")
    else:
        raise AudioOutputError(f"Unsupported WAV format tag: {format_tag}")

    usable_samples = samples.size - (samples.size % channels)
    samples = samples[:usable_samples]
    if samples.size == 0:
        raise AudioOutputError("TTS audio is empty")
    # TTS engines occasionally produce tiny NaN/overshoot values. Sending
    # those directly to a virtual cable is heard as clicks or harsh digital
    # distortion, so normalize the final decoded buffer before playback.
    samples = np.nan_to_num(samples.astype(np.float32, copy=False), nan=0.0, posinf=1.0, neginf=-1.0)
    samples = np.clip(samples, -1.0, 1.0)
    return DecodedAudio(samples.reshape(-1, channels), sample_rate)


def _decode_with_ffmpeg(audio_bytes: bytes, media_type: str | None = None) -> DecodedAudio:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioOutputError(
            "MP3 TTS audio needs ffmpeg for Discord playback. Install ffmpeg and add it to PATH, "
            "or use a WAV-producing TTS engine."
        )
    input_args = ["-i", "pipe:0"]
    looks_like_mp3 = audio_bytes[:3] == b"ID3" or (
        len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0
    )
    if "mpeg" in str(media_type or "").lower() or looks_like_mp3:
        input_args = ["-f", "mp3", *input_args]
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                *input_args,
                "-f",
                "f32le",
                "-ar",
                "48000",
                "-ac",
                "2",
                "pipe:1",
            ],
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioOutputError(f"ffmpeg could not decode TTS audio: {exc}") from exc
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AudioOutputError(f"Could not decode MP3 TTS audio{f': {detail}' if detail else ''}")
    samples = np.frombuffer(completed.stdout, dtype="<f4")
    if samples.size == 0 or samples.size % 2:
        raise AudioOutputError("Decoded TTS audio did not contain complete stereo frames")
    return DecodedAudio(samples.reshape(-1, 2), 48000)


def decode_audio(audio_bytes: bytes, media_type: str | None = None) -> DecodedAudio:
    """Decode WAV directly and use ffmpeg for MP3/other TTS formats."""

    if not audio_bytes:
        raise AudioOutputError("TTS audio is empty")
    if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        return _decode_wav(audio_bytes)
    return _decode_with_ffmpeg(audio_bytes, media_type)


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or samples.shape[0] <= 1:
        return samples
    target_length = max(1, int(round(samples.shape[0] * target_rate / source_rate)))
    # Prefer a proper band-limited polyphase conversion for the common
    # 44.1/48 kHz TTS-to-VB-CABLE conversion. Keep the lightweight linear
    # implementation as a fallback when SciPy is not installed.
    try:
        from math import gcd
        from scipy.signal import resample_poly

        divisor = gcd(int(source_rate), int(target_rate))
        up = int(target_rate) // divisor
        down = int(source_rate) // divisor
        converted = np.stack(
            [resample_poly(samples[:, index], up, down) for index in range(samples.shape[1])],
            axis=1,
        ).astype(np.float32, copy=False)
        if converted.shape[0] >= target_length:
            return converted[:target_length]
        return np.pad(converted, ((0, target_length - converted.shape[0]), (0, 0)), mode="edge")
    except Exception:
        pass
    source_positions = np.linspace(0.0, 1.0, samples.shape[0], endpoint=False)
    target_positions = np.linspace(0.0, 1.0, target_length, endpoint=False)
    channels = [np.interp(target_positions, source_positions, samples[:, index]) for index in range(samples.shape[1])]
    return np.stack(channels, axis=1).astype(np.float32, copy=False)


def _fit_channels(samples: np.ndarray, channels: int) -> np.ndarray:
    if channels <= 0 or samples.shape[1] == channels:
        return samples
    if channels == 1:
        return samples.mean(axis=1, keepdims=True)
    if samples.shape[1] == 1:
        return np.repeat(samples, channels, axis=1)
    if samples.shape[1] > channels:
        return samples[:, :channels]
    return np.pad(samples, ((0, 0), (0, channels - samples.shape[1])), mode="edge")


class AudioOutputService:
    """Serialized, cancellable playback to one Windows output endpoint."""

    def __init__(self) -> None:
        self._request_lock = asyncio.Lock()
        self._serialization_lock = asyncio.Lock()
        self._playback_task: asyncio.Task | None = None
        self._stop_event: threading.Event | None = None
        self._status: dict[str, Any] = {
            "playing": False,
            "device_found": False,
            "device_selected": None,
            "last_playback_error": None,
            "backend": "sounddevice" if _sounddevice_module() is not None else None,
        }

    def status(self, device_name: str | None = None) -> dict[str, Any]:
        selected = self._status.get("device_selected")
        found = bool(self._status.get("device_found"))
        if device_name:
            try:
                selected = select_output_device(device_name)
                found = True
            except AudioOutputError:
                selected = None
                found = False
        return {
            **self._status,
            "device_found": found,
            "device_selected": selected,
            "available_devices": list_output_devices(),
        }

    def _play_sync(
        self,
        audio_bytes: bytes,
        media_type: str | None,
        device: dict[str, Any],
        stop_event: threading.Event,
    ) -> None:
        sd = _sounddevice_module()
        if sd is None:
            raise AudioOutputError("sounddevice is not installed; install it before using Discord voice output")
        decoded = decode_audio(audio_bytes, media_type)
        sample_rate = int(device.get("default_samplerate") or 48000)
        samples = _resample(decoded.samples, decoded.sample_rate, sample_rate)
        max_channels = max(int(device.get("max_output_channels") or 1), 1)
        # VB-CABLE's stable WASAPI endpoint is stereo. Mirroring a mono TTS
        # signal to both channels avoids host-specific mono negotiation that
        # can sound phasey or corrupted in Discord's microphone path.
        target_channels = 2 if max_channels >= 2 else 1
        samples = _fit_channels(samples, target_channels)
        samples = np.clip(np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0)
        logger.info(
            "Discord audio playback device=%s source_rate=%s target_rate=%s channels=%s frames=%s",
            device.get("name"),
            decoded.sample_rate,
            sample_rate,
            samples.shape[1],
            samples.shape[0],
        )
        _event_log(
            "debug",
            f"audio playback format device={device.get('name')!r} source_rate={decoded.sample_rate} target_rate={sample_rate} channels={samples.shape[1]} frames={samples.shape[0]}",
        )
        # Keep a small block loop so cancellation stops a new Discord reply
        # quickly instead of waiting for the full TTS clip.
        block_size = max(256, int(sample_rate * 0.05))
        with sd.OutputStream(
            samplerate=sample_rate,
            channels=samples.shape[1],
            dtype="float32",
            device=int(device["index"]),
            blocksize=block_size,
        ) as stream:
            for start in range(0, samples.shape[0], block_size):
                if stop_event.is_set():
                    break
                stream.write(samples[start : start + block_size])

    async def stop(self) -> None:
        async with self._request_lock:
            task = self._playback_task
            self._playback_task = None
            if self._stop_event:
                self._stop_event.set()
            sd = _sounddevice_module()
            if sd is not None:
                try:
                    sd.stop()
                except Exception:
                    pass
            if task and not task.done():
                task.cancel()
        if task and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._status["playing"] = False

    async def play(
        self,
        audio_bytes: bytes,
        media_type: str | None = None,
        *,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        try:
            device = select_output_device(device_name)
        except AudioOutputError as exc:
            self._status.update({"device_found": False, "device_selected": None, "last_playback_error": str(exc)})
            raise
        await self.stop()
        stop_event = threading.Event()
        async with self._request_lock:
            self._stop_event = stop_event
            self._status.update(
                {
                    "playing": True,
                    "device_found": True,
                    "device_selected": device,
                    "last_playback_error": None,
                }
            )
            task = asyncio.create_task(asyncio.to_thread(self._play_sync, audio_bytes, media_type, device, stop_event))
            self._playback_task = task
        try:
            await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._status["last_playback_error"] = str(exc)
            raise AudioOutputError(str(exc)) from exc
        finally:
            if self._playback_task is task:
                self._playback_task = None
            self._status["playing"] = False
        return self.status(device_name)

    async def play_serialized(
        self,
        audio_bytes: bytes,
        media_type: str | None = None,
        *,
        device_name: str | None = None,
    ) -> dict[str, Any]:
        """Play after any earlier bridge response has finished.

        Discord text replies and voice-channel replies share this lock so a
        late response cannot cut into a currently spoken response.
        """

        async with self._serialization_lock:
            return await self.play(audio_bytes, media_type, device_name=device_name)


_audio_output_service = AudioOutputService()


def get_audio_output_service() -> AudioOutputService:
    return _audio_output_service
