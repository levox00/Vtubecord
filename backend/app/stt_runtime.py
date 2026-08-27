from __future__ import annotations

"""Runtime helpers for the optional NVIDIA NeMo-Speech.cpp ASR sidecar.

The backend deliberately owns the small amount of orchestration here instead
of importing the Python NeMo stack.  This keeps Faster-Whisper compatible and
lets installations opt into the native sidecar when its executable and model
weights are present.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ``stt_runtime.py`` lives directly under ``backend/app``.  The other
# integrations are nested one level deeper, so their ``parents[3]`` root
# calculation does not apply here.  Keeping this canonical prevents model
# downloads from ending up beside the project instead of inside it.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = PROJECT_ROOT / "assets" / "whisper" / "nemotron"
LICENSE_FILE = PROJECT_ROOT / "data" / "stt-license-acceptance.json"
SIDECAR_PORT = 8092
SIDECAR_URL = f"http://127.0.0.1:{SIDECAR_PORT}"

NEMO_MODELS: list[dict[str, Any]] = [
    {
        "id": "nemotron-3.5-asr-streaming-0.6b",
        "name": "NVIDIA Nemotron 3.5 ASR Streaming",
        "provider": "nemo_speech",
        "runtime": "nemo-speech.cpp",
        "params": "0.6B",
        "size_mb": 720,
        "vram_mb": 1100,
        "relative_speed": "realtime",
        "wer": "streaming",
        "description": "Multilingual low-latency streaming ASR for 40 locales.",
        "languages": "Multilingual (40 locales)",
        "streaming": True,
        "default": True,
        "license": "OpenMDW-1.1",
        "license_url": "https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b",
        "source_url": "https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b",
        "filename": "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf",
        "download_url": "https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/main/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf?download=true",
        "verification": "Official artifact size and SHA-256 (Hugging Face metadata)",
    },
    {
        "id": "nemotron-speech-streaming-en-0.6b",
        "name": "NVIDIA Nemotron Speech Streaming English",
        "provider": "nemo_speech",
        "runtime": "nemo-speech.cpp",
        "params": "0.6B",
        "size_mb": 720,
        "vram_mb": 1100,
        "relative_speed": "realtime",
        "wer": "streaming",
        "description": "English-only realtime Nemotron Speech Streaming model.",
        "languages": "English",
        "streaming": True,
        "default": False,
        "license": "NVIDIA Open Model License",
        "license_url": "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b",
        "source_url": "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b",
        "filename": "nemotron-speech-streaming-en-0.6b.q8_0.gguf",
        "download_url": "https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b/resolve/main/nemotron-speech-streaming-en-0.6b.q8_0.gguf?download=true",
        "verification": "Official artifact size and SHA-256 (Hugging Face metadata)",
    },
]

# Downloading a GGUF takes long enough that it must be observable.  Keeping
# this state in the backend also means the UI can be refreshed or reopened
# without losing the actual download/error state.
_nemo_download_states: dict[str, dict[str, Any]] = {}
_nemo_download_tasks: dict[str, asyncio.Task[None]] = {}
_nemo_install_task: asyncio.Task[None] | None = None
_nemo_install_state: dict[str, Any] = {
    "status": "idle",
    "executable": None,
    "error": None,
    "last_output": None,
    "started_at": None,
    "finished_at": None,
}

CHUNK_RIGHT_CONTEXT = {80: 0, 160: 1, 320: 3, 560: 6, 1120: 13}


def nemo_model(model_id: str) -> dict[str, Any] | None:
    return next((m for m in NEMO_MODELS if m["id"] == model_id), None)


def nemo_model_path(model_id: str) -> Path:
    model = nemo_model(model_id)
    if not model:
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    return MODEL_DIR / str(model["filename"])


def legacy_nemo_model_path(model_id: str) -> Path:
    """Return the pre-fix location used by older STT builds, if applicable."""

    model = nemo_model(model_id)
    if not model:
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    return LEGACY_PROJECT_ROOT / "assets" / "whisper" / "nemotron" / str(model["filename"])


def existing_nemo_model_path(model_id: str) -> Path:
    """Resolve a ready model from the canonical or legacy download directory."""

    canonical = nemo_model_path(model_id)
    if canonical.is_file() and canonical.stat().st_size > 0:
        return canonical
    legacy = legacy_nemo_model_path(model_id)
    if legacy != canonical and legacy.is_file() and legacy.stat().st_size > 0:
        return legacy
    return canonical


def nemo_partial_path(model_id: str) -> Path:
    """Choose a resumable partial from either the canonical or legacy folder."""

    canonical = nemo_model_path(model_id).with_suffix(nemo_model_path(model_id).suffix + ".part")
    if canonical.is_file():
        return canonical
    legacy = legacy_nemo_model_path(model_id).with_suffix(legacy_nemo_model_path(model_id).suffix + ".part")
    return legacy if legacy.is_file() else canonical


def model_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_acceptance() -> dict[str, Any]:
    try:
        return json.loads(LICENSE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def license_accepted(model_id: str, revision: str | None = None) -> bool:
    record = _load_acceptance().get(model_id)
    if not isinstance(record, dict):
        return False
    return bool(record.get("accepted") and (not revision or record.get("revision") == revision))


def accept_license(model_id: str, revision: str = "main") -> dict[str, Any]:
    if not nemo_model(model_id):
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    data = _load_acceptance()
    record = {
        "accepted": True,
        "model_id": model_id,
        "revision": revision,
        "license_id": nemo_model(model_id)["license"],
        "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    data[model_id] = record
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return record


def record_model_hash(model_id: str, sha256: str) -> None:
    data = _load_acceptance()
    record = data.get(model_id)
    if not isinstance(record, dict):
        return
    record["sha256"] = sha256
    data[model_id] = record
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def model_status(model_id: str) -> dict[str, Any]:
    model = nemo_model(model_id)
    if not model:
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    path = existing_nemo_model_path(model_id)
    ready = path.is_file() and path.stat().st_size > 0
    digest_path = path.with_suffix(path.suffix + ".sha256")
    try:
        digest = digest_path.read_text(encoding="ascii").strip() or None
    except OSError:
        digest = None
    return {
        "downloaded": ready,
        "ready": ready,
        "path": str(path),
        "sha256": digest,
        "license_accepted": license_accepted(model_id),
        "download": nemo_download_status(model_id),
    }


def _partial_size(model_id: str) -> int:
    try:
        return nemo_partial_path(model_id).stat().st_size
    except OSError:
        return 0


def _update_nemo_download_state(model_id: str, **values: Any) -> dict[str, Any]:
    state = _nemo_download_states.setdefault(
        model_id,
        {
            "model": model_id,
            "status": "idle",
            "downloaded_bytes": 0,
            "total_bytes": None,
            "progress_percent": None,
            "speed_bytes_per_sec": None,
            "error": None,
            "started_at": None,
            "updated_at": None,
        },
    )
    state.update(values)
    total = state.get("total_bytes")
    downloaded = int(state.get("downloaded_bytes") or 0)
    state["progress_percent"] = round(downloaded * 100 / total, 1) if isinstance(total, int) and total > 0 else None
    state["updated_at"] = time.time()
    return state


def nemo_download_status(model_id: str) -> dict[str, Any]:
    """Return a UI-ready snapshot without exposing an internal task object."""
    model = nemo_model(model_id)
    if not model:
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    target = existing_nemo_model_path(model_id)
    if target.is_file() and target.stat().st_size > 0:
        return {
            "model": model_id,
            "status": "ready",
            "downloaded_bytes": target.stat().st_size,
            "total_bytes": target.stat().st_size,
            "progress_percent": 100.0,
            "speed_bytes_per_sec": None,
            "error": None,
            "started_at": None,
            "updated_at": None,
        }

    state = _nemo_download_states.get(model_id)
    if state:
        snapshot = dict(state)
    else:
        partial_bytes = _partial_size(model_id)
        snapshot = {
            "model": model_id,
            "status": "paused" if partial_bytes else "idle",
            "downloaded_bytes": partial_bytes,
            "total_bytes": None,
            "progress_percent": None,
            "speed_bytes_per_sec": None,
            "error": None,
            "started_at": None,
            "updated_at": None,
        }
    snapshot["model"] = model_id
    return snapshot


async def download_nemo_model(
    model_id: str,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    model = nemo_model(model_id)
    if not model:
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    if not license_accepted(model_id):
        raise PermissionError(f"Accept the {model['license']} for {model_id} before downloading")

    # A model downloaded by the pre-fix build may already be complete in the
    # old sibling directory.  Reuse it and avoid a needless 700+ MB download.
    existing = existing_nemo_model_path(model_id)
    if existing.is_file() and existing.stat().st_size > 0:
        digest_path = existing.with_suffix(existing.suffix + ".sha256")
        digest = digest_path.read_text(encoding="ascii").strip() if digest_path.exists() else ""
        return {
            "status": "ready",
            "model": model_id,
            "path": str(existing),
            "sha256": digest,
            "size_bytes": existing.stat().st_size,
        }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = nemo_model_path(model_id)
    partial = nemo_partial_path(model_id)
    existing_bytes = _partial_size(model_id)
    digest = hashlib.sha256()
    if existing_bytes:
        # Preserve a valid partial file on interruptions and resume it on the
        # next attempt.  Re-hashing it is small compared with re-downloading
        # a 700+ MB model and lets the final SHA-256 check stay meaningful.
        with partial.open("rb") as existing:
            for block in iter(lambda: existing.read(1024 * 1024), b""):
                digest.update(block)

    async with httpx.AsyncClient(
        follow_redirects=True,
        # A large local-model download may legitimately be quiet for over a
        # minute on a slow connection.  Keep the connection timeout bounded,
        # but do not abort a healthy stream just because it is slow.
        timeout=httpx.Timeout(connect=30.0, read=None, write=30.0, pool=30.0),
    ) as client:
        expected_size: int | None = None
        expected_sha: str | None = None
        try:
            head = await client.head(str(model["download_url"]))
            if head.is_success:
                size_header = head.headers.get("x-linked-size") or head.headers.get("content-length")
                if size_header and size_header.isdigit():
                    expected_size = int(size_header)
                # Xet ETags are storage identifiers, not necessarily the
                # SHA-256 of the response bytes.  Only trust an explicit
                # checksum header; always record the locally computed digest.
                linked_sha = head.headers.get("x-linked-sha256", "").strip('"')
                if len(linked_sha) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in linked_sha):
                    expected_sha = linked_sha.lower()
        except httpx.HTTPError:
            # A GET can still succeed when a CDN does not implement HEAD.
            pass

        # If a previous run completed the .part file but stopped before the
        # final rename, Range bytes=<full-size>- is invalid and returns 416.
        # Verify and promote that complete file instead of requesting it again.
        if existing_bytes and expected_size is not None and existing_bytes >= expected_size:
            partial_digest = digest.hexdigest()
            if existing_bytes == expected_size and (not expected_sha or partial_digest == expected_sha):
                partial.replace(target)
                target.with_suffix(target.suffix + ".sha256").write_text(partial_digest + "\n", encoding="ascii")
                record_model_hash(model_id, partial_digest)
                return {"status": "ready", "model": model_id, "path": str(target), "sha256": partial_digest, "size_bytes": expected_size}
            partial.unlink(missing_ok=True)
            existing_bytes = 0
            digest = hashlib.sha256()

        headers = {"Range": f"bytes={existing_bytes}-"} if existing_bytes else {}
        async with client.stream("GET", str(model["download_url"]), headers=headers) as response:
            response.raise_for_status()
            resumed = response.status_code == 206 and existing_bytes > 0
            if not resumed:
                # If the CDN does not support Range, start cleanly rather than
                # appending the full response to the old partial file.
                existing_bytes = 0
                digest = hashlib.sha256()
            content_range = response.headers.get("content-range", "")
            if content_range.rsplit("/", 1)[-1].isdigit():
                expected_size = int(content_range.rsplit("/", 1)[-1])
            if expected_size is None:
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    expected_size = existing_bytes + int(content_length)
            downloaded_bytes = existing_bytes
            started = time.monotonic()
            if progress_callback:
                progress_callback(downloaded_bytes, expected_size, 0.0)
            with partial.open("ab" if resumed else "wb") as handle:
                async for block in response.aiter_bytes(1024 * 1024):
                    if block:
                        handle.write(block)
                        digest.update(block)
                        downloaded_bytes += len(block)
                        if progress_callback:
                            elapsed = max(time.monotonic() - started, 0.001)
                            progress_callback(downloaded_bytes, expected_size, (downloaded_bytes - existing_bytes) / elapsed)
    actual_size = partial.stat().st_size
    sha = digest.hexdigest()
    if expected_size is not None and actual_size != expected_size:
        raise IOError(f"Model size verification failed: expected {expected_size}, got {actual_size}")
    if expected_sha and sha != expected_sha:
        raise IOError("Model SHA-256 verification failed")
    partial.replace(target)
    target.with_suffix(target.suffix + ".sha256").write_text(sha + "\n", encoding="ascii")
    record_model_hash(model_id, sha)
    return {"status": "ready", "model": model_id, "path": str(target), "sha256": sha, "size_bytes": actual_size}


async def _run_nemo_download(model_id: str) -> None:
    started_at = time.time()
    _update_nemo_download_state(
        model_id,
        status="downloading",
        downloaded_bytes=_partial_size(model_id),
        error=None,
        started_at=started_at,
    )

    def report(downloaded: int, total: int | None, speed: float) -> None:
        _update_nemo_download_state(
            model_id,
            status="downloading",
            downloaded_bytes=downloaded,
            total_bytes=total,
            speed_bytes_per_sec=round(speed, 1) if speed > 0 else None,
            error=None,
        )

    try:
        result = await download_nemo_model(model_id, progress_callback=report)
        _update_nemo_download_state(
            model_id,
            status="ready",
            downloaded_bytes=int(result["size_bytes"]),
            total_bytes=int(result["size_bytes"]),
            speed_bytes_per_sec=None,
            error=None,
        )
        logger.info("Nemotron model '%s' downloaded: %s", model_id, result["sha256"])
    except asyncio.CancelledError:
        _update_nemo_download_state(model_id, status="paused", speed_bytes_per_sec=None)
        raise
    except Exception as exc:
        logger.exception("Failed downloading Nemotron model '%s'", model_id)
        _update_nemo_download_state(
            model_id,
            status="error",
            downloaded_bytes=_partial_size(model_id),
            speed_bytes_per_sec=None,
            error=str(exc),
        )


async def start_nemo_download(model_id: str) -> dict[str, Any]:
    """Start or resume one model download and immediately return its state."""
    model = nemo_model(model_id)
    if not model:
        raise ValueError(f"Unknown Nemotron model: {model_id}")
    if not license_accepted(model_id):
        raise PermissionError(f"Accept the {model['license']} for {model_id} before downloading")
    # The model and its native runtime are a single user-facing download.  A
    # model can already be present from an earlier build, so start/check the
    # runtime installation before the early-ready return below as well.
    await start_nemo_install()
    existing = _nemo_download_tasks.get(model_id)
    if existing and not existing.done():
        return nemo_download_status(model_id)
    if existing_nemo_model_path(model_id).is_file() and existing_nemo_model_path(model_id).stat().st_size > 0:
        return nemo_download_status(model_id)

    _nemo_download_tasks[model_id] = asyncio.create_task(_run_nemo_download(model_id))
    return nemo_download_status(model_id)


def _nemo_executable_candidates() -> list[Path]:
    return [
        PROJECT_ROOT / "tools" / "nemo-speech" / "nemo-speech.exe",
        PROJECT_ROOT / "tools" / "nemo-speech" / "nemo-speech",
        PROJECT_ROOT / "tools" / "nemo-speech" / "bin" / "nemo-speech.exe",
        PROJECT_ROOT / "tools" / "nemo-speech" / "bin" / "nemo-speech",
        PROJECT_ROOT / "tools" / "nemo-speech.cpp" / "build" / "bin" / "nemo-speech.exe",
        PROJECT_ROOT / "tools" / "nemo-speech.cpp" / "build" / "bin" / "nemo-speech",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "NeMoSpeech" / "bin" / "nemo-speech.exe",
    ]


def nemo_executable_path() -> str | None:
    for candidate in _nemo_executable_candidates():
        if candidate.is_file():
            return str(candidate)
    return shutil.which("nemo-speech")


def nemo_install_status() -> dict[str, Any]:
    """Return the current native runtime installation state for the UI."""
    executable = nemo_executable_path()
    if executable:
        return {**_nemo_install_state, "status": "ready", "executable": executable, "error": None}
    return dict(_nemo_install_state)


async def _run_nemo_install() -> None:
    global _nemo_install_state
    script = PROJECT_ROOT / "scripts" / "windows" / "install_nemo_speech.ps1"
    if nemo_executable_path():
        _nemo_install_state.update(status="ready", executable=nemo_executable_path(), error=None, finished_at=time.time())
        return
    if sys.platform != "win32":
        _nemo_install_state.update(status="error", error="Automatic NeMo-Speech.cpp installation is currently supported on Windows only.", finished_at=time.time())
        return
    if not script.is_file():
        _nemo_install_state.update(status="error", error=f"Installer script not found: {script}", finished_at=time.time())
        return
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        _nemo_install_state.update(status="error", error="PowerShell was not found; install NeMo-Speech.cpp manually.", finished_at=time.time())
        return
    _nemo_install_state.update(status="installing", executable=None, error=None, last_output="Starting the official NVIDIA installer…", started_at=time.time(), finished_at=None)
    try:
        process = await asyncio.create_subprocess_exec(
            powershell,
            "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(script), "-Root", str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        output_tail: list[str] = []
        assert process.stdout is not None
        async for raw_line in process.stdout:
            line = raw_line.decode(errors="replace").strip()
            if line:
                output_tail.append(line)
                output_tail = output_tail[-8:]
                _nemo_install_state["last_output"] = line
        return_code = await process.wait()
        executable = nemo_executable_path()
        if return_code == 0 and executable:
            _nemo_install_state.update(status="ready", executable=executable, error=None, last_output="NeMo-Speech.cpp is ready.", finished_at=time.time())
        else:
            detail = _nemo_install_state.get("last_output") or f"Installer exited with code {return_code}."
            _nemo_install_state.update(status="error", executable=executable, error=detail, last_output="\n".join(output_tail), finished_at=time.time())
    except Exception as exc:
        logger.exception("Failed installing NeMo-Speech.cpp")
        _nemo_install_state.update(status="error", error=str(exc), finished_at=time.time())


async def start_nemo_install() -> dict[str, Any]:
    """Start the official runtime installer once and return immediately."""
    global _nemo_install_task
    if nemo_executable_path():
        _nemo_install_state.update(status="ready", executable=nemo_executable_path(), error=None)
        return nemo_install_status()
    if _nemo_install_task and not _nemo_install_task.done():
        return nemo_install_status()
    _nemo_install_task = asyncio.create_task(_run_nemo_install())
    return nemo_install_status()


class NemoSidecarManager:
    """Best-effort lifecycle manager for one native nemo-speech process."""

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.model_id: str | None = None
        self.port = SIDECAR_PORT
        self.ready = False
        self.device = "unknown"
        self.error: str | None = None
        self._lock = asyncio.Lock()

    def executable(self) -> str | None:
        return nemo_executable_path()

    async def stop(self) -> None:
        process = self.process
        self.ready = False
        self.process = None
        self.model_id = None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def _probe(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                ready = await client.get(f"http://127.0.0.1:{self.port}/ready")
                if ready.is_success:
                    data = ready.json() if ready.headers.get("content-type", "").startswith("application/json") else {}
                    self.device = str(data.get("device") or data.get("gpu") or "cuda")
                    return True
        except Exception:
            return False
        return False

    async def ensure(self, model_id: str, chunk_ms: int = 320) -> bool:
        model = nemo_model(model_id)
        if not model:
            raise ValueError(f"Unknown Nemotron model: {model_id}")
        async with self._lock:
            if self.model_id == model_id and self.ready and await self._probe():
                return True
            # START_ALL may own the sidecar instead of this backend process.
            # Reuse an already-ready listener rather than starting a second
            # process on the same port.
            if self.process is None and await self._probe():
                self.model_id = model_id
                self.ready = True
                self.error = None
                return True
            await self.stop()
            model_path = existing_nemo_model_path(model_id)
            if not model_path.exists():
                self.error = f"Model file is not downloaded: {model_id}"
                return False
            executable = self.executable()
            if not executable:
                self.error = "NeMo-Speech.cpp executable was not found. Run scripts\\windows\\install_nemo_speech.ps1, then restart the project; Faster-Whisper fallback remains available."
                return False
            right_context = CHUNK_RIGHT_CONTEXT.get(int(chunk_ms), 3)
            command = [
                executable,
                "serve",
                "--host", "127.0.0.1",
                "--port", str(self.port),
                "--asr-model", str(model_path),
                "--asr.backend.gpu", "0",
                "--asr.streaming.rnnt_right_context", str(right_context),
            ]
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=str(PROJECT_ROOT),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as exc:
                self.error = str(exc)
                return False
            for _ in range(60):
                if await self._probe():
                    self.model_id = model_id
                    self.ready = True
                    self.error = None
                    return True
                if self.process.returncode is not None:
                    break
                await asyncio.sleep(0.25)
            self.error = "NeMo-Speech.cpp did not become ready"
            await self.stop()
            return False

    async def runtime(self, configured_model: str) -> dict[str, Any]:
        probe = await self._probe()
        sidecar_active = bool(probe and (self.ready or self.model_id or str(configured_model).startswith("nemotron-")))
        configured_nemo = str(configured_model).startswith("nemotron-")
        if configured_nemo and not probe:
            if not self.executable():
                self.error = "NeMo-Speech.cpp executable was not found. Run scripts\\windows\\install_nemo_speech.ps1, then restart the project; Faster-Whisper fallback remains available."
            elif nemo_model(configured_model) and not existing_nemo_model_path(configured_model).exists():
                self.error = f"Model file is not downloaded: {configured_model}"
            elif self.error and (
                self.error.startswith("NeMo-Speech.cpp executable was not found")
                or self.error.startswith("Model file is not downloaded")
            ):
                # A user may install the sidecar or finish a model download
                # while the UI remains open.  Do not keep showing the stale
                # missing-dependency error after a refresh.
                self.error = None
        return {
            "provider": "nemo_speech" if sidecar_active else "faster_whisper",
            "model": self.model_id or configured_model,
            "device": self.device if probe else "cuda (configured)" if configured_model.startswith("nemotron-") else "unknown",
            "ready": sidecar_active,
            "streaming": sidecar_active,
            "sidecar_url": f"http://127.0.0.1:{self.port}",
            "sidecar_port": self.port,
            "error": self.error,
            "sidecar_installed": bool(self.executable()),
            "model_downloaded": bool(existing_nemo_model_path(configured_model).exists()) if configured_nemo and nemo_model(configured_model) else False,
            "installation": nemo_install_status(),
        }


nemo_sidecar = NemoSidecarManager()
