"""OBS Studio WebSocket v5 integration.

The controller intentionally exposes a small allowlist of OBS requests. It
does not pass arbitrary request names or payloads from an LLM to OBS.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import uuid
from typing import Any

import websockets

from app.core.config import settings

logger = logging.getLogger(__name__)


class ObsError(RuntimeError):
    """A safe, user-facing OBS connection or request error."""


def _authentication(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(
        hashlib.sha256(f"{password}{salt}".encode("utf-8")).digest()
    ).decode("ascii")
    return base64.b64encode(
        hashlib.sha256(f"{secret}{challenge}".encode("utf-8")).digest()
    ).decode("ascii")


def _clean_host(value: str) -> str:
    host = str(value or "127.0.0.1").strip()
    host = re.sub(r"^wss?://", "", host, flags=re.IGNORECASE).split("/", 1)[0]
    if host.startswith("[") and "]" in host:
        return host
    # A pasted host may contain the default port. The configured port remains
    # authoritative, so remove only a simple trailing numeric port.
    return re.sub(r":\d+$", "", host) or "127.0.0.1"


class ObsWebSocketClient:
    """Minimal JSON client for the OBS WebSocket v5 protocol."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0) -> None:
        self.host = _clean_host(host)
        self.port = max(1, min(65535, int(port)))
        self.password = str(password or "")
        self.timeout = max(1.0, min(30.0, float(timeout)))
        self.socket: Any = None
        self.hello: dict[str, Any] = {}

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    async def __aenter__(self) -> "ObsWebSocketClient":
        try:
            self.socket = await websockets.connect(
                self.url,
                open_timeout=self.timeout,
                close_timeout=1,
                ping_interval=20,
                max_size=2 * 1024 * 1024,
            )
            hello = await self._receive()
            if hello.get("op") != 0:
                raise ObsError("OBS WebSocket did not send a valid hello message.")
            self.hello = hello.get("d") if isinstance(hello.get("d"), dict) else {}
            identify: dict[str, Any] = {
                "rpcVersion": min(1, int(self.hello.get("rpcVersion") or 1)),
                # No events are needed; every action is verified with a read.
                "eventSubscriptions": 0,
            }
            auth = self.hello.get("authentication")
            if isinstance(auth, dict):
                if not self.password:
                    raise ObsError("OBS WebSocket requires a password. Add it in the OBS integration settings.")
                identify["authentication"] = _authentication(
                    self.password,
                    str(auth.get("salt") or ""),
                    str(auth.get("challenge") or ""),
                )
            await self.socket.send(json.dumps({"op": 1, "d": identify}))
            identified = await self._receive()
            if identified.get("op") != 2:
                raise ObsError("OBS WebSocket authentication failed. Check the configured password.")
            return self
        except ObsError:
            await self._close()
            raise
        except (OSError, asyncio.TimeoutError) as exc:
            await self._close()
            raise ObsError(
                f"Could not connect to OBS WebSocket at {self.host}:{self.port}. Start OBS and enable its WebSocket server."
            ) from exc
        except Exception as exc:
            await self._close()
            message = str(exc).lower()
            if "authentication" in message or "4009" in message:
                raise ObsError("OBS WebSocket authentication failed. Check the configured password.") from exc
            raise ObsError("OBS WebSocket connection failed.") from exc

    async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        await self._close()

    async def _close(self) -> None:
        socket, self.socket = self.socket, None
        if socket is not None:
            try:
                await socket.close()
            except Exception:
                pass

    async def _receive(self) -> dict[str, Any]:
        if self.socket is None:
            raise ObsError("OBS WebSocket is not connected.")
        try:
            raw = await asyncio.wait_for(self.socket.recv(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise ObsError("OBS WebSocket timed out while waiting for a response.") from exc
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ObsError("OBS WebSocket returned an invalid response.") from exc
        return payload if isinstance(payload, dict) else {}

    async def request(self, request_type: str, request_data: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.socket is None:
            raise ObsError("OBS WebSocket is not connected.")
        request_id = uuid.uuid4().hex
        data: dict[str, Any] = {
            "requestType": request_type,
            "requestId": request_id,
        }
        if request_data:
            data["requestData"] = request_data
        await self.socket.send(json.dumps({"op": 6, "d": data}))

        while True:
            payload = await self._receive()
            if payload.get("op") != 7:
                continue
            response = payload.get("d") if isinstance(payload.get("d"), dict) else {}
            if response.get("requestId") != request_id:
                continue
            status = response.get("requestStatus") if isinstance(response.get("requestStatus"), dict) else {}
            if not status.get("result"):
                comment = str(status.get("comment") or "OBS rejected the request.").strip()
                raise ObsError(f"OBS {request_type} failed: {comment[:240]}")
            result = response.get("responseData")
            return result if isinstance(result, dict) else {}


class ObsController:
    def __init__(self) -> None:
        self.last_connected = False
        self.last_error: str | None = None

    def _client(self) -> ObsWebSocketClient:
        cfg = settings.integrations.obs
        return ObsWebSocketClient(cfg.host, cfg.port, cfg.password, cfg.request_timeout)

    @staticmethod
    async def _status_from(client: ObsWebSocketClient) -> dict[str, Any]:
        version = await client.request("GetVersion")
        stream = await client.request("GetStreamStatus")
        record = await client.request("GetRecordStatus")
        virtual_camera = await client.request("GetVirtualCamStatus")
        scenes = await client.request("GetSceneList")
        return {
            "connected": True,
            "obs_studio_version": version.get("obsVersion") or client.hello.get("obsStudioVersion"),
            "obs_websocket_version": version.get("obsWebSocketVersion") or client.hello.get("obsWebSocketVersion"),
            "current_scene": scenes.get("currentProgramSceneName"),
            "scenes": [
                item.get("sceneName")
                for item in (scenes.get("scenes") or [])
                if isinstance(item, dict) and item.get("sceneName")
            ],
            "stream": {
                "active": bool(stream.get("outputActive")),
                "reconnecting": bool(stream.get("outputReconnecting")),
                "timecode": stream.get("outputTimecode"),
                "duration_ms": stream.get("outputDuration"),
                "bytes": stream.get("outputBytes"),
                "skipped_frames": stream.get("outputSkippedFrames"),
                "total_frames": stream.get("outputTotalFrames"),
            },
            "recording": {
                "active": bool(record.get("outputActive")),
                "paused": bool(record.get("outputPaused")),
                "timecode": record.get("outputTimecode"),
                "duration_ms": record.get("outputDuration"),
                "bytes": record.get("outputBytes"),
            },
            "virtual_camera": {
                "active": bool(virtual_camera.get("outputActive")),
            },
        }

    @staticmethod
    async def _add_discord_camera_status(result: dict[str, Any]) -> dict[str, Any]:
        """Attach observed Discord camera state without making OBS depend on it."""

        from app.api.discord_bridge import bridge_is_connected, current_voice_state

        if not bridge_is_connected():
            result["discord_camera"] = {
                "bridge_connected": False,
                "voice_connected": False,
                "active": False,
            }
            return result
        try:
            voice = await current_voice_state()
        except Exception:
            logger.exception("Could not read Discord camera state while checking OBS")
            result["discord_camera"] = {
                "bridge_connected": True,
                "voice_connected": False,
                "active": False,
                "error": "Discord camera status is unavailable.",
            }
            return result
        result["discord_camera"] = {
            "bridge_connected": True,
            "voice_connected": bool(voice.get("connected")),
            "active": bool(voice.get("self_video")),
            "device_id": voice.get("video_device_id"),
            "device_name": voice.get("video_device_name"),
        }
        return result

    async def status(self, *, raise_on_error: bool = False) -> dict[str, Any]:
        try:
            async with self._client() as client:
                result = await self._status_from(client)
            await self._add_discord_camera_status(result)
        except ObsError as exc:
            self.last_connected = False
            self.last_error = str(exc)
            if raise_on_error:
                raise
            return {"connected": False, "error": str(exc)}
        self.last_connected = True
        self.last_error = None
        return result

    async def _set_output(self, status_request: str, action_request: str, *, desired: bool) -> dict[str, Any]:
        async with self._client() as client:
            before = await client.request(status_request)
            changed = bool(before.get("outputActive")) != desired
            if changed:
                await client.request(action_request)
            result = await self._status_from(client)
        status_key = {
            "GetStreamStatus": "stream",
            "GetRecordStatus": "recording",
            "GetVirtualCamStatus": "virtual_camera",
        }[status_request]
        if bool((result.get(status_key) or {}).get("active")) != desired:
            action = "start" if desired else "stop"
            label = status_key.replace("_", " ")
            raise ObsError(f"OBS accepted the request but did not {action} {label}.")
        await self._add_discord_camera_status(result)
        self.last_connected = True
        self.last_error = None
        result["changed"] = changed
        return result

    async def start_stream(self) -> dict[str, Any]:
        return await self._set_output("GetStreamStatus", "StartStream", desired=True)

    async def stop_stream(self) -> dict[str, Any]:
        return await self._set_output("GetStreamStatus", "StopStream", desired=False)

    async def start_recording(self) -> dict[str, Any]:
        return await self._set_output("GetRecordStatus", "StartRecord", desired=True)

    async def stop_recording(self) -> dict[str, Any]:
        return await self._set_output("GetRecordStatus", "StopRecord", desired=False)

    async def start_virtual_camera(self) -> dict[str, Any]:
        return await self._set_output("GetVirtualCamStatus", "StartVirtualCam", desired=True)

    async def stop_virtual_camera(self) -> dict[str, Any]:
        return await self._set_output("GetVirtualCamStatus", "StopVirtualCam", desired=False)

    async def start_discord_camera(self) -> dict[str, Any]:
        virtual_status = await self.start_virtual_camera()
        virtual_started_here = bool(virtual_status.get("changed"))
        from app.api.discord_bridge import set_self_camera_state

        discord = await set_self_camera_state(
            enabled=True,
            device_name=settings.integrations.obs.discord_camera_name,
        )
        if not discord.get("ok"):
            if virtual_started_here:
                try:
                    await self.stop_virtual_camera()
                except ObsError:
                    pass
            raise ObsError(str(discord.get("error") or "Discord could not enable the OBS Virtual Camera."))
        return {"obs": virtual_status, "discord": discord}

    async def stop_discord_camera(self) -> dict[str, Any]:
        from app.api.discord_bridge import set_self_camera_state

        discord = await set_self_camera_state(
            enabled=False,
            device_name=settings.integrations.obs.discord_camera_name,
        )
        if not discord.get("ok"):
            raise ObsError(str(discord.get("error") or "Discord could not disable Neuro's camera."))
        virtual_status = await self.stop_virtual_camera()
        return {"obs": virtual_status, "discord": discord}

    async def set_scene(self, requested_scene: str) -> dict[str, Any]:
        scene = re.sub(r"\s+", " ", str(requested_scene or "").strip())
        if not scene:
            raise ObsError("Tell me which OBS scene to switch to.")
        allowed = [str(item).strip() for item in settings.integrations.obs.allowed_scenes if str(item).strip()]
        if allowed and scene.casefold() not in {item.casefold() for item in allowed}:
            raise ObsError(f"OBS scene “{scene}” is not in the configured allowlist.")

        async with self._client() as client:
            scenes = await client.request("GetSceneList")
            available = [
                str(item.get("sceneName"))
                for item in (scenes.get("scenes") or [])
                if isinstance(item, dict) and item.get("sceneName")
            ]
            canonical = next((name for name in available if name.casefold() == scene.casefold()), None)
            if canonical is None:
                raise ObsError(f"OBS scene “{scene}” was not found.")
            if scenes.get("currentProgramSceneName") != canonical:
                await client.request("SetCurrentProgramScene", {"sceneName": canonical})
            result = await self._status_from(client)
        self.last_connected = True
        self.last_error = None
        return result


obs_controller = ObsController()
