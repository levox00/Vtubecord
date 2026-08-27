"""Live resource and service monitoring for the web UI.

The regular telemetry endpoint is intentionally presentation-oriented and contains
estimated model characteristics.  This module exposes measurements gathered from
the running host and local model services so the header monitor can distinguish
configured models from processes that are actually running.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter

from app.core.config import settings

try:  # psutil is optional so the API still works in minimal installations.
    import psutil
except ImportError:  # pragma: no cover - exercised only in minimal deployments
    psutil = None  # type: ignore[assignment]


router = APIRouter()


def _number(value: Any, digits: int = 1) -> float | int | None:
    """Convert a possibly unavailable metric into a JSON-safe number."""
    if value is None:
        return None
    try:
        rounded = round(float(value), digits)
        return int(rounded) if digits == 0 else rounded
    except (TypeError, ValueError):
        return None


def _gpu_processes() -> dict[int, dict[str, Any]]:
    """Return per-process GPU memory from nvidia-smi when CUDA is available."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {}
    try:
        output = subprocess.check_output(
            [
                smi,
                "--query-compute-apps=pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    result: dict[int, dict[str, Any]] = {}
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            vram = float(parts[2].split()[0])
        except (TypeError, ValueError, IndexError):
            continue
        result[pid] = {"pid": pid, "process_name": parts[1], "vram_mb": round(vram, 1)}
    return result


def _process_role(command: str) -> str | None:
    """Map a local model-server command line to a monitor role."""
    normalized = command.lower().replace("\\", "/")
    if "llama-server" in normalized or "llama.cpp" in normalized:
        return "llm"
    if "tools/zonos" in normalized or "zonos/server.py" in normalized:
        return "tts-zonos"
    if "tools/index-tts" in normalized or "index-tts/server.py" in normalized:
        return "tts-indextts"
    if "faster-whisper" in normalized or "whisper" in normalized:
        return "stt"
    return None


def _collect_processes() -> list[dict[str, Any]]:
    """Collect local model/backend process memory and CPU metrics."""
    if psutil is None:
        return []

    gpu_processes = _gpu_processes()
    processes: list[dict[str, Any]] = []
    try:
        iterator = psutil.process_iter(
            ["pid", "name", "cmdline", "status", "memory_info", "cpu_percent"]
        )
        for process in iterator:
            try:
                info = process.info
                pid = int(info.get("pid") or 0)
                command_parts = info.get("cmdline") or []
                command = " ".join(str(part) for part in command_parts if part)
                if pid == os.getpid():
                    role = "backend"
                else:
                    role = _process_role(command)
                if not role:
                    continue

                memory_info = info.get("memory_info")
                rss = getattr(memory_info, "rss", None)
                gpu = gpu_processes.get(pid, {})
                processes.append(
                    {
                        "role": role,
                        "pid": pid,
                        "name": str(info.get("name") or "python"),
                        "status": str(info.get("status") or "unknown"),
                        "ram_mb": _number((rss or 0) / (1024 * 1024), 1),
                        "vram_mb": gpu.get("vram_mb"),
                        "cpu_percent": _number(info.get("cpu_percent"), 1),
                    }
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError):
                continue
    except (psutil.Error, OSError):
        return []

    return sorted(processes, key=lambda item: (item["role"], item["pid"]))


def _host_metrics() -> dict[str, Any]:
    """Collect host CPU/RAM and reuse the GPU summary used by settings telemetry."""
    gpu = {
        "name": "Integrated / CPU",
        "total_vram_mb": 0,
        "used_vram_mb": 0,
        "free_vram_mb": 0,
        "utilization_pct": 0,
        "temperature_c": None,
        "available": False,
    }
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            output = subprocess.check_output(
                [
                    smi,
                    "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=1.5,
            ).strip()
            parts = [part.strip() for part in output.split(",")]
            if len(parts) >= 5:
                gpu = {
                    "name": parts[0],
                    "total_vram_mb": int(float(parts[1])),
                    "used_vram_mb": int(float(parts[2])),
                    "free_vram_mb": int(float(parts[3])),
                    "utilization_pct": int(float(parts[4])),
                    "temperature_c": int(float(parts[5])) if len(parts) > 5 else None,
                    "available": True,
                }
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    if psutil is None:
        return {
            "cpu_percent": None,
            "ram": {
                "total_mb": None,
                "used_mb": None,
                "available_mb": None,
                "percent": None,
                "available": False,
            },
            "gpu": gpu,
        }

    try:
        memory = psutil.virtual_memory()
        return {
            "cpu_percent": _number(psutil.cpu_percent(interval=None), 1),
            "ram": {
                "total_mb": _number(memory.total / (1024 * 1024), 1),
                "used_mb": _number(memory.used / (1024 * 1024), 1),
                "available_mb": _number(memory.available / (1024 * 1024), 1),
                "percent": _number(memory.percent, 1),
                "available": True,
            },
            "gpu": gpu,
        }
    except (psutil.Error, OSError):
        return {
            "cpu_percent": None,
            "ram": {
                "total_mb": None,
                "used_mb": None,
                "available_mb": None,
                "percent": None,
                "available": False,
            },
            "gpu": gpu,
        }


async def _probe_service(name: str, url: str) -> dict[str, Any]:
    """Probe a local model service without allowing a dead service to stall polling."""
    endpoint = url.rstrip("/") + "/health"
    started = asyncio.get_running_loop().time()
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(endpoint)
        elapsed = (asyncio.get_running_loop().time() - started) * 1000
        return {
            "name": name,
            "url": url,
            "status": "online" if response.is_success else "error",
            "latency_ms": _number(elapsed, 1),
            "http_status": response.status_code,
        }
    except (httpx.HTTPError, OSError):
        return {
            "name": name,
            "url": url,
            "status": "offline",
            "latency_ms": None,
            "http_status": None,
        }


def _model_record(
    model_id: str,
    label: str,
    model: str,
    engine: str,
    roles: set[str],
    processes: list[dict[str, Any]],
) -> dict[str, Any]:
    matching = [process for process in processes if process["role"] in roles]
    # Model servers often have a tiny launcher plus a large worker process. The
    # worker owns the model memory, so report the largest matching process.
    process = max(
        matching,
        key=lambda item: (item.get("vram_mb") or 0, item.get("ram_mb") or 0),
        default=None,
    )
    if process:
        status = "active"
    elif engine == "edge-tts":
        status = "cloud"
    else:
        status = "configured"
    return {
        "id": model_id,
        "label": label,
        "model": model or "Not configured",
        "engine": engine,
        "status": status,
        "pid": process.get("pid") if process else None,
        "process_name": process.get("name") if process else None,
        "ram_mb": process.get("ram_mb") if process else None,
        "vram_mb": process.get("vram_mb") if process else None,
        "cpu_percent": process.get("cpu_percent") if process else None,
    }


@router.get("/resource-monitor")
async def get_resource_monitor() -> dict[str, Any]:
    """Return current host, model-process, and local-service resource metrics."""
    processes = _collect_processes()
    services = await asyncio.gather(
        _probe_service("Zonos TTS", settings.tts.zonos_url),
        _probe_service("Index-TTS", settings.tts.indextts_url),
        _probe_service("LLM server", settings.llm.base_url.removesuffix("/v1")),
    )

    models = [
        _model_record("llm", "Language model", settings.llm.model, settings.llm.provider, {"llm"}, processes),
        _model_record("tts", "Text to speech", settings.tts.engine, settings.tts.engine, {f"tts-{settings.tts.engine}"}, processes),
        _model_record("stt", "Speech to text", settings.stt.model, "faster-whisper", {"stt", "backend"}, processes),
    ]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": _host_metrics(),
        "models": models,
        "processes": processes,
        "services": services,
    }
