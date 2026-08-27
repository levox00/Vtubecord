"""Discord voice capture and turn detection for the two-cable setup.

The Equicord bridge exposes connection state, but intentionally does not
transport raw voice packets. On Windows we therefore capture the recording
endpoint of a dedicated VB-CABLE with PortAudio and feed the PCM frames into
the already-managed NeMo-Speech.cpp sidecar. A second cable is used for TTS,
so Neuro's own voice never enters this capture stream.
"""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
import wave
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import numpy as np

from app.audio_output import (
    AudioOutputError,
    _resample,
    _sounddevice_module,
    list_input_devices,
    select_input_device,
)
from app.core.config import settings
from app.stt_runtime import nemo_model, nemo_sidecar

logger = logging.getLogger(__name__)


def _event_log(level: str, message: str) -> None:
    try:
        from app.debug.events import add_event_log

        add_event_log(level, "discord_voice", message)
    except Exception:
        logger.log(getattr(logging, str(level).upper(), logging.INFO), str(message))


@dataclass(frozen=True)
class VoiceTranscript:
    channel_id: str
    text: str
    language: str = "auto"
    duration: float | None = None


TranscriptHandler = Callable[[VoiceTranscript], Awaitable[None]]


class DiscordVoiceInputManager:
    """Capture one Discord voice channel and expose finalized turns."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._channel_id: str | None = None
        self._handler: TranscriptHandler | None = None
        self._partial_handler: TranscriptHandler | None = None
        self._last_final: tuple[str, float] | None = None
        self._last_partial_log_at = 0.0
        self._status: dict[str, Any] = {
            "enabled": False,
            "running": False,
            "state": "idle",
            "channel_id": None,
            "device_found": False,
            "device_selected": None,
            "last_error": None,
            "last_partial": "",
            "last_final": "",
            "last_language": "auto",
            "started_at": None,
            "frames_dropped": 0,
        }

    def set_transcript_handler(self, handler: TranscriptHandler | None) -> None:
        self._handler = handler

    def set_partial_handler(self, handler: TranscriptHandler | None) -> None:
        self._partial_handler = handler

    def set_state(self, state: str) -> None:
        """Expose coordinator state without coupling the manager to Discord."""

        if self._status.get("running") or state in {"processing", "speaking"}:
            self._status["state"] = state

    def status(self) -> dict[str, Any]:
        cfg = settings.discord_voice_input
        selected = self._status.get("device_selected")
        found = bool(self._status.get("device_found"))
        if cfg.device_name:
            try:
                selected = select_input_device(cfg.device_name)
                found = True
            except AudioOutputError:
                if not self._status.get("running"):
                    selected = None
                    found = False
        return {
            **self._status,
            "enabled": bool(cfg.enabled),
            "configured_device_name": str(cfg.device_name or "CABLE-A Output"),
            "chunk_ms": int(cfg.chunk_ms or 320),
            "silence_ms": int(cfg.silence_ms or 1200),
            "device_found": found,
            "device_selected": selected,
            "available_devices": list_input_devices(),
            "runtime": (
                "nemo-speech.cpp"
                if str(settings.stt.provider or "").lower() == "nemo_speech" and nemo_model(str(settings.stt.model))
                else "faster-whisper"
            ),
        }

    async def sync(self, connected: bool, channel_id: str | None) -> None:
        """Start/stop capture as bridge voice state changes."""

        cfg = settings.discord_voice_input
        desired = bool(cfg.enabled and connected and str(channel_id or "").strip())
        target = str(channel_id or "").strip() or None
        if not desired:
            if self._task and not self._task.done():
                _event_log("info", "voice capture stopping: Discord bridge is not voice-connected or input is disabled")
            await self.stop()
            return
        if self._task and not self._task.done() and self._channel_id == target:
            return
        await self.stop()
        self._channel_id = target
        self._stop_event = asyncio.Event()
        self._status.update(
            {
                "enabled": True,
                "running": False,
                "state": "loading",
                "channel_id": target,
                "last_error": None,
                "last_partial": "",
                "started_at": None,
            }
        )
        self._task = asyncio.create_task(self._run(target, self._stop_event))
        _event_log("info", f"voice capture starting channel={target} device={cfg.device_name!r} chunk_ms={cfg.chunk_ms}")

    async def stop(self) -> None:
        task = self._task
        if self._stop_event:
            self._stop_event.set()
        self._task = None
        self._channel_id = None
        self._status.update({"running": False, "state": "idle", "channel_id": None, "last_partial": ""})
        if task and not task.done() and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(task, timeout=6)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except Exception:
                logger.debug("Discord voice capture stopped with an error", exc_info=True)

    async def _emit_final(self, channel_id: str, text: str, language: str, duration: Any) -> None:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return
        now = time.monotonic()
        if self._last_final and self._last_final[0] == normalized and now - self._last_final[1] < 1.5:
            return
        self._last_final = (normalized, now)
        self._status.update(
            {
                "state": "processing",
                "last_partial": "",
                "last_final": normalized,
                "last_language": str(language or "auto"),
            }
        )
        if self._handler:
            try:
                await self._handler(
                    VoiceTranscript(
                        channel_id=channel_id,
                        text=normalized,
                        language=str(language or "auto"),
                        duration=float(duration) if isinstance(duration, (int, float)) else None,
                    )
                )
            except Exception:
                logger.exception("Discord voice transcript handler failed")

    async def _emit_partial(self, channel_id: str, text: str, language: str) -> None:
        if not self._partial_handler or not str(text or "").strip():
            return
        try:
            await self._partial_handler(
                VoiceTranscript(channel_id=channel_id, text=str(text), language=str(language or "auto"))
            )
        except Exception:
            logger.debug("Discord voice partial handler failed", exc_info=True)

    async def _run(self, channel_id: str, stop_event: asyncio.Event) -> None:
        sidecar_ws = None
        stream = None
        receiver: asyncio.Task | None = None
        sender: asyncio.Task | None = None
        stop_waiter: asyncio.Task | None = None
        try:
            sd = _sounddevice_module()
            if sd is None:
                raise AudioOutputError("sounddevice is not installed; install it before enabling Discord voice transcription")
            model_id = str(settings.stt.model or "")
            provider = str(settings.stt.provider or "").strip().lower()
            if provider != "nemo_speech" or not nemo_model(model_id):
                _event_log(
                    "info",
                    f"using configured Faster-Whisper voice runtime provider={provider or 'auto'} model={model_id or 'default'}",
                )
                await self._run_faster_whisper(channel_id, stop_event, sd)
                return
            chunk_ms = int(settings.discord_voice_input.chunk_ms or settings.stt.stream_chunk_ms or 320)
            if chunk_ms not in (80, 160, 320, 560, 1120):
                chunk_ms = 320
            nemo_sidecar.port = int(settings.stt.sidecar_port or 8092)
            if not await nemo_sidecar.ensure(model_id, chunk_ms):
                if settings.stt.fallback_enabled:
                    _event_log(
                        "warning",
                        f"Nemotron sidecar unavailable; using configured Faster-Whisper fallback: {nemo_sidecar.error or 'not ready'}",
                    )
                    await self._run_faster_whisper(channel_id, stop_event, sd)
                    return
                raise AudioOutputError(nemo_sidecar.error or "NeMo-Speech.cpp is not ready")
            _event_log("info", f"Nemotron sidecar ready model={model_id} device={nemo_sidecar.device} chunk_ms={chunk_ms}")

            device = select_input_device(settings.discord_voice_input.device_name)
            self._status.update({"device_found": True, "device_selected": device, "state": "connecting"})
            _event_log(
                "info",
                f"voice capture device selected index={device.get('index')} name={device.get('name')!r} sample_rate={device.get('default_samplerate')}",
            )

            import websockets

            sidecar_ws = await websockets.connect(
                f"ws://127.0.0.1:{settings.stt.sidecar_port or 8092}/v1/realtime",
                open_timeout=5,
                close_timeout=2,
                max_size=None,
            )
            await sidecar_ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "sample_rate": 16000,
                        "language": str(settings.stt.stream_language or "auto"),
                        "chunk_ms": chunk_ms,
                    }
                )
            )

            loop = asyncio.get_running_loop()
            audio_queue: asyncio.Queue[tuple[bytes, float]] = asyncio.Queue(maxsize=48)
            native_rate = int(device.get("default_samplerate") or 48000)
            native_channels = min(max(int(device.get("max_input_channels") or 1), 1), 2)
            block_size = max(256, int(native_rate * chunk_ms / 1000))

            def on_audio(indata: Any, frames: int, _time_info: Any, callback_status: Any) -> None:
                if callback_status:
                    logger.debug("Discord voice input status: %s", callback_status)
                try:
                    samples = np.asarray(indata, dtype=np.float32)
                    if samples.ndim == 1:
                        samples = samples[:, None]
                    mono = samples[:, :native_channels].mean(axis=1, keepdims=True)
                    rms = float(np.sqrt(np.mean(np.square(mono))) if mono.size else 0.0)
                    if native_rate != 16000:
                        mono = _resample(mono, native_rate, 16000)
                    pcm = np.clip(mono[:, 0], -1.0, 1.0)
                    payload = (pcm * 32767.0).astype("<i2", copy=False).tobytes()
                    loop.call_soon_threadsafe(_put_audio, payload, rms)
                except Exception:
                    logger.debug("Discord voice input callback failed", exc_info=True)

            def _put_audio(payload: bytes, rms: float) -> None:
                if stop_event.is_set():
                    return
                try:
                    audio_queue.put_nowait((payload, rms))
                except asyncio.QueueFull:
                    self._status["frames_dropped"] = int(self._status.get("frames_dropped") or 0) + 1

            stream = sd.InputStream(
                samplerate=native_rate,
                channels=native_channels,
                dtype="float32",
                device=int(device["index"]),
                blocksize=block_size,
                callback=on_audio,
            )
            stream.start()
            self._status.update({"running": True, "state": "listening", "started_at": time.time()})
            _event_log("info", f"voice capture stream started channel={channel_id} native_rate={native_rate} channels={native_channels}")

            async def relay_sidecar() -> None:
                assert sidecar_ws is not None
                async for message in sidecar_ws:
                    if isinstance(message, bytes):
                        continue
                    try:
                        event = json.loads(message)
                    except (TypeError, ValueError):
                        continue
                    event_type = str(event.get("type") or event.get("event") or "").lower()
                    text = str(event.get("text") or event.get("transcript") or event.get("delta") or "")
                    is_final = bool(
                        event.get("is_final")
                        or event.get("final")
                        or "final" in event_type
                        or "completed" in event_type
                    )
                    if text and is_final:
                        await self._emit_final(
                            channel_id,
                            text,
                            str(event.get("language") or settings.stt.stream_language or "auto"),
                            event.get("duration"),
                        )
                    elif text:
                        self._status.update({"last_partial": text, "state": "user_speaking"})
                        if time.monotonic() - self._last_partial_log_at >= 1.5:
                            self._last_partial_log_at = time.monotonic()
                            _event_log("debug", f"voice STT partial channel={channel_id} chars={len(text)} text={text[:100]!r}")
                        await self._emit_partial(
                            channel_id,
                            text,
                            str(event.get("language") or settings.stt.stream_language or "auto"),
                        )
                    elif event_type in {"endpoint", "speech_end", "utterance_end"}:
                        self._status["state"] = "endpointing"

            async def send_audio() -> None:
                assert sidecar_ws is not None
                speech_started_at: float | None = None
                last_voice_at: float | None = None
                silence_seconds = max(0.3, int(settings.discord_voice_input.silence_ms or 1200) / 1000)
                while not stop_event.is_set():
                    payload, rms = await audio_queue.get()
                    await sidecar_ws.send(payload)
                    now = time.monotonic()
                    # This is endpoint detection only, not speaker/content
                    # filtering. Everyone on Cable A shares the same stream.
                    if rms >= 0.004:
                        if speech_started_at is None:
                            speech_started_at = now
                            self._status["state"] = "user_speaking"
                        last_voice_at = now
                    elif speech_started_at is not None and last_voice_at is not None and now - last_voice_at >= silence_seconds:
                        self._status["state"] = "endpointing"
                        _event_log("info", f"voice endpoint detected channel={channel_id} silence_ms={settings.discord_voice_input.silence_ms}")
                        await sidecar_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        await sidecar_ws.send(json.dumps({"type": "flush"}))
                        speech_started_at = None
                        last_voice_at = None

            receiver = asyncio.create_task(relay_sidecar())
            sender = asyncio.create_task(send_audio())
            stop_waiter = asyncio.create_task(stop_event.wait())
            done, _pending = await asyncio.wait(
                {receiver, sender, stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done and not stop_event.is_set():
                error = receiver.exception()
                if error:
                    raise error
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._status.update({"last_error": str(exc), "state": "error"})
            logger.warning("Discord voice capture stopped: %s", exc)
            _event_log("error", f"voice capture failed: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            for task in (receiver, sender, stop_waiter):
                if task and not task.done():
                    task.cancel()
            if any(task and not task.done() for task in (receiver, sender, stop_waiter)):
                await asyncio.gather(
                    *(task for task in (receiver, sender, stop_waiter) if task),
                    return_exceptions=True,
                )
            if sidecar_ws is not None:
                try:
                    await sidecar_ws.close()
                except Exception:
                    pass
            self._status["running"] = False
            if self._status.get("state") not in {"error"}:
                self._status["state"] = "idle"
            _event_log("info", f"voice capture stream stopped channel={channel_id}")

    async def _transcribe_faster_whisper(self, pcm16: bytes) -> tuple[str, str, float | None]:
        """Transcribe one endpointed PCM utterance using the active STT settings."""

        if not pcm16:
            return "", str(settings.stt.language or "auto"), None
        from app.api.routes import _get_whisper

        sample_rate = 16000
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            with wave.open(path, "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(sample_rate)
                writer.writeframes(pcm16)

            model = _get_whisper()
            language = None if settings.stt.language == "auto" else settings.stt.language

            def transcribe() -> tuple[list[str], Any]:
                segments, info = model.transcribe(
                    path,
                    language=language,
                    beam_size=settings.stt.beam_size or 5,
                    vad_filter=settings.stt.vad_filter,
                    temperature=settings.stt.temperature or 0.0,
                )
                return [str(segment.text or "").strip() for segment in segments if str(segment.text or "").strip()], info

            parts, info = await asyncio.to_thread(transcribe)
            text = " ".join(parts).strip()
            detected_language = str(getattr(info, "language", None) or settings.stt.language or "auto")
            duration = getattr(info, "duration", None)
            return text, detected_language, float(duration) if isinstance(duration, (int, float)) else None
        finally:
            try:
                import os

                os.unlink(path)
            except OSError:
                pass

    async def _run_faster_whisper(self, channel_id: str, stop_event: asyncio.Event, sd: Any) -> None:
        """Capture and endpoint audio for the active Faster-Whisper model.

        Faster-Whisper has no realtime partial protocol, so this keeps the same
        VAD/queue behavior as Nemotron and transcribes each finalized utterance
        with the model selected in the web UI.
        """

        device = select_input_device(settings.discord_voice_input.device_name)
        chunk_ms = int(settings.discord_voice_input.chunk_ms or settings.stt.stream_chunk_ms or 320)
        native_rate = int(device.get("default_samplerate") or 48000)
        native_channels = min(max(int(device.get("max_input_channels") or 1), 1), 2)
        block_size = max(256, int(native_rate * chunk_ms / 1000))
        loop = asyncio.get_running_loop()
        audio_queue: asyncio.Queue[tuple[bytes, float]] = asyncio.Queue(maxsize=48)
        stream = None

        def put_audio(payload: bytes, rms: float) -> None:
            if stop_event.is_set():
                return
            try:
                audio_queue.put_nowait((payload, rms))
            except asyncio.QueueFull:
                self._status["frames_dropped"] = int(self._status.get("frames_dropped") or 0) + 1

        def on_audio(indata: Any, _frames: int, _time_info: Any, callback_status: Any) -> None:
            if callback_status:
                logger.debug("Discord voice input status: %s", callback_status)
            try:
                samples = np.asarray(indata, dtype=np.float32)
                if samples.ndim == 1:
                    samples = samples[:, None]
                mono = samples[:, :native_channels].mean(axis=1, keepdims=True)
                rms = float(np.sqrt(np.mean(np.square(mono))) if mono.size else 0.0)
                if native_rate != 16000:
                    mono = _resample(mono, native_rate, 16000)
                pcm = np.clip(mono[:, 0], -1.0, 1.0)
                payload = (pcm * 32767.0).astype("<i2", copy=False).tobytes()
                loop.call_soon_threadsafe(put_audio, payload, rms)
            except Exception:
                logger.debug("Discord voice input callback failed", exc_info=True)

        try:
            stream = sd.InputStream(
                samplerate=native_rate,
                channels=native_channels,
                dtype="float32",
                device=int(device["index"]),
                blocksize=block_size,
                callback=on_audio,
            )
            stream.start()
            self._status.update(
                {
                    "running": True,
                    "state": "listening",
                    "started_at": time.time(),
                    "device_found": True,
                    "device_selected": device,
                    "last_error": None,
                }
            )
            _event_log(
                "info",
                f"Faster-Whisper voice capture started channel={channel_id} model={settings.stt.model!r} device={device.get('name')!r}",
            )
            speech_buffer = bytearray()
            speech_started_at: float | None = None
            last_voice_at: float | None = None
            silence_seconds = max(0.3, int(settings.discord_voice_input.silence_ms or 1200) / 1000)
            while not stop_event.is_set():
                payload, rms = await audio_queue.get()
                now = time.monotonic()
                if rms >= 0.004:
                    if speech_started_at is None:
                        speech_started_at = now
                        self._status["state"] = "user_speaking"
                    last_voice_at = now
                    speech_buffer.extend(payload)
                elif speech_started_at is not None:
                    speech_buffer.extend(payload)
                    if last_voice_at is not None and now - last_voice_at >= silence_seconds:
                        pcm16 = bytes(speech_buffer)
                        speech_buffer.clear()
                        speech_started_at = None
                        last_voice_at = None
                        self._status["state"] = "endpointing"
                        _event_log("info", f"Faster-Whisper endpoint detected channel={channel_id}")
                        text, language, duration = await self._transcribe_faster_whisper(pcm16)
                        if text:
                            await self._emit_final(channel_id, text, language, duration)
                        else:
                            self._status["state"] = "listening"
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass


discord_voice_input = DiscordVoiceInputManager()


async def stop_discord_voice_input() -> None:
    await discord_voice_input.stop()
