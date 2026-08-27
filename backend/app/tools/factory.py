from __future__ import annotations

from app.tools.discord import register_discord_tools
from app.tools.obs import register_obs_tools
from app.tools.registry import ToolRegistry
from app.tools.spotify import register_spotify_tools


def create_tool_registry() -> ToolRegistry:
    """Build the action allowlist for one chat turn.

    Future integrations (for example OBS scenes/recording or Discord message
    moderation) belong in their own module and add one ``register_*_tools``
    call here. Chat routing and model adapters do not need to change.
    """

    registry = ToolRegistry()
    register_spotify_tools(registry)
    register_discord_tools(registry)
    register_obs_tools(registry)
    return registry
