from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.integrations.spotify import SPOTIFY_TOOL_DEFINITIONS, SpotifyError, spotify_controller
from app.tools.registry import ToolExecutionError, ToolRegistry, ToolSpec

SPOTIFY_GUIDANCE = (
    "Spotify tools control playback, queue, volume, shuffle, repeat, and status. "
    "Use spotify_play for one named song and spotify_play_artist when the user asks for songs/music "
    "from an artist or supplies an artist-profile URL. Preserve requested titles and artist names. "
    "Use spotify_play_favorites for requests for favorite, favourite, liked, or saved songs; it reads the "
    "user's actual Spotify Liked Songs and you must not invent a title or claim success before the tool result. "
    "That tool requires Spotify's user-library-read permission; if it is missing, ask the user to reconnect Spotify. "
    "Use spotify_save_current for 'favorite this song', 'like the current track', or 'save what is playing'; "
    "it saves the exact current track returned by Spotify and requires user-library-modify permission. "
    "'Start/play music' without a song "
    "means resume; 'next song' means skip. For 'what's playing', 'current song', or 'what am I "
    "listening to', call spotify_current_track (spotify_status is a compatibility alias) and use "
    "the returned title, artists, album, and playback state in the reply. Never guess the current track. "
    "When speaking through Discord, never mention Discord channel IDs, bridge metadata, or internal routing details."
)

SPOTIFY_INTENT_HINTS = (
    "spotify",
    "song",
    "track",
    "music",
    "play",
    "playback",
    "pause",
    "resume",
    "skip",
    "next",
    "previous",
    "queue",
    "volume",
    "shuffle",
    "repeat",
    "playing",
    "listening",
    "current song",
    "current track",
    "now playing",
    "listen to",
    "put on",
    "artist",
    "profile",
    "favorite",
    "favorites",
    "favourite",
    "favourites",
    "liked songs",
    "liked tracks",
    "saved songs",
    "saved tracks",
    "favorite this",
    "favourite this",
    "favorit this",
    "like the current",
    "save what is playing",
)


def register_spotify_tools(registry: ToolRegistry) -> None:
    for definition in SPOTIFY_TOOL_DEFINITIONS:
        function = definition["function"]
        name = str(function["name"])

        async def handler(arguments: dict[str, Any], *, _name: str = name) -> dict[str, Any]:
            if not spotify_controller.is_authenticated():
                raise ToolExecutionError(
                    "Spotify is not connected yet. Open Settings → Integrations → Spotify and connect your account."
                )
            try:
                action, normalized_arguments = spotify_controller.action_from_tool(_name, arguments)
                result = await spotify_controller.execute_action(action, normalized_arguments)
            except SpotifyError as exc:
                raise ToolExecutionError(f"Spotify couldn't complete that: {exc}") from exc
            return {
                "action": action,
                "arguments": normalized_arguments,
                "data": result,
                "confirmation": spotify_controller.format_action_response(action, normalized_arguments, result),
            }

        registry.register(
            ToolSpec(
                name=name,
                description=str(function["description"]),
                parameters=dict(function["parameters"]),
                handler=handler,
                category="spotify",
                guidance=SPOTIFY_GUIDANCE,
                intent_hints=SPOTIFY_INTENT_HINTS,
                available=lambda: bool(settings.integrations.spotify.enabled),
                max_calls_per_turn=1,
            )
        )
