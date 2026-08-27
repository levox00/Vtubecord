from __future__ import annotations

"""Managed downloadable GGUF models for the local llama.cpp runtime.

The application runs GGUF files through llama.cpp.  The upstream NVIDIA and
Google repositories publish Transformers/Safetensors weights, so the catalog
links the original model plus a documented llama.cpp-compatible conversion.
No model weights are bundled or redistributed by this project.
"""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from app.core.paths import data_root

logger = logging.getLogger(__name__)

PROJECT_ROOT = data_root()
GGUF_DIR = PROJECT_ROOT / "assets" / "models" / "gguf"
LICENSE_FILE = PROJECT_ROOT / "data" / "llm-model-license-acceptance.json"

# Q4_K_M is a practical quality/VRAM default for a local RTX setup.  These
# repositories are GGUF conversions for llama.cpp; ``official_source_url``
# makes that distinction explicit in the UI.
LLM_DOWNLOAD_CATALOG: list[dict[str, Any]] = [
    {
        "id": "mistral-nemo-minitron-8b-instruct-q4-k-m",
        "name": "NVIDIA Mistral-NeMo-Minitron 8B Instruct",
        "filename": "Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M.gguf",
        "size_bytes": 5_145_298_624,
        "quantization": "Q4_K_M",
        "parameters": "8B",
        "description": "Instruction-tuned NVIDIA Minitron model for local chat and character responses.",
        "source_url": "https://huggingface.co/bartowski/Mistral-NeMo-Minitron-8B-Instruct-GGUF",
        "official_source_url": "https://huggingface.co/nvidia/Mistral-NeMo-Minitron-8B-Instruct",
        "download_url": "https://huggingface.co/bartowski/Mistral-NeMo-Minitron-8B-Instruct-GGUF/resolve/main/Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M.gguf?download=true",
        "license": "NVIDIA Open Model License",
        "license_url": "https://huggingface.co/nvidia/Mistral-NeMo-Minitron-8B-Instruct/blob/main/LICENSE",
        "requires_hf_access": False,
    },
    {
        "id": "gemma-2-2b-it-q4-k-m",
        "name": "Google Gemma 2 2B IT",
        "filename": "gemma-2-2b-it-Q4_K_M.gguf",
        "size_bytes": 1_708_582_752,
        "quantization": "Q4_K_M",
        "parameters": "2B",
        "description": "Small instruction-tuned Gemma model; fast and lightweight for local chat.",
        "source_url": "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF",
        "official_source_url": "https://huggingface.co/google/gemma-2-2b-it",
        "download_url": "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf?download=true",
        "license": "Gemma Terms of Use",
        "license_url": "https://ai.google.dev/gemma/terms",
        # Google requires access approval on the official Hugging Face page.
        # The UI asks the user to do that before storing its local confirmation.
        "requires_hf_access": True,
    },
]

_download_states: dict[str, dict[str, Any]] = {}
_download_tasks: dict[str, asyncio.Task[None]] = {}


def catalog_model(model_id: str) -> dict[str, Any] | None:
    return next((model for model in LLM_DOWNLOAD_CATALOG if model["id"] == model_id), None)


def model_path(model_id: str) -> Path:
    model = catalog_model(model_id)
    if not model:
        raise ValueError(f"Unknown local LLM model: {model_id}")
    return GGUF_DIR / str(model["filename"])


def _partial_path(model_id: str) -> Path:
    target = model_path(model_id)
    return target.with_suffix(target.suffix + ".part")


def _partial_size(model_id: str) -> int:
    try:
        return _partial_path(model_id).stat().st_size
    except OSError:
        return 0


def _load_license_acceptance() -> dict[str, Any]:
    try:
        return json.loads(LICENSE_FILE.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}


def license_accepted(model_id: str) -> bool:
    record = _load_license_acceptance().get(model_id)
    return bool(isinstance(record, dict) and record.get("accepted"))


def accept_license(model_id: str) -> dict[str, Any]:
    model = catalog_model(model_id)
    if not model:
        raise ValueError(f"Unknown local LLM model: {model_id}")
    data = _load_license_acceptance()
    record = {
        "accepted": True,
        "model_id": model_id,
        "license": model["license"],
        "official_source_url": model["official_source_url"],
        "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    data[model_id] = record
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return record


def _update_download_state(model_id: str, **values: Any) -> dict[str, Any]:
    state = _download_states.setdefault(
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
    received = int(state.get("downloaded_bytes") or 0)
    state["progress_percent"] = round(received * 100 / total, 1) if isinstance(total, int) and total > 0 else None
    state["updated_at"] = time.time()
    return state


def download_status(model_id: str) -> dict[str, Any]:
    if not catalog_model(model_id):
        raise ValueError(f"Unknown local LLM model: {model_id}")
    target = model_path(model_id)
    if target.is_file() and target.stat().st_size > 0:
        size = target.stat().st_size
        return {
            "model": model_id,
            "status": "ready",
            "downloaded_bytes": size,
            "total_bytes": size,
            "progress_percent": 100.0,
            "speed_bytes_per_sec": None,
            "error": None,
            "started_at": None,
            "updated_at": None,
        }
    state = _download_states.get(model_id)
    if state:
        return {**state, "model": model_id}
    partial_size = _partial_size(model_id)
    return {
        "model": model_id,
        "status": "paused" if partial_size else "idle",
        "downloaded_bytes": partial_size,
        "total_bytes": None,
        "progress_percent": None,
        "speed_bytes_per_sec": None,
        "error": None,
        "started_at": None,
        "updated_at": None,
    }


def model_status(model_id: str) -> dict[str, Any]:
    model = catalog_model(model_id)
    if not model:
        raise ValueError(f"Unknown local LLM model: {model_id}")
    target = model_path(model_id)
    ready = target.is_file() and target.stat().st_size > 0
    return {
        **model,
        "size_gb": round((target.stat().st_size if ready else model["size_bytes"]) / (1024**3), 2),
        "downloaded": ready,
        "ready": ready,
        "license_accepted": license_accepted(model_id),
        "download": download_status(model_id),
    }


def list_models() -> list[dict[str, Any]]:
    """Return catalog items followed by manually copied local GGUF files."""
    result = [model_status(model["id"]) for model in LLM_DOWNLOAD_CATALOG]
    catalog_filenames = {str(model["filename"]) for model in LLM_DOWNLOAD_CATALOG}
    if GGUF_DIR.exists():
        for path in sorted(GGUF_DIR.glob("*.gguf")):
            if path.name in catalog_filenames:
                continue
            size = path.stat().st_size
            result.append(
                {
                    "id": f"local:{path.name}",
                    "name": path.stem,
                    "filename": path.name,
                    "size_bytes": size,
                    "size_gb": round(size / (1024**3), 2),
                    "quantization": None,
                    "parameters": None,
                    "description": "Local GGUF file",
                    "source_url": None,
                    "official_source_url": None,
                    "download_url": None,
                    "license": None,
                    "license_url": None,
                    "requires_hf_access": False,
                    "downloaded": True,
                    "ready": True,
                    "license_accepted": True,
                    "download": {
                        "model": f"local:{path.name}",
                        "status": "ready",
                        "downloaded_bytes": size,
                        "total_bytes": size,
                        "progress_percent": 100.0,
                        "speed_bytes_per_sec": None,
                        "error": None,
                        "started_at": None,
                        "updated_at": None,
                    },
                }
            )
    return result


async def download_model(
    model_id: str,
    progress_callback: Callable[[int, int | None, float], None] | None = None,
) -> dict[str, Any]:
    model = catalog_model(model_id)
    if not model:
        raise ValueError(f"Unknown local LLM model: {model_id}")
    if not license_accepted(model_id):
        raise PermissionError(f"Accept the {model['license']} before downloading this model")

    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    target = model_path(model_id)
    partial = _partial_path(model_id)
    existing_bytes = _partial_size(model_id)
    digest = hashlib.sha256()
    if existing_bytes:
        with partial.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)

    async with httpx.AsyncClient(
        follow_redirects=True,
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
                # Hugging Face's Xet ``ETag`` is not guaranteed to be the
                # downloaded file's SHA-256.  Only trust an explicit checksum
                # header; the local digest is always recorded after download.
                linked_sha = head.headers.get("x-linked-sha256", "").strip('"')
                if len(linked_sha) == 64 and all(char in "0123456789abcdefABCDEF" for char in linked_sha):
                    expected_sha = linked_sha.lower()
        except httpx.HTTPError:
            # The subsequent GET provides the useful error if the CDN is not
            # reachable or does not support a HEAD request.
            pass

        # A previous process can finish writing the .part file and exit before
        # the final rename.  Asking a CDN for ``bytes=<full-size>-`` produces
        # 416, so verify that complete partial first and promote it directly.
        if existing_bytes and expected_size is not None and existing_bytes >= expected_size:
            partial_digest = digest.hexdigest()
            if existing_bytes == expected_size and (not expected_sha or partial_digest == expected_sha):
                partial.replace(target)
                target.with_suffix(target.suffix + ".sha256").write_text(partial_digest + "\n", encoding="ascii")
                return {"status": "ready", "model": model_id, "path": str(target), "filename": target.name, "size_bytes": expected_size}
            # The partial is too large or failed its digest check.  Restarting
            # from zero is safer than appending to a corrupted file.
            partial.unlink(missing_ok=True)
            existing_bytes = 0
            digest = hashlib.sha256()

        headers = {"Range": f"bytes={existing_bytes}-"} if existing_bytes else {}
        async with client.stream("GET", str(model["download_url"]), headers=headers) as response:
            response.raise_for_status()
            resumed = response.status_code == 206 and existing_bytes > 0
            if not resumed:
                existing_bytes = 0
                digest = hashlib.sha256()
            content_range = response.headers.get("content-range", "")
            if content_range.rsplit("/", 1)[-1].isdigit():
                expected_size = int(content_range.rsplit("/", 1)[-1])
            if expected_size is None:
                content_length = response.headers.get("content-length")
                if content_length and content_length.isdigit():
                    expected_size = existing_bytes + int(content_length)

            downloaded = existing_bytes
            started = time.monotonic()
            if progress_callback:
                progress_callback(downloaded, expected_size, 0.0)
            with partial.open("ab" if resumed else "wb") as handle:
                async for block in response.aiter_bytes(1024 * 1024):
                    if not block:
                        continue
                    handle.write(block)
                    digest.update(block)
                    downloaded += len(block)
                    if progress_callback:
                        elapsed = max(time.monotonic() - started, 0.001)
                        progress_callback(downloaded, expected_size, (downloaded - existing_bytes) / elapsed)

    actual_size = partial.stat().st_size
    digest_value = digest.hexdigest()
    if expected_size is not None and actual_size != expected_size:
        raise IOError(f"Model size verification failed: expected {expected_size}, got {actual_size}")
    if expected_sha and digest_value != expected_sha:
        raise IOError("Model SHA-256 verification failed")
    partial.replace(target)
    target.with_suffix(target.suffix + ".sha256").write_text(digest_value + "\n", encoding="ascii")
    return {"status": "ready", "model": model_id, "path": str(target), "filename": target.name, "size_bytes": actual_size}


async def _run_download(model_id: str) -> None:
    _update_download_state(
        model_id,
        status="downloading",
        downloaded_bytes=_partial_size(model_id),
        error=None,
        started_at=time.time(),
    )

    def report(downloaded: int, total: int | None, speed: float) -> None:
        _update_download_state(
            model_id,
            status="downloading",
            downloaded_bytes=downloaded,
            total_bytes=total,
            speed_bytes_per_sec=round(speed, 1) if speed > 0 else None,
            error=None,
        )

    try:
        result = await download_model(model_id, progress_callback=report)
        _update_download_state(
            model_id,
            status="ready",
            downloaded_bytes=int(result["size_bytes"]),
            total_bytes=int(result["size_bytes"]),
            speed_bytes_per_sec=None,
            error=None,
        )
        logger.info("Downloaded local LLM %s", model_id)
    except asyncio.CancelledError:
        _update_download_state(model_id, status="paused", speed_bytes_per_sec=None)
        raise
    except Exception as exc:
        logger.exception("Failed downloading local LLM %s", model_id)
        _update_download_state(
            model_id,
            status="error",
            downloaded_bytes=_partial_size(model_id),
            speed_bytes_per_sec=None,
            error=str(exc),
        )


async def start_download(model_id: str) -> dict[str, Any]:
    model = catalog_model(model_id)
    if not model:
        raise ValueError(f"Unknown local LLM model: {model_id}")
    if not license_accepted(model_id):
        raise PermissionError(f"Accept the {model['license']} before downloading this model")
    task = _download_tasks.get(model_id)
    if task and not task.done():
        return download_status(model_id)
    if model_path(model_id).is_file() and model_path(model_id).stat().st_size > 0:
        return download_status(model_id)
    _download_tasks[model_id] = asyncio.create_task(_run_download(model_id))
    return download_status(model_id)
