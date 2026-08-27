"""Session-aware debug logger — writes to logs/<date>/session_<time>.log"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_current_session_file: Path | None = None
_initialized = False


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class _SessionFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        return f"[{ts}] [{record.levelname:5s}] [{record.name}] {record.getMessage()}"


def init_session(name: str = "session") -> Path:
    """Create a new log file for this session. Returns the file path."""
    global _current_session_file, _initialized

    today = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    day_dir = _ensure_dir(_LOG_DIR / today)
    log_file = day_dir / f"{name}_{time_str}.log"

    _current_session_file = log_file

    # Configure root logger to write to this file
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove existing file handlers
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler) and hasattr(h, "_session_file"):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_SessionFormatter())
    fh._session_file = True  # type: ignore[attr-defined]
    root.addHandler(fh)

    # Also ensure a stderr handler exists
    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in root.handlers):
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.WARNING)
        sh.setFormatter(_SessionFormatter())
        root.addHandler(sh)

    _initialized = True
    log = logging.getLogger("session")
    log.info("Session started: %s — log file: %s", name, log_file)
    return log_file


def get_session_log() -> Path | None:
    return _current_session_file


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Creates a session if none exists."""
    if not _initialized:
        init_session()
    return logging.getLogger(name)


def log_exception(logger: logging.Logger, msg: str, exc: Exception | None = None) -> None:
    """Log an exception with full traceback."""
    logger.error("%s: %s", msg, exc or "", exc_info=True)


def log_request(method: str, path: str, status: int, duration_ms: float, extra: dict[str, Any] | None = None) -> None:
    """Log an HTTP request."""
    log = logging.getLogger("http")
    parts = [f"{method} {path} → {status}", f"{duration_ms:.1f}ms"]
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}={v}")
    log.info(" | ".join(parts))


def cleanup_old_logs(max_days: int = 30) -> int:
    """Remove log directories older than max_days. Returns count removed."""
    if not _LOG_DIR.exists():
        return 0
    removed = 0
    cutoff = datetime.now().timestamp() - (max_days * 86400)
    for d in sorted(_LOG_DIR.iterdir()):
        if d.is_dir() and d.stat().st_mtime < cutoff:
            for f in d.iterdir():
                f.unlink(missing_ok=True)
            d.rmdir()
            removed += 1
    return removed
