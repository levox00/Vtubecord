"""Small bridge between Python logging and the in-app Logs panel."""
from __future__ import annotations

import logging


def add_event_log(level: str, source: str, message: str) -> None:
    """Write an event to the session log and the UI's bounded log buffer."""

    normalized = str(level or "info").lower()
    logger = logging.getLogger(source)
    log_method = getattr(logger, normalized, logger.info)
    log_method(str(message))
    try:
        # Import lazily to avoid the routes ↔ bridge import cycle at startup.
        from app.api.routes import add_log

        add_log(normalized, source, str(message))
    except Exception:
        # File logging above must remain available even during early startup.
        pass
