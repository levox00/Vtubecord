from __future__ import annotations

import logging
from html import escape
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.core.config import discord_responds_to_every_message, settings
from app.schemas.chat import (
    DiscordConfigUpdate,
    DiscordJoinRequest,
    IntegrationStatus,
    IntegrationsResponse,
    ObsConfigUpdate,
    ObsControlRequest,
    SpotifyControlRequest,
    SpotifyConfigUpdate,
    TwitchConfigUpdate,
)

from app.integrations import discord_worker
from app.integrations.spotify import SpotifyError, spotify_controller
from app.integrations.obs import ObsError, obs_controller
from app.audio_output import (
    AudioOutputError,
    get_audio_output_service,
    list_input_devices,
    list_output_devices,
    select_input_device,
    select_output_device,
)

logger = logging.getLogger(__name__)


def _event_log(level: str, message: str) -> None:
    try:
        from app.debug.events import add_event_log

        add_event_log(level, "discord_integration", message)
    except Exception:
        logger.log(getattr(logging, str(level).upper(), logging.INFO), str(message))

router = APIRouter()


def _discord_client_executables(build: str | None = None) -> list[str]:
    """Return the executable names for the selected client build."""
    build_key = (build or settings.integrations.discord.build or "stable").lower()
    mapping = {
        "stable": ["discord.exe", "discord"],
        "canary": ["discordcanary.exe", "discordcanary"],
        "ptb": ["discordptb.exe", "discordptb"],
    }
    return mapping.get(build_key, mapping["stable"])


def _is_discord_client_running(build: str | None = None) -> bool:
    """Check whether the selected Discord desktop client executable is active."""
    names = _discord_client_executables(build)
    import subprocess

    try:
        import psutil
        procs = {p.name().lower() for p in psutil.process_iter(attrs=["name"]) if p.info.get("name")}
        for name in names:
            if any(name.lower() == proc or proc.endswith(name.lower()) for proc in procs):
                return True
    except Exception:
        pass

    # Broad fallback: any process with "discord" in its name
    try:
        import psutil
        for p in psutil.process_iter(attrs=["name"]):
            pname = (p.info.get("name") or "").lower()
            if "discord" in pname:
                return True
    except Exception:
        pass

    # tasklist fallback
    try:
        out = subprocess.check_output(["tasklist"], stderr=subprocess.DEVNULL, text=True)
        if "discord" in out.lower():
            return True
    except Exception:
        pass

    return False


def _build_client_join_target(cfg, selected_build: str | None = None) -> str:
    """Best-effort deep link to a voice channel in the desktop client.

    Discord's custom protocol requires the guild/channel route to be explicit.
    A bare channel ID without a guild is not a valid join target for a voice
    channel, so we prefer the server + channel form and fall back to the app root
    only when nothing is configured.
    """
    channel_id = (getattr(cfg, "voice_channel_id", "") or "").strip()
    server_id = (getattr(cfg, "server_id", "") or "").strip()

    if server_id and channel_id:
        return f"discord://discord.com/channels/{server_id}/{channel_id}"
    if server_id:
        return f"discord://discord.com/channels/{server_id}"
    return "discord://"


def _mask_secret(value: str) -> str:
    """Mask a secret, showing only the last 4 characters."""
    if not value or len(value) <= 4:
        return "****" if value else ""
    return "*" * (len(value) - 4) + value[-4:]


def _get_integrations_status() -> list[IntegrationStatus]:
    """Build the list of integration statuses with masked secrets."""
    cfg = settings.integrations

    try:
        from app.api.discord_bridge import _active_connections

        discord_bridge_connected = bool(_active_connections)
    except Exception:
        discord_bridge_connected = False
    discord_configured = (
        bool(cfg.discord.bot_token)
        if str(cfg.discord.mode or "client").lower() == "bot"
        else discord_bridge_connected
    )
    spotify_configured = bool(cfg.spotify.client_id and cfg.spotify.client_secret)
    twitch_configured = bool(cfg.twitch.client_id and cfg.twitch.client_secret)
    obs_configured = bool(cfg.obs.host and cfg.obs.port)

    # Ask the worker for runtime status if available
    try:
        ds = discord_worker.get_status()
        discord_connected = bool(ds.get("connected")) or discord_bridge_connected
    except Exception:
        discord_connected = discord_bridge_connected

    return [
        IntegrationStatus(
            name="discord",
            enabled=cfg.discord.enabled,
            connected=discord_connected,
            configured=discord_configured,
            description="Discord bot for chat interaction and voice channel presence",
        ),
        IntegrationStatus(
            name="spotify",
            enabled=cfg.spotify.enabled,
            connected=spotify_controller.is_authenticated(),
            configured=spotify_configured,
            description="Spotify integration for music playback and queue management",
        ),
        IntegrationStatus(
            name="twitch",
            enabled=cfg.twitch.enabled,
            connected=False,
            configured=twitch_configured,
            description="Twitch integration for stream alerts and chat interaction",
        ),
        IntegrationStatus(
            name="obs",
            enabled=cfg.obs.enabled,
            connected=obs_controller.last_connected,
            configured=obs_configured,
            description="OBS Studio streaming, recording, scenes, Virtual Camera, and Discord camera routing",
        ),
    ]


@router.get("/integrations", response_model=IntegrationsResponse)
async def get_integrations() -> IntegrationsResponse:
    return IntegrationsResponse(integrations=_get_integrations_status())


@router.post("/integrations/discord")
async def update_discord(req: DiscordConfigUpdate) -> dict:
    discord = settings.integrations.discord
    if req.enabled is not None:
        discord.enabled = req.enabled
    if req.mode is not None:
        discord.mode = req.mode
    if req.build is not None:
        discord.build = req.build
    if req.channel_id is not None:
        discord.channel_id = req.channel_id.strip()
    if req.voice_channel_id is not None:
        discord.voice_channel_id = req.voice_channel_id.strip()
    if req.command_prefix is not None:
        # Whitespace-only means no prefix. Trimming also prevents an invisible
        # leading/trailing space from making a valid-looking prefix fail.
        discord.command_prefix = req.command_prefix.strip()
    if req.status_text is not None:
        discord.status_text = req.status_text
    if req.bot_token is not None:
        discord.bot_token = req.bot_token
    if req.server_id is not None:
        discord.server_id = req.server_id.strip()
    if req.auto_join_voice is not None:
        discord.auto_join_voice = req.auto_join_voice
    if req.join_message_author_voice is not None:
        discord.join_message_author_voice = req.join_message_author_voice
    if req.live_join_enabled is not None:
        discord.live_join_enabled = req.live_join_enabled
    if req.live_join_follow_author is not None:
        discord.live_join_follow_author = req.live_join_follow_author
    if req.join_method is not None:
        discord.join_method = req.join_method
    if req.voice_channel_mode is not None:
        discord.voice_channel_mode = req.voice_channel_mode
    if req.voice_channel_threshold is not None:
        discord.voice_channel_threshold = req.voice_channel_threshold
    if req.channel_mode is not None:
        discord.channel_mode = req.channel_mode
    if req.channel_list is not None:
        discord.channel_list = list(dict.fromkeys(item.strip() for item in req.channel_list if item.strip()))
    if req.allowed_user_ids is not None:
        discord.allowed_user_ids = list(
            dict.fromkeys(item.strip() for item in req.allowed_user_ids if item.strip())
        )
    if req.bridge_user_id is not None:
        discord.bridge_user_id = req.bridge_user_id.strip()
    if req.auto_reply is not None:
        discord.auto_reply = req.auto_reply
    if req.respond_to_every_message is not None:
        discord.respond_to_every_message = req.respond_to_every_message
        discord.auto_reply = req.respond_to_every_message
    if req.typing_indicator is not None:
        discord.typing_indicator = req.typing_indicator
    if req.voice_output_enabled is not None:
        settings.discord_voice_output.enabled = req.voice_output_enabled
    if req.voice_output_device_name is not None:
        settings.discord_voice_output.device_name = req.voice_output_device_name.strip() or "CABLE-B Input"
    if req.voice_input_enabled is not None:
        settings.discord_voice_input.enabled = req.voice_input_enabled
    if req.voice_input_device_name is not None:
        settings.discord_voice_input.device_name = req.voice_input_device_name.strip() or "CABLE-A Output"
    if req.voice_input_chunk_ms is not None:
        settings.discord_voice_input.chunk_ms = req.voice_input_chunk_ms if req.voice_input_chunk_ms in (80, 160, 320, 560, 1120) else 320
    if req.voice_input_silence_ms is not None:
        settings.discord_voice_input.silence_ms = min(max(int(req.voice_input_silence_ms), 600), 3000)
    if req.voice_input_mirror_transcript is not None:
        settings.discord_voice_input.mirror_transcript = req.voice_input_mirror_transcript
    if req.voice_input_mirror_text is not None:
        settings.discord_voice_input.mirror_text = req.voice_input_mirror_text

    from app.core.config import save_config
    save_config(settings)
    _event_log(
        "info",
        "Discord settings saved: enabled=%s mode=%s author_voice_join=%s voice_input=%s voice_output=%s input_device=%r output_device=%r"
        % (
            discord.enabled,
            discord.mode,
            discord.join_message_author_voice,
            settings.discord_voice_input.enabled,
            settings.discord_voice_output.enabled,
            settings.discord_voice_input.device_name,
            settings.discord_voice_output.device_name,
        ),
    )

    # Push config update to connected plugin + UI
    try:
        from app.api.discord_bridge import broadcast_config_updated
        await broadcast_config_updated()
        from app.api.discord_bridge import sync_discord_voice_input
        await sync_discord_voice_input()
    except Exception:
        pass

    return {
        "ok": True,
        "integration": "discord",
        "config": {
            "enabled": discord.enabled,
            "mode": discord.mode,
            "build": discord.build,
            "channel_id": discord.channel_id,
            "voice_channel_id": discord.voice_channel_id,
            "command_prefix": discord.command_prefix,
            "status_text": discord.status_text,
            "bot_token": _mask_secret(discord.bot_token),
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
            "bridge_user_id": discord.bridge_user_id,
            "auto_reply": discord.auto_reply,
            "respond_to_every_message": discord_responds_to_every_message(discord),
            "typing_indicator": discord.typing_indicator,
            "voice_output_enabled": settings.discord_voice_output.enabled,
            "voice_output_device_name": settings.discord_voice_output.device_name,
            "voice_input_enabled": settings.discord_voice_input.enabled,
            "voice_input_device_name": settings.discord_voice_input.device_name,
            "voice_input_chunk_ms": settings.discord_voice_input.chunk_ms,
            "voice_input_silence_ms": settings.discord_voice_input.silence_ms,
            "voice_input_mirror_transcript": settings.discord_voice_input.mirror_transcript,
            "voice_input_mirror_text": settings.discord_voice_input.mirror_text,
        },
    }


@router.post("/integrations/spotify")
async def update_spotify(req: SpotifyConfigUpdate) -> dict:
    spotify = settings.integrations.spotify
    if req.enabled is not None:
        spotify.enabled = req.enabled
    if req.client_id is not None:
        spotify.client_id = req.client_id
    if req.client_secret is not None:
        spotify.client_secret = req.client_secret
    if req.redirect_uri is not None:
        spotify.redirect_uri = req.redirect_uri

    from app.core.config import save_config
    save_config(settings)

    return {
        "ok": True,
        "integration": "spotify",
        "config": {
            "enabled": spotify.enabled,
            "client_id": _mask_secret(spotify.client_id),
            "client_secret": _mask_secret(spotify.client_secret),
            "redirect_uri": spotify.redirect_uri,
        },
    }


def _spotify_redirect_uri(request: Request) -> str:
    """Use a Spotify-compliant loopback callback for local installations.

    Spotify rejects ``localhost`` redirect URIs. Existing projects may still
    have the old localhost/8088 value, so normalize those values to the
    explicit IPv4 loopback address while preserving custom HTTPS callbacks.
    """
    default_uri = "http://127.0.0.1:8000/api/integrations/spotify/callback"
    configured = settings.integrations.spotify.redirect_uri.strip()
    if not configured:
        return default_uri

    parsed = urlparse(configured)
    if parsed.hostname == "localhost":
        # Migrate the existing callback to the backend's supported route.
        if parsed.port in (None, 8000, 8088) or parsed.path in ("", "/callback"):
            return default_uri
        netloc = f"127.0.0.1:{parsed.port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "[::1]"}:
        return configured
    if parsed.scheme == "https":
        return configured
    # Keep custom values visible to the user, but default unsupported local
    # values to the explicit callback rather than generating a localhost URL.
    return configured if configured.startswith("http://127.0.0.1:") else default_uri


@router.get("/integrations/spotify/auth-url")
async def spotify_auth_url(request: Request) -> dict:
    try:
        redirect_uri = _spotify_redirect_uri(request)
        url = spotify_controller.create_auth_url(redirect_uri)
    except SpotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.integrations.spotify.redirect_uri != redirect_uri:
        settings.integrations.spotify.redirect_uri = redirect_uri
        from app.core.config import save_config

        save_config(settings)
    return {"ok": True, "auth_url": url, "redirect_uri": redirect_uri}


@router.get("/integrations/spotify/callback", response_class=HTMLResponse)
async def spotify_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> HTMLResponse:
    message = "Spotify connection cancelled."
    success = False
    if error:
        message = f"Spotify authorization was declined: {error}"
    elif not code or not state:
        message = "Spotify authorization did not include the required code."
    else:
        try:
            await spotify_controller.complete_auth(code, state)
            settings.integrations.spotify.enabled = True
            from app.core.config import save_config

            save_config(settings)
            message = "Spotify is connected. You can close this window and return to the AI VTuber."
            success = True
        except SpotifyError as exc:
            message = str(exc)
        except Exception:
            logger.exception("Spotify OAuth callback failed")
            message = "Spotify connection failed. Check the backend logs for details."

    status = "Connected" if success else "Unable to connect"
    color = "#23a55a" if success else "#f23f43"
    safe_message = escape(message)
    return HTMLResponse(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{status}</title>
<style>body{{font-family:system-ui,sans-serif;background:#1e1f22;color:#dbdee1;display:grid;place-items:center;min-height:100vh;margin:0}}main{{max-width:32rem;padding:2rem;text-align:center}}h1{{color:{color}}}p{{line-height:1.6;color:#b5bac1}}</style></head>
<body><main><h1>{status}</h1><p>{safe_message}</p><p>You can close this window.</p></main>
<script>window.opener?.postMessage({{type:'spotify-auth',success:{str(success).lower()}}}, '*'); setTimeout(() => window.close(), 700);</script>
</body></html>"""
    )


@router.get("/integrations/spotify/status")
async def spotify_status() -> dict:
    status = await spotify_controller.status()
    status["ai_control_mode"] = spotify_controller.ai_control_mode
    status["ai_tool_capable"] = spotify_controller.ai_control_mode == "tool_calling"
    tokens = spotify_controller._load_tokens()
    scopes = set(str(tokens.get("scope") or "").split())
    status["liked_songs_scope_granted"] = "user-library-read" in scopes
    status["liked_songs_modify_scope_granted"] = "user-library-modify" in scopes
    return status


@router.post("/integrations/spotify/control")
async def spotify_control(req: SpotifyControlRequest) -> dict:
    if not settings.integrations.spotify.enabled:
        raise HTTPException(status_code=400, detail="Spotify integration is disabled.")
    try:
        status = await spotify_controller.control(
            req.action,
            query=req.query,
            volume=req.volume,
            device_id=req.device_id,
        )
    except SpotifyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "status": status}


@router.post("/integrations/spotify/logout")
async def spotify_logout() -> dict:
    spotify_controller.clear_tokens()
    return {"ok": True}


@router.post("/integrations/twitch")
async def update_twitch(req: TwitchConfigUpdate) -> dict:
    twitch = settings.integrations.twitch
    if req.enabled is not None:
        twitch.enabled = req.enabled
    if req.client_id is not None:
        twitch.client_id = req.client_id
    if req.client_secret is not None:
        twitch.client_secret = req.client_secret
    if req.channel is not None:
        twitch.channel = req.channel

    from app.core.config import save_config
    save_config(settings)

    return {
        "ok": True,
        "integration": "twitch",
        "config": {
            "enabled": twitch.enabled,
            "client_id": _mask_secret(twitch.client_id),
            "client_secret": _mask_secret(twitch.client_secret),
            "channel": twitch.channel,
        },
    }


@router.post("/integrations/obs")
async def update_obs(req: ObsConfigUpdate) -> dict:
    obs = settings.integrations.obs
    if req.enabled is not None:
        obs.enabled = req.enabled
    if req.host is not None:
        obs.host = req.host.strip() or "127.0.0.1"
    if req.port is not None:
        if not 1 <= req.port <= 65535:
            raise HTTPException(status_code=400, detail="OBS WebSocket port must be between 1 and 65535.")
        obs.port = req.port
    if req.password is not None:
        # A masked value sent back by an older UI means keep the saved secret.
        if not req.password or "*" not in req.password:
            obs.password = req.password
    if req.request_timeout is not None:
        obs.request_timeout = max(1.0, min(30.0, req.request_timeout))
    if req.allowed_scenes is not None:
        obs.allowed_scenes = list(dict.fromkeys(item.strip() for item in req.allowed_scenes if item.strip()))
    if req.discord_camera_name is not None:
        obs.discord_camera_name = req.discord_camera_name.strip() or "OBS Virtual Camera"

    from app.core.config import save_config

    save_config(settings)
    return {
        "ok": True,
        "integration": "obs",
        "config": {
            "enabled": obs.enabled,
            "host": obs.host,
            "port": obs.port,
            "password": _mask_secret(obs.password),
            "request_timeout": obs.request_timeout,
            "allowed_scenes": obs.allowed_scenes,
            "discord_camera_name": obs.discord_camera_name,
        },
    }


@router.get("/integrations/obs/status")
async def obs_status() -> dict:
    status = await obs_controller.status()
    obs = settings.integrations.obs
    return {
        **status,
        "enabled": obs.enabled,
        "config": {
            "host": obs.host,
            "port": obs.port,
            "password_configured": bool(obs.password),
            "request_timeout": obs.request_timeout,
            "allowed_scenes": obs.allowed_scenes,
            "discord_camera_name": obs.discord_camera_name,
        },
    }


@router.post("/integrations/obs/test")
async def test_obs() -> dict:
    try:
        status = await obs_controller.status(raise_on_error=True)
    except ObsError as exc:
        return {"ok": False, "success": False, "message": str(exc)}
    return {
        "ok": True,
        "success": True,
        "message": f"Connected to OBS {status.get('obs_studio_version') or ''}.".strip(),
        "status": status,
    }


@router.post("/integrations/obs/control")
async def control_obs(req: ObsControlRequest) -> dict:
    if not settings.integrations.obs.enabled:
        raise HTTPException(status_code=400, detail="OBS integration is disabled.")
    operations = {
        "status": lambda: obs_controller.status(raise_on_error=True),
        "set_scene": lambda: obs_controller.set_scene(req.scene or ""),
        "start_stream": obs_controller.start_stream,
        "stop_stream": obs_controller.stop_stream,
        "start_recording": obs_controller.start_recording,
        "stop_recording": obs_controller.stop_recording,
        "start_virtual_camera": obs_controller.start_virtual_camera,
        "stop_virtual_camera": obs_controller.stop_virtual_camera,
        "start_discord_camera": obs_controller.start_discord_camera,
        "stop_discord_camera": obs_controller.stop_discord_camera,
    }
    try:
        result = await operations[req.action]()
    except ObsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "status": result}


@router.post("/integrations/discord/test")
async def test_discord() -> dict:
    discord = settings.integrations.discord
    if not discord.bot_token:
        return {"ok": False, "error": "No bot token configured"}
    if not discord.enabled:
        return {"ok": False, "error": "Discord integration is not enabled"}

    # Placeholder — actual connection test would go here
    try:
        runtime = discord_worker.get_status()
    except Exception:
        runtime = {"connected": False}
    return {"ok": True, "connected": bool(runtime.get("connected", False)), "runtime": runtime}


@router.post("/integrations/discord/join")
async def discord_join(req: DiscordJoinRequest) -> dict:
    """Request the running Discord integration (bot or client) to join a voice channel.

    Client-mode cannot auto-join a Discord voice channel from the server because the
    Discord desktop client itself must be running and must be controlled by the user.
    We therefore check for the local desktop client and return a clear status instead of
    pretending the join request succeeded.
    """
    import subprocess
    import sys

    discord = settings.integrations.discord

    # update persisted config fields if provided
    if req.channel_id is not None:
        discord.voice_channel_id = req.channel_id
    if req.method is not None:
        try:
            discord.join_method = req.method
        except Exception:
            setattr(discord, "join_method", req.method)
    if req.mode is not None:
        discord.voice_channel_mode = req.mode
    if req.threshold is not None:
        discord.voice_channel_threshold = req.threshold
    if req.mode_type is not None:
        discord.mode = req.mode_type

    try:
        discord.live_join_enabled = True
    except Exception:
        setattr(discord, "live_join_enabled", True)

    from app.core.config import save_config
    save_config(settings)

    # --- Bridge path: use Equicord plugin to join voice directly ---
    try:
        from app.api.discord_bridge import _active_connections, _send_command
        if _active_connections and discord.voice_channel_id:
            logger.info("Bridge connected — attempting join_voice via Equicord")
            result = await _send_command(
                "join_voice",
                {"channel_id": discord.voice_channel_id},
                timeout=10.0,
            )
            if result.get("ok"):
                return {
                    "ok": True,
                    "action": "bridge_join",
                    "message": f"Joined voice channel {discord.voice_channel_id} via Equicord bridge.",
                    "channel_id": discord.voice_channel_id,
                    "bridge": True,
                }
            logger.warning("Bridge join_voice failed: %s", result)
    except Exception as e:
        logger.debug("Bridge join attempt skipped: %s", e)

    # --- Fallback: deep link / bot worker ---
    mode = (req.mode_type or getattr(discord, "mode", "client") or "client").lower()
    if mode == "client":
        selected_build = (getattr(discord, "build", "stable") or "stable").lower()
        running = _is_discord_client_running(selected_build)
        if not running:
            return {
                "ok": False,
                "action": "client_not_running",
                "message": f"Discord {selected_build} is not running. Would you like to start it and join the channel?",
                "client_running": False,
                "selected_build": selected_build,
                "join_target": _build_client_join_target(discord, selected_build),
                "config": {
                    "voice_channel_id": discord.voice_channel_id,
                    "join_method": getattr(discord, "join_method", None),
                    "voice_channel_mode": discord.voice_channel_mode,
                    "voice_channel_threshold": discord.voice_channel_threshold,
                    "live_join_enabled": getattr(discord, "live_join_enabled", True),
                    "mode": getattr(discord, "mode", "client"),
                    "build": getattr(discord, "build", "stable"),
                },
            }

        join_target = _build_client_join_target(discord, selected_build)
        return {
            "ok": True,
            "action": "client_running",
            "message": "Selected Discord client is running. Attempting to open the target channel in Discord.",
            "client_running": True,
            "selected_build": selected_build,
            "join_target": join_target,
            "config": {
                "voice_channel_id": discord.voice_channel_id,
                "join_method": getattr(discord, "join_method", None),
                "voice_channel_mode": discord.voice_channel_mode,
                "voice_channel_threshold": discord.voice_channel_threshold,
                "live_join_enabled": getattr(discord, "live_join_enabled", True),
                "mode": getattr(discord, "mode", "client"),
                "build": getattr(discord, "build", "stable"),
            },
        }

    # bot mode: start worker and ask it to join via the configured token
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        discord_worker.start_worker(loop)
    except RuntimeError:
        pass

    runtime = {}
    try:
        runtime = discord_worker.get_status()
    except Exception:
        runtime = {"connected": False}

    return {
        "ok": True,
        "action": "join_requested",
        "config": {
            "voice_channel_id": discord.voice_channel_id,
            "join_method": getattr(discord, "join_method", None),
            "voice_channel_mode": discord.voice_channel_mode,
            "voice_channel_threshold": discord.voice_channel_threshold,
            "live_join_enabled": getattr(discord, "live_join_enabled", True),
            "mode": getattr(discord, "mode", "bot"),
        },
        "runtime": runtime,
    }


@router.post("/integrations/discord/start")
async def discord_start() -> dict:
    """Start the persistent discord integration worker (if not already running)."""
    import asyncio

    loop = asyncio.get_running_loop()
    task = discord_worker.start_worker(loop)
    status = {}
    try:
        status = discord_worker.get_status()
    except Exception:
        status = {"connected": False}
    return {"ok": True, "task_running": task is not None, "runtime": status}


@router.get("/integrations/discord/config")
async def get_discord_config() -> dict:
    """Return the persisted Discord integration configuration (safe for frontend).

    This exposes non-secret config back to the UI so the settings panel can
    populate its fields on load.
    """
    cfg = settings.integrations.discord
    from app.api.integrations import _mask_secret

    return {
        "ok": True,
        "config": {
            "enabled": cfg.enabled,
            "mode": getattr(cfg, "mode", "client"),
            "build": getattr(cfg, "build", "stable"),
            "channel_id": cfg.channel_id,
            "voice_channel_id": cfg.voice_channel_id,
            "command_prefix": cfg.command_prefix,
            "status_text": cfg.status_text,
            "bot_token_masked": _mask_secret(cfg.bot_token),
            "server_id": cfg.server_id,
            "auto_join_voice": cfg.auto_join_voice,
            "join_message_author_voice": getattr(cfg, "join_message_author_voice", False),
            "live_join_enabled": getattr(cfg, "live_join_enabled", False),
            "live_join_follow_author": getattr(cfg, "live_join_follow_author", False),
            "join_method": getattr(cfg, "join_method", "manual"),
            "voice_channel_mode": cfg.voice_channel_mode,
            "voice_channel_threshold": cfg.voice_channel_threshold,
            "channel_mode": cfg.channel_mode,
            "channel_list": cfg.channel_list,
            "allowed_user_ids": cfg.allowed_user_ids,
            "bridge_user_id": cfg.bridge_user_id,
            "auto_reply": cfg.auto_reply,
            "respond_to_every_message": discord_responds_to_every_message(cfg),
            "typing_indicator": cfg.typing_indicator,
            "voice_output_enabled": settings.discord_voice_output.enabled,
            "voice_output_device_name": settings.discord_voice_output.device_name,
            "voice_input_enabled": settings.discord_voice_input.enabled,
            "voice_input_device_name": settings.discord_voice_input.device_name,
            "voice_input_chunk_ms": settings.discord_voice_input.chunk_ms,
            "voice_input_silence_ms": settings.discord_voice_input.silence_ms,
            "voice_input_mirror_transcript": settings.discord_voice_input.mirror_transcript,
            "voice_input_mirror_text": settings.discord_voice_input.mirror_text,
        },
    }


@router.post("/integrations/discord/stop")
async def discord_stop() -> dict:
    """Stop the persistent discord integration worker."""
    await discord_worker.stop_worker()
    return {"ok": True, "stopped": True}


@router.get("/integrations/discord/status")
async def discord_status() -> dict:
    """Return runtime status for the discord integration worker."""
    try:
        status = discord_worker.get_status()
    except Exception:
        status = {"connected": False}
    cfg = settings.integrations.discord
    return {
        "ok": True,
        "runtime": status,
        "config": {
            "enabled": cfg.enabled,
            "bot_token_masked": _mask_secret(cfg.bot_token),
            "voice_channel_id": cfg.voice_channel_id,
            "live_join_enabled": getattr(cfg, "live_join_enabled", False),
            "live_join_follow_author": getattr(cfg, "live_join_follow_author", False),
        },
    }


def _discord_voice_output_config() -> dict[str, object]:
    cfg = settings.discord_voice_output
    return {"enabled": bool(cfg.enabled), "device_name": str(cfg.device_name or "CABLE-B Input")}


def _discord_voice_input_config() -> dict[str, object]:
    cfg = settings.discord_voice_input
    return {
        "enabled": bool(cfg.enabled),
        "device_name": str(cfg.device_name or "CABLE-A Output"),
        "chunk_ms": int(cfg.chunk_ms or 320),
        "silence_ms": int(cfg.silence_ms or 1200),
        "mirror_transcript": bool(cfg.mirror_transcript),
        "mirror_text": bool(cfg.mirror_text),
    }


@router.get("/integrations/discord/voice-output/devices")
async def discord_voice_output_devices() -> dict:
    """List Windows playback endpoints available to the Discord cable path."""

    return {"ok": True, "devices": list_output_devices()}


@router.get("/integrations/discord/voice-output/status")
async def discord_voice_output_status() -> dict:
    """Return cable, Equicord, and voice-channel readiness."""

    from app.api.discord_bridge import _active_connections, current_voice_state

    cfg = _discord_voice_output_config()
    service = get_audio_output_service()
    audio_status = service.status(str(cfg["device_name"]))
    bridge_connected = bool(_active_connections)
    voice_state: dict[str, object] = {"connected": False, "channel_id": None}
    if bridge_connected:
        try:
            voice_state = await current_voice_state()
        except Exception as exc:
            logger.debug("Could not read Discord voice state for audio status: %s", exc)
    return {
        "ok": True,
        "config": cfg,
        "device_found": bool(audio_status.get("device_found")),
        "device_selected": audio_status.get("device_selected"),
        "available_devices": audio_status.get("available_devices", []),
        "playing": bool(audio_status.get("playing")),
        "last_playback_error": audio_status.get("last_playback_error"),
        "bridge_connected": bridge_connected,
        "voice_connected": bool(voice_state.get("connected")),
        "voice_channel_id": voice_state.get("channel_id"),
        "diagnostics": {
            "ready": bool(cfg["enabled"] and bridge_connected and voice_state.get("connected") and audio_status.get("device_found")),
            "reason": (
                "disabled_in_settings" if not cfg["enabled"] else
                "bridge_disconnected" if not bridge_connected else
                "voice_not_connected" if not voice_state.get("connected") else
                "playback_device_missing" if not audio_status.get("device_found") else
                "playback_error" if audio_status.get("last_playback_error") else
                "ready"
            ),
            "next_step": (
                "Enable Discord voice output and press Save Discord settings." if not cfg["enabled"] else
                "Connect the Equicord bridge." if not bridge_connected else
                "Join a Discord voice channel with the Neuro account." if not voice_state.get("connected") else
                f"Select an available playback device matching {cfg['device_name']!r}." if not audio_status.get("device_found") else
                "Check the last playback error and test the selected device." if audio_status.get("last_playback_error") else
                "Ready to route AI speech through the selected cable."
            ),
        },
    }


@router.post("/integrations/discord/voice-output/test")
async def discord_voice_output_test() -> dict:
    """Generate a short sample and play it through the configured endpoint."""

    from app.api.routes import _generate_tts_audio
    from app.schemas.chat import TTSRequest

    cfg = settings.discord_voice_output
    service = get_audio_output_service()
    try:
        # This tests only the local output device; a Discord voice channel is
        # not required for the device test.
        select_output_device(cfg.device_name)
        audio = await _generate_tts_audio(TTSRequest(text="Discord voice output is working."))
        status = await service.play(audio.data, audio.media_type, device_name=cfg.device_name)
    except (AudioOutputError, HTTPException) as exc:
        detail = getattr(exc, "detail", None) or str(exc)
        _event_log("error", f"Discord voice output test failed for {cfg.device_name!r}: {detail}")
        return {"ok": False, "error": detail, "status": service.status(cfg.device_name)}
    except Exception as exc:
        logger.exception("Discord voice output test failed")
        _event_log("error", f"Discord voice output test failed for {cfg.device_name!r}: {exc}")
        return {"ok": False, "error": str(exc), "status": service.status(cfg.device_name)}
    _event_log("info", f"Discord voice output test played through {cfg.device_name!r}")
    return {"ok": True, "message": "Test audio played through the configured device.", "status": status}


@router.get("/integrations/discord/voice-input/devices")
async def discord_voice_input_devices() -> dict:
    """List recording endpoints available for Discord call capture."""

    return {"ok": True, "devices": list_input_devices()}


@router.get("/integrations/discord/voice-input/status")
async def discord_voice_input_status() -> dict:
    """Return capture, Nemotron, bridge, and queue readiness."""

    from app.api.discord_bridge import _active_connections, _discord_voice_queues, current_voice_state, sync_discord_voice_input
    from app.discord_voice import discord_voice_input

    cfg = _discord_voice_input_config()
    bridge_connected = bool(_active_connections)
    voice_state: dict[str, object] = {"connected": False, "channel_id": None}
    if bridge_connected:
        try:
            voice_state = await current_voice_state()
        except Exception as exc:
            logger.debug("Could not read Discord voice state for input status: %s", exc)
    await sync_discord_voice_input(voice_state)
    capture = discord_voice_input.status()
    configured_provider = str(settings.stt.provider or "").strip().lower()
    if not configured_provider:
        configured_provider = "nemo_speech" if str(settings.stt.model).startswith("nemotron-") else "faster_whisper"
    if configured_provider == "nemo_speech":
        try:
            from app.stt_runtime import nemo_sidecar
            runtime = await nemo_sidecar.runtime(settings.stt.model)
        except Exception:
            runtime = {"provider": "nemo_speech", "model": settings.stt.model, "ready": False}
    else:
        # Faster-Whisper loads lazily on the first endpointed utterance. It is
        # still the selected runtime and should not be reported as a missing
        # Nemotron sidecar while the capture stream is waiting for speech.
        runtime = {
            "provider": "faster_whisper",
            "model": settings.stt.model,
            "device": settings.stt.device,
            "compute_type": settings.stt.compute_type,
            "ready": True,
            "streaming": False,
        }
    channel_id = voice_state.get("channel_id")
    queue_depth = 0
    if channel_id:
        queue = _discord_voice_queues.get(str(channel_id))
        if queue is not None:
            queue_depth = queue.qsize()
    voice_connected = bool(voice_state.get("connected"))
    capture_running = bool(capture.get("running"))
    capture_error = capture.get("last_error")
    runtime_ready = bool(runtime.get("ready"))
    device_found = bool(capture.get("device_found"))
    diagnostics_reason = (
        "disabled_in_settings" if not cfg["enabled"] else
        "bridge_disconnected" if not bridge_connected else
        "voice_not_connected" if not voice_connected else
        "capture_device_missing" if not device_found else
        "runtime_not_ready" if not runtime_ready and not capture_running else
        "capture_error" if capture_error else
        "streaming" if capture_running else
        "waiting_for_capture"
    )
    diagnostics_next_step = {
        "disabled_in_settings": "Enable Discord voice transcription and press Save Discord settings.",
        "bridge_disconnected": "Connect the Equicord bridge.",
        "voice_not_connected": "Join a Discord voice channel with the Neuro account.",
        "capture_device_missing": f"Select an available recording device matching {cfg['device_name']!r}.",
        "runtime_not_ready": "Start/download the selected Nemotron streaming runtime and wait for it to become ready.",
        "capture_error": str(capture_error or "Check the Discord voice capture logs."),
        "streaming": "Audio is being captured and streamed to Nemotron.",
        "waiting_for_capture": "Waiting for the capture stream to start.",
    }[diagnostics_reason]
    return {
        "ok": True,
        "config": cfg,
        "capture": capture,
        "runtime": runtime,
        "bridge_connected": bridge_connected,
        "voice_connected": voice_connected,
        "voice_channel_id": voice_state.get("channel_id"),
        "queue_depth": queue_depth,
        "diagnostics": {
            "ready": diagnostics_reason == "streaming",
            "reason": diagnostics_reason,
            "next_step": diagnostics_next_step,
        },
    }


@router.post("/integrations/discord/voice-input/test")
async def discord_voice_input_test() -> dict:
    """Validate that the configured Discord capture endpoint is available."""

    cfg = settings.discord_voice_input
    from app.discord_voice import discord_voice_input

    try:
        device = select_input_device(cfg.device_name)
    except AudioOutputError as exc:
        _event_log("error", f"Discord voice input device test failed for {cfg.device_name!r}: {exc}")
        return {"ok": False, "error": str(exc), "status": discord_voice_input.status()}
    _event_log("info", f"Discord voice input device test passed: {device.get('name')!r}")
    return {
        "ok": True,
        "message": "Discord capture device is available. Join a voice channel to begin streaming.",
        "device": device,
        "status": discord_voice_input.status(),
    }


@router.post("/integrations/spotify/test")
async def test_spotify() -> dict:
    spotify = settings.integrations.spotify
    if not spotify.client_id or not spotify.client_secret:
        return {"ok": False, "error": "Spotify client ID and secret not configured"}
    if not spotify.enabled:
        return {"ok": False, "error": "Spotify integration is not enabled"}

    status = await spotify_controller.status()
    if not status.get("connected"):
        return {
            "ok": False,
            "success": False,
            "connected": False,
            "message": "Spotify credentials are configured, but the account is not connected.",
        }
    if status.get("error"):
        return {"ok": False, "success": False, "connected": True, "message": status["error"]}
    return {
        "ok": True,
        "success": True,
        "connected": True,
        "message": "Spotify is connected and ready for playback control.",
    }
