from __future__ import annotations

import re
from typing import Any

from app.core.config import save_config, settings
from app.integrations import discord_worker
from app.tools.registry import ToolExecutionError, ToolRegistry, ToolSpec

EMPTY_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

DISCORD_GUIDANCE = (
    "Discord tools can send text to the configured speaking channel, report routing status, toggle AI replies, "
    "join or leave voice, speak an explicit sentence in the current voice call, and mute or deafen Neuro's own Discord client. A join uses the requesting author's current voice channel when "
    "'Follow requesting author on join' is enabled; otherwise it uses the configured channel. "
    "The join tool enables Live Join itself. Mute/deafen never changes other participants. "
    "When the user asks to say, speak, or announce words in the call (for example, 'say hello in the call'), "
    "call discord_speak_voice with the exact requested words; do not answer with a quotation as a substitute. "
    "Explicit voice speech requires Discord Voice Output and an active Equicord voice channel. "
    "Report bridge/client setup errors honestly and never claim a voice-state change succeeded before its tool result."
)

DISCORD_INTENT_HINTS = (
    "discord",
    "voice call",
    "voice chat",
    "voice channel",
    "join call",
    "join the call",
    "leave call",
    "leave the call",
    "mute",
    "unmute",
    "deafen",
    "undeafen",
    "deaf",
    "microphone",
    "mic",
    "speak in the call",
    "say in the call",
    "in the call",
    "speak in voice",
    "say in voice",
    "in voice",
    "say something in the call",
    "say something in voice",
    "voice reply",
    "announce in the call",
    "announce in voice",
    "tell them in voice",
    "send message",
    "message discord",
    "reply on discord",
    "respond on discord",
    "use discord",
    "discord chat",
)


def parse_discord_voice_command(text: str) -> tuple[str, dict[str, Any]] | None:
    """Recognize only deterministic self mute/deafen compatibility commands.

    Speech is deliberately *not* parsed here. ``discord_speak_voice`` must be
    selected by the active LLM through the registered tool schema, so ordinary
    language is interpreted by the model rather than a phrase heuristic.
    """

    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    value = re.sub(r"[.!?]+$", "", value).strip()
    for _ in range(2):
        value = re.sub(r"^(?:please|hey|hi|could you|can you|would you)\s+", "", value).strip()

    subject = r"(?:yourself|your (?:own )?(?:mic|microphone|client|account)|your (?:discord )?(?:client|account))"
    if re.search(rf"\b(?:unmute|unsilence)\s+{subject}\b", value) or re.search(
        r"\b(?:turn|switch)\s+your (?:mic|microphone)\s+(?:back )?on\b", value
    ):
        return "discord_set_mute", {"enabled": False}
    if re.search(rf"\b(?:mute|silence)\s+{subject}\b", value) or re.search(
        r"\b(?:turn|switch)\s+your (?:mic|microphone)\s+off\b", value
    ):
        return "discord_set_mute", {"enabled": True}
    if re.search(rf"\b(?:undeafen|un-deafen)\s+{subject}\b", value):
        return "discord_set_deafen", {"enabled": False}
    if re.search(rf"\bdeafen\s+{subject}\b", value):
        return "discord_set_deafen", {"enabled": True}
    return None


def _discord_enabled() -> bool:
    return bool(settings.integrations.discord.enabled)


def _voice_join_available() -> bool:
    cfg = settings.integrations.discord
    return bool(cfg.enabled and (cfg.voice_channel_id or getattr(cfg, "live_join_follow_author", False)))


def _voice_leave_available() -> bool:
    return bool(settings.integrations.discord.enabled)


def _voice_control_available() -> bool:
    """Self mute/deafen is a control of the desktop Equicord client."""

    cfg = settings.integrations.discord
    return bool(cfg.enabled and str(cfg.mode or "client").lower() == "client")


async def _status(_arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.integrations.discord
    from app.core.config import discord_responds_to_every_message

    worker_status = discord_worker.get_status()
    voice_state: dict[str, Any] = {"connected": False, "channel_id": None, "self_mute": None, "self_deaf": None}
    try:
        from app.api.discord_bridge import _active_connections, current_voice_state

        bridge_connections = len(_active_connections)
        if bridge_connections:
            voice_state = await current_voice_state()
    except Exception:
        bridge_connections = 0
    return {
        "enabled": cfg.enabled,
        "mode": cfg.mode,
        "configured_voice_channel_id": cfg.voice_channel_id or None,
        "live_join_enabled": cfg.live_join_enabled,
        "live_join_follow_author": getattr(cfg, "live_join_follow_author", False),
        "respond_to_every_message": discord_responds_to_every_message(cfg),
        "bridge_connected": bridge_connections > 0,
        "voice_state": voice_state,
        "self_voice_controls": {
            "available": _voice_control_available(),
            "mute_tool": "discord_set_mute",
            "deafen_tool": "discord_set_deafen",
        },
        "text_routing": {
            "auto_reply": cfg.auto_reply,
            "command_prefix": cfg.command_prefix,
            "typing_indicator": cfg.typing_indicator,
            "speaking_channel_id": cfg.channel_id or None,
            "channel_mode": cfg.channel_mode,
            "channel_list": cfg.channel_list,
            "allowed_user_ids": cfg.allowed_user_ids,
        },
        "worker": worker_status,
    }


async def _send_text(arguments: dict[str, Any]) -> dict[str, Any]:
    from app.api.discord_bridge import send_discord_text

    content = str(arguments.get("content") or "").strip()
    if not content:
        raise ToolExecutionError("Tell me what to send on Discord.")
    result = await send_discord_text(content)
    if not result.get("ok"):
        raise ToolExecutionError(str(result.get("error") or "Discord could not send the message."))
    return {
        **result,
        "content": content,
        "confirmation": f"Sent the message in Discord channel {result.get('channel_id')}.",
    }


async def _set_auto_reply(arguments: dict[str, Any]) -> dict[str, Any]:
    enabled = arguments.get("enabled")
    if not isinstance(enabled, bool):
        raise ToolExecutionError("Discord automatic replies must be enabled or disabled.")
    settings.integrations.discord.auto_reply = enabled
    settings.integrations.discord.respond_to_every_message = enabled
    save_config(settings)
    try:
        from app.api.discord_bridge import broadcast_config_updated

        await broadcast_config_updated()
    except Exception:
        pass
    return {
        "auto_reply": enabled,
        "confirmation": f"Discord automatic replies are now {'enabled' if enabled else 'disabled'}.",
    }


async def _join(_arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.integrations.discord
    if not cfg.enabled:
        raise ToolExecutionError("Discord is disabled in Settings → Integrations.")
    author_channel_id: str | None = None
    if getattr(cfg, "live_join_follow_author", False):
        try:
            from app.api.discord_bridge import current_voice_join_author_channel

            author_channel_id = current_voice_join_author_channel()
        except Exception:
            author_channel_id = None
    channel_id = str(author_channel_id or cfg.voice_channel_id or "").strip()
    if not channel_id:
        if getattr(cfg, "live_join_follow_author", False):
            raise ToolExecutionError("The requesting Discord user is not currently in a voice channel and no fallback channel is configured.")
        raise ToolExecutionError("No Discord voice channel is configured.")

    # Match the working Join button: an explicit join request opts into the
    # desired joined state instead of requiring the toggle to be set first.
    cfg.live_join_enabled = True
    save_config(settings)

    if str(cfg.mode or "client").lower() == "client":
        from app.api.discord_bridge import (
            _active_connections,
            join_voice_verified,
            schedule_voice_join_guard,
        )

        if not _active_connections:
            raise ToolExecutionError(
                "The Discord desktop bridge is not connected. Start Discord with the Equicord bridge plugin first."
            )
        result = await join_voice_verified(channel_id)
    else:
        result = await discord_worker.join_voice(channel_id)
    if not result.get("ok"):
        raise ToolExecutionError(str(result.get("error") or "Discord could not join the configured voice channel."))
    if str(cfg.mode or "client").lower() == "client":
        schedule_voice_join_guard(channel_id)
    return {
        "channel_id": channel_id,
        "mode": cfg.mode,
        "joined": True,
        "followed_author": bool(author_channel_id and author_channel_id == channel_id),
        "details": result,
        "confirmation": (
            "Joined the requesting author's Discord voice call."
            if author_channel_id and author_channel_id == channel_id
            else "Joined the configured Discord voice call."
        ),
    }


async def _leave(_arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.integrations.discord
    if str(cfg.mode or "client").lower() == "client":
        from app.api.discord_bridge import _active_connections, _send_command

        if not _active_connections:
            raise ToolExecutionError("The Discord desktop bridge is not connected.")
        result = await _send_command("leave_voice", {}, timeout=10.0)
    else:
        result = await discord_worker.leave_voice()
    if not result.get("ok"):
        raise ToolExecutionError(str(result.get("error") or "Discord could not leave voice."))

    # The existing worker treats live_join_enabled as its desired connection
    # state. Disable it after a requested leave so its polling loop does not
    # immediately reconnect.
    cfg.live_join_enabled = False
    save_config(settings)
    return {
        "left": True,
        "mode": cfg.mode,
        "details": result,
        "confirmation": "Left the Discord voice call.",
    }


async def _set_mute(arguments: dict[str, Any]) -> dict[str, Any]:
    enabled = arguments.get("enabled")
    if not isinstance(enabled, bool):
        raise ToolExecutionError("Tell me whether Neuro should be muted or unmuted.")
    from app.api.discord_bridge import set_self_voice_state

    result = await set_self_voice_state(mute=enabled)
    if not result.get("ok"):
        raise ToolExecutionError(str(result.get("error") or "Discord could not change Neuro's mute state."))
    return {
        **result,
        "muted": enabled,
        "confirmation": f"Neuro's Discord microphone is now {'muted' if enabled else 'unmuted'}.",
    }


async def _set_deafen(arguments: dict[str, Any]) -> dict[str, Any]:
    enabled = arguments.get("enabled")
    if not isinstance(enabled, bool):
        raise ToolExecutionError("Tell me whether Neuro should be deafened or undeafened.")
    from app.api.discord_bridge import set_self_voice_state

    result = await set_self_voice_state(deaf=enabled)
    if not result.get("ok"):
        raise ToolExecutionError(str(result.get("error") or "Discord could not change Neuro's deafen state."))
    return {
        **result,
        "deafened": enabled,
        "confirmation": f"Neuro is now {'deafened' if enabled else 'undeafened'} in Discord.",
    }


async def _speak_voice(arguments: dict[str, Any]) -> dict[str, Any]:
    text = str(arguments.get("text") or "").strip()
    if not text:
        raise ToolExecutionError("Tell me exactly what to say in the Discord voice call.")
    if len(text) > 2000:
        raise ToolExecutionError("The explicit voice sentence is too long; keep it under 2000 characters.")
    from app.api.discord_bridge import speak_discord_voice

    result = await speak_discord_voice(text)
    if not result.get("ok"):
        raise ToolExecutionError(str(result.get("error") or "Discord could not speak that sentence."))
    return {
        **result,
        "spoken_text": text,
        "confirmation": f'I said "{text}" in the current Discord voice call.',
    }


def register_discord_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="discord_voice_status",
            description="Report Discord bridge/bot and configured voice-channel status without changing anything.",
            parameters=EMPTY_PARAMETERS,
            handler=_status,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_discord_enabled,
            max_calls_per_turn=2,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_send_message",
            description=(
                "Send a text message to Discord using the configured speaking channel, the most recent eligible "
                "channel, or the first configured channel."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 8000,
                        "description": "The exact message content to send to Discord.",
                    }
                },
                "required": ["content"],
                "additionalProperties": False,
            },
            handler=_send_text,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_discord_enabled,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_set_auto_reply",
            description=(
                "Enable or disable responses to every eligible Discord message. When disabled, a non-empty command prefix is required; an empty prefix disables command-mode replies."
            ),
            parameters={
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": ["enabled"],
                "additionalProperties": False,
            },
            handler=_set_auto_reply,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_discord_enabled,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_join_voice",
            description=(
                "Join the requesting author's current Discord voice channel when author-follow is enabled; "
                "otherwise join the configured permitted voice channel."
            ),
            parameters=EMPTY_PARAMETERS,
            handler=_join,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_voice_join_available,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_leave_voice",
            description="Leave the current Discord voice call and disable automatic rejoining.",
            parameters=EMPTY_PARAMETERS,
            handler=_leave,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_voice_leave_available,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_set_mute",
            description=(
                "Mute or unmute Neuro's own Discord microphone in the current voice call. "
                "This never mutes another participant."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "true to mute Neuro, false to unmute Neuro.",
                    }
                },
                "required": ["enabled"],
                "additionalProperties": False,
            },
            handler=_set_mute,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_voice_control_available,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_set_deafen",
            description=(
                "Deafen or undeafen Neuro's own Discord client in the current voice call. "
                "This never deafens another participant."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "true to deafen Neuro, false to undeafen Neuro.",
                    }
                },
                "required": ["enabled"],
                "additionalProperties": False,
            },
            handler=_set_deafen,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_voice_control_available,
        )
    )
    registry.register(
        ToolSpec(
            name="discord_speak_voice",
            description=(
                "Say the supplied exact text once in the current Discord voice call using the configured TTS voice. "
                "Use this when the user explicitly asks Neuro to say, speak, or announce something in voice, "
                "such as 'say I like this in the call'. Call the function instead of replying with prose first."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                        "description": "The exact sentence Neuro should speak in the current Discord voice call.",
                    }
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=_speak_voice,
            category="discord",
            guidance=DISCORD_GUIDANCE,
            intent_hints=DISCORD_INTENT_HINTS,
            available=_voice_control_available,
        )
    )
