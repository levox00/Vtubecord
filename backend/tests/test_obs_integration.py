from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.api import discord_bridge
from app.core.config import settings
from app.integrations.obs import ObsController, ObsError
from app.tools import create_tool_registry


class FakeObsClient:
    def __init__(self, *, apply_actions: bool = True) -> None:
        self.apply_actions = apply_actions
        self.hello = {
            "obsStudioVersion": "31.0.0",
            "obsWebSocketVersion": "5.6.0",
        }
        self.stream = False
        self.recording = False
        self.virtual_camera = False
        self.current_scene = "Just Chatting"
        self.scenes = ["Gameplay", "Just Chatting", "BRB"]
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "FakeObsClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def request(
        self,
        request_type: str,
        request_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = request_data or {}
        self.requests.append((request_type, data))
        if self.apply_actions:
            if request_type == "StartStream":
                self.stream = True
            elif request_type == "StopStream":
                self.stream = False
            elif request_type == "StartRecord":
                self.recording = True
            elif request_type == "StopRecord":
                self.recording = False
            elif request_type == "StartVirtualCam":
                self.virtual_camera = True
            elif request_type == "StopVirtualCam":
                self.virtual_camera = False
            elif request_type == "SetCurrentProgramScene":
                self.current_scene = str(data["sceneName"])

        if request_type == "GetVersion":
            return {"obsVersion": "31.0.0", "obsWebSocketVersion": "5.6.0"}
        if request_type == "GetStreamStatus":
            return {"outputActive": self.stream, "outputReconnecting": False}
        if request_type == "GetRecordStatus":
            return {"outputActive": self.recording, "outputPaused": False}
        if request_type == "GetVirtualCamStatus":
            return {"outputActive": self.virtual_camera}
        if request_type == "GetSceneList":
            return {
                "currentProgramSceneName": self.current_scene,
                "scenes": [{"sceneName": name} for name in self.scenes],
            }
        return {}


def _controller_with(client: FakeObsClient, monkeypatch: pytest.MonkeyPatch) -> ObsController:
    controller = ObsController()
    monkeypatch.setattr(controller, "_client", lambda: client)
    monkeypatch.setattr(discord_bridge, "bridge_is_connected", lambda: False)
    return controller


def test_obs_outputs_are_idempotent_and_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        client = FakeObsClient()
        controller = _controller_with(client, monkeypatch)

        started = await controller.start_stream()
        assert started["stream"]["active"] is True
        assert started["changed"] is True

        already_started = await controller.start_stream()
        assert already_started["stream"]["active"] is True
        assert already_started["changed"] is False

        stopped = await controller.stop_stream()
        assert stopped["stream"]["active"] is False
        assert stopped["changed"] is True
        assert [name for name, _data in client.requests].count("StartStream") == 1

    asyncio.run(run())


def test_obs_does_not_report_success_when_output_state_did_not_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        controller = _controller_with(FakeObsClient(apply_actions=False), monkeypatch)
        with pytest.raises(ObsError, match="did not start stream"):
            await controller.start_stream()

    asyncio.run(run())


def test_obs_scene_names_are_canonicalized_and_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = FakeObsClient()
        controller = _controller_with(client, monkeypatch)
        monkeypatch.setattr(settings.integrations.obs, "allowed_scenes", ["Gameplay", "BRB"])

        result = await controller.set_scene("gameplay")
        assert result["current_scene"] == "Gameplay"
        with pytest.raises(ObsError, match="allowlist"):
            await controller.set_scene("Just Chatting")

    asyncio.run(run())


def test_discord_camera_rolls_back_virtual_camera_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        controller = ObsController()
        stopped = False

        async def start_virtual_camera() -> dict[str, Any]:
            return {"changed": True, "virtual_camera": {"active": True}}

        async def stop_virtual_camera() -> dict[str, Any]:
            nonlocal stopped
            stopped = True
            return {"changed": True, "virtual_camera": {"active": False}}

        async def reject_camera(**_kwargs: Any) -> dict[str, Any]:
            return {"ok": False, "error": "Discord camera device was not found."}

        monkeypatch.setattr(controller, "start_virtual_camera", start_virtual_camera)
        monkeypatch.setattr(controller, "stop_virtual_camera", stop_virtual_camera)
        monkeypatch.setattr(discord_bridge, "set_self_camera_state", reject_camera)

        with pytest.raises(ObsError, match="not found"):
            await controller.start_discord_camera()
        assert stopped is True

    asyncio.run(run())


def test_discord_camera_command_requires_verified_video_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        states = iter(
            [
                {"connected": True, "self_video": False},
                {
                    "connected": True,
                    "self_video": True,
                    "video_device_name": "OBS Virtual Camera",
                },
            ]
        )

        async def voice_state() -> dict[str, Any]:
            return next(states)

        async def send_command(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "payload": {
                    "ok": True,
                    "video_enabled": True,
                    "video_device_name": "OBS Virtual Camera",
                },
            }

        monkeypatch.setattr(discord_bridge, "_active_connections", [object()])
        monkeypatch.setattr(discord_bridge, "current_voice_state", voice_state)
        monkeypatch.setattr(discord_bridge, "_send_command", send_command)

        result = await discord_bridge.set_self_camera_state(enabled=True)
        assert result["ok"] is True
        assert result["verified"] is True
        assert result["device_name"] == "OBS Virtual Camera"

    asyncio.run(run())


def test_obs_tools_are_available_to_semantic_tool_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings.integrations.obs, "enabled", True)
    registry = create_tool_registry()
    names = {spec.name for spec in registry.candidate_specs("stream your OBS camera to Discord")}
    assert "obs_start_discord_camera" in names
    assert "obs_start_stream" in names
    assert registry.get("obs_set_scene") is not None
    assert registry.candidate_specs("please go live now")
