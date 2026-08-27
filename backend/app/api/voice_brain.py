from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.agent.voice_brain import voice_brain
from app.core.config import VoiceBrainConfig, save_config, settings

router = APIRouter()


class VoiceBrainSessionOpen(BaseModel):
    session_id: str
    surface: str
    channel_key: str = ""
    conversation_id: str | None = None
    master_preset_id: str | None = None
    enabled: bool = True
    phase: str = "listening"


class VoiceBrainHeartbeat(BaseModel):
    phase: str | None = None
    conversation_id: str | None = None
    enabled: bool | None = None


class VoiceBrainEventCreate(BaseModel):
    event_type: str
    source: str = "web_voice"
    priority: int = Field(default=50, ge=0, le=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class VoiceBrainSettingsUpdate(BaseModel):
    enabled: bool | None = None
    tick_seconds: float | None = None
    min_silence_seconds: float | None = None
    min_speak_cooldown_seconds: float | None = None
    soft_max_silence_seconds: float | None = None
    hard_max_silence_seconds: float | None = None
    max_proactive_turns_per_hour: int | None = None
    decision_temperature: float | None = None
    decision_max_tokens: int | None = None
    minimum_speak_confidence: float | None = None
    event_ttl_seconds: float | None = None
    max_pending_events: int | None = None
    reflection_enabled: bool | None = None
    auto_memory_enabled: bool | None = None
    evaluator_enabled: bool | None = None
    allowed_autonomous_capabilities: list[str] | None = None


@router.get("/voice-brain/settings")
async def get_voice_brain_settings() -> dict[str, Any]:
    return settings.voice_brain.model_dump()


@router.patch("/voice-brain/settings")
async def update_voice_brain_settings(req: VoiceBrainSettingsUpdate) -> dict[str, Any]:
    data = settings.voice_brain.model_dump()
    data.update(req.model_dump(exclude_none=True))
    try:
        updated = VoiceBrainConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    settings.voice_brain = updated
    save_config(settings)
    return updated.model_dump()


@router.get("/voice-brain/status")
async def get_voice_brain_status(session_id: str | None = None) -> dict[str, Any]:
    return voice_brain.session_status(session_id)


@router.post("/voice-brain/sessions/open")
async def open_voice_brain_session(req: VoiceBrainSessionOpen) -> dict[str, Any]:
    try:
        return await voice_brain.open_session(**req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/voice-brain/sessions/{session_id}/heartbeat")
async def heartbeat_voice_brain_session(
    session_id: str,
    req: VoiceBrainHeartbeat,
) -> dict[str, Any]:
    try:
        return await voice_brain.heartbeat(session_id, **req.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Voice brain session is not open") from exc


@router.post("/voice-brain/sessions/{session_id}/events")
async def create_voice_brain_event(
    session_id: str,
    req: VoiceBrainEventCreate,
) -> dict[str, str]:
    try:
        event_id = await voice_brain.publish_event(session_id, **req.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Voice brain session is not open") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"event_id": event_id}


@router.post("/voice-brain/sessions/{session_id}/close")
async def close_voice_brain_session(session_id: str) -> dict[str, bool]:
    await voice_brain.close_session(session_id)
    return {"closed": True}


@router.websocket("/ws/voice-brain/{session_id}")
async def voice_brain_events(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    queue = voice_brain.subscribe(session_id)
    await websocket.send_json(
        {"type": "voice_brain_state", "data": voice_brain.session_status(session_id)}
    )
    try:
        while True:
            event = await queue.get()
            try:
                await websocket.send_json(event)
            finally:
                queue.task_done()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        voice_brain.unsubscribe(session_id, queue)
