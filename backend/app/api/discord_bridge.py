"""Discord Bridge — WebSocket endpoint for Equicord userplugin.

Allows the AI VTuber to control Discord directly through the user's
Equicord/Vencord client. The plugin connects via WebSocket and the AI
can send messages, join voice channels, read events, etc.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _event_log(level: str, message: str) -> None:
    from app.debug.events import add_event_log

    add_event_log(level, "discord_bridge", message)

router = APIRouter()

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_active_connections: list[WebSocket] = []
_ui_connections: list[WebSocket] = []
_pending_responses: dict[str, asyncio.Future] = {}
_command_counter = 0


def bridge_is_connected() -> bool:
    """Return whether at least one Equicord AI Bridge client is online."""

    return bool(_active_connections)
_recent_bridge_messages: list[dict] = []  # recent messages for UI sync
_MAX_RECENT = 100
_event_tasks: set[asyncio.Task] = set()
_channel_locks: dict[str, asyncio.Lock] = {}
_processed_message_ids: list[str] = []
_processed_message_id_set: set[str] = set()
_MAX_PROCESSED_IDS = 1000
# Client-originated messages are echoed back through the Equicord event stream.
# Keep a short-lived content fingerprint so mirrored transcripts and AI replies
# cannot be routed back into the chat pipeline when a plugin build omits its
# ``is_self``/author metadata.
_recent_outgoing_client_messages: list[tuple[str, str, float]] = []
_OUTGOING_ECHO_TTL_SECONDS = 20.0
_MAX_OUTGOING_ECHOES = 200
_last_eligible_channel_id: str | None = None
_discord_conversation_ids: dict[str, str] = {}
_discord_voice_conversation_ids: dict[str, str] = {}
_discord_voice_queues: dict[str, asyncio.Queue] = {}
_discord_voice_workers: dict[str, asyncio.Task] = {}
_voice_merge_buffers: dict[str, list[Any]] = {}
_voice_merge_tasks: dict[str, asyncio.Task] = {}
_VOICE_FRAGMENT_HOLD_SECONDS = 2.0
_last_voice_response_text: dict[str, str] = {}
_MAX_PENDING_VOICE_TURNS = 1
# Latest voice channel observed for each Discord user from Equicord events.
# This lets an eligible message trigger a join to the author's current call.
_discord_user_voice_channels: dict[str, str] = {}
_voice_join_author_channel: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "discord_voice_join_author_channel",
    default=None,
)
_last_voice_input_sync_signature: tuple[Any, ...] | None = None
_voice_join_guard_task: asyncio.Task | None = None
_discord_voice_brain_session_id: str | None = None
_DISCORD_TYPING_INTERVAL_SECONDS = 7.0


def _sanitize_discord_voice_tts_text(text: str, channel_id: str | None = None) -> str:
    """Remove internal Discord routing metadata from voice audio text."""

    value = str(text or "").strip()
    value = re.sub(r"\[Discord voice participant[^\]]*\]\s*", "", value, flags=re.IGNORECASE)
    target = str(channel_id or "").strip()
    if target:
        escaped = re.escape(target)
        value = re.sub(
            rf"\b(?:in|to|from)\s+(?:the\s+)?(?:Discord\s+)?channel\s+(?:ID\s*(?:is\s*)?[:=]?\s*)?{escaped}\b",
            " in the current voice call",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            rf"\b(?:Discord\s+)?channel\s*(?:ID|_id)?\s*(?:is\s*)?[:=]?\s*{escaped}\b",
            "",
            value,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\s{2,}", " ", value).strip()


def _normalize_outgoing_client_message(content: str) -> str:
    return re.sub(r"\s+", " ", str(content or "")).strip().casefold()


def _remember_outgoing_client_message(channel_id: str, content: str) -> None:
    """Remember a client message before sending it so its bridge echo is ignored."""

    channel = str(channel_id or "").strip()
    normalized = _normalize_outgoing_client_message(content)
    if not channel or not normalized:
        return
    now = time.monotonic()
    cutoff = now - _OUTGOING_ECHO_TTL_SECONDS
    _recent_outgoing_client_messages[:] = [
        item for item in _recent_outgoing_client_messages if item[2] >= cutoff
    ]
    _recent_outgoing_client_messages.append((channel, normalized, now))
    if len(_recent_outgoing_client_messages) > _MAX_OUTGOING_ECHOES:
        del _recent_outgoing_client_messages[:-_MAX_OUTGOING_ECHOES]


def _consume_outgoing_client_echo(channel_id: str, content: str) -> bool:
    """Consume a matching outgoing client message fingerprint, if present."""

    channel = str(channel_id or "").strip()
    normalized = _normalize_outgoing_client_message(content)
    now = time.monotonic()
    cutoff = now - _OUTGOING_ECHO_TTL_SECONDS
    _recent_outgoing_client_messages[:] = [
        item for item in _recent_outgoing_client_messages if item[2] >= cutoff
    ]
    for index, (sent_channel, sent_content, _sent_at) in enumerate(_recent_outgoing_client_messages):
        if sent_channel == channel and sent_content == normalized:
            del _recent_outgoing_client_messages[index]
            return True
    return False


def _bridge_config(discord: Any) -> dict[str, Any]:
    """The single, non-secret Discord configuration shared with UI and plugin."""
    from app.core.config import discord_responds_to_every_message, settings as cfg

    return {
        "enabled": discord.enabled,
        "mode": discord.mode,
        "build": discord.build,
        "channel_id": discord.channel_id,
        "voice_channel_id": discord.voice_channel_id,
        "command_prefix": discord.command_prefix,
        "status_text": discord.status_text,
        "server_id": discord.server_id,
        "auto_join_voice": discord.auto_join_voice,
        "join_message_author_voice": discord.join_message_author_voice,
        "live_join_enabled": discord.live_join_enabled,
        "live_join_follow_author": discord.live_join_follow_author,
        "join_method": discord.join_method,
        "voice_channel_mode": discord.voice_channel_mode,
        "voice_channel_threshold": discord.voice_channel_threshold,
        "channel_mode": discord.channel_mode,
        "channel_list": discord.channel_list,
        "allowed_user_ids": discord.allowed_user_ids,
        "auto_reply": discord.auto_reply,
        "respond_to_every_message": discord_responds_to_every_message(discord),
        "typing_indicator": discord.typing_indicator,
        "bridge_user_id": discord.bridge_user_id,
        "voice_output_enabled": bool(
            getattr(cfg, "discord_voice_output", None) and cfg.discord_voice_output.enabled
        ),
        "voice_output_device_name": str(
            getattr(getattr(cfg, "discord_voice_output", None), "device_name", "CABLE-B Input") or "CABLE-B Input"
        ),
        "voice_input_enabled": bool(
            getattr(cfg, "discord_voice_input", None) and cfg.discord_voice_input.enabled
        ),
        "voice_input_device_name": str(
            getattr(getattr(cfg, "discord_voice_input", None), "device_name", "CABLE-A Output") or "CABLE-A Output"
        ),
        "voice_input_chunk_ms": int(
            getattr(getattr(cfg, "discord_voice_input", None), "chunk_ms", 320) or 320
        ),
        "voice_input_silence_ms": int(
            getattr(getattr(cfg, "discord_voice_input", None), "silence_ms", 1200) or 1200
        ),
        "voice_input_mirror_transcript": bool(
            getattr(getattr(cfg, "discord_voice_input", None), "mirror_transcript", False)
        ),
    }


def current_voice_join_author_channel() -> str | None:
    """Return the requesting author's voice channel for the current chat task."""

    return _voice_join_author_channel.get()


def _next_command_id() -> str:
    global _command_counter
    _command_counter += 1
    return f"cmd_{_command_counter}_{int(time.time())}"


# ---------------------------------------------------------------------------
# Helpers — send commands to the plugin
# ---------------------------------------------------------------------------


async def _send_command(action: str, payload: dict, timeout: float = 10.0) -> dict:
    """Send a command to the connected Equicord plugin and wait for response."""
    if not _active_connections:
        _event_log("warning", f"command={action} blocked: no Equicord bridge connection")
        return {"ok": False, "error": "No Equicord plugin connected"}

    cmd_id = _next_command_id()
    msg = {"type": "command", "action": action, "id": cmd_id, "payload": payload}

    future: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending_responses[cmd_id] = future

    try:
        await _active_connections[0].send_json(msg)
        result = await asyncio.wait_for(future, timeout=timeout)
        if action in {"get_voice_state", "join_voice", "leave_voice", "set_voice_state", "set_self_mute", "set_self_deaf", "set_camera_state"}:
            _event_log("info" if result.get("ok") else "warning", f"command={action} ok={bool(result.get('ok'))}")
        return result
    except asyncio.TimeoutError:
        _event_log("warning", f"command={action} timed out after {timeout:.1f}s")
        return {"ok": False, "error": "Command timed out"}
    except Exception:
        logger.exception("Discord bridge command %s failed", action)
        _event_log("error", f"command={action} failed while waiting for Equicord")
        return {"ok": False, "error": "Discord bridge command failed"}
    finally:
        _pending_responses.pop(cmd_id, None)


def _command_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Return the plugin payload without assuming a particular response wrapper."""

    payload = result.get("payload") if isinstance(result, dict) else None
    return payload if isinstance(payload, dict) else {}


async def current_voice_state() -> dict[str, Any]:
    """Read and normalize the Equicord client's current voice state."""

    result = await _send_command("get_voice_state", {}, timeout=5.0)
    payload = _command_payload(result)
    users = payload.get("users") if isinstance(payload.get("users"), list) else []
    current_user_id = str(payload.get("current_user_id") or "").strip()
    if not current_user_id:
        try:
            from app.core.config import settings as cfg

            current_user_id = str(cfg.integrations.discord.bridge_user_id or "").strip()
        except Exception:
            current_user_id = ""
    current_user = next(
        (
            user
            for user in users
            if isinstance(user, dict)
            and current_user_id
            and str(user.get("user_id") or user.get("id") or "").strip() == current_user_id
        ),
        None,
    )

    def _optional_bool(value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

    def _state_flag(*keys: str) -> bool | None:
        source = current_user if isinstance(current_user, dict) else payload
        for key in keys:
            if key in source:
                value = _optional_bool(source.get(key))
                if value is not None:
                    return value
        return None

    return {
        "ok": bool(result.get("ok")),
        "connected": bool(payload.get("connected")),
        "channel_id": str(payload.get("channel_id") or "").strip() or None,
        "guild_id": str(payload.get("guild_id") or "").strip() or None,
        "current_user_id": current_user_id or None,
        "self_mute": _state_flag("self_mute", "selfMute", "mute"),
        "self_deaf": _state_flag("self_deaf", "selfDeaf", "deaf"),
        "self_video": _state_flag("self_video", "selfVideo", "video"),
        "video_device_id": str(payload.get("video_device_id") or "").strip() or None,
        "video_device_name": str(payload.get("video_device_name") or "").strip() or None,
        "video_devices": payload.get("video_devices") if isinstance(payload.get("video_devices"), list) else [],
        "users": users,
        "raw": result,
    }


def _bridge_command_is_unsupported(result: dict[str, Any]) -> bool:
    """Recognize old Equicord bridges which do not know voice-state commands."""

    payload = _command_payload(result)
    error = str(
        result.get("error")
        or result.get("message")
        or payload.get("error")
        or payload.get("message")
        or ""
    ).lower()
    return any(
        marker in error
        for marker in (
            "unknown action",
            "unknown command",
            "unsupported",
            "unrecognized",
            "not implemented",
            "invalid action",
            "does not support",
            "no handler",
        )
    )


async def set_self_voice_state(*, mute: bool | None = None, deaf: bool | None = None) -> dict[str, Any]:
    """Change only Neuro's own mute/deafen state in the active Equicord call.

    The canonical bridge command is ``set_voice_state``. A small compatibility
    fallback is retained for older bridge plugins which exposed separate
    ``set_self_mute``/``set_self_deaf`` actions. No command is sent until the
    client is confirmed to be connected to a voice channel.
    """

    requested: dict[str, bool] = {}
    if mute is not None:
        requested["mute"] = bool(mute)
    if deaf is not None:
        requested["deaf"] = bool(deaf)
    if not requested:
        return {"ok": False, "error": "No mute or deafen state was requested."}
    if not _active_connections:
        return {"ok": False, "error": "No Equicord plugin connected."}

    before = await current_voice_state()
    if not before.get("connected"):
        return {"ok": False, "error": "Neuro is not connected to a Discord voice channel."}

    result = await _send_command("set_voice_state", requested, timeout=10.0)
    command = "set_voice_state"
    if not result.get("ok") and _bridge_command_is_unsupported(result):
        # Keep compatibility with the first bridge builds that implemented
        # these as separate actions. This is only attempted after the
        # canonical command was explicitly rejected as unsupported.
        fallback_actions: list[tuple[str, dict[str, bool]]] = []
        if mute is not None and deaf is None:
            fallback_actions = [
                ("set_self_mute", {"enabled": bool(mute)}),
                ("set_mute", {"enabled": bool(mute)}),
            ]
        elif deaf is not None and mute is None:
            fallback_actions = [
                ("set_self_deaf", {"enabled": bool(deaf)}),
                ("set_deafen", {"enabled": bool(deaf)}),
            ]
        for fallback_action, fallback_payload in fallback_actions:
            command = fallback_action
            result = await _send_command(command, fallback_payload, timeout=10.0)
            if result.get("ok") or not _bridge_command_is_unsupported(result):
                break

    if not result.get("ok"):
        return {
            "ok": False,
            "error": str(result.get("error") or "Discord rejected the voice-state change."),
            "requested": requested,
            "command": command,
            "details": result,
        }

    # Voice state events can arrive a little after the command response. Poll
    # briefly so the tool result can distinguish an applied state from a mere
    # accepted request without delaying normal chat for a long time.
    observed = before
    verified = False
    for delay in (0.1, 0.25, 0.5):
        await asyncio.sleep(delay)
        observed = await current_voice_state()
        checks: list[bool] = []
        if mute is not None and observed.get("self_mute") is not None:
            checks.append(observed.get("self_mute") == bool(mute))
        if deaf is not None and observed.get("self_deaf") is not None:
            checks.append(observed.get("self_deaf") == bool(deaf))
        if checks and all(checks):
            verified = True
            break

    return {
        "ok": True,
        "requested": requested,
        "command": command,
        "verified": verified,
        "voice_state": observed,
    }


async def set_self_camera_state(*, enabled: bool, device_name: str = "OBS Virtual Camera") -> dict[str, Any]:
    """Select OBS Virtual Camera and verify Neuro's own Discord video state."""

    if not _active_connections:
        return {"ok": False, "error": "No Equicord plugin connected."}
    before = await current_voice_state()
    if not before.get("connected"):
        return {"ok": False, "error": "Neuro is not connected to a Discord voice channel."}

    result = await _send_command(
        "set_camera_state",
        {"enabled": bool(enabled), "device_name": str(device_name or "OBS Virtual Camera").strip()},
        timeout=12.0,
    )
    payload = _command_payload(result)
    command_error = str(
        result.get("error")
        or payload.get("error")
        or ""
    ).strip()
    if not result.get("ok") or command_error:
        return {
            "ok": False,
            "error": command_error or "Discord rejected the camera-state change.",
            "details": result,
        }

    directly_verified = (
        isinstance(payload.get("video_enabled"), bool)
        and payload.get("video_enabled") == bool(enabled)
    )
    observed = before
    state_verified = False
    for delay in (0.1, 0.25, 0.5, 0.8):
        await asyncio.sleep(delay)
        observed = await current_voice_state()
        if observed.get("self_video") == bool(enabled):
            state_verified = True
            break
    verified = directly_verified or state_verified
    if not verified:
        return {
            "ok": False,
            "error": "Discord accepted the camera command, but the resulting video state could not be verified.",
            "details": result,
            "voice_state": observed,
        }
    return {
        "ok": True,
        "camera_enabled": bool(enabled),
        "device_name": payload.get("video_device_name") or observed.get("video_device_name") or device_name,
        "verified": True,
        "voice_state": observed,
        "details": result,
    }


def _voice_channel_from_author(author: dict[str, Any], message: dict[str, Any] | None = None) -> str | None:
    """Extract a voice-channel hint when the bridge includes one in a message."""

    message = message or {}
    candidates: list[Any] = [
        message.get("voice_channel_id"),
        author.get("voice_channel_id"),
        author.get("voiceChannelId"),
    ]
    for key in ("voice", "voice_state", "voiceState"):
        nested = author.get(key)
        if isinstance(nested, dict):
            candidates.extend((nested.get("channel_id"), nested.get("channelId")))
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return None


async def _maybe_join_message_author_voice(
    author: dict[str, Any],
    message: dict[str, Any],
) -> None:
    """Join the eligible message author's current call when explicitly enabled."""

    from app.core.config import settings as cfg

    discord = cfg.integrations.discord
    if not getattr(discord, "join_message_author_voice", False):
        return
    author_id = str(
        author.get("id") or author.get("user_id") or author.get("userId") or ""
    ).strip()
    if not author_id:
        return
    target = _voice_channel_from_author(author, message) or _discord_user_voice_channels.get(author_id)
    if not target:
        _event_log("debug", f"message-author voice join skipped user={author_id}: no current voice channel known")
        return
    try:
        state = await current_voice_state()
        if state.get("connected"):
            if state.get("channel_id") == target:
                return
            # Treat an active call as a session lock. Messages from another
            # channel can still receive text replies, but must not pull the
            # AI out of the current conversation mid-call.
            _event_log(
                "info",
                f"message-author voice join skipped user={author_id}: active voice session locked to channel={state.get('channel_id')}",
            )
            return
        _event_log("info", f"joining message author voice channel user={author_id} channel={target}")
        result = await join_voice_verified(target)
        if result.get("ok"):
            _event_log("info", f"joined message author voice channel user={author_id} channel={target}")
        else:
            _event_log("warning", f"message author voice join failed user={author_id} channel={target}: {result.get('error')}")
    except Exception as exc:
        logger.warning("Could not join message author's voice channel: %s", exc)
        _event_log("error", f"message author voice join failed user={author_id}: {exc}")


async def join_voice_verified(channel_id: str) -> dict[str, Any]:
    """Use the same bridge command as the UI button and verify the resulting state."""

    target = str(channel_id or "").strip()
    if not target:
        return {"ok": False, "error": "No Discord voice channel is configured."}

    result = await _send_command("join_voice", {"channel_id": target}, timeout=10.0)
    if not result.get("ok"):
        return result

    # Discord updates its voice store shortly after the command response. Do
    # not tell the LLM that the join succeeded until that state is observable.
    state: dict[str, Any] = {}
    for delay in (0.2, 0.5, 1.0):
        await asyncio.sleep(delay)
        state = await current_voice_state()
        if state.get("connected") and state.get("channel_id") == target:
            return {**result, "ok": True, "verified": True, "voice_state": state}

    return {
        "ok": False,
        "error": "Discord accepted the join command but did not stay connected to the configured voice channel.",
        "command_result": result,
        "voice_state": state,
    }


async def _guard_requested_voice_join(channel_id: str) -> None:
    """Recover once when Discord drops a tool-requested join moments later."""

    # The supplied logs show a transient disconnect about ten seconds after
    # the first programmatic join. Check just after that window and retry once.
    await asyncio.sleep(12.0)
    from app.core.config import settings as cfg

    discord = cfg.integrations.discord
    if not discord.enabled or not discord.live_join_enabled:
        return

    state = await current_voice_state()
    if state.get("connected") and state.get("channel_id") == channel_id:
        return

    logger.warning("Discord voice join dropped shortly after connecting; retrying once")
    await join_voice_verified(channel_id)


def schedule_voice_join_guard(channel_id: str) -> None:
    """Replace any older guard with one for the latest explicit join request."""

    global _voice_join_guard_task
    if _voice_join_guard_task and not _voice_join_guard_task.done():
        _voice_join_guard_task.cancel()
    _voice_join_guard_task = asyncio.create_task(_guard_requested_voice_join(channel_id))
    _voice_join_guard_task.add_done_callback(_event_task_done)


def _split_discord_content(content: str, limit: int = 1900) -> list[str]:
    """Split text below Discord's message limit without cutting every line."""

    remaining = str(content or "").strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        boundary = max(remaining.rfind("\n", 0, limit), remaining.rfind(" ", 0, limit))
        if boundary < limit // 2:
            boundary = limit
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return chunks


def default_text_channel_id() -> str | None:
    """Resolve the configured/default Discord channel used by AI tools."""

    from app.core.config import settings as cfg

    discord = cfg.integrations.discord
    candidates = [
        str(discord.channel_id or "").strip(),
        str(_last_eligible_channel_id or "").strip(),
        *(str(item).strip() for item in discord.channel_list),
    ]
    return next((candidate for candidate in candidates if candidate), None)


async def send_discord_text(
    content: str,
    *,
    channel_id: str | None = None,
    reply_to: str | None = None,
    transport: str | None = None,
) -> dict[str, Any]:
    """Send text through the configured bot or Equicord bridge transport."""

    from app.core.config import settings as cfg

    discord = cfg.integrations.discord
    target = str(channel_id or default_text_channel_id() or "").strip()
    if not target:
        return {
            "ok": False,
            "error": "No Discord speaking channel is configured and no eligible channel has been seen yet.",
        }
    selected_transport = str(transport or discord.mode or "client").lower()
    chunks = _split_discord_content(content)
    if not chunks:
        return {"ok": False, "error": "Discord message content is empty."}

    sent = 0
    for index, chunk in enumerate(chunks):
        current_reply = reply_to if index == 0 else None
        if selected_transport == "bot":
            from app.integrations import discord_worker

            result = await discord_worker.send_message(target, chunk, reply_to=current_reply)
        else:
            # The Equicord bridge's proven send path accepts channel_id and
            # content. Reply metadata differs between Discord client builds,
            # so keep AI replies on that compatible path.
            payload: dict[str, Any] = {"channel_id": target, "content": chunk}
            # Equicord broadcasts client-created messages back over the same
            # socket. Register the fingerprint before sending to cover the
            # race where the echo arrives before the command response.
            _remember_outgoing_client_message(target, chunk)
            result = await _send_command("send_message", payload)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": str(result.get("error") or "Discord could not send the message."),
                "channel_id": target,
                "sent_chunks": sent,
            }
        sent += 1
    return {"ok": True, "channel_id": target, "sent_chunks": sent}


async def _send_discord_typing_once(channel_id: str, transport: str) -> dict[str, Any]:
    """Emit one native typing event through the active Discord transport."""

    if str(transport or "client").lower() == "bot":
        from app.integrations import discord_worker

        return await discord_worker.send_typing(channel_id)
    if not _active_connections:
        return {"ok": False, "error": "No Equicord plugin connected"}
    return await _send_command(
        "typing",
        {"channel_id": channel_id},
        timeout=3.0,
    )


async def _discord_typing_heartbeat(channel_id: str, transport: str) -> None:
    """Refresh Discord's expiring typing state until generation finishes."""

    while True:
        try:
            await _send_discord_typing_once(channel_id, transport)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Typing is presence polish and must never block or fail a reply.
            logger.debug("Discord typing heartbeat failed", exc_info=True)
        await asyncio.sleep(_DISCORD_TYPING_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def _discord_typing_indicator(channel_id: str, transport: str):
    """Keep Discord typing visible only while the AI response is generated."""

    from app.core.config import settings as cfg

    if not cfg.integrations.discord.typing_indicator:
        yield
        return

    task = asyncio.create_task(
        _discord_typing_heartbeat(channel_id, transport),
        name=f"discord-typing-{channel_id}",
    )
    # Let the immediate first heartbeat run without delaying model generation
    # on a slow or disconnected Discord bridge.
    await asyncio.sleep(0)
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def speak_discord_voice(text: str) -> dict[str, Any]:
    """Generate and play one explicit AI utterance through the Discord cable."""

    from app.core.config import settings as cfg

    utterance = str(text or "").strip()
    if not utterance:
        return {"ok": False, "error": "The voice utterance is empty."}
    if str(cfg.integrations.discord.mode or "client").lower() != "client":
        return {"ok": False, "error": "Explicit Discord voice speech requires the Equicord desktop client mode."}
    if not cfg.discord_voice_output.enabled:
        return {
            "ok": False,
            "error": "Discord voice output is disabled. Enable Mirror AI TTS / LLM responses in Discord settings first.",
        }
    state = await current_voice_state()
    if not state.get("connected"):
        return {"ok": False, "error": "Neuro is not connected to a Discord voice channel."}

    from app.api.routes import _generate_tts_audio
    from app.audio_output import get_audio_output_service, select_output_device
    from app.schemas.chat import TTSRequest

    try:
        # Validate the cable before loading a local TTS model, then reuse the
        # same TTS generation path as the browser and automatic Discord replies.
        select_output_device(cfg.discord_voice_output.device_name)
        audio = await _generate_tts_audio(TTSRequest(text=utterance))
        playback = await get_audio_output_service().play_serialized(
            audio.data,
            audio.media_type,
            device_name=cfg.discord_voice_output.device_name,
        )
    except Exception as exc:
        logger.warning("Explicit Discord voice speech failed: %s", exc)
        _event_log("error", f"explicit voice speech failed: {exc}")
        return {"ok": False, "error": str(exc)}

    _event_log(
        "info",
        f"explicit voice speech played channel={state.get('channel_id')} chars={len(utterance)} device={cfg.discord_voice_output.device_name!r}",
    )
    return {
        "ok": True,
        "spoken_text": utterance,
        "channel_id": state.get("channel_id"),
        "device": playback.get("device_selected"),
        "confirmation": "I said that in the current Discord voice call.",
    }


async def _broadcast_event(event_type: str, payload: dict) -> None:
    """Broadcast an event from Discord to all connected AI consumers."""
    msg = {"type": "event", "event": event_type, "payload": payload}
    for ws in list(_active_connections):
        try:
            await ws.send_json(msg)
        except Exception:
            pass


async def _broadcast_to_ui(event_type: str, payload: dict) -> None:
    """Broadcast a Discord event to all connected frontend UI clients."""
    msg = {"type": "bridge_event", "event": event_type, "payload": payload}
    for ws in list(_ui_connections):
        try:
            await ws.send_json(msg)
        except Exception:
            pass


async def broadcast_config_updated() -> None:
    """Push the current Discord config to both the plugin and the UI."""
    from app.core.config import settings as cfg
    d = cfg.integrations.discord
    config = _bridge_config(d)
    # Push to plugin (as a command)
    if _active_connections:
        msg = {"type": "command", "action": "config_updated", "id": "cfg_push", "payload": config}
        for ws in list(_active_connections):
            try:
                await ws.send_json(msg)
            except Exception:
                pass
    # Push to UI (as a bridge event)
    await _broadcast_to_ui("config_updated", config)


async def _sync_config_from_plugin(payload: dict[str, Any]) -> None:
    """Accept a whitelist of plugin settings, persist it, and fan it back out."""
    from app.core.config import save_config, settings as cfg

    discord = cfg.integrations.discord
    allowed = {
        "command_prefix", "channel_list", "channel_mode", "auto_reply",
        "allowed_user_ids",
        "bridge_user_id", "voice_channel_id", "channel_id", "server_id",
        "respond_to_every_message",
    }
    for key in allowed:
        if key not in payload:
            continue
        value = payload[key]
        if key in {"channel_list", "allowed_user_ids"} and not isinstance(value, list):
            continue
        if key not in {"channel_list", "allowed_user_ids"} and not isinstance(value, (str, bool)):
            continue
        if isinstance(value, list):
            value = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        elif isinstance(value, str):
            value = value.strip()
        setattr(discord, key, value)

    save_config(cfg)
    await broadcast_config_updated()
    _spawn_event_task(sync_discord_voice_input())


# ---------------------------------------------------------------------------
# REST endpoints — for backend-initiated actions
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    channel_id: str
    content: str = ""
    reply_to: str | None = None


class ReactRequest(BaseModel):
    channel_id: str
    message_id: str
    emoji: str


class JoinVoiceRequest(BaseModel):
    channel_id: str


@router.get("/discord/bridge/status")
async def bridge_status() -> dict:
    """Check if the Equicord plugin is connected."""
    return {
        "ok": True,
        "connected": len(_active_connections) > 0,
        "connections": len(_active_connections),
    }


@router.post("/discord/bridge/send")
async def bridge_send_message(req: SendMessageRequest) -> dict:
    """Send a message through the bridge."""
    payload = {"channel_id": req.channel_id, "content": req.content}
    if req.reply_to:
        payload["reply_to"] = req.reply_to
    return await _send_command("send_message", payload)


@router.post("/discord/bridge/react")
async def bridge_react(req: ReactRequest) -> dict:
    """React to a message through the bridge."""
    return await _send_command("react", {
        "channel_id": req.channel_id,
        "message_id": req.message_id,
        "emoji": req.emoji,
    })


@router.post("/discord/bridge/join-voice")
async def bridge_join_voice(req: JoinVoiceRequest) -> dict:
    """Join a voice channel through the bridge."""
    return await _send_command("join_voice", {"channel_id": req.channel_id})


@router.post("/discord/bridge/leave-voice")
async def bridge_leave_voice() -> dict:
    """Leave the current voice channel."""
    return await _send_command("leave_voice", {})


@router.get("/discord/bridge/channels")
async def bridge_get_channels() -> dict:
    """Get list of accessible channels."""
    return await _send_command("get_channels", {}, timeout=15.0)


@router.get("/discord/bridge/guilds")
async def bridge_get_guilds() -> dict:
    """Get list of guilds."""
    return await _send_command("get_guilds", {}, timeout=15.0)


@router.get("/discord/bridge/voice-state")
async def bridge_voice_state() -> dict:
    """Get current voice channel and connected users."""
    result = await _send_command("get_voice_state", {}, timeout=10.0)
    # REST polling is also used by the settings UI, so keep the capture
    # lifecycle correct even when a client does not emit a state event.
    try:
        payload = _command_payload(result)
        await sync_discord_voice_input()
    except Exception:
        payload = {}
    if payload:
        return {**result, "payload": payload}
    return result


@router.get("/discord/bridge/recent-messages")
async def bridge_recent_messages() -> dict:
    """Get recent bridge messages for UI sync."""
    return {"ok": True, "messages": _recent_bridge_messages[-50:]}


# ---------------------------------------------------------------------------
# WebSocket — Equicord plugin connects here
# ---------------------------------------------------------------------------


@router.websocket("/ws/discord")
async def discord_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for the Equicord AI Bridge plugin."""
    await websocket.accept()
    _active_connections.append(websocket)
    logger.info("Equicord bridge plugin connected (%d total)", len(_active_connections))
    _event_log("info", f"Equicord bridge connected (connections={len(_active_connections)})")

    # Push current config to newly connected plugin
    try:
        from app.core.config import settings as cfg
        d = cfg.integrations.discord
        config = _bridge_config(d)
        await websocket.send_json({"type": "command", "action": "config_updated", "id": "cfg_push", "payload": config})
        asyncio.create_task(sync_discord_voice_input())
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "command_response":
                # Plugin responding to a command we sent
                cmd_id = data.get("id")
                future = _pending_responses.get(cmd_id)
                if future and not future.done():
                    future.set_result(data)

            elif msg_type == "event":
                # Plugin forwarding a Discord event
                event_name = data.get("event", "")
                payload = data.get("payload", {})
                await _handle_discord_event(event_name, payload)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info("Equicord bridge plugin disconnected")
        _event_log("warning", "Equicord bridge disconnected")
    except Exception as e:
        logger.exception("Bridge WebSocket error: %s", e)
    finally:
        if websocket in _active_connections:
            _active_connections.remove(websocket)
        if not _active_connections:
            # Voice-state observations belong to a bridge session. Do not use
            # stale channel IDs after Equicord reconnects, otherwise a later
            # message could make the AI join a channel the author already left.
            _discord_user_voice_channels.clear()
            try:
                from app.discord_voice import stop_discord_voice_input
                await stop_discord_voice_input()
            except Exception:
                logger.debug("Failed to stop Discord voice capture after bridge disconnect", exc_info=True)
        # Cancel any pending commands for this connection
        for cmd_id, future in list(_pending_responses.items()):
            if not future.done():
                future.set_result({"ok": False, "error": "Bridge disconnected"})
        logger.info("Bridge cleanup complete (%d connections left)", len(_active_connections))
        _event_log("info", f"Equicord bridge cleanup complete (connections={len(_active_connections)})")


@router.websocket("/ws/bridge-events")
async def bridge_events_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for the frontend UI to receive Discord bridge events in real-time."""
    await websocket.accept()
    _ui_connections.append(websocket)
    logger.info("Frontend UI connected to bridge events (%d total)", len(_ui_connections))

    # Push current config to newly connected UI
    try:
        from app.core.config import settings as cfg
        d = cfg.integrations.discord
        config = _bridge_config(d)
        await websocket.send_json({"type": "bridge_event", "event": "config_updated", "payload": config})
    except Exception:
        pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("Frontend UI disconnected from bridge events")
    except Exception as e:
        logger.exception("Bridge events WebSocket error: %s", e)
    finally:
        if websocket in _ui_connections:
            _ui_connections.remove(websocket)
        logger.info("Bridge events cleanup (%d UI connections left)", len(_ui_connections))


# ---------------------------------------------------------------------------
# Event handling — forward Discord events to the AI chat system
# ---------------------------------------------------------------------------


def _spawn_event_task(coro: Any) -> None:
    """Keep bridge command responses readable while an LLM turn is running."""

    task = asyncio.create_task(coro)
    _event_tasks.add(task)
    task.add_done_callback(_event_task_done)


def _event_task_done(task: asyncio.Task) -> None:
    _event_tasks.discard(task)
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("Discord event task failed")


async def shutdown_event_tasks() -> None:
    """Cancel outstanding Discord LLM turns during backend shutdown."""

    global _voice_join_guard_task
    if _voice_join_guard_task and not _voice_join_guard_task.done():
        _voice_join_guard_task.cancel()
        await asyncio.gather(_voice_join_guard_task, return_exceptions=True)
    _voice_join_guard_task = None

    tasks = list(_event_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    for task in list(_discord_voice_workers.values()):
        if not task.done():
            task.cancel()
    if _discord_voice_workers:
        await asyncio.gather(*_discord_voice_workers.values(), return_exceptions=True)
    _discord_voice_workers.clear()
    _discord_voice_queues.clear()
    _voice_merge_buffers.clear()
    _voice_merge_tasks.clear()
    _recent_outgoing_client_messages.clear()
    _last_voice_response_text.clear()
    try:
        from app.discord_voice import stop_discord_voice_input
        await stop_discord_voice_input()
    except Exception:
        logger.debug("Discord voice input shutdown failed", exc_info=True)


def _is_likely_voice_fragment(text: str) -> bool:
    """Identify short endpoint fragments worth holding for a continuation."""

    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return False
    letters = sum(character.isalpha() for character in normalized)
    if letters < 3:
        return True
    if re.search(r"(?:\.{2,}|…)$", normalized):
        return True
    words = re.findall(r"[\w']+", normalized)
    return len(words) <= 1 and len(normalized) <= 8


def _merge_voice_transcripts(transcripts: list[Any]) -> Any:
    """Build one transcript from a short endpoint fragment and its continuation."""

    from app.discord_voice import VoiceTranscript

    first = transcripts[0]
    parts: list[str] = []
    duration = 0.0
    for item in transcripts:
        part = " ".join(str(getattr(item, "text", "") or "").split()).strip()
        if part and (not parts or part.casefold() != parts[-1].casefold()):
            parts.append(part)
        value = getattr(item, "duration", None)
        if isinstance(value, (int, float)):
            duration += float(value)
    return VoiceTranscript(
        channel_id=str(getattr(first, "channel_id", "") or "").strip(),
        text=" ".join(parts),
        language=str(getattr(first, "language", "auto") or "auto"),
        duration=duration or None,
    )


async def _flush_voice_fragment(channel_id: str) -> None:
    """Flush a held fragment when no continuation arrives in the merge window."""

    try:
        await asyncio.sleep(_VOICE_FRAGMENT_HOLD_SECONDS)
        transcripts = _voice_merge_buffers.pop(channel_id, [])
        _voice_merge_tasks.pop(channel_id, None)
        if transcripts:
            await _queue_discord_voice_transcript(_merge_voice_transcripts(transcripts))
    except asyncio.CancelledError:
        raise


async def _queue_discord_voice_transcript(transcript: Any) -> None:
    """Publish, mirror, and enqueue one finalized (possibly merged) utterance."""

    channel_id = str(getattr(transcript, "channel_id", "") or "").strip()
    text = str(getattr(transcript, "text", "") or "").strip()
    if not channel_id or not text:
        return
    await _broadcast_to_ui(
        "voice_transcript",
        {
            "channel_id": channel_id,
            "text": text,
            "language": getattr(transcript, "language", "auto"),
            "duration": getattr(transcript, "duration", None),
            "queued": True,
        },
    )
    from app.core.config import settings as cfg
    if getattr(cfg.discord_voice_input, "mirror_transcript", False):
        _spawn_event_task(_mirror_voice_transcript_to_channel(channel_id, text))
    queue = _discord_voice_queues.setdefault(
        channel_id,
        asyncio.Queue(maxsize=_MAX_PENDING_VOICE_TURNS),
    )
    # TTS is much slower than realtime speech. Keep the active turn and the
    # newest pending turn only; replaying every stale utterance makes the AI
    # appear to be stuck in a loop after a backlog builds up.
    while queue.full():
        try:
            dropped = queue.get_nowait()
            queue.task_done()
            dropped_text = str(getattr(dropped, "text", "") or "").strip()
            _event_log(
                "warning",
                f"voice turn coalesced channel={channel_id} dropped_chars={len(dropped_text)}",
            )
        except asyncio.QueueEmpty:
            break
    await queue.put(transcript)
    _event_log(
        "info",
        f"voice turn queued channel={channel_id} depth={queue.qsize()} max_pending={_MAX_PENDING_VOICE_TURNS}",
    )
    worker = _discord_voice_workers.get(channel_id)
    if worker is None or worker.done():
        worker = asyncio.create_task(_discord_voice_queue_worker(channel_id))
        _discord_voice_workers[channel_id] = worker
        _event_tasks.add(worker)
        worker.add_done_callback(_event_task_done)


async def _on_discord_voice_transcript(transcript: Any) -> None:
    """Merge short endpoint fragments before starting an AI turn."""

    channel_id = str(getattr(transcript, "channel_id", "") or "").strip()
    text = str(getattr(transcript, "text", "") or "").strip()
    if not channel_id or not text:
        _event_log("warning", "voice transcript discarded: missing channel or text")
        return
    _event_log("info", f"voice transcript finalized channel={channel_id} chars={len(text)} text={text[:120]!r}")

    pending = _voice_merge_buffers.get(channel_id)
    if pending is not None:
        pending.append(transcript)
        task = _voice_merge_tasks.pop(channel_id, None)
        if task and not task.done():
            task.cancel()
        _voice_merge_buffers.pop(channel_id, None)
        merged = _merge_voice_transcripts(pending)
        _event_log(
            "info",
            f"voice fragments merged channel={channel_id} parts={len(pending)} chars={len(merged.text)}",
        )
        await _queue_discord_voice_transcript(merged)
        return

    if _is_likely_voice_fragment(text):
        _voice_merge_buffers[channel_id] = [transcript]
        task = asyncio.create_task(_flush_voice_fragment(channel_id))
        _voice_merge_tasks[channel_id] = task
        _event_tasks.add(task)
        task.add_done_callback(_event_task_done)
        _event_log(
            "info",
            f"voice fragment held channel={channel_id} for={_VOICE_FRAGMENT_HOLD_SECONDS:.1f}s chars={len(text)}",
        )
        return

    await _queue_discord_voice_transcript(transcript)


async def _mirror_voice_transcript_to_channel(channel_id: str, text: str) -> None:
    """Mirror a finalized Whisper turn to the active voice channel's chat."""

    result = await send_discord_text(text, channel_id=channel_id, transport="client")
    if result.get("ok"):
        _event_log("info", f"Whisper transcript mirrored to voice channel channel={channel_id}")
    else:
        _event_log(
            "warning",
            f"Whisper transcript mirror failed channel={channel_id}: {result.get('error') or 'Discord rejected the message'}",
        )


async def _on_discord_voice_partial(transcript: Any) -> None:
    """Expose interim words to the UI without starting an LLM turn."""

    await _broadcast_to_ui(
        "voice_transcript_partial",
        {
            "channel_id": str(getattr(transcript, "channel_id", "") or ""),
            "text": str(getattr(transcript, "text", "") or ""),
            "language": getattr(transcript, "language", "auto"),
        },
    )


async def _discord_voice_queue_worker(channel_id: str) -> None:
    """Process voice turns serially so TTS can never overlap."""

    queue = _discord_voice_queues.setdefault(
        channel_id,
        asyncio.Queue(maxsize=_MAX_PENDING_VOICE_TURNS),
    )
    while True:
        transcript = await queue.get()
        try:
            _event_log("info", f"voice turn started channel={channel_id} remaining={queue.qsize()}")
            await _respond_to_discord_voice_utterance(transcript)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Discord voice response failed")
        finally:
            queue.task_done()
            _event_log("info", f"voice turn finished channel={channel_id} remaining={queue.qsize()}")
            try:
                from app.discord_voice import discord_voice_input
                if discord_voice_input.status().get("running"):
                    discord_voice_input.set_state("listening")
            except Exception:
                pass


async def _respond_to_discord_voice_utterance(transcript: Any) -> None:
    """Generate and speak one queued Discord voice turn."""

    from app.api.routes import _process_chat, _generate_tts_audio
    from app.core.config import settings as cfg
    from app.db.session import AsyncSessionLocal
    from app.schemas.chat import ChatRequest, TTSRequest

    channel_id = str(getattr(transcript, "channel_id", "") or "").strip()
    text = str(getattr(transcript, "text", "") or "").strip()
    if not channel_id or not text:
        return
    _event_log(
        "info",
        f"voice LLM request channel={channel_id} chars={len(text)} model={cfg.llm.provider}/{cfg.llm.model}",
    )
    try:
        from app.discord_voice import discord_voice_input
        discord_voice_input.set_state("processing")
    except Exception:
        pass

    # Do not expose the internal channel ID to the LLM. It is retained in the
    # surrounding task state for routing, but it is not part of the user's
    # conversational request.
    contextual_message = f"[Discord voice participant]\n{text}"
    join_context = _voice_join_author_channel.set(channel_id)
    try:
        async with AsyncSessionLocal() as db:
            response = await _process_chat(
                db,
                ChatRequest(
                    message=contextual_message,
                    conversation_id=_discord_voice_conversation_ids.get(channel_id),
                    source="discord_voice",
                    voice_session_id=f"discord_voice:{channel_id}",
                    situational_context="A participant in the currently connected Discord voice call just spoke.",
                ),
            )
            _discord_voice_conversation_ids[channel_id] = response.conversation_id
    finally:
        _voice_join_author_channel.reset(join_context)
    _event_log(
        "info",
        f"voice LLM response channel={channel_id} chars={len(response.content or '')} tools={len(response.tools_used or [])}",
    )

    if not response.content:
        return

    voice_output: dict[str, Any] = {"attempted": False, "played": False}
    output_cfg = cfg.discord_voice_output
    explicit_voice_tool_used = "discord_speak_voice" in (response.tools_used or [])
    if output_cfg.enabled and not explicit_voice_tool_used:
        voice_state = await current_voice_state()
        if _discord_voice_output_allowed("client", True, bool(voice_state.get("connected"))):
            voice_output["attempted"] = True
            try:
                from app.audio_output import AudioOutputError, get_audio_output_service, select_output_device

                select_output_device(output_cfg.device_name)
                _event_log("info", f"voice TTS request channel={channel_id} engine={cfg.tts.engine} voice_ref={bool(cfg.tts.voice_ref)}")
                spoken_content = _sanitize_discord_voice_tts_text(response.content, channel_id)
                if not spoken_content:
                    _event_log("warning", f"voice TTS skipped channel={channel_id}: response contained only internal metadata")
                    voice_output["skipped"] = "internal_metadata_only"
                    spoken_content = ""
                if not spoken_content:
                    raise RuntimeError("The response contained no user-facing voice text.")
                audio = await _generate_tts_audio(TTSRequest(text=spoken_content))
                playback = await get_audio_output_service().play_serialized(
                    audio.data,
                    audio.media_type,
                    device_name=output_cfg.device_name,
                )
                voice_output.update({"played": True, "device": playback.get("device_selected")})
                _event_log("info", f"voice TTS played channel={channel_id} device={output_cfg.device_name!r}")
            except Exception as exc:
                voice_output["error"] = str(exc)
                logger.warning("Discord voice input response playback failed: %s", exc)
                _event_log("error", f"voice TTS failed channel={channel_id}: {exc}")
    elif explicit_voice_tool_used:
        voice_output["skipped"] = "explicit_voice_tool"
        _event_log(
            "info",
            f"automatic voice output skipped channel={channel_id}: explicit discord_speak_voice tool already played",
        )
    else:
        _event_log("warning", f"voice TTS skipped channel={channel_id}: Discord voice output is disabled")

    # Voice turns are shown in the web UI and optionally mirrored to a normal
    # Discord text channel. The default is voice-only to avoid duplicate chat.
    if cfg.discord_voice_input.mirror_text and cfg.integrations.discord.channel_id:
        await send_discord_text(
            response.content,
            channel_id=cfg.integrations.discord.channel_id,
            transport="client",
        )
    await _broadcast_to_ui(
        "voice_ai_response",
        {
            "channel_id": channel_id,
            "content": response.content,
            "message_id": response.message_id,
            "tools_used": response.tools_used,
            "voice_output": voice_output,
            "timestamp": response.created_at.isoformat() if response.created_at else None,
        },
    )
    try:
        from app.discord_voice import discord_voice_input
        discord_voice_input.set_state("speaking" if voice_output.get("played") else "listening")
    except Exception:
        pass


async def deliver_voice_brain_response(channel_id: str, response: Any) -> dict[str, Any]:
    """Deliver one already-generated autonomous turn to the active Discord call."""

    from app.agent.voice_brain import voice_brain
    from app.core.config import settings as cfg

    target = str(channel_id or "").strip()
    session_id = f"discord_voice:{target}"
    delivery: dict[str, Any] = {"attempted": False, "played": False, "surface": "discord_voice"}
    if not target or not str(getattr(response, "content", "") or "").strip():
        delivery["error"] = "No active Discord voice target or response text."
        return delivery
    try:
        await voice_brain.heartbeat(
            session_id,
            phase="speaking",
            conversation_id=getattr(response, "conversation_id", None),
        )
    except KeyError:
        pass
    delivery["attempted"] = True
    try:
        playback = await speak_discord_voice(str(response.content))
        delivery.update(playback)
        delivery["played"] = bool(playback.get("ok"))
    except Exception as exc:
        delivery["error"] = str(exc)
        _event_log("error", f"autonomous Discord voice delivery failed channel={target}: {exc}")

    if cfg.discord_voice_input.mirror_text and cfg.integrations.discord.channel_id:
        mirrored = await send_discord_text(
            str(response.content),
            channel_id=cfg.integrations.discord.channel_id,
            transport="client",
        )
        delivery["text_mirrored"] = bool(mirrored.get("ok"))
    await _broadcast_to_ui(
        "voice_ai_response",
        {
            "channel_id": target,
            "content": response.content,
            "message_id": response.message_id,
            "tools_used": response.tools_used,
            "voice_output": delivery,
            "proactive": True,
            "timestamp": response.created_at.isoformat() if response.created_at else None,
        },
    )
    try:
        await voice_brain.heartbeat(
            session_id,
            phase="listening",
            conversation_id=getattr(response, "conversation_id", None),
        )
    except KeyError:
        pass
    return delivery


async def sync_discord_voice_input(state: dict[str, Any] | None = None) -> None:
    """Synchronize capture with the bridge's current voice connection."""

    global _last_voice_input_sync_signature, _discord_voice_brain_session_id
    try:
        from app.discord_voice import discord_voice_input
        from app.core.config import settings as cfg
        state = state or (await current_voice_state() if _active_connections else {"connected": False, "channel_id": None})
        signature = (
            bool(cfg.discord_voice_input.enabled),
            bool(state.get("connected")),
            str(state.get("channel_id") or ""),
            str(cfg.discord_voice_input.device_name or ""),
            int(cfg.discord_voice_input.chunk_ms or 320),
            int(cfg.discord_voice_input.silence_ms or 1200),
            str(cfg.stt.provider or ""),
            str(cfg.stt.model or ""),
            str(cfg.stt.device or ""),
            str(cfg.stt.compute_type or ""),
        )
        if signature != _last_voice_input_sync_signature:
            _event_log(
                "info",
                "voice input sync: enabled=%s connected=%s channel=%s device=%s chunk_ms=%s silence_ms=%s provider=%s model=%s device_mode=%s compute=%s"
                % signature,
            )
            # A model/provider/device change from the web UI must take effect
            # on the active voice call, not only after reconnecting Discord.
            if _last_voice_input_sync_signature is not None and discord_voice_input.status().get("running"):
                await discord_voice_input.stop()
            _last_voice_input_sync_signature = signature
        discord_voice_input.set_transcript_handler(_on_discord_voice_transcript)
        discord_voice_input.set_partial_handler(_on_discord_voice_partial)
        await discord_voice_input.sync(bool(state.get("connected")), state.get("channel_id"))

        # The autonomous executive is scoped to an actual live voice
        # connection. It is opened/closed with Discord state, never by normal
        # text-channel traffic.
        from app.agent.voice_brain import voice_brain

        connected_channel = str(state.get("channel_id") or "").strip()
        next_session_id = f"discord_voice:{connected_channel}" if state.get("connected") and connected_channel else None
        if _discord_voice_brain_session_id and _discord_voice_brain_session_id != next_session_id:
            await voice_brain.close_session(_discord_voice_brain_session_id)
            _discord_voice_brain_session_id = None
        if next_session_id:
            input_phase = str(discord_voice_input.status().get("state") or "listening")
            if input_phase not in {"listening", "user_speaking", "processing", "speaking"}:
                input_phase = "listening"
            await voice_brain.open_session(
                session_id=next_session_id,
                surface="discord_voice",
                channel_key=connected_channel,
                conversation_id=_discord_voice_conversation_ids.get(connected_channel),
                enabled=True,
                phase=input_phase,
            )
            _discord_voice_brain_session_id = next_session_id
    except Exception:
        logger.debug("Could not synchronize Discord voice input", exc_info=True)
        _event_log("error", "voice input sync failed; see backend session log for traceback")


async def _handle_discord_event(event_name: str, payload: dict) -> None:
    """Process a Discord event from the Equicord plugin."""
    logger.debug("Bridge event: %s", event_name)
    if event_name not in {"typing_start", "channel_select"}:
        _event_log("debug", f"bridge event received: {event_name}")

    if event_name == "config_updated":
        await _sync_config_from_plugin(payload)
        return

    if event_name == "message_create":
        # Never await a complete LLM turn from this receive loop. Tool calls
        # and AI replies use the same socket and their command_response frames
        # must remain readable while generation is in progress.
        _spawn_event_task(_on_message_create(payload, transport="client"))
        return

    # Non-message events are cheap and can be broadcast synchronously.
    await _broadcast_to_ui(event_name, payload)
    if event_name == "voice_state_update":
        await _on_voice_state_update(payload)
        _spawn_event_task(sync_discord_voice_input())
    elif event_name == "typing_start":
        pass  # Typing is ephemeral, just log it
    elif event_name == "channel_select":
        pass  # UI state, just log it
    else:
        logger.debug("Unhandled bridge event: %s", event_name)


async def _record_incoming_message(
    message: dict[str, Any],
    *,
    routing_status: str,
    routing_detail: str,
) -> None:
    """Store only in-scope bridge messages and expose their routing decision."""

    author = message.get("author", {})
    bridge_msg = {
        "type": "incoming",
        "channel_id": str(message.get("channel_id") or ""),
        "guild_id": message.get("guild_id"),
        "message_id": str(message.get("id") or ""),
        "author": author,
        "content": str(message.get("content") or ""),
        "timestamp": message.get("timestamp"),
        "routing_status": routing_status,
        "routing_detail": routing_detail,
    }
    _recent_bridge_messages.append(bridge_msg)
    if len(_recent_bridge_messages) > _MAX_RECENT:
        _recent_bridge_messages.pop(0)
    await _broadcast_to_ui(
        "message_create",
        {
            **message,
            "routing_status": routing_status,
            "routing_detail": routing_detail,
        },
    )


async def _on_message_create(message: dict, *, transport: str = "client") -> None:
    """Handle one incoming message from either Discord transport."""

    global _last_eligible_channel_id

    author = message.get("author", {})
    content = str(message.get("content") or "").strip()
    channel_id = str(message.get("channel_id") or "").strip()
    guild_id = message.get("guild_id")
    message_id = str(message.get("id") or "").strip()

    from app.core.config import settings as cfg
    discord = cfg.integrations.discord

    if not content or not channel_id:
        _event_log("warning", "message_create ignored: missing content or channel_id")
        return
    if transport == "client" and _consume_outgoing_client_echo(channel_id, content):
        _event_log(
            "debug",
            f"message_create ignored: outgoing bridge echo channel={channel_id} chars={len(content)}",
        )
        return
    author_id = str(
        author.get("id") or author.get("user_id") or author.get("userId") or ""
    ).strip()
    if message.get("is_self") or author.get("self") or author.get("bot"):
        return
    # Skip echoing messages created by the account that hosts the bridge.
    if discord.bridge_user_id and author_id == str(discord.bridge_user_id).strip():
        return
    if message_id and not _remember_message_id(message_id):
        return

    # Do not retain unrelated server traffic merely because the client plugin
    # can observe it. This also keeps the user's test messages from being
    # immediately evicted by busy servers.
    if discord.server_id and str(guild_id or "") != str(discord.server_id).strip():
        return

    if not _channel_is_eligible(discord, channel_id, guild_id):
        await _record_incoming_message(
            message,
            routing_status="ignored_channel",
            routing_detail="This channel is excluded by the Discord channel filter.",
        )
        return
    if not _author_is_eligible(discord, author_id):
        await _record_incoming_message(
            message,
            routing_status="ignored_user",
            routing_detail="This author's Discord user ID is not in Allowed Users.",
        )
        return

    prompt, routing_status, routing_detail = _route_discord_prompt(discord, content)
    _event_log(
        "info" if prompt is not None else "debug",
        f"message route channel={channel_id} status={routing_status} chars={len(content)}",
    )
    await _record_incoming_message(
        message,
        routing_status=routing_status,
        routing_detail=routing_detail,
    )
    if prompt is None:
        return
    _last_eligible_channel_id = channel_id

    # Joining is deliberately tied to an accepted message, so unrelated
    # server traffic cannot pull the AI into voice. The opt-in helper uses the
    # author's latest Equicord voice-state event.
    await _maybe_join_message_author_voice(author, message)

    lock = _channel_locks.setdefault(channel_id, asyncio.Lock())
    async with lock:
        await _respond_to_discord_message(
            prompt,
            channel_id,
            message_id,
            guild_id,
            author=author,
            message=message,
            transport=transport,
        )


def _remember_message_id(message_id: str) -> bool:
    if message_id in _processed_message_id_set:
        return False
    _processed_message_ids.append(message_id)
    _processed_message_id_set.add(message_id)
    if len(_processed_message_ids) > _MAX_PROCESSED_IDS:
        expired = _processed_message_ids.pop(0)
        _processed_message_id_set.discard(expired)
    return True


def _author_is_eligible(discord: Any, author_id: str) -> bool:
    allowed = {str(item).strip() for item in discord.allowed_user_ids if str(item).strip()}
    return not allowed or author_id in allowed


def _route_discord_prompt(discord: Any, content: str) -> tuple[str | None, str, str]:
    """Apply the prefix contract and describe the decision for the UI."""

    from app.core.config import discord_responds_to_every_message

    prefix = str(discord.command_prefix or "").strip()
    normalized = str(content or "").lstrip()
    if discord_responds_to_every_message(discord):
        # In all-message mode a prefix is optional. If present, strip it so
        # the character does not receive the routing marker as user content.
        if prefix and normalized.lower().startswith(prefix.lower()):
            prompt = normalized[len(prefix):].strip()
            if not prompt:
                return None, "empty_after_prefix", f"Add a message after {prefix}"
            return prompt, "accepted", "Accepted and sent to the AI."
        prompt = normalized.strip()
        if not prompt:
            return None, "empty", "The message did not contain text for the AI."
        return prompt, "accepted", "Accepted and sent to the AI."

    # Command mode is deliberately strict: an empty prefix disables command
    # routing rather than silently turning every message into an AI prompt.
    if prefix:
        if not normalized.lower().startswith(prefix.lower()):
            return None, "needs_prefix", f"Waiting for the configured prefix: {prefix}"
        prompt = normalized[len(prefix):].strip()
        if not prompt:
            return None, "empty_after_prefix", f"Add a message after {prefix}"
        return prompt, "accepted", "Accepted and sent to the AI."
    return None, "prefix_disabled", "Respond to every message is off and no command prefix is configured."


def _discord_voice_output_allowed(transport: str, enabled: bool, voice_connected: bool) -> bool:
    """Only the desktop bridge may route final replies into a voice call."""

    return str(transport or "client").lower() == "client" and bool(enabled) and bool(voice_connected)


def _prompt_from_discord_message(discord: Any, content: str) -> str | None:
    """Compatibility wrapper used by routing tests and older callers."""

    prompt, _status, _detail = _route_discord_prompt(discord, content)
    return prompt


def _channel_is_eligible(discord: Any, channel_id: str, guild_id: str | None) -> bool:
    """Apply server/channel filters consistently to normal messages and commands."""
    if not discord.enabled:
        return False
    if discord.server_id and str(guild_id or "") != str(discord.server_id).strip():
        return False
    channel_id = str(channel_id or "").strip()
    listed = {str(item).strip() for item in discord.channel_list if str(item).strip()}
    # An empty list always means every channel, including when the UI still
    # has the old "allowlist" mode selected.
    if discord.channel_mode == "allowlist" and listed and channel_id not in listed:
        return False
    if discord.channel_mode == "blocklist" and channel_id in listed:
        return False
    return True


async def _respond_to_discord_message(
    content: str,
    channel_id: str,
    message_id: str,
    guild_id: str | None,
    *,
    author: dict[str, Any] | None = None,
    message: dict[str, Any] | None = None,
    transport: str = "client",
) -> None:
    """Generate an AI reply and mirror the result into the web UI."""
    try:
        from app.api.routes import _process_chat
        from app.schemas.chat import ChatRequest
        from app.db.session import AsyncSessionLocal

        author = author or {}
        author_name = str(
            author.get("global_name") or author.get("username") or author.get("name") or "Discord user"
        ).strip()
        author_id = str(
            author.get("id") or author.get("user_id") or author.get("userId") or "unknown"
        ).strip()
        # Keep source metadata useful to the persona without inserting the
        # word "Discord" into every turn. That word is itself an actionable
        # tool hint and previously made ordinary Discord chat look like a
        # request to control Discord.
        contextual_message = f"[Chat participant: {author_name} | user_id={author_id}]\n{content}"
        _event_log(
            "info",
            f"message processing started transport={transport} channel={channel_id} chars={len(content)}",
        )
        join_author_channel = _voice_channel_from_author(author, message)
        if not join_author_channel and author_id != "unknown":
            join_author_channel = _discord_user_voice_channels.get(author_id)
        async with _discord_typing_indicator(channel_id, transport):
            join_context = _voice_join_author_channel.set(join_author_channel)
            try:
                async with AsyncSessionLocal() as db:
                    req = ChatRequest(
                        message=contextual_message,
                        conversation_id=_discord_conversation_ids.get(channel_id),
                    )
                    response = await _process_chat(db, req)
                    _discord_conversation_ids[channel_id] = response.conversation_id
            finally:
                _voice_join_author_channel.reset(join_context)
        _event_log(
            "info",
            f"message response generated channel={channel_id} chars={len(response.content or '')} tools={len(response.tools_used or [])}",
        )

        # Send the response back through the same Discord transport.
        if response.content:
            sent = await send_discord_text(
                response.content,
                channel_id=channel_id,
                reply_to=message_id or None,
                transport=transport,
            )
            if not sent.get("ok"):
                logger.warning("Discord AI response could not be sent: %s", sent.get("error"))
                _event_log("error", f"Discord response send failed channel={channel_id}: {sent.get('error')}")
                return

            # Desktop Equicord replies may optionally be spoken through the
            # VB-CABLE playback endpoint. This is intentionally after the
            # complete chat/tool turn and never runs for bot transport, so
            # intermediate tool messages and web UI speech stay untouched.
            voice_output: dict[str, Any] = {"attempted": False}
            explicit_voice_tool_used = "discord_speak_voice" in (response.tools_used or [])
            if transport == "client" and not explicit_voice_tool_used:
                from app.audio_output import AudioOutputError, get_audio_output_service, select_output_device
                from app.api.routes import _generate_tts_audio
                from app.core.config import settings as cfg
                from app.schemas.chat import TTSRequest

                output_cfg = cfg.discord_voice_output
                if output_cfg.enabled:
                    voice_state = await current_voice_state()
                    voice_connected = bool(voice_state.get("connected"))
                    author_voice_channel = _voice_channel_from_author(author, message)
                    if not author_voice_channel and author_id != "unknown":
                        author_voice_channel = _discord_user_voice_channels.get(author_id)
                    author_in_active_voice = bool(
                        voice_connected
                        and author_voice_channel
                        and author_voice_channel == voice_state.get("channel_id")
                    )
                    _event_log(
                        "info",
                        "voice output decision channel=%s enabled=true connected=%s "
                        "author_voice=%s same_active_voice=%s device=%r"
                        % (
                            channel_id,
                            voice_connected,
                            author_voice_channel or "none",
                            author_in_active_voice,
                            output_cfg.device_name,
                        ),
                    )
                    if _discord_voice_output_allowed(
                        transport,
                        output_cfg.enabled,
                        voice_connected and author_in_active_voice,
                    ):
                        voice_output["attempted"] = True
                        try:
                            # Fail before loading a TTS model when the cable
                            # was unplugged or renamed in Windows.
                            select_output_device(output_cfg.device_name)
                            spoken_content = _sanitize_discord_voice_tts_text(response.content, channel_id)
                            if not spoken_content:
                                raise RuntimeError("The response contained no user-facing voice text.")
                            audio = await _generate_tts_audio(TTSRequest(text=spoken_content))
                            playback = await get_audio_output_service().play_serialized(
                                audio.data,
                                audio.media_type,
                                device_name=output_cfg.device_name,
                            )
                            voice_output.update({"played": True, "device": playback.get("device_selected")})
                            _event_log("info", f"voice output played channel={channel_id} device={output_cfg.device_name!r}")
                        except Exception as exc:
                            voice_output.update({"played": False, "error": str(exc)})
                            logger.warning("Discord voice output failed: %s", exc)
                            _event_log("error", f"voice output failed channel={channel_id}: {exc}")
                    else:
                        if not voice_connected:
                            voice_output["error"] = "Equicord desktop client is not connected to a voice channel."
                            _event_log("warning", f"voice output skipped channel={channel_id}: desktop bridge is not voice-connected")
                        elif not author_in_active_voice:
                            voice_output["error"] = "Text-only reply: message author is not in Neuro's active voice channel."
                            _event_log(
                                "info",
                                f"voice output skipped channel={channel_id}: author is not in the active voice session",
                            )
                else:
                    _event_log("warning", f"voice output skipped channel={channel_id}: disabled in settings")
            elif transport == "client" and explicit_voice_tool_used:
                _event_log(
                    "info",
                    f"automatic voice output skipped channel={channel_id}: explicit discord_speak_voice tool already played",
                )
                voice_output["skipped"] = "explicit_voice_tool"
            elif transport != "client":
                _event_log("debug", f"voice output skipped channel={channel_id}: transport={transport}")

            # Store and broadcast the AI response for UI sync
            ai_msg = {
                "type": "outgoing",
                "channel_id": channel_id,
                "guild_id": guild_id,
                "message_id": response.message_id,
                "author": {"name": "AI", "id": "ai"},
                "content": response.content,
                "tools_used": response.tools_used,
                "voice_output": voice_output,
                "timestamp": response.created_at.isoformat() if response.created_at else None,
            }
            _recent_bridge_messages.append(ai_msg)
            if len(_recent_bridge_messages) > _MAX_RECENT:
                _recent_bridge_messages.pop(0)
            await _broadcast_to_ui("ai_response", ai_msg)

    except Exception as e:
        logger.exception("Failed to process bridge message: %s", e)


async def _on_voice_state_update(voice_states: list[dict] | dict | Any) -> None:
    """Handle voice state updates from Discord.

    Equicord versions have sent both a single state object and an array of
    state objects. Normalize both forms so a dict is not accidentally iterated
    as a sequence of string keys (which previously caused ``.get`` errors).
    """
    if isinstance(voice_states, dict):
        states = [voice_states]
    elif isinstance(voice_states, list):
        states = [state for state in voice_states if isinstance(state, dict)]
    else:
        logger.warning("Ignoring malformed voice_state_update payload: %r", type(voice_states).__name__)
        return

    for state in states:
        user_id = str(state.get("user_id") or state.get("userId") or "").strip()
        channel_id = state.get("channel_id") or state.get("channelId")
        old_channel_id = state.get("old_channel_id") or state.get("oldChannelId")
        mute = state.get("mute", False)
        self_mute = state.get("self_mute", False)
        deaf = state.get("deaf", False)
        self_deaf = state.get("self_deaf", False)

        action = "joined" if channel_id and not old_channel_id else \
                 "left" if not channel_id and old_channel_id else \
                 "moved" if channel_id != old_channel_id else \
                 "updated"

        if user_id:
            if channel_id:
                _discord_user_voice_channels[user_id] = str(channel_id).strip()
            else:
                _discord_user_voice_channels.pop(user_id, None)

        logger.info("Voice %s: user=%s channel=%s", action, user_id, channel_id or old_channel_id)
        _event_log(
            "info",
            f"Discord voice state {action}: user={user_id or 'unknown'} channel={channel_id or old_channel_id or 'none'}",
        )

        # Notify the AI about voice changes
        try:
            from app.character.state import CharacterState
            state_obj = CharacterState()
            state_obj.add_event({
                "type": "voice_state",
                "action": action,
                "user_id": user_id,
                "channel_id": channel_id,
                "old_channel_id": old_channel_id,
            })
        except Exception:
            pass


async def _handle_direct_command(content: str, channel_id: str, message_id: str, author: dict) -> None:
    """Backward-compatible entry point; semantic tool routing owns commands."""
    from app.core.config import settings as cfg
    prompt = _prompt_from_discord_message(cfg.integrations.discord, content)
    if prompt:
        await _respond_to_discord_message(
            prompt,
            channel_id,
            message_id,
            None,
            author=author,
            transport="client",
        )
