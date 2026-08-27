from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.integrations.obs import ObsError, obs_controller
from app.tools.registry import ToolExecutionError, ToolRegistry, ToolSpec

EMPTY_PARAMETERS = {"type": "object", "properties": {}, "additionalProperties": False}

OBS_GUIDANCE = (
    "OBS tools control the configured OBS Studio instance. Use obs_start_stream/obs_stop_stream only "
    "for the internet livestream output configured inside OBS. Use obs_start_discord_camera to show "
    "the OBS Virtual Camera as Neuro's camera in an already joined Discord voice call; this is separate "
    "from OBS internet streaming. Use obs_set_scene for named scene changes. Never claim a stream, "
    "recording, virtual camera, Discord camera, or scene changed until the tool reports verified state."
)

OBS_INTENT_HINTS = (
    "obs",
    "livestream",
    "live stream",
    "start stream",
    "stop stream",
    "end stream",
    "go live",
    "go offline",
    "start broadcasting",
    "stop broadcasting",
    "scene",
    "switch scene",
    "change scene",
    "recording",
    "start recording",
    "stop recording",
    "record this",
    "record the stream",
    "virtual camera",
    "virtual cam",
    "obs camera",
    "discord camera",
    "discord video",
    "camera to discord",
    "camera in discord",
    "share your camera",
    "show your camera",
    "turn on camera",
    "turn off camera",
)


def _available() -> bool:
    return bool(settings.integrations.obs.enabled)


async def _run(operation: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    try:
        return await operation()
    except ObsError as exc:
        raise ToolExecutionError(str(exc)) from exc


async def _status(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(lambda: obs_controller.status(raise_on_error=True))
    return {**result, "confirmation": _status_confirmation(result)}


def _status_confirmation(result: dict[str, Any]) -> str:
    scene = result.get("current_scene") or "unknown scene"
    stream = "live" if (result.get("stream") or {}).get("active") else "offline"
    recording = "recording" if (result.get("recording") or {}).get("active") else "not recording"
    virtual = "on" if (result.get("virtual_camera") or {}).get("active") else "off"
    discord = "on" if (result.get("discord_camera") or {}).get("active") else "off"
    return (
        f"OBS is connected on {scene}; stream {stream}, {recording}, "
        f"virtual camera {virtual}, Discord camera {discord}."
    )


async def _set_scene(arguments: dict[str, Any]) -> dict[str, Any]:
    scene = str(arguments.get("scene") or "").strip()
    result = await _run(lambda: obs_controller.set_scene(scene))
    return {**result, "confirmation": f"Switched OBS to scene {result.get('current_scene')}."}


async def _start_stream(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.start_stream)
    if not (result.get("stream") or {}).get("active"):
        raise ToolExecutionError("OBS did not report an active livestream after the start request.")
    return {**result, "confirmation": "OBS livestream output is now active."}


async def _stop_stream(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.stop_stream)
    if (result.get("stream") or {}).get("active"):
        raise ToolExecutionError("OBS still reports an active livestream after the stop request.")
    return {**result, "confirmation": "OBS livestream output is stopped."}


async def _start_recording(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.start_recording)
    if not (result.get("recording") or {}).get("active"):
        raise ToolExecutionError("OBS did not report an active recording after the start request.")
    return {**result, "confirmation": "OBS recording is now active."}


async def _stop_recording(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.stop_recording)
    if (result.get("recording") or {}).get("active"):
        raise ToolExecutionError("OBS still reports an active recording after the stop request.")
    return {**result, "confirmation": "OBS recording is stopped."}


async def _start_virtual_camera(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.start_virtual_camera)
    if not (result.get("virtual_camera") or {}).get("active"):
        raise ToolExecutionError("OBS did not report an active Virtual Camera after the start request.")
    return {**result, "confirmation": "OBS Virtual Camera is now active."}


async def _stop_virtual_camera(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.stop_virtual_camera)
    if (result.get("virtual_camera") or {}).get("active"):
        raise ToolExecutionError("OBS still reports an active Virtual Camera after the stop request.")
    return {**result, "confirmation": "OBS Virtual Camera is stopped."}


async def _start_discord_camera(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.start_discord_camera)
    return {
        **result,
        "confirmation": "OBS Virtual Camera is active and verified as Neuro's Discord camera.",
    }


async def _stop_discord_camera(_arguments: dict[str, Any]) -> dict[str, Any]:
    result = await _run(obs_controller.stop_discord_camera)
    return {
        **result,
        "confirmation": "Neuro's Discord camera and OBS Virtual Camera are stopped.",
    }


def register_obs_tools(registry: ToolRegistry) -> None:
    common = {
        "category": "obs",
        "guidance": OBS_GUIDANCE,
        "intent_hints": OBS_INTENT_HINTS,
        "available": _available,
    }
    registry.register(ToolSpec(
        name="obs_get_status",
        description="Read OBS connection, current scene, livestream, recording, and Virtual Camera status without changing anything.",
        parameters=EMPTY_PARAMETERS,
        handler=_status,
        max_calls_per_turn=2,
        **common,
    ))
    registry.register(ToolSpec(
        name="obs_set_scene",
        description="Switch the active OBS program scene to an allowed scene name.",
        parameters={
            "type": "object",
            "properties": {"scene": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["scene"],
            "additionalProperties": False,
        },
        handler=_set_scene,
        **common,
    ))
    for name, description, handler in (
        ("obs_start_stream", "Start the OBS internet livestream output already configured in OBS.", _start_stream),
        ("obs_stop_stream", "Stop the active OBS internet livestream output when explicitly requested.", _stop_stream),
        ("obs_start_recording", "Start recording locally in OBS.", _start_recording),
        ("obs_stop_recording", "Stop the active OBS recording when explicitly requested.", _stop_recording),
        ("obs_start_virtual_camera", "Start OBS Virtual Camera without changing Discord camera state.", _start_virtual_camera),
        ("obs_stop_virtual_camera", "Stop OBS Virtual Camera when explicitly requested.", _stop_virtual_camera),
        ("obs_start_discord_camera", "Start OBS Virtual Camera, select it in Discord, and turn on Neuro's camera in the current voice call.", _start_discord_camera),
        ("obs_stop_discord_camera", "Turn off Neuro's Discord camera and stop OBS Virtual Camera.", _stop_discord_camera),
    ):
        registry.register(ToolSpec(
            name=name,
            description=description,
            parameters=EMPTY_PARAMETERS,
            handler=handler,
            **common,
        ))
