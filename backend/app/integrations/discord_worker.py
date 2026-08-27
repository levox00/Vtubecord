"""
Lightweight Discord integration worker.
- Attempts to connect as either a client or bot using provided token (bot_token).
- Watches the persisted config YAML (via settings) for a "join request" (live_join_enabled true / voice_channel_id set) and executes a join.

Notes:
- This is a best-effort helper. Real production usage should run a dedicated Discord process using discord.py/hikari and robust reconnection/voice handling.
- The module imports discord only when available; absence will be logged and the worker will be a no-op.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

try:
    import discord
    from discord import Intents
except Exception:  # pragma: no cover - optional dependency
    discord = None

from app.core.config import settings

logger = logging.getLogger(__name__)

_worker_task: Optional[asyncio.Task] = None
_client: Optional["discord.Client"] = None
_voice_client = None
_status = {"connected": False, "user": None, "guilds": []}
_voice_lock = asyncio.Lock()


async def join_voice(channel_id: str) -> dict:
    """Join one explicitly configured channel through the running bot worker."""

    global _voice_client
    client = _client
    if discord is None:
        return {"ok": False, "error": "discord.py is not installed"}
    if client is None or not getattr(client, "is_ready", lambda: False)():
        return {"ok": False, "error": "Discord bot is not connected yet"}
    try:
        numeric_id = int(str(channel_id).strip())
    except (TypeError, ValueError):
        return {"ok": False, "error": "The configured Discord voice channel ID is invalid"}

    async with _voice_lock:
        channel = client.get_channel(numeric_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(numeric_id)
            except Exception:
                return {"ok": False, "error": "Discord could not find the configured voice channel"}
        configured_server = str(settings.integrations.discord.server_id or "").strip()
        channel_server = str(getattr(getattr(channel, "guild", None), "id", "") or "")
        if configured_server and channel_server != configured_server:
            return {"ok": False, "error": "The voice channel is outside the configured Discord server"}
        if not hasattr(channel, "connect"):
            return {"ok": False, "error": "The configured Discord channel is not a voice channel"}
        try:
            if _voice_client and getattr(_voice_client, "is_connected", lambda: False)():
                current_id = str(getattr(getattr(_voice_client, "channel", None), "id", "") or "")
                if current_id == str(numeric_id):
                    return {"ok": True, "already_connected": True, "channel_id": str(numeric_id)}
                if hasattr(_voice_client, "move_to"):
                    await _voice_client.move_to(channel)
                else:
                    await _voice_client.disconnect()
                    _voice_client = await channel.connect()
            else:
                _voice_client = await channel.connect()
        except Exception:
            logger.exception("Failed to join Discord voice channel %s", numeric_id)
            return {"ok": False, "error": "Discord failed to connect to the configured voice channel"}
    return {"ok": True, "channel_id": str(numeric_id)}


async def leave_voice() -> dict:
    """Disconnect the bot worker from its current voice channel."""

    global _voice_client
    async with _voice_lock:
        if _voice_client is None or not getattr(_voice_client, "is_connected", lambda: False)():
            _voice_client = None
            return {"ok": True, "already_disconnected": True}
        try:
            await _voice_client.disconnect()
        except Exception:
            logger.exception("Failed to leave Discord voice")
            return {"ok": False, "error": "Discord failed to leave the voice channel"}
        _voice_client = None
    return {"ok": True}


async def send_message(channel_id: str, content: str, *, reply_to: str | None = None) -> dict:
    """Send text through the running discord.py bot transport."""

    client = _client
    if discord is None:
        return {"ok": False, "error": "discord.py is not installed"}
    if client is None or not getattr(client, "is_ready", lambda: False)():
        return {"ok": False, "error": "Discord bot is not connected yet"}
    try:
        numeric_id = int(str(channel_id).strip())
    except (TypeError, ValueError):
        return {"ok": False, "error": "The Discord text channel ID is invalid"}
    channel = client.get_channel(numeric_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(numeric_id)
        except Exception:
            return {"ok": False, "error": "Discord could not find the text channel"}
    configured_server = str(settings.integrations.discord.server_id or "").strip()
    channel_server = str(getattr(getattr(channel, "guild", None), "id", "") or "")
    if configured_server and channel_server != configured_server:
        return {"ok": False, "error": "The text channel is outside the configured Discord server"}
    if not hasattr(channel, "send"):
        return {"ok": False, "error": "The configured Discord channel cannot receive messages"}
    kwargs = {"mention_author": False}
    if reply_to:
        try:
            kwargs["reference"] = discord.MessageReference(
                message_id=int(reply_to),
                channel_id=numeric_id,
            )
        except (TypeError, ValueError):
            pass
    try:
        message = await channel.send(str(content), **kwargs)
    except Exception:
        logger.exception("Failed to send Discord bot message to %s", numeric_id)
        return {"ok": False, "error": "Discord failed to send the message"}
    return {"ok": True, "channel_id": str(numeric_id), "message_id": str(message.id)}


async def send_typing(channel_id: str) -> dict:
    """Emit one native Discord typing event through the bot transport."""

    client = _client
    if discord is None:
        return {"ok": False, "error": "discord.py is not installed"}
    if client is None or not getattr(client, "is_ready", lambda: False)():
        return {"ok": False, "error": "Discord bot is not connected yet"}
    try:
        numeric_id = int(str(channel_id).strip())
    except (TypeError, ValueError):
        return {"ok": False, "error": "The Discord text channel ID is invalid"}
    channel = client.get_channel(numeric_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(numeric_id)
        except Exception:
            return {"ok": False, "error": "Discord could not find the text channel"}
    configured_server = str(settings.integrations.discord.server_id or "").strip()
    channel_server = str(getattr(getattr(channel, "guild", None), "id", "") or "")
    if configured_server and channel_server != configured_server:
        return {"ok": False, "error": "The text channel is outside the configured Discord server"}
    if not hasattr(channel, "typing"):
        return {"ok": False, "error": "The configured Discord channel cannot show typing"}
    try:
        # Awaiting discord.py's Typing object emits a single event which is
        # visible for about ten seconds. The bridge refreshes it while the
        # model is still generating.
        await channel.typing()
    except Exception:
        logger.exception("Failed to send Discord bot typing event to %s", numeric_id)
        return {"ok": False, "error": "Discord failed to send the typing indicator"}
    return {"ok": True, "channel_id": str(numeric_id)}


async def _poll_config_and_join(client: "discord.Client"):
    """Poll the in-memory settings and attempt joins when requested."""
    global _voice_client, _status
    while True:
        try:
            cfg = settings.integrations.discord
            if getattr(cfg, "live_join_enabled", False) and cfg.voice_channel_id:
                result = await join_voice(cfg.voice_channel_id)
                if not result.get("ok"):
                    logger.warning("Discord voice auto-join failed: %s", result.get("error"))
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            try:
                if _voice_client and getattr(_voice_client, "is_connected", lambda: False)():
                    await _voice_client.disconnect()
            except Exception:
                pass
            raise
        except Exception:
            logger.exception("Error in discord worker poll loop")
            await asyncio.sleep(5)


async def _watch_and_join(loop: asyncio.AbstractEventLoop):
    global _client, _status
    if discord is None:
        logger.info("discord.py not installed — discord worker disabled")
        return

    while True:
        token = settings.integrations.discord.bot_token
        if not token:
            logger.info("No discord token configured — worker will retry in 5s")
            await asyncio.sleep(5)
            continue

        intents = Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        _client = client

        @client.event
        async def on_ready():
            try:
                _status["connected"] = True
                _status["user"] = f"{client.user}"
                _status["guilds"] = [g.id for g in client.guilds]
                logger.info(f"Discord client logged in as {client.user} (id={client.user.id})")
            except Exception:
                logger.exception("Error in on_ready")

        @client.event
        async def on_disconnect():
            try:
                _status["connected"] = False
                logger.info("Discord client disconnected")
            except Exception:
                pass

        @client.event
        async def on_message(message):
            """Route bot-mode Discord text through the same AI policy as Equicord."""

            try:
                if client.user is None or message.author.id == client.user.id or message.author.bot:
                    return
                from app.api.discord_bridge import _on_message_create

                guild = getattr(message, "guild", None)
                await _on_message_create(
                    {
                        "id": str(message.id),
                        "channel_id": str(message.channel.id),
                        "guild_id": str(guild.id) if guild else None,
                        "content": str(message.content or ""),
                        "timestamp": message.created_at.isoformat() if message.created_at else None,
                        "author": {
                            "id": str(message.author.id),
                            "username": str(message.author),
                            "global_name": str(getattr(message.author, "display_name", "") or ""),
                            "bot": bool(message.author.bot),
                        },
                    },
                    transport="bot",
                )
            except Exception:
                logger.exception("Failed to process Discord bot message")

        poll_task = loop.create_task(_poll_config_and_join(client))
        try:
            logger.info("Starting Discord client")
            await client.start(token)
        except asyncio.CancelledError:
            logger.info("Discord client shutdown requested")
            break
        except Exception as e:
            logger.exception(f"Discord client errored: {e}")
            # try to close and then restart after a delay
            try:
                await client.close()
            except Exception:
                pass
            _client = None
            _status["connected"] = False
            await asyncio.sleep(5)
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            try:
                await client.close()
            except Exception:
                pass
            _client = None
            _status["connected"] = False

    logger.info("Discord worker exiting")


def start_worker(loop: asyncio.AbstractEventLoop) -> Optional[asyncio.Task]:
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return _worker_task
    _worker_task = loop.create_task(_watch_and_join(loop))
    return _worker_task


async def stop_worker():
    global _worker_task, _client, _status
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    _worker_task = None
    # also attempt to close client if present
    try:
        if _client is not None:
            await _client.close()
    except Exception:
        pass
    _client = None
    _status = {"connected": False, "user": None, "guilds": []}


def get_status() -> dict:
    status = dict(_status)
    status["voice_connected"] = bool(
        _voice_client and getattr(_voice_client, "is_connected", lambda: False)()
    )
    status["voice_channel_id"] = (
        str(getattr(getattr(_voice_client, "channel", None), "id", "") or "") or None
    )
    return status
