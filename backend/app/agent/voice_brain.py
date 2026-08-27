from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from app.character.service import get_or_create_character
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.llm.base import ChatMessage
from app.llm.openai_compatible import create_llm_provider
from app.memory.context import estimate_tokens, pack_recent_messages
from app.models.character import (
    Memory,
    Message,
    VoiceBrainEvent,
    VoiceBrainInteraction,
    VoiceBrainSession,
)

logger = logging.getLogger(__name__)

CapabilityHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _default_internal_state() -> dict[str, float]:
    return {
        "curiosity": 0.70,
        "social_drive": 0.55,
        "boredom": 0.10,
        "energy": 0.70,
        "focus": 0.55,
        "uncertainty": 0.20,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract one JSON object from strict, fenced, or lightly wrapped output."""

    value = str(text or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", value):
        try:
            parsed, _ = decoder.raw_decode(value[match.start() :])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


@dataclass
class BrainDecision:
    action: str = "WAIT"
    reason: str = "No worthwhile autonomous action."
    topic: str = ""
    confidence: float = 0.0
    next_wake_seconds: float = 45.0
    capability: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    speak_after_action: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "topic": self.topic,
            "confidence": self.confidence,
            "next_wake_seconds": self.next_wake_seconds,
            "capability": self.capability,
            "arguments": self.arguments,
            "speak_after_action": self.speak_after_action,
        }


def parse_brain_decision(text: str) -> BrainDecision:
    payload = _extract_json_object(text)
    if not payload:
        return BrainDecision(reason="The executive response was not valid JSON.")
    action = str(payload.get("action") or "WAIT").strip().upper()
    if action not in {"WAIT", "SPEAK", "START_TOPIC", "OBSERVE", "REFLECT", "ACT"}:
        action = "WAIT"
    arguments = payload.get("arguments")
    return BrainDecision(
        action=action,
        reason=str(payload.get("reason") or "").strip()[:600],
        topic=str(payload.get("topic") or "").strip()[:400],
        confidence=_clamp(float(payload.get("confidence") or 0.0)),
        next_wake_seconds=max(10.0, min(600.0, float(payload.get("next_wake_seconds") or 45.0))),
        capability=str(payload.get("capability") or "").strip()[:128],
        arguments=dict(arguments) if isinstance(arguments, dict) else {},
        speak_after_action=bool(payload.get("speak_after_action", False)),
    )


@dataclass
class PendingEvent:
    id: str
    event_type: str
    source: str
    priority: int
    payload: dict[str, Any]
    created_monotonic: float


@dataclass
class RuntimeVoiceSession:
    id: str
    surface: str
    channel_key: str
    conversation_id: str | None
    master_preset_id: str | None
    enabled: bool
    phase: str = "listening"
    active: bool = True
    last_heartbeat: float = field(default_factory=time.monotonic)
    last_user_monotonic: float = field(default_factory=time.monotonic)
    last_ai_monotonic: float = field(default_factory=time.monotonic)
    next_wake_monotonic: float = field(default_factory=time.monotonic)
    proactive_turns: int = 0
    window_started_monotonic: float = field(default_factory=time.monotonic)
    turns_since_summary: int = 0
    last_decision: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    internal_state: dict[str, float] = field(default_factory=_default_internal_state)
    events: deque[PendingEvent] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class Capability:
    name: str
    description: str
    handler: CapabilityHandler
    autonomous_safe: bool = False


class VoiceBrainRuntime:
    """Persistent event-driven executive for live voice sessions only.

    The runtime decides *whether* an interaction is worthwhile. Character chat
    generation still decides *how* the chosen thought is expressed. External
    actions are separately allowlisted capabilities so a decision can never
    become arbitrary API/game access.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, RuntimeVoiceSession] = {}
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._capabilities: dict[str, Capability] = {}
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._decision_semaphore = asyncio.Semaphore(1)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run_loop(), name="voice-brain-runtime")
        logger.info("Voice brain runtime started")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._sessions.clear()
        self._subscribers.clear()
        logger.info("Voice brain runtime stopped")

    def register_capability(
        self,
        name: str,
        description: str,
        handler: CapabilityHandler,
        *,
        autonomous_safe: bool = False,
    ) -> None:
        """Register a future game/OBS capability behind an explicit safety bit."""

        normalized = str(name or "").strip()
        if not normalized or not re.fullmatch(r"[a-zA-Z0-9_.-]+", normalized):
            raise ValueError("Invalid voice-brain capability name")
        self._capabilities[normalized] = Capability(
            name=normalized,
            description=str(description or "").strip(),
            handler=handler,
            autonomous_safe=bool(autonomous_safe),
        )

    async def open_session(
        self,
        *,
        session_id: str,
        surface: str,
        channel_key: str = "",
        conversation_id: str | None = None,
        master_preset_id: str | None = None,
        enabled: bool = True,
        phase: str = "listening",
    ) -> dict[str, Any]:
        session_id = str(session_id or "").strip()[:256]
        if not session_id:
            raise ValueError("session_id is required")
        if surface not in {"web_voice", "discord_voice"}:
            raise ValueError("Voice brain sessions are limited to web_voice and discord_voice")

        now = time.monotonic()
        existing = self._sessions.get(session_id)
        if existing:
            existing.active = True
            existing.enabled = bool(enabled)
            existing.phase = phase
            existing.last_heartbeat = now
            existing.channel_key = str(channel_key or existing.channel_key)
            existing.conversation_id = conversation_id or existing.conversation_id
            existing.master_preset_id = master_preset_id or existing.master_preset_id
            await self._persist_session(existing)
            await self._emit(existing.id, "state", self._public_session(existing))
            return self._public_session(existing)

        async with AsyncSessionLocal() as db:
            character = await get_or_create_character(db)
            result = await db.execute(
                select(VoiceBrainSession).where(VoiceBrainSession.id == session_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = VoiceBrainSession(
                    id=session_id,
                    character_id=character.id,
                    surface=surface,
                    channel_key=str(channel_key or ""),
                    conversation_id=conversation_id,
                    enabled=bool(enabled),
                    phase=phase,
                    internal_state={},
                )
                db.add(row)
                await db.flush()
            internal = dict(row.internal_state or {})
            created = RuntimeVoiceSession(
                id=session_id,
                surface=surface,
                channel_key=str(channel_key or row.channel_key or ""),
                conversation_id=conversation_id or row.conversation_id,
                master_preset_id=master_preset_id,
                enabled=bool(enabled),
                phase=phase,
                proactive_turns=int(row.proactive_turns_in_window or 0),
                turns_since_summary=int(row.turns_since_summary or 0),
                internal_state={
                    **_default_internal_state(),
                    **{key: _clamp(value) for key, value in internal.items() if isinstance(value, (int, float))},
                },
            )
            last_user = _aware(row.last_user_at)
            last_ai = _aware(row.last_ai_at)
            wall_now = _utcnow()
            if last_user:
                created.last_user_monotonic = now - max(0.0, (wall_now - last_user).total_seconds())
            if last_ai:
                created.last_ai_monotonic = now - max(0.0, (wall_now - last_ai).total_seconds())
            self._sessions[session_id] = created
            row.surface = surface
            row.channel_key = created.channel_key
            row.conversation_id = created.conversation_id
            row.enabled = created.enabled
            row.phase = phase
            await db.commit()

        await self.publish_event(
            session_id,
            "voice_session_started",
            source=surface,
            priority=35,
            payload={"surface": surface},
        )
        await self._emit(session_id, "state", self._public_session(created))
        return self._public_session(created)

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        session.active = False
        session.phase = "idle"
        await self._persist_session(session)
        await self._emit(session.id, "state", self._public_session(session))

    async def heartbeat(
        self,
        session_id: str,
        *,
        phase: str | None = None,
        conversation_id: str | None = None,
        enabled: bool | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        session.active = True
        session.last_heartbeat = time.monotonic()
        if phase:
            session.phase = phase
        if conversation_id:
            session.conversation_id = conversation_id
        if enabled is not None:
            session.enabled = bool(enabled)
        if persist:
            await self._persist_session(session)
        return self._public_session(session)

    async def publish_event(
        self,
        session_id: str,
        event_type: str,
        *,
        source: str = "runtime",
        priority: int = 50,
        payload: dict[str, Any] | None = None,
        db_session: Any | None = None,
    ) -> str:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        cfg = settings.voice_brain
        event_payload = dict(payload or {})
        if len(json.dumps(event_payload, ensure_ascii=False, default=str)) > 32768:
            raise ValueError("Voice brain event payload exceeds 32 KiB")
        event = PendingEvent(
            id=str(uuid.uuid4()),
            event_type=str(event_type or "observation")[:64],
            source=str(source or "runtime")[:64],
            priority=max(0, min(100, int(priority))),
            payload=event_payload,
            created_monotonic=time.monotonic(),
        )
        while len(session.events) >= max(8, int(cfg.max_pending_events)):
            # Prefer dropping the oldest low-priority perception.
            lowest = min(range(len(session.events)), key=lambda index: session.events[index].priority)
            del session.events[lowest]
        session.events.append(event)
        if event.event_type in {"user_spoke", "user_returned", "barge_in"}:
            session.last_user_monotonic = time.monotonic()
            session.internal_state["boredom"] = 0.02
            session.internal_state["social_drive"] = _clamp(session.internal_state.get("social_drive", 0.5) + 0.08)
            session.next_wake_monotonic = time.monotonic() + float(cfg.min_silence_seconds)
        elif event.priority >= 75:
            session.next_wake_monotonic = min(session.next_wake_monotonic, time.monotonic() + 0.25)
        if db_session is not None:
            db_session.add(
                VoiceBrainEvent(
                    id=event.id,
                    session_id=session.id,
                    event_type=event.event_type,
                    source=event.source,
                    priority=event.priority,
                    payload=event.payload,
                )
            )
        else:
            await self._persist_event(session, event)
        await self._emit(session_id, "event", self._public_event(event))
        return event.id

    async def note_completed_turn(
        self,
        session_id: str,
        *,
        conversation_id: str,
        role: str,
        text: str,
        proactive: bool = False,
    ) -> None:
        session = self._sessions.get(session_id)
        if not session:
            return
        session.conversation_id = conversation_id
        now = time.monotonic()
        if role == "user":
            session.last_user_monotonic = now
        else:
            session.last_ai_monotonic = now
            session.internal_state["social_drive"] = _clamp(session.internal_state.get("social_drive", 0.5) - 0.18)
            session.internal_state["boredom"] = 0.0
            if proactive:
                session.proactive_turns += 1
        session.turns_since_summary += 1
        await self._persist_session(session)
        if (
            settings.voice_brain.reflection_enabled
            and session.turns_since_summary >= max(4, settings.memory.summary_trigger_messages)
        ):
            asyncio.create_task(self._refresh_summary(session), name=f"voice-brain-reflect:{session.id}")

    def session_status(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            session = self._sessions.get(session_id)
            return self._public_session(session) if session else {"id": session_id, "active": False}
        return {
            "enabled": bool(settings.voice_brain.enabled),
            "running": bool(self._task and not self._task.done()),
            "sessions": [self._public_session(item) for item in self._sessions.values()],
            "capabilities": [
                {
                    "name": item.name,
                    "description": item.description,
                    "autonomous_safe": item.autonomous_safe,
                    "allowed": item.name in settings.voice_brain.allowed_autonomous_capabilities,
                }
                for item in self._capabilities.values()
            ],
        }

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(session_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    def subscriber_count(self, session_id: str) -> int:
        return len(self._subscribers.get(session_id) or ())

    async def _emit(self, session_id: str, event_type: str, data: dict[str, Any]) -> None:
        envelope = {"type": f"voice_brain_{event_type}", "data": data}
        for queue in list(self._subscribers.get(session_id) or ()):
            if queue.full():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                pass

    async def _run_loop(self) -> None:
        try:
            while not self._stopping.is_set():
                await asyncio.sleep(max(0.5, min(5.0, float(settings.voice_brain.tick_seconds))))
                now = time.monotonic()
                for session in list(self._sessions.values()):
                    if self._should_schedule(session, now):
                        asyncio.create_task(self._consider(session), name=f"voice-brain-decide:{session.id}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Voice brain runtime loop failed")

    def _should_schedule(
        self,
        session: RuntimeVoiceSession,
        now: float,
        *,
        ignore_owned_lock: bool = False,
    ) -> bool:
        cfg = settings.voice_brain
        if (
            not cfg.enabled
            or not session.enabled
            or not session.active
            or (session.lock.locked() and not ignore_owned_lock)
        ):
            return False
        if session.surface == "web_voice" and self.subscriber_count(session.id) == 0:
            return False
        if session.surface == "web_voice" and now - session.last_heartbeat > 20.0:
            return False
        if session.phase not in {"listening", "idle"}:
            return False
        if now < session.next_wake_monotonic:
            return False
        silence = now - max(session.last_user_monotonic, session.last_ai_monotonic)
        urgent = any(item.priority >= 80 for item in session.events)
        if silence < float(cfg.min_silence_seconds) and not urgent:
            return False
        if now - session.last_ai_monotonic < float(cfg.min_speak_cooldown_seconds) and not urgent:
            return False
        if now - session.window_started_monotonic >= 3600.0:
            session.window_started_monotonic = now
            session.proactive_turns = 0
        if session.proactive_turns >= max(0, int(cfg.max_proactive_turns_per_hour)):
            session.next_wake_monotonic = session.window_started_monotonic + 3600.0
            return False
        return True

    async def _consider(self, session: RuntimeVoiceSession) -> None:
        async with session.lock:
            if not self._should_schedule(session, time.monotonic(), ignore_owned_lock=True):
                return
            session.phase = "deciding"
            await self._emit(session.id, "state", self._public_session(session))
            try:
                decision, consumed = await self._decide(session)
                session.last_decision = decision.as_dict()
                session.last_error = None
                await self._record_decision(session, consumed, decision)
                await self._apply_decision(session, decision, consumed)
            except Exception as exc:
                logger.exception("Voice brain decision failed for %s", session.id)
                session.last_error = str(exc)[:800]
                session.next_wake_monotonic = time.monotonic() + 60.0
                await self._emit(
                    session.id,
                    "error",
                    {"message": "Voice brain decision failed", "detail": session.last_error},
                )
            finally:
                if session.phase == "deciding":
                    session.phase = "listening"
                await self._persist_session(session)
                await self._emit(session.id, "state", self._public_session(session))

    def _evolve_internal_state(self, session: RuntimeVoiceSession) -> None:
        cfg = settings.voice_brain
        silence = max(0.0, time.monotonic() - max(session.last_user_monotonic, session.last_ai_monotonic))
        soft = max(30.0, float(cfg.soft_max_silence_seconds))
        session.internal_state["boredom"] = _clamp(silence / soft)
        session.internal_state["social_drive"] = _clamp(
            session.internal_state.get("social_drive", 0.5) + min(0.08, silence / soft * 0.035)
        )
        session.internal_state["curiosity"] = _clamp(
            session.internal_state.get("curiosity", 0.7) + (0.02 if session.events else -0.005)
        )

    async def _decide(self, session: RuntimeVoiceSession) -> tuple[BrainDecision, list[PendingEvent]]:
        self._evolve_internal_state(session)
        cfg = settings.voice_brain
        now = time.monotonic()
        ttl = max(60.0, float(cfg.event_ttl_seconds))
        while session.events and now - session.events[0].created_monotonic > ttl:
            session.events.popleft()
        consumed = sorted(list(session.events), key=lambda item: (-item.priority, item.created_monotonic))[:12]
        silence = now - max(session.last_user_monotonic, session.last_ai_monotonic)
        context = await self._decision_context(session)
        events_text = "\n".join(
            f"- {item.event_type} (source={item.source}, priority={item.priority}): "
            f"{json.dumps(item.payload, ensure_ascii=False, default=str)[:700]}"
            for item in consumed
        ) or "- periodic wake with no new salient event"
        capabilities = [
            f"- {item.name}: {item.description}"
            for item in self._capabilities.values()
            if item.autonomous_safe and item.name in cfg.allowed_autonomous_capabilities
        ]
        system = ChatMessage(
            role="system",
            content=(
                "You are the private executive controller of a live AI character. You decide whether it is "
                "worth interrupting a live voice call; you do not write the spoken reply. Silence is a valid "
                "and often best action. Prefer specific follow-ups, genuine observations, unfinished topics, "
                "and salient game/world events over generic check-ins. Never speak just because a timer fired. "
                "Do not repeat a recent topic. Do not expose internal state. Return exactly one JSON object with: "
                "action (WAIT|SPEAK|START_TOPIC|OBSERVE|REFLECT|ACT), reason, topic, confidence (0..1), "
                "next_wake_seconds (10..600), capability, arguments, speak_after_action (boolean). "
                "ACT is allowed only for a listed capability and normally should not be narrated."
            ),
        )
        user = ChatMessage(
            role="user",
            content=(
                f"Surface: {session.surface}\nPhase: {session.phase}\nSilence seconds: {silence:.1f}\n"
                f"Proactive budget used: {session.proactive_turns}/{cfg.max_proactive_turns_per_hour}\n"
                f"Internal state: {json.dumps(session.internal_state, sort_keys=True)}\n"
                f"Conversation summary: {context.get('summary') or '(none yet)'}\n"
                f"Open loops: {json.dumps(context.get('open_loops') or [], ensure_ascii=False)}\n"
                f"Recent observations:\n{events_text}\n"
                f"Autonomous capabilities:\n{chr(10).join(capabilities) if capabilities else '- none; ACT is unavailable'}"
            ),
        )
        async with self._decision_semaphore:
            response = await create_llm_provider().generate(
                [system, user],
                temperature=float(cfg.decision_temperature),
                max_tokens=int(cfg.decision_max_tokens),
            )
        decision = parse_brain_decision(response.content)
        if decision.action in {"SPEAK", "START_TOPIC"} and decision.confidence < float(cfg.minimum_speak_confidence):
            decision.action = "WAIT"
            decision.reason = "Speak confidence was below the configured threshold."
        if decision.action == "ACT" and not self._capability_allowed(decision.capability):
            decision.action = "OBSERVE"
            decision.reason = "Requested autonomous capability is unavailable or not allowlisted."
        return decision, consumed

    async def _apply_decision(
        self,
        session: RuntimeVoiceSession,
        decision: BrainDecision,
        events: list[PendingEvent],
    ) -> None:
        now = time.monotonic()
        if decision.action == "REFLECT":
            await self._refresh_summary(session)
            session.next_wake_monotonic = now + decision.next_wake_seconds
            return
        capability_result: dict[str, Any] | None = None
        if decision.action == "ACT":
            capability_result = await self._execute_capability(decision.capability, decision.arguments)
            if not capability_result.get("ok"):
                session.next_wake_monotonic = now + decision.next_wake_seconds
                return
            await self.publish_event(
                session.id,
                "capability_result",
                source=decision.capability,
                priority=60,
                payload=capability_result,
            )
            if not decision.speak_after_action:
                await self._store_interaction(
                    session,
                    decision,
                    events,
                    "",
                    {"surface": session.surface, "capability_result": capability_result},
                )
                session.next_wake_monotonic = now + decision.next_wake_seconds
                return
        if decision.action in {"SPEAK", "START_TOPIC", "ACT"}:
            await self._generate_and_deliver(session, decision, events, capability_result)
            session.next_wake_monotonic = time.monotonic() + max(
                float(settings.voice_brain.min_speak_cooldown_seconds),
                decision.next_wake_seconds,
            )
            return
        session.next_wake_monotonic = now + decision.next_wake_seconds

    async def _generate_and_deliver(
        self,
        session: RuntimeVoiceSession,
        decision: BrainDecision,
        events: list[PendingEvent],
        capability_result: dict[str, Any] | None,
    ) -> None:
        from app.api.routes import _chat_proactive_inner
        from app.schemas.chat import ProactiveChatRequest

        instruction = (
            "You decided that speaking now adds real value. "
            f"Purpose: {decision.reason or 'continue naturally'}. "
            f"Topic or angle: {decision.topic or 'choose the most relevant specific thread'}. "
            "Produce one concise, natural spoken turn in character. A comment, reaction, joke, or question are all "
            "valid; do not force a question and do not use a generic check-in."
        )
        if capability_result:
            instruction += f" A permitted autonomous action just returned: {json.dumps(capability_result, ensure_ascii=False)[:1200]}."
        situational = "\n".join(
            f"{item.event_type}: {json.dumps(item.payload, ensure_ascii=False, default=str)[:500]}"
            for item in events[:8]
        )
        session.phase = "generating"
        await self._emit(session.id, "state", self._public_session(session))
        async with AsyncSessionLocal() as db:
            response = await _chat_proactive_inner(
                ProactiveChatRequest(
                    conversation_id=session.conversation_id,
                    trigger="agent_decision",
                    master_preset_id=session.master_preset_id,
                    voice_session_id=session.id,
                    surface=session.surface,
                    agent_instruction=instruction,
                    situational_context=situational or None,
                ),
                db,
            )
        session.conversation_id = response.conversation_id
        session.last_ai_monotonic = time.monotonic()
        session.proactive_turns += 1
        session.turns_since_summary += 1
        delivery: dict[str, Any] = {"surface": session.surface}
        session.phase = "speaking"
        if session.surface == "discord_voice":
            from app.api.discord_bridge import deliver_voice_brain_response

            delivery.update(await deliver_voice_brain_response(session.channel_key, response))
        else:
            await self._emit(session.id, "message", response.model_dump(mode="json"))
            delivery["queued_to_web"] = self.subscriber_count(session.id) > 0
        await self._store_interaction(session, decision, events, response.content, delivery)
        session.phase = "listening"
        if (
            settings.voice_brain.reflection_enabled
            and session.turns_since_summary >= max(4, settings.memory.summary_trigger_messages)
        ):
            asyncio.create_task(self._refresh_summary(session), name=f"voice-brain-reflect:{session.id}")

    async def _decision_context(self, session: RuntimeVoiceSession) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(VoiceBrainSession).where(VoiceBrainSession.id == session.id)
            )
            row = result.scalar_one_or_none()
            return {
                "summary": str(row.conversation_summary or "")[:5000] if row else "",
                "open_loops": list(row.open_loops or [])[:12] if row else [],
            }

    async def _refresh_summary(self, session: RuntimeVoiceSession) -> None:
        if not session.conversation_id or session.phase == "reflecting":
            return
        prior_phase = session.phase
        session.phase = "reflecting"
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Message)
                    .where(Message.conversation_id == session.conversation_id)
                    .order_by(Message.created_at.asc())
                )
                rows = list(result.scalars().all())
                if len(rows) < 4:
                    return
                recent = pack_recent_messages(rows[-120:], max(2200, settings.memory.context_budget_tokens - 2500))
                transcript = "\n".join(f"{item.role}: {item.content}" for item in recent)
                previous_result = await db.execute(
                    select(VoiceBrainSession).where(VoiceBrainSession.id == session.id)
                )
                state_row = previous_result.scalar_one_or_none()
                prior_summary = str(state_row.conversation_summary or "") if state_row else ""
                response = await create_llm_provider().generate(
                    [
                        ChatMessage(
                            role="system",
                            content=(
                                "Compress a live voice relationship into durable context. Preserve concrete facts, decisions, "
                                "preferences, promises, emotional changes, inside jokes, and unresolved follow-ups. Never invent. "
                                "Return JSON: summary (string), open_loops (string[]), memory_candidates "
                                "([{content,type,importance,confidence}]). Candidates must be facts explicitly supported by user speech."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=f"Previous summary:\n{prior_summary}\n\nRecent transcript:\n{transcript}",
                        ),
                    ],
                    temperature=0.0,
                    max_tokens=min(1200, max(500, settings.llm.max_tokens)),
                )
                payload = _extract_json_object(response.content) or {}
                summary = str(payload.get("summary") or "").strip()
                loops = payload.get("open_loops")
                if state_row and summary:
                    state_row.conversation_summary = summary[: max(2000, settings.memory.summary_tokens * 4)]
                    state_row.open_loops = [str(item)[:500] for item in loops[:16]] if isinstance(loops, list) else []
                    state_row.turns_since_summary = 0
                if settings.voice_brain.auto_memory_enabled:
                    await self._store_memory_candidates(db, state_row.character_id if state_row else None, payload)
                await db.commit()
                session.turns_since_summary = 0
        except Exception:
            logger.exception("Voice brain reflection failed for %s", session.id)
        finally:
            session.phase = prior_phase if prior_phase != "reflecting" else "listening"

    async def _store_memory_candidates(
        self,
        db: Any,
        character_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        if not character_id:
            return
        raw = payload.get("memory_candidates")
        if not isinstance(raw, list):
            return
        existing_result = await db.execute(
            select(Memory.content).where(Memory.character_id == character_id).limit(1000)
        )
        existing = {re.sub(r"\W+", " ", str(item).casefold()).strip() for item in existing_result.scalars().all()}
        allowed_types = {"episodic", "semantic", "relationship", "experience"}
        for candidate in raw[:8]:
            if not isinstance(candidate, dict):
                continue
            content = " ".join(str(candidate.get("content") or "").split()).strip()[:1000]
            confidence = _clamp(float(candidate.get("confidence") or 0.0))
            importance = _clamp(float(candidate.get("importance") or 0.5))
            normalized = re.sub(r"\W+", " ", content.casefold()).strip()
            if len(content) < 12 or confidence < 0.72 or importance < 0.45 or normalized in existing:
                continue
            memory_type = str(candidate.get("type") or "episodic").lower()
            if memory_type not in allowed_types:
                memory_type = "episodic"
            db.add(
                Memory(
                    character_id=character_id,
                    memory_type=memory_type,
                    content=content,
                    importance=importance,
                    source="voice_brain_reflection",
                    tags=["auto-extracted", f"confidence:{confidence:.2f}"],
                )
            )
            existing.add(normalized)

    def _capability_allowed(self, name: str) -> bool:
        capability = self._capabilities.get(name)
        return bool(
            capability
            and capability.autonomous_safe
            and name in settings.voice_brain.allowed_autonomous_capabilities
        )

    async def _execute_capability(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        capability = self._capabilities.get(name)
        if not capability or not self._capability_allowed(name):
            return {"ok": False, "error": "Capability is not available for autonomous use."}
        try:
            result = capability.handler(dict(arguments))
            if asyncio.iscoroutine(result):
                result = await result
            return {"ok": True, "capability": name, "result": result}
        except Exception as exc:
            logger.exception("Autonomous capability %s failed", name)
            return {"ok": False, "capability": name, "error": str(exc)[:400]}

    async def _persist_session(self, session: RuntimeVoiceSession) -> None:
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(VoiceBrainSession).where(VoiceBrainSession.id == session.id)
                )
                row = result.scalar_one_or_none()
                if not row:
                    return
                now = _utcnow()
                row.surface = session.surface
                row.channel_key = session.channel_key
                row.conversation_id = session.conversation_id
                row.enabled = session.enabled
                row.phase = session.phase
                row.internal_state = dict(session.internal_state)
                row.turns_since_summary = session.turns_since_summary
                row.proactive_turns_in_window = session.proactive_turns
                row.proactive_window_started_at = now - timedelta(
                    seconds=max(0.0, time.monotonic() - session.window_started_monotonic)
                )
                row.last_user_at = now - timedelta(
                    seconds=max(0.0, time.monotonic() - session.last_user_monotonic)
                )
                row.last_ai_at = now - timedelta(
                    seconds=max(0.0, time.monotonic() - session.last_ai_monotonic)
                )
                row.last_decision_at = now
                await db.commit()
        except Exception:
            logger.debug("Could not persist voice brain session %s", session.id, exc_info=True)

    async def _persist_event(self, session: RuntimeVoiceSession, event: PendingEvent) -> None:
        try:
            async with AsyncSessionLocal() as db:
                db.add(
                    VoiceBrainEvent(
                        id=event.id,
                        session_id=session.id,
                        event_type=event.event_type,
                        source=event.source,
                        priority=event.priority,
                        payload=event.payload,
                    )
                )
                await db.commit()
        except Exception:
            logger.debug("Could not persist voice brain event %s", event.id, exc_info=True)

    async def _record_decision(
        self,
        session: RuntimeVoiceSession,
        events: list[PendingEvent],
        decision: BrainDecision,
    ) -> None:
        consumed_ids = {item.id for item in events}
        session.events = deque(item for item in session.events if item.id not in consumed_ids)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(VoiceBrainEvent).where(VoiceBrainEvent.id.in_(consumed_ids))
                )
                now = _utcnow()
                for row in result.scalars().all():
                    row.status = "processed"
                    row.decision = decision.as_dict()
                    row.processed_at = now
                await db.commit()
        except Exception:
            logger.debug("Could not store voice brain decision", exc_info=True)
        await self._emit(session.id, "decision", decision.as_dict())

    async def _store_interaction(
        self,
        session: RuntimeVoiceSession,
        decision: BrainDecision,
        events: list[PendingEvent],
        output: str,
        delivery: dict[str, Any],
    ) -> None:
        evaluation: dict[str, Any] = {}
        if settings.voice_brain.evaluator_enabled:
            try:
                evaluation_response = await create_llm_provider().generate(
                    [
                        ChatMessage(
                            role="system",
                            content=(
                                "You are a strict evaluator of autonomous live voice timing. Return JSON with "
                                "relevance, timing, specificity, personality, non_repetition (0..10), total (0..10), "
                                "and critique. Penalize generic questions and needless interruption."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=(
                                f"Decision: {json.dumps(decision.as_dict(), ensure_ascii=False)}\n"
                                f"Observations: {json.dumps([self._public_event(item) for item in events], ensure_ascii=False)}\n"
                                f"Spoken output: {output}"
                            ),
                        ),
                    ],
                    temperature=0.0,
                    max_tokens=420,
                )
                evaluation = _extract_json_object(evaluation_response.content) or {}
            except Exception:
                logger.debug("Voice brain evaluator failed", exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                db.add(
                    VoiceBrainInteraction(
                        session_id=session.id,
                        trigger_event_ids=[item.id for item in events],
                        decision=decision.as_dict(),
                        output=output,
                        delivery=delivery,
                        evaluation=evaluation,
                    )
                )
                await db.commit()
        except Exception:
            logger.debug("Could not persist voice brain interaction", exc_info=True)

    def _public_event(self, event: PendingEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "event_type": event.event_type,
            "source": event.source,
            "priority": event.priority,
            "payload": event.payload,
        }

    def _public_session(self, session: RuntimeVoiceSession | None) -> dict[str, Any]:
        if not session:
            return {"active": False}
        now = time.monotonic()
        return {
            "id": session.id,
            "surface": session.surface,
            "active": session.active,
            "enabled": session.enabled and bool(settings.voice_brain.enabled),
            "phase": session.phase,
            "conversation_id": session.conversation_id,
            "silence_seconds": max(0.0, now - max(session.last_user_monotonic, session.last_ai_monotonic)),
            "next_wake_seconds": max(0.0, session.next_wake_monotonic - now),
            "proactive_turns_this_hour": session.proactive_turns,
            "proactive_limit_per_hour": settings.voice_brain.max_proactive_turns_per_hour,
            "pending_events": len(session.events),
            "internal_state": dict(session.internal_state),
            "last_decision": dict(session.last_decision),
            "last_error": session.last_error,
            "subscriber_count": self.subscriber_count(session.id),
        }


voice_brain = VoiceBrainRuntime()
