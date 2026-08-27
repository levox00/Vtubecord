from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import time as _time

from app.api.routes import router
from app.api.discord_bridge import router as bridge_router
from app.api.resource_monitor import router as resource_monitor_router
from app.api.character_profiles import router as character_profiles_router
from app.api.voice_brain import router as voice_brain_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.debug import init_session, get_logger, cleanup_old_logs

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Initialize session debug logger ---
    log_file = init_session("backend")
    log.info("Session log: %s", log_file)
    cleanup_old_logs(max_days=30)

    # Import legacy YAML/JSON character data into Markdown once. Runtime
    # emotions, memories, personality drift, and conversations remain in SQLite.
    from app.character.profiles import sync_active_profile
    from app.core.config import save_config
    sync_active_profile(settings)
    save_config(settings)

    # Ensure data directory exists for SQLite
    if "sqlite" in settings.database.url:
        db_path = settings.database.url.split("///")[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Create tables (Alembic will replace this in later phases)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info("Database tables created")

    try:
        from app.agent.voice_brain import voice_brain

        await voice_brain.start()
    except Exception as e:
        log.exception("Failed to start voice brain runtime: %s", e)

    # Start optional integration workers (discord) in background
    import asyncio
    try:
        from app.integrations.discord_worker import start_worker
        loop = asyncio.get_event_loop()
        start_worker(loop)
        log.info("Discord integration worker started")
    except Exception as e:
        log.exception("Failed to start integration workers: %s", e)

    yield

    # Shutdown integration workers
    try:
        from app.agent.voice_brain import voice_brain
        from app.api.discord_bridge import shutdown_event_tasks
        from app.integrations.discord_worker import stop_worker
        from app.discord_voice import stop_discord_voice_input
        await shutdown_event_tasks()
        await stop_discord_voice_input()
        await stop_worker()
        await voice_brain.stop()
        log.info("Discord integration worker stopped")
    except Exception:
        pass

    log.info("Session ended")
    await engine.dispose()


app = FastAPI(
    title="AI VTuber / Persistent Character",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request with method, path, status, and duration."""
    from app.debug import log_request as _log_request
    start = _time.monotonic()
    response = await call_next(request)
    elapsed = (_time.monotonic() - start) * 1000
    _log_request(request.method, request.url.path, response.status_code, elapsed)
    return response

app.include_router(router, prefix="/api")
app.include_router(bridge_router, prefix="/api")
app.include_router(resource_monitor_router, prefix="/api")
app.include_router(character_profiles_router, prefix="/api")
app.include_router(voice_brain_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "AI VTuber",
        "version": "0.1.0",
        "docs": "/docs",
    }
