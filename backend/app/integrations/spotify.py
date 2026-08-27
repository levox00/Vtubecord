"""Spotify Web API integration and natural-language playback commands.

The integration uses Spotify's Authorization Code flow because playback control
requires a user's account and an active Spotify Premium device. Tokens are kept
in the ignored ``data`` directory so the client secret and refresh token do not
need to be sent to the browser.
"""

from __future__ import annotations

import base64
import json
import logging
import random
import re
import secrets
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

AUTH_ENDPOINT = "https://accounts.spotify.com/authorize"
TOKEN_ENDPOINT = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
TOKEN_FILE = Path(__file__).resolve().parents[3] / "data" / "spotify_tokens.json"
TOKEN_TTL_SECONDS = 600
# Spotify Development Mode reduced GET /search from 50 to 10 results per
# request in 2026. Extended-mode apps also accept 10, so this is portable.
SPOTIFY_SEARCH_LIMIT = 10
AI_CAPABILITY_STATES = {"unknown", "tool_capable", "parser_fallback"}
SCOPES = " ".join(
    (
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "user-read-private",
        "user-read-email",
        # Required for the Liked Songs / saved tracks playback tool.
        "user-library-read",
        # Required to add the current track to the user's Liked Songs.
        "user-library-modify",
    )
)


def _empty_parameters() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def _tool(name: str, description: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters or _empty_parameters(),
        },
    }


SPOTIFY_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    _tool(
        "spotify_play",
        "Play a specific song on Spotify. Omit query to resume the current playback context. Use spotify_play_artist for an artist's songs or profile.",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Song and artist to search for, preferably in the form 'song title by artist'.",
                }
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "spotify_play_artist",
        "Start playback from an artist's Spotify profile/context. Use this for requests such as 'play songs from Bruno Mars' or 'play some music by Daft Punk', not for a named song.",
        {
            "type": "object",
            "properties": {
                "artist": {
                    "type": "string",
                    "description": "Artist name, Spotify artist URI, or open.spotify.com artist-profile URL.",
                }
            },
            "required": ["artist"],
            "additionalProperties": False,
        },
    ),
    _tool("spotify_pause", "Pause the active Spotify playback."),
    _tool("spotify_resume", "Resume the current Spotify playback context."),
    _tool("spotify_next", "Skip to the next Spotify track."),
    _tool("spotify_previous", "Go back to the previous Spotify track."),
    _tool(
        "spotify_set_volume",
        "Set Spotify volume from 0 to 100 percent.",
        {
            "type": "object",
            "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["volume"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "spotify_adjust_volume",
        "Raise or lower Spotify volume by a percentage-point delta.",
        {
            "type": "object",
            "properties": {"delta": {"type": "integer", "minimum": -100, "maximum": 100}},
            "required": ["delta"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "spotify_queue",
        "Search for a song and add it to the Spotify queue.",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Song or artist to queue."}},
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "spotify_set_shuffle",
        "Enable or disable Spotify shuffle.",
        {
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}},
            "required": ["enabled"],
            "additionalProperties": False,
        },
    ),
    _tool(
        "spotify_set_repeat",
        "Set Spotify repeat mode to context, track, or off.",
        {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["context", "track", "off"]}},
            "required": ["mode"],
            "additionalProperties": False,
        },
    ),
    _tool("spotify_toggle", "Toggle Spotify between playing and paused."),
    _tool(
        "spotify_play_favorites",
        "Play a shuffled set of tracks from the user's Spotify Liked Songs (saved tracks) library. "
        "Use this for requests such as 'play my favorite songs', 'play my liked songs', or 'play my saved tracks'. "
        "Never invent a track title; the tool result contains the actual selected tracks.",
        {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "How many saved tracks to start in the playback queue (default 10).",
                },
                "shuffle": {
                    "type": "boolean",
                    "description": "Shuffle the selected saved tracks before playback (default true).",
                },
            },
            "additionalProperties": False,
        },
    ),
    _tool(
        "spotify_save_current",
        "Save/like the exact Spotify track currently playing by adding it to the user's Liked Songs. "
        "Use this for requests such as 'favorite this song', 'like the current track', or 'save what is playing'.",
    ),
    _tool(
        "spotify_current_track",
        "Get the exact Spotify track currently playing (or paused), including its title, artists, album, and playback state.",
    ),
    # Keep the original status name for clients and models that already know
    # it. Both names intentionally read the same player endpoint.
    _tool("spotify_status", "Report the current Spotify player state and track."),
]

_CAPABILITY_STATE: dict[str, str] = {}


def capability_key(provider: str, base_url: str, model: str) -> str:
    return "|".join((str(provider or "").lower(), str(base_url or "").rstrip("/"), str(model or "")))


def get_capability_state(key: str) -> str:
    return _CAPABILITY_STATE.get(key, "unknown")


def set_capability_state(key: str, state: str) -> str:
    if state not in AI_CAPABILITY_STATES:
        raise ValueError(f"Unsupported Spotify AI capability state: {state}")
    _CAPABILITY_STATE[key] = state
    return state


class SpotifyError(RuntimeError):
    """A user-facing Spotify API error."""


def _normalize_track_text(value: str | None) -> str:
    """Normalize titles and artist names for tolerant matching.

    This deliberately stays dependency-free.  Spotify is the knowledge source
    for canonical names; the local matching layer only handles punctuation,
    accents, word order, and small spelling differences.
    """

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _track_text_similarity(left: str | None, right: str | None) -> float:
    """Return a 0..1 similarity score for a requested/canonical field."""

    query = _normalize_track_text(left)
    candidate = _normalize_track_text(right)
    if not query or not candidate:
        return 0.0
    if query == candidate:
        return 1.0
    if query in candidate or candidate in query:
        # This handles suffixes such as ``(Remastered)`` without allowing a
        # completely unrelated result to pass as an exact match.
        return 0.93

    sequence_score = SequenceMatcher(None, query, candidate).ratio()
    query_tokens = " ".join(sorted(query.split()))
    candidate_tokens = " ".join(sorted(candidate.split()))
    token_score = SequenceMatcher(None, query_tokens, candidate_tokens).ratio()
    return max(sequence_score, token_score)


def _split_track_and_artist(query: str) -> tuple[str, str | None]:
    """Extract ``title by artist``/``title from artist`` from a play query."""

    cleaned = re.sub(r"\s+", " ", str(query or "").strip())
    cleaned = re.sub(r"\s+on\s+spotify$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip(" \t\"'")
    cleaned = re.sub(
        r"^(?:something\s+called|the\s+(?:song|track)(?:\s+called)?)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(?:from|by)\s+(?:the\s+)?artist\s+",
        " by ",
        cleaned,
        flags=re.IGNORECASE,
    )
    match = re.match(
        r"^(?P<title>.+?)\s+(?:by|from|performed\s+by)\s+(?P<artist>.+?)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return cleaned, None
    title = match.group("title").strip(" \t\"'")
    artist = match.group("artist").strip(" \t\"'")
    return title, artist or None


_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _parse_percentage(value: str) -> int | None:
    """Parse a numeric or spoken 0–100 percentage."""

    cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
    cleaned = re.sub(r"(?:%|percent|percentage)\s*$", "", cleaned).strip()
    if not cleaned:
        return None
    if re.fullmatch(r"\d{1,3}", cleaned):
        number = int(cleaned)
        return number if 0 <= number <= 100 else None
    cleaned = cleaned.replace("-", " ")
    if cleaned in {"a hundred", "one hundred", "hundred"}:
        return 100
    parts = cleaned.split()
    if len(parts) == 1:
        number = _NUMBER_WORDS.get(parts[0])
        return number if number is not None and number <= 100 else None
    if len(parts) == 2 and parts[0] in _NUMBER_WORDS and parts[1] in _NUMBER_WORDS:
        first = _NUMBER_WORDS[parts[0]]
        second = _NUMBER_WORDS[parts[1]]
        if first >= 20 and second < 10:
            return first + second
    return None


def _canonical_track(track: dict[str, Any]) -> dict[str, Any]:
    """Keep only stable, user-facing fields from a Spotify search result."""

    album = track.get("album") or {}
    images = album.get("images") or []
    return {
        "id": track.get("id"),
        "uri": track.get("uri"),
        "name": track.get("name"),
        "artists": [
            artist.get("name")
            for artist in track.get("artists", [])
            if isinstance(artist, dict) and artist.get("name")
        ],
        "album": album.get("name"),
        "image_url": images[0].get("url") if images and isinstance(images[0], dict) else None,
        "duration_ms": track.get("duration_ms"),
    }


def _canonical_artist(artist: dict[str, Any]) -> dict[str, Any]:
    """Keep stable artist-profile fields returned by Spotify."""

    images = artist.get("images") or []
    external_urls = artist.get("external_urls") or {}
    return {
        "id": artist.get("id"),
        "uri": artist.get("uri"),
        "name": artist.get("name"),
        "image_url": images[0].get("url") if images and isinstance(images[0], dict) else None,
        "external_url": external_urls.get("spotify") if isinstance(external_urls, dict) else None,
        "type": "artist",
    }


def _spotify_artist_id(value: str | None) -> str | None:
    """Extract an artist ID from a Spotify URI or public artist-profile URL."""

    text = str(value or "").strip()
    uri_match = re.fullmatch(r"spotify:artist:([A-Za-z0-9]+)", text, flags=re.IGNORECASE)
    if uri_match:
        return uri_match.group(1)
    url_match = re.match(
        r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?artist/([A-Za-z0-9]+)(?:[/?#].*)?$",
        text,
        flags=re.IGNORECASE,
    )
    return url_match.group(1) if url_match else None


class SpotifyController:
    def __init__(self) -> None:
        self._pending_states: dict[str, tuple[str, float]] = {}
        self._ai_control_mode = "detecting"

    @property
    def ai_control_mode(self) -> str:
        return self._ai_control_mode

    def set_ai_control_mode(self, mode: str) -> None:
        if mode in {"detecting", "tool_calling", "parser_fallback"}:
            self._ai_control_mode = mode

    # ------------------------------------------------------------------
    # Token and OAuth helpers
    # ------------------------------------------------------------------
    def _load_tokens(self) -> dict[str, Any]:
        try:
            if TOKEN_FILE.exists():
                data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as exc:
            logger.warning("Unable to read Spotify token store: %s", exc)
        return {}

    def _save_tokens(self, tokens: dict[str, Any]) -> None:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = TOKEN_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        temporary.replace(TOKEN_FILE)

    def is_authenticated(self) -> bool:
        tokens = self._load_tokens()
        return bool(tokens.get("access_token") or tokens.get("refresh_token"))

    def clear_tokens(self) -> None:
        try:
            TOKEN_FILE.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Unable to clear Spotify token store: %s", exc)

    def create_auth_url(self, redirect_uri: str) -> str:
        client_id = settings.integrations.spotify.client_id.strip()
        if not client_id or not settings.integrations.spotify.client_secret.strip():
            raise SpotifyError("Spotify Client ID and Client Secret must be configured first.")

        state = secrets.token_urlsafe(32)
        self._pending_states[state] = (redirect_uri, time.time())
        # Prune abandoned OAuth attempts while keeping state validation bounded.
        cutoff = time.time() - TOKEN_TTL_SECONDS
        self._pending_states = {
            key: value for key, value in self._pending_states.items() if value[1] >= cutoff
        }
        # A reconnect is required when an older token predates the Liked Songs
        # scope. Force Spotify's consent screen in that case so the user does
        # not silently receive another token without library access.
        existing_scopes = set(str(self._load_tokens().get("scope") or "").split())
        query = urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": SCOPES,
                "state": state,
                "show_dialog": "true"
                if not {"user-library-read", "user-library-modify"}.issubset(existing_scopes)
                else "false",
            }
        )
        return f"{AUTH_ENDPOINT}?{query}"

    async def complete_auth(self, code: str, state: str) -> None:
        pending = self._pending_states.pop(state, None)
        if pending is None or time.time() - pending[1] > TOKEN_TTL_SECONDS:
            raise SpotifyError("Spotify authorization expired. Please start the connection again.")

        redirect_uri = pending[0]
        client_id = settings.integrations.spotify.client_id.strip()
        client_secret = settings.integrations.spotify.client_secret.strip()
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Authorization": f"Basic {credentials}"},
            )
        if response.status_code >= 400:
            detail = response.json().get("error_description", response.text[:200])
            raise SpotifyError(f"Spotify authorization failed: {detail}")

        payload = response.json()
        self._save_tokens(
            {
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token"),
                "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)),
                "scope": payload.get("scope", SCOPES),
            }
        )

    async def _refresh_access_token(self, tokens: dict[str, Any]) -> str:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise SpotifyError("Spotify is not connected. Connect your Spotify account first.")

        client_id = settings.integrations.spotify.client_id.strip()
        client_secret = settings.integrations.spotify.client_secret.strip()
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TOKEN_ENDPOINT,
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                headers={"Authorization": f"Basic {credentials}"},
            )
        if response.status_code >= 400:
            self.clear_tokens()
            raise SpotifyError("Spotify authorization expired. Connect your account again.")

        payload = response.json()
        tokens.update(
            {
                "access_token": payload["access_token"],
                "expires_at": int(time.time()) + int(payload.get("expires_in", 3600)),
            }
        )
        if payload.get("refresh_token"):
            tokens["refresh_token"] = payload["refresh_token"]
        self._save_tokens(tokens)
        return str(tokens["access_token"])

    async def _access_token(self) -> str:
        tokens = self._load_tokens()
        access_token = tokens.get("access_token")
        if access_token and float(tokens.get("expires_at", 0)) > time.time() + 60:
            return str(access_token)
        return await self._refresh_access_token(tokens)

    async def _request(self, method: str, path: str, *, retry: bool = True, **kwargs: Any) -> Any:
        token = await self._access_token()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(method, f"{API_BASE}{path}", headers=headers, **kwargs)

        if response.status_code == 401 and retry:
            tokens = self._load_tokens()
            tokens["expires_at"] = 0
            await self._refresh_access_token(tokens)
            return await self._request(method, path, retry=False, **kwargs)

        if response.status_code >= 400:
            try:
                payload = response.json()
                error = payload.get("error", {})
                detail = error.get("message") or error.get("reason") or response.text
            except ValueError:
                detail = response.text
            detail = (detail or "Unknown Spotify error").strip()
            if response.status_code == 403:
                detail = f"Spotify denied playback control ({detail}). An active Spotify Premium device is required."
            elif response.status_code == 404:
                detail = "Spotify could not find an active playback device. Start Spotify on a device first."
            raise SpotifyError(detail[:300])

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Player operations
    # ------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        if not self.is_authenticated():
            return {"connected": False, "is_playing": False, "item": None, "device": None}
        try:
            payload = await self._request("GET", "/me/player")
        except SpotifyError as exc:
            return {
                "connected": True,
                "is_playing": False,
                "item": None,
                "device": None,
                "error": str(exc),
            }
        if not payload:
            return {"connected": True, "is_playing": False, "item": None, "device": None}
        return {"connected": True, **self._format_player(payload)}

    @staticmethod
    def _format_player(payload: dict[str, Any]) -> dict[str, Any]:
        item = payload.get("item") or {}
        album = item.get("album") or {}
        images = album.get("images") or []
        return {
            "is_playing": bool(payload.get("is_playing")),
            "progress_ms": payload.get("progress_ms", 0),
            "volume_percent": (payload.get("device") or {}).get("volume_percent"),
            "device": {
                "id": (payload.get("device") or {}).get("id"),
                "name": (payload.get("device") or {}).get("name"),
                "type": (payload.get("device") or {}).get("type"),
                "is_active": (payload.get("device") or {}).get("is_active", False),
            },
            "item": {
                "id": item.get("id"),
                "uri": item.get("uri"),
                "name": item.get("name"),
                "artists": [artist.get("name") for artist in item.get("artists", []) if artist.get("name")],
                "album": album.get("name"),
                "image_url": images[0].get("url") if images else None,
                "duration_ms": item.get("duration_ms"),
            },
        }

    async def control(
        self,
        action: str,
        *,
        query: str | None = None,
        volume: int | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        params = {"device_id": device_id} if device_id else None
        matched_track: dict[str, Any] | None = None
        matched_artist: dict[str, Any] | None = None
        if action == "pause":
            await self._request("PUT", "/me/player/pause", params=params)
        elif action in {"play", "resume"}:
            body: dict[str, Any] | None = None
            if query:
                # Artist-profile links are unambiguous even when the generic
                # player UI submits them through the ordinary play action.
                if _spotify_artist_id(query):
                    matched_artist = await self.resolve_artist(query)
                    body = {"context_uri": matched_artist["uri"]}
                else:
                    matched_track = await self.resolve_track(query)
                    body = {"uris": [matched_track["uri"]]}
            await self._request("PUT", "/me/player/play", params=params, json=body)
        elif action == "play_artist":
            if not query:
                raise SpotifyError("Tell me which artist profile to play.")
            matched_artist = await self.resolve_artist(query)
            await self._request(
                "PUT",
                "/me/player/play",
                params=params,
                json={"context_uri": matched_artist["uri"]},
            )
        elif action == "next":
            await self._request("POST", "/me/player/next", params=params)
        elif action == "previous":
            await self._request("POST", "/me/player/previous", params=params)
        elif action == "volume":
            if volume is None or not 0 <= volume <= 100:
                raise SpotifyError("Spotify volume must be between 0 and 100 percent.")
            params = {"volume_percent": volume, **(params or {})}
            await self._request("PUT", "/me/player/volume", params=params)
        elif action == "shuffle":
            params = {"state": str(bool(volume)), **(params or {})}
            await self._request("PUT", "/me/player/shuffle", params=params)
        elif action == "repeat":
            params = {"state": query or "context", **(params or {})}
            await self._request("PUT", "/me/player/repeat", params=params)
        elif action == "queue":
            if not query:
                raise SpotifyError("Tell me which song to add to the Spotify queue.")
            matched_track = await self.resolve_track(query)
            await self._request("POST", "/me/player/queue", params={"uri": matched_track["uri"]})
        elif action == "toggle":
            current = await self.status()
            await self.control("pause" if current.get("is_playing") else "resume", device_id=device_id)
        else:
            raise SpotifyError(f"Unsupported Spotify action: {action}")
        result = await self.status()
        if matched_track:
            # ``/me/player`` can briefly lag behind ``/me/player/play``. Keep
            # the exact track selected by the resolver available for the
            # confirmation and UI instead of reporting the previous track.
            result = {**result, "matched_track": matched_track}
        if matched_artist:
            # Player state can lag behind a new context in the same way it can
            # lag behind a selected track. Preserve the verified profile for
            # an accurate confirmation and UI response.
            result = {**result, "matched_artist": matched_artist}
        return result

    async def play_favorites(self, *, count: int = 10, shuffle: bool = True) -> dict[str, Any]:
        """Start playback using tracks from the user's Spotify Liked Songs library.

        Spotify does not expose a separate ``favorites`` player context. The
        saved-track collection is read first and the selected URIs are sent to
        the normal ``/me/player/play`` endpoint. The selected tracks remain in
        the result so follow-up text can only describe tracks Spotify returned.
        """

        if isinstance(count, bool) or not isinstance(count, int):
            raise SpotifyError("The number of favorite songs must be a whole number.")
        if not 1 <= count <= 50:
            raise SpotifyError("Choose between 1 and 50 favorite songs.")
        if not isinstance(shuffle, bool):
            raise SpotifyError("Shuffle must be enabled or disabled.")

        tokens = self._load_tokens()
        granted_scopes = set(str(tokens.get("scope") or "").split())
        if "user-library-read" not in granted_scopes:
            raise SpotifyError(
                "Spotify needs the user-library-read permission to access your Liked Songs. "
                "Disconnect and reconnect Spotify in Settings → Integrations → Spotify, then try again."
            )

        try:
            payload = await self._request("GET", "/me/tracks", params={"limit": 50, "offset": 0})
        except SpotifyError as exc:
            detail = str(exc)
            if "scope" in detail.lower() or "forbidden" in detail.lower():
                raise SpotifyError(
                    "Spotify did not grant access to your Liked Songs. "
                    "Disconnect and reconnect Spotify to approve the user-library-read permission."
                ) from exc
            raise

        items = payload.get("items") if isinstance(payload, dict) else None
        tracks = [
            _canonical_track(item.get("track") or {})
            for item in (items or [])
            if isinstance(item, dict) and isinstance(item.get("track"), dict) and item["track"].get("uri")
        ]
        if not tracks:
            raise SpotifyError("Your Spotify Liked Songs library is empty.")

        selected = list(tracks)
        if shuffle:
            random.SystemRandom().shuffle(selected)
        selected = selected[: min(count, len(selected))]
        uris = [str(track["uri"]) for track in selected if track.get("uri")]
        if not uris:
            raise SpotifyError("Spotify returned no playable tracks from your Liked Songs.")
        await self._request("PUT", "/me/player/play", json={"uris": uris})
        result = await self.status()
        return {
            **result,
            "favorite_count": len(tracks),
            "selected_count": len(selected),
            "favorite_tracks": selected,
            "shuffle": shuffle,
        }

    async def save_current_track(self) -> dict[str, Any]:
        """Add the exact current Spotify track to the user's Liked Songs."""

        tokens = self._load_tokens()
        granted_scopes = set(str(tokens.get("scope") or "").split())
        if "user-library-modify" not in granted_scopes:
            raise SpotifyError(
                "Spotify needs the user-library-modify permission to favorite the current song. "
                "Disconnect and reconnect Spotify in Settings → Integrations → Spotify, then try again."
            )

        current = await self.status()
        if current.get("error"):
            raise SpotifyError(str(current["error"]))
        item = current.get("item") if isinstance(current.get("item"), dict) else {}
        track_id = str(item.get("id") or "").strip()
        if not track_id:
            raise SpotifyError("There is no current Spotify track to favorite.")

        await self._request("PUT", "/me/tracks", params={"ids": track_id})
        return {**current, "saved_track": dict(item)}

    async def resolve_track(self, query: str) -> dict[str, Any]:
        """Resolve a natural-language track query to a verified Spotify track.

        The resolver is intentionally tiny and local: it extracts an optional
        artist from ``title by artist``, asks Spotify for a small candidate set,
        and uses tolerant matching to correct punctuation, accents, and minor
        spelling errors.  It never plays the first arbitrary search result.
        """

        raw_query = re.sub(r"\s+", " ", str(query or "").strip())
        title, artist = _split_track_and_artist(raw_query)
        if not title:
            raise SpotifyError("Tell me which song or artist to play.")

        search_queries: list[str] = []
        if artist:
            # Spotify's fielded query gives an exact artist hint while the
            # title-only fallback still allows us to recover from a typo in
            # the artist name and match it locally against returned artists.
            search_queries.append(f"track:{title} artist:{artist}")
            search_queries.append(f"track:{title}")
        else:
            search_queries.append(raw_query)
            search_queries.append(f"track:{title}")
            # A quoted fielded search gives Spotify a better chance of
            # returning an exact multi-word title instead of an unrelated
            # artist whose name happens to resemble part of the transcript.
            quoted_title = title.replace('"', "").strip()
            if quoted_title:
                search_queries.append(f'track:"{quoted_title}"')

        candidates: list[dict[str, Any]] = []
        seen_uris: set[str] = set()
        for search_query in search_queries:
            search_params = {
                "q": search_query,
                "type": "track",
                "limit": SPOTIFY_SEARCH_LIMIT,
            }
            try:
                search = await self._request("GET", "/search", params=search_params)
            except SpotifyError as exc:
                # Defensive compatibility for a future per-app limit change:
                # Spotify's server default remains valid even if a numeric
                # limit is reduced again.
                if "invalid limit" not in str(exc).lower():
                    raise
                logger.warning(
                    "Spotify rejected search limit %s; retrying with its server default",
                    SPOTIFY_SEARCH_LIMIT,
                )
                search = await self._request(
                    "GET",
                    "/search",
                    params={"q": search_query, "type": "track"},
                )
            tracks = ((search or {}).get("tracks") or {}).get("items") or []
            for track in tracks:
                if not isinstance(track, dict) or not track.get("uri"):
                    continue
                uri = str(track["uri"])
                if uri in seen_uris:
                    continue
                seen_uris.add(uri)
                candidates.append(track)

        best: tuple[float, float, float, dict[str, Any]] | None = None
        for track in candidates:
            canonical = _canonical_track(track)
            title_score = _track_text_similarity(title, canonical.get("name"))
            artist_scores = [
                _track_text_similarity(artist or title, value)
                for value in canonical.get("artists", [])
            ]
            artist_score = max(artist_scores, default=0.0)

            if artist:
                # Title is the stronger signal, but a known artist is still
                # required to avoid playing another artist's identically
                # named track.
                score = title_score * 0.68 + artist_score * 0.32
                qualifies = title_score >= 0.68 and artist_score >= 0.45 and score >= 0.70
            else:
                # For ``play Daft Punk`` Spotify may return tracks whose title
                # is unrelated to the artist name, so accept either a strong
                # title or artist match. A weak 0.60 similarity is not enough
                # to safely turn a noisy voice transcript into playback.
                score = max(title_score, artist_score)
                qualifies = title_score >= 0.72 or artist_score >= 0.85

            # When no artist was requested, an exact title must keep Spotify's
            # own result order. Using artist-name similarity as a tie breaker
            # made an obscure artist named similarly to the title outrank the
            # first canonical exact-title result (for example Sailor Song by
            # Gigi Perez). Artist similarity remains useful only when the title
            # itself is not already a strong match.
            ranking_artist_score = (
                artist_score if artist or title_score < 0.60 else 0.0
            )
            if qualifies and (
                best is None
                or (score, title_score, ranking_artist_score) > best[:3]
            ):
                best = (score, title_score, ranking_artist_score, canonical)

        if best is None:
            requested = f"{title} by {artist}" if artist else raw_query
            raise SpotifyError(f"I couldn't find a close Spotify match for “{requested}”.")

        resolved = dict(best[3])
        resolved["match_score"] = round(best[0], 3)
        resolved["requested_title"] = title
        if artist:
            resolved["requested_artist"] = artist
        logger.info(
            "Spotify query resolved %r to %r by %s (score %.3f)",
            raw_query,
            resolved.get("name"),
            ", ".join(resolved.get("artists") or []),
            best[0],
        )
        return resolved

    async def resolve_artist(self, query: str) -> dict[str, Any]:
        """Resolve an artist name/profile and return its playable context URI."""

        raw_query = re.sub(r"\s+", " ", str(query or "").strip())
        if not raw_query:
            raise SpotifyError("Tell me which artist profile to play.")

        artist_id = _spotify_artist_id(raw_query)
        if artist_id:
            payload = await self._request("GET", f"/artists/{artist_id}")
            resolved = _canonical_artist(payload or {})
            if not resolved.get("uri"):
                raise SpotifyError("Spotify could not read that artist profile.")
            resolved["match_score"] = 1.0
            return resolved

        search_queries = [f"artist:{raw_query}", raw_query]
        candidates: list[dict[str, Any]] = []
        seen_uris: set[str] = set()
        for search_query in search_queries:
            params = {
                "q": search_query,
                "type": "artist",
                "limit": SPOTIFY_SEARCH_LIMIT,
            }
            try:
                search = await self._request("GET", "/search", params=params)
            except SpotifyError as exc:
                if "invalid limit" not in str(exc).lower():
                    raise
                logger.warning(
                    "Spotify rejected artist search limit %s; retrying with its server default",
                    SPOTIFY_SEARCH_LIMIT,
                )
                search = await self._request(
                    "GET",
                    "/search",
                    params={"q": search_query, "type": "artist"},
                )
            artists = ((search or {}).get("artists") or {}).get("items") or []
            for artist in artists:
                if not isinstance(artist, dict) or not artist.get("uri"):
                    continue
                uri = str(artist["uri"])
                if uri in seen_uris:
                    continue
                seen_uris.add(uri)
                candidates.append(artist)

        best: tuple[float, int, dict[str, Any]] | None = None
        for index, artist in enumerate(candidates):
            canonical = _canonical_artist(artist)
            score = _track_text_similarity(raw_query, canonical.get("name"))
            # Preserve Spotify's search ordering when scores tie.
            if score >= 0.62 and (best is None or (score, -index) > best[:2]):
                best = (score, -index, canonical)

        if best is None:
            raise SpotifyError(f"I couldn't find a close Spotify artist match for “{raw_query}”.")

        resolved = dict(best[2])
        resolved["match_score"] = round(best[0], 3)
        resolved["requested_artist"] = raw_query
        logger.info(
            "Spotify artist query resolved %r to profile %r (score %.3f)",
            raw_query,
            resolved.get("name"),
            best[0],
        )
        return resolved

    # ------------------------------------------------------------------
    # Chat command bridge
    # ------------------------------------------------------------------
    @staticmethod
    def parse_command(text: str) -> tuple[str, dict[str, Any]] | None:
        raw_value = re.sub(r"\s+", " ", text.strip())
        # Spotify IDs are case-sensitive. Capture profile URIs/URLs before the
        # ordinary case-insensitive natural-language parser lowercases text.
        raw_artist_profile_match = re.fullmatch(
            r"(?:play|playback)\s+((?:spotify:artist:|https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?artist/).+?)[.!]?$",
            raw_value,
            flags=re.IGNORECASE,
        )
        if raw_artist_profile_match:
            return "play_artist", {"query": raw_artist_profile_match.group(1).strip()}

        value = raw_value.lower()
        value = re.sub(r"[.!?]+$", "", value).strip()
        # Natural requests often contain a short politeness wrapper. Keep the
        # parser conservative by removing only wrappers at the edges.
        value = re.sub(
            r"^(?:hi|hey|hello)\s+(?:[a-z0-9_-]+\s+){0,2}[a-z0-9_-]+[, ]+(?=(?:please\s+)?(?:can|could|would)\s+you\s+)",
            "",
            value,
        )
        value = re.sub(r"^(?:hey\s+)?(?:please\s+|can you\s+|could you\s+|would you\s+)", "", value)
        value = re.sub(r"\s+(?:for me\s+)?please$", "", value).strip()
        value = re.sub(r"\s+for me$", "", value).strip()
        value = re.sub(r"^spotify\s+", "", value).strip()

        # Saving the current track is distinct from playing the user's
        # existing favorites. Recognize direct like/favorite wording before
        # the generic ``play <query>`` parser so it cannot become a search.
        favorite_verb = r"(?:favorite|favourite|favorit|save|like)"
        current_track = r"(?:this|the\s+current(?:ly)?(?:\s+playing)?|current(?:ly)?(?:\s+playing)?)"
        if re.fullmatch(
            rf"{favorite_verb}\s+{current_track}\s+(?:song|track|music)",
            value,
        ) or re.fullmatch(
            rf"{favorite_verb}\s+(?:the\s+)?(?:currently\s+)?playing\s+(?:song|track|music)",
            value,
        ) or re.fullmatch(
            rf"(?:add|save)\s+{current_track}\s+(?:song|track)\s+to\s+(?:my\s+)?(?:favorites?|favourites?|liked\s+(?:songs?|tracks?)|saved\s+(?:songs?|tracks?))",
            value,
        ) or re.fullmatch(
            r"(?:favorite|favourite|favorit|save|like)\s+what(?:'s|s|\s+is)\s+(?:currently\s+)?playing",
            value,
        ):
            return "save_current", {}

        # Liked Songs are a library, not a searchable track title. Recognize
        # these phrases before the generic ``play <query>`` parser so a model
        # or voice transcript cannot turn them into an invented song search.
        favorite_pattern = (
            r"(?:play|put on|listen to|start)\s+"
            r"(?:(?:my|the)\s+)?"
            r"(?:favorites?|favourites?|"
            r"favorite\s+(?:songs?|tracks?|music)|favourite\s+(?:songs?|tracks?|music)|"
            r"liked\s+(?:songs?|tracks?)|saved\s+(?:songs?|tracks?))"
            r"(?:\s+(?:in order|without shuffle))?"
            r"(?:\s+on spotify)?"
        )
        if re.fullmatch(favorite_pattern, value):
            return "play_favorites", {"count": 10, "shuffle": not bool(re.search(r"in order|without shuffle", value))}
        if re.fullmatch(r"(?:shuffle)\s+(?:(?:my|the)\s+)?(?:favorites?|favourites?|liked\s+(?:songs?|tracks?)|saved\s+(?:songs?|tracks?))", value):
            return "play_favorites", {"count": 10, "shuffle": True}

        # Voice transcription and excited chat often stretch or repeat the
        # command verb (for example ``pllayyyy``). Collapse repeated letters
        # in the first word only, and only use the result when it is a known
        # Spotify command. Song and artist names are left untouched.
        words = value.split(" ", 1)
        if words:
            collapsed_command = re.sub(r"(.)\1+", r"\1", words[0])
            command_words = {
                "play", "playback", "pause", "stop", "resume", "unpause",
                "continue", "start", "begin", "next", "skip", "previous",
                "prev", "back", "rewind", "queue", "add", "toggle",
            }
            if collapsed_command in command_words:
                value = " ".join((collapsed_command, words[1])) if len(words) > 1 else collapsed_command

        # Make common spoken song requests equivalent to ``play title by
        # artist`` so the resolver can verify the exact track instead of
        # leaving the request to ordinary conversation.
        value = re.sub(
            r"^(?:play|playback)\s+(?:something\s+called|the\s+(?:song|track)(?:\s+called)?)\s+",
            "play ",
            value,
        )
        value = re.sub(r"\s+(?:from|by)\s+(?:the\s+)?artist\s+", " by ", value)

        if re.fullmatch(r"(?:pause|stop)(?:\s+(?:spotify|the music|music|the song|the track|playback))?", value):
            return "pause", {}
        if re.fullmatch(
            r"(?:resume|unpause|continue|start|begin)(?:\s+(?:spotify|the music|music|the song|the track|playback|playing))?",
            value,
        ):
            return "resume", {}

        # “play music” means resume the current context, while “play <query>”
        # remains a search request. Navigation phrases are checked first so
        # “play the next song” cannot become a search for “the next song”.
        if re.fullmatch(r"(?:play|playback)\s+(?:the\s+)?(?:next|following)\s+(?:song|track)", value):
            return "next", {}
        if re.fullmatch(r"(?:skip|skip to)\s+(?:the\s+)?(?:next|following)\s+(?:song|track)", value):
            return "next", {}
        if re.fullmatch(r"(?:next|skip)(?:\s+(?:to\s+)?)?(?:the\s+)?(?:song|track)?", value):
            return "next", {}

        if re.fullmatch(r"(?:play|playback)\s+(?:the\s+)?(?:previous|prior)\s+(?:song|track)", value):
            return "previous", {}
        if re.fullmatch(r"(?:previous|prev)(?:\s+(?:the\s+)?(?:song|track))?", value):
            return "previous", {}
        if re.fullmatch(r"(?:back|go back)\s+(?:one|a|the|1)?\s*(?:song|track)", value):
            return "previous", {}
        if re.fullmatch(r"(?:one|1)\s+(?:song|track)\s+back", value):
            return "previous", {}
        if re.fullmatch(r"(?:rewind)(?:\s+(?:one|a|the|1)?\s*(?:song|track))?", value):
            return "previous", {}

        if re.fullmatch(r"(?:toggle|toggle playback)", value):
            return "toggle", {}
        # Status requests are deliberately read-only. Keep these broad enough
        # for speech transcripts while requiring a clear playback phrase so
        # ordinary questions do not trigger Spotify.
        if re.fullmatch(
            r"(?:"
            r"what(?:'s| is)\s+(?:the\s+)?(?:current\s+)?(?:song|track|music)?\s*"
            r"(?:currently\s+)?playing(?:\s+right\s+now)?|"
            r"what(?:'s| is)\s+(?:currently\s+)?playing(?:\s+right\s+now)?|"
            r"what(?:'s| is)\s+(?:the\s+)?current\s+(?:song|track)|"
            r"(?:now\s+playing|(?:the\s+)?current\s+(?:song|track)(?:\s+playing)?|currently\s+playing)|"
            r"(?:what|which)\s+(?:song|track)\s+is\s+(?:currently\s+)?playing|"
            r"(?:what\s+are\s+we|what\s+am\s+i)\s+listening\s+to|"
            r"(?:tell\s+me|show\s+me)\s+(?:what\s+is\s+)?(?:currently\s+)?playing"
            r")(?:\s+(?:on|in)\s+spotify)?",
            value,
        ):
            return "status", {}

        volume_match = re.fullmatch(
            r"(?:set|change|turn)?\s*(?:the\s+)?volume(?:\s+(?:to|at))?\s+(.+?)\s*(?:%|percent|percentage)?",
            value,
        )
        if volume_match:
            volume = _parse_percentage(volume_match.group(1))
            if volume is not None:
                return "volume", {"volume": volume}
        relative_volume_match = re.fullmatch(
            r"(?:turn\s+)?(?:the\s+)?volume\s+(up|down|higher|lower)",
            value,
        )
        if relative_volume_match:
            direction = relative_volume_match.group(1)
            return "volume_relative", {"delta": 10 if direction in {"up", "higher"} else -10}

        queue_match = re.fullmatch(r"(?:queue|add)\s+(.+?)(?:\s+to\s+(?:the\s+)?queue)?", value)
        if queue_match:
            query = queue_match.group(1).strip()
            query = re.sub(
                r"^(?:(?:the|a)\s+)?(?:song|track)(?:\s+called)?\s+",
                "",
                query,
                flags=re.IGNORECASE,
            ).strip()
            return "queue", {"query": query}

        # Artist collections must start the artist's Spotify context rather
        # than search for a track whose title happens to resemble the phrase.
        # This is intentionally checked before the generic play matcher.
        artist_play_patterns = (
            r"(?:play|playback|put on|listen to)\s+(?:(?:some|the)\s+)?(?:songs?|tracks?|music)\s+(?:from|by)\s+(.+)",
            r"(?:play|playback|put on|listen to)\s+(?:the\s+)?(?:spotify\s+)?artist(?:\s+profile)?\s+(?:for|of|from|by)?\s*(.+)",
            r"(?:play|playback|put on|listen to)\s+(.+?)\s+from\s+(?:their|his|her|the)\s+(?:spotify\s+)?(?:artist\s+)?profile",
        )
        for pattern in artist_play_patterns:
            artist_match = re.fullmatch(pattern, value)
            if artist_match:
                artist = artist_match.group(1).strip()
                if artist:
                    return "play_artist", {"query": artist}

        artist_profile_match = re.fullmatch(
            r"(?:play|playback)\s+((?:spotify:artist:|https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?artist/).+)",
            value,
        )
        if artist_profile_match:
            return "play_artist", {"query": artist_profile_match.group(1).strip()}

        if re.fullmatch(r"(?:play|playback)(?:\s+(?:spotify|the music|music|the song|a song|playback))?", value):
            return "resume", {}
        play_match = re.fullmatch(r"(?:play|playback)\s+(.+?)(?:\s+on\s+spotify)?", value)
        if play_match:
            query = play_match.group(1).strip()
            if query not in {"music", "a song", "the music", "spotify", "playback"}:
                return "play", {"query": query}
        return None

    @staticmethod
    def parse_contextual_command(text: str, recent_context: list[str] | None = None) -> tuple[str, dict[str, Any]] | None:
        """Resolve short follow-ups when the preceding turn establishes Spotify context.

        Phrases such as ``make it fifty`` are intentionally not Spotify
        commands on their own. They become a volume request only when the
        recent conversation clearly discusses volume, preventing an unrelated
        number in ordinary chat from changing playback.
        """

        if not recent_context:
            return None
        value = re.sub(r"\s+", " ", str(text or "").strip().lower())
        value = re.sub(r"[.!?]+$", "", value).strip()
        follow_up = re.fullmatch(
            r"(?:make|set|change|turn)\s+it(?:\s+(?:to|at))?\s+(.+?)\s*(?:%|percent|percentage)?",
            value,
        )
        if not follow_up:
            return None
        context = " ".join(str(item or "") for item in recent_context[-6:]).lower()
        if not re.search(r"\b(?:volume|louder|quieter|loudness|percent|percentage)\b", context):
            return None
        volume = _parse_percentage(follow_up.group(1))
        return ("volume", {"volume": volume}) if volume is not None else None

    @staticmethod
    def tool_from_action(action: str, arguments: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        """Map a recognized request to the function the LLM must call."""

        args = dict(arguments or {})
        if action == "play_favorites":
            count = args.get("count", 10)
            if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) != count:
                raise SpotifyError("The number of favorite songs must be a whole number.")
            count_int = int(count)
            if not 1 <= count_int <= 50:
                raise SpotifyError("Choose between 1 and 50 favorite songs.")
            shuffle = args.get("shuffle", True)
            if not isinstance(shuffle, bool):
                raise SpotifyError("Shuffle must be enabled or disabled.")
            return "spotify_play_favorites", {
                "count": count_int,
                "shuffle": shuffle,
            }
        mapping = {
            "play": "spotify_play",
            "play_artist": "spotify_play_artist",
            "pause": "spotify_pause",
            "resume": "spotify_resume",
            "next": "spotify_next",
            "previous": "spotify_previous",
            "volume": "spotify_set_volume",
            "volume_relative": "spotify_adjust_volume",
            "queue": "spotify_queue",
            "shuffle": "spotify_set_shuffle",
            "repeat": "spotify_set_repeat",
            "toggle": "spotify_toggle",
            "status": "spotify_current_track",
            "play_favorites": "spotify_play_favorites",
            "save_current": "spotify_save_current",
        }
        name = mapping.get(action)
        if name is None:
            raise SpotifyError(f"Unknown Spotify action: {action}")
        return name, args

    @classmethod
    def arguments_for_tool_request(cls, name: str, text: str) -> dict[str, Any] | None:
        """Ground routed Spotify arguments in the user's original wording.

        The semantic model owns the choice of tool. This method only prevents
        small models from silently replacing a title, artist, percentage, or
        mode while serializing that chosen tool's arguments.
        """

        parsed_arguments_for_fallback: dict[str, Any] | None = None
        parsed = cls.parse_command(text)
        if parsed is not None:
            parsed_name, parsed_arguments = cls.tool_from_action(*parsed)
            if parsed_name == name:
                if name not in {"spotify_play", "spotify_play_artist", "spotify_queue"}:
                    return parsed_arguments
                parsed_arguments_for_fallback = parsed_arguments
            else:
                return None

        value = re.sub(r"\s+", " ", str(text or "").strip())
        value = re.sub(r"[.!?]+$", "", value).strip()
        if name in {
            "spotify_pause",
            "spotify_resume",
            "spotify_next",
            "spotify_previous",
            "spotify_toggle",
            "spotify_current_track",
            "spotify_status",
            "spotify_save_current",
        }:
            return {}

        if name == "spotify_play_artist":
            artist_patterns = (
                r"\b(?:play|playback|put\s+on|listen\s+to)\b\s+(?:(?:some|the)\s+)?(?:songs?|tracks?|music)\s+(?:from|by)\s+(.+)",
                r"\b(?:play|playback|put\s+on|listen\s+to)\b\s+(?:the\s+)?(?:spotify\s+)?artist(?:\s+profile)?\s+(?:for|of|from|by)?\s*(.+)",
                r"\b(?:play|playback|put\s+on|listen\s+to)\b\s+(.+?)\s+from\s+(?:their|his|her|the)\s+(?:spotify\s+)?(?:artist\s+)?profile",
                r"\b(?:play|playback)\b\s+((?:spotify:artist:|https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?artist/).+)",
            )
            artist = ""
            for pattern in artist_patterns:
                match = re.search(pattern, value, flags=re.IGNORECASE)
                if match:
                    artist = match.group(1).strip()
                    break
            if not artist and parsed_arguments_for_fallback:
                artist = str(parsed_arguments_for_fallback.get("query") or "").strip()
            artist = re.sub(
                r"\s+(?:on\s+spotify|for\s+me|please)\s*$",
                "",
                artist,
                flags=re.IGNORECASE,
            ).strip()
            return {"artist": artist} if artist else None

        if name in {"spotify_play", "spotify_queue"}:
            anchors = (
                r"\b(?:play|playback|put\s+on|listen\s+to)\b\s+(.+)"
                if name == "spotify_play"
                else r"\b(?:queue|add)\b\s+(.+)"
            )
            match = re.search(anchors, value, flags=re.IGNORECASE)
            if not match:
                return parsed_arguments_for_fallback
            query = match.group(1).strip()
            query = re.sub(r"^(?:me\s+)?", "", query, flags=re.IGNORECASE)
            query = re.sub(
                r"^(?:(?:the|a)\s+(?:song|track)(?:\s+called)?|something\s+called)\s+",
                "",
                query,
                flags=re.IGNORECASE,
            )
            while True:
                cleaned = re.sub(
                    r"\s+(?:on\s+spotify|to\s+(?:the\s+)?(?:spotify\s+)?queue|for\s+me|please)\s*$",
                    "",
                    query,
                    flags=re.IGNORECASE,
                ).strip()
                if cleaned == query:
                    break
                query = cleaned
            if not query:
                return {} if name == "spotify_play" else None
            if name == "spotify_play" and query.lower() in {
                "music",
                "a song",
                "the music",
                "spotify",
                "playback",
            }:
                return {}
            return {"query": query}

        if name == "spotify_set_volume":
            match = re.search(
                r"(?:volume|make\s+it|set\s+it|change\s+it|turn\s+it).*?"
                r"(?P<value>\d{1,3}|(?:a|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[ -](?:one|two|three|four|five|six|seven|eight|nine))?|hundred)"
                r"\s*(?:%|percent|percentage)?\b",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                volume = _parse_percentage(match.group("value"))
                if volume is not None:
                    return {"volume": volume}
            return None
        if name == "spotify_adjust_volume":
            if re.search(r"\b(?:up|higher|louder|increase)\b", value, flags=re.IGNORECASE):
                return {"delta": 10}
            if re.search(r"\b(?:down|lower|quieter|decrease)\b", value, flags=re.IGNORECASE):
                return {"delta": -10}
            return None
        if name == "spotify_set_shuffle":
            if re.search(r"\b(?:off|disable|disabled|stop)\b", value, flags=re.IGNORECASE):
                return {"enabled": False}
            if re.search(r"\b(?:on|enable|enabled|start)\b", value, flags=re.IGNORECASE):
                return {"enabled": True}
            return None
        if name == "spotify_set_repeat":
            if re.search(r"\b(?:off|disable|disabled|stop)\b", value, flags=re.IGNORECASE):
                return {"mode": "off"}
            if re.search(r"\b(?:this|current|one)\s+(?:song|track)\b|\btrack\b", value, flags=re.IGNORECASE):
                return {"mode": "track"}
            if re.search(r"\b(?:playlist|album|context|all)\b", value, flags=re.IGNORECASE):
                return {"mode": "context"}
        return None

    @staticmethod
    def action_from_tool(name: str, arguments: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        """Map a validated function name to the existing controller actions."""

        args = arguments or {}
        mapping = {
            "spotify_pause": ("pause", {}),
            "spotify_resume": ("resume", {}),
            "spotify_next": ("next", {}),
            "spotify_previous": ("previous", {}),
            "spotify_toggle": ("toggle", {}),
            "spotify_current_track": ("status", {}),
            "spotify_status": ("status", {}),
            "spotify_save_current": ("save_current", {}),
        }
        if name in mapping:
            return mapping[name]
        if name == "spotify_play":
            query = args.get("query")
            if query is not None and not isinstance(query, str):
                raise SpotifyError("Spotify play query must be text.")
            query_text = str(query or "").strip()
            return ("play", {"query": query_text}) if query_text else ("resume", {})
        if name == "spotify_play_artist":
            artist = args.get("artist")
            if not isinstance(artist, str) or not artist.strip():
                raise SpotifyError("Tell me which artist profile to play.")
            return "play_artist", {"query": artist.strip()}
        if name == "spotify_play_favorites":
            count = args.get("count", 10)
            if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) != count:
                raise SpotifyError("The number of favorite songs must be a whole number.")
            count_int = int(count)
            if not 1 <= count_int <= 50:
                raise SpotifyError("Choose between 1 and 50 favorite songs.")
            shuffle = args.get("shuffle", True)
            if not isinstance(shuffle, bool):
                raise SpotifyError("Shuffle must be enabled or disabled.")
            return "play_favorites", {"count": count_int, "shuffle": shuffle}
        if name == "spotify_set_volume":
            volume = args.get("volume")
            if isinstance(volume, bool) or not isinstance(volume, (int, float)) or int(volume) != volume:
                raise SpotifyError("Spotify volume must be a whole number from 0 to 100.")
            volume_int = int(volume)
            if not 0 <= volume_int <= 100:
                raise SpotifyError("Spotify volume must be between 0 and 100 percent.")
            return "volume", {"volume": volume_int}
        if name == "spotify_adjust_volume":
            delta = args.get("delta")
            if isinstance(delta, bool) or not isinstance(delta, (int, float)) or int(delta) != delta:
                raise SpotifyError("Spotify volume adjustment must be a whole-number delta.")
            return "volume_relative", {"delta": max(-100, min(100, int(delta)))}
        if name == "spotify_queue":
            query = str(args.get("query") or "").strip()
            if not query:
                raise SpotifyError("Tell me which song to add to the Spotify queue.")
            return "queue", {"query": query}
        if name == "spotify_set_shuffle":
            enabled = args.get("enabled")
            if not isinstance(enabled, bool):
                raise SpotifyError("Shuffle must be enabled or disabled.")
            return "shuffle", {"enabled": enabled}
        if name == "spotify_set_repeat":
            mode = str(args.get("mode") or "").lower().strip()
            if mode not in {"context", "track", "off"}:
                raise SpotifyError("Repeat mode must be context, track, or off.")
            return "repeat", {"mode": mode}
        raise SpotifyError(f"Unknown Spotify tool: {name}")

    async def execute_action(self, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one normalized action and return the resulting player state."""

        values = dict(args or {})
        if action == "status":
            return await self.status()
        if action == "play_favorites":
            return await self.play_favorites(
                count=int(values.get("count", 10)),
                shuffle=bool(values.get("shuffle", True)),
            )
        if action == "save_current":
            return await self.save_current_track()
        if action == "volume_relative":
            current = await self.status()
            if current.get("error"):
                raise SpotifyError(str(current["error"]))
            current_volume = current.get("volume_percent")
            values = {"volume": max(0, min(100, int(current_volume if current_volume is not None else 50) + int(values.get("delta", 0))))}
            action = "volume"
        if action == "shuffle":
            values = {"volume": 1 if values.get("enabled") else 0}
        if action == "repeat":
            values = {"query": values.get("mode", "context")}
        return await self.control(action, **values)

    @staticmethod
    def format_action_response(action: str, args: dict[str, Any], result: dict[str, Any]) -> str:
        if action == "status":
            if result.get("error"):
                return f"Spotify couldn't read the current player: {result['error']}"
            item = result.get("item") or {}
            if not item.get("name"):
                return "Spotify is connected, but nothing is currently playing."
            artists = ", ".join(item.get("artists") or [])
            state = "playing" if result.get("is_playing") else "paused"
            return f"Spotify is {state}: {item['name']} by {artists}."
        if action == "play_favorites":
            selected_count = int(result.get("selected_count") or len(result.get("favorite_tracks") or []) or 0)
            if selected_count == 1:
                return "Playing one track from your Spotify Liked Songs."
            return f"Playing {selected_count} tracks from your Spotify Liked Songs."
        if action == "save_current":
            saved_track = result.get("saved_track") or result.get("item") or {}
            if isinstance(saved_track, dict):
                saved_name = str(saved_track.get("name") or "").strip()
                saved_artists = ", ".join(
                    str(value).strip()
                    for value in (saved_track.get("artists") or [])
                    if str(value).strip()
                )
                if saved_name and saved_artists:
                    return f"Saved “{saved_name}” by {saved_artists} to your Spotify Liked Songs."
                if saved_name:
                    return f"Saved “{saved_name}” to your Spotify Liked Songs."
            return "Saved the current Spotify track to your Liked Songs."
        # Prefer the resolver's canonical match because Spotify's player
        # endpoint can briefly return the previous item immediately after a
        # play/queue request.
        item = result.get("matched_track") or result.get("item") or {}
        track = item.get("name")
        artists = ", ".join(item.get("artists") or [])
        if action == "play_artist":
            artist = result.get("matched_artist") or {}
            artist_name = artist.get("name") or args.get("query")
            return f"Playing songs from {artist_name}'s Spotify artist profile."
        if action in {"play", "resume"}:
            suffix = f" by {artists}" if track and artists else ""
            return f"Playing {track or 'Spotify'}{suffix}."
        if action == "pause":
            return "Spotify playback paused."
        if action == "next":
            return f"Skipped to {track}." if track else "Skipped to the next Spotify track."
        if action == "previous":
            return f"Went back to {track}." if track else "Went back to the previous Spotify track."
        if action == "volume":
            return f"Spotify volume set to {args.get('volume')} percent."
        if action == "volume_relative":
            return "Spotify volume adjusted."
        if action == "queue":
            suffix = f" by {artists}" if track and artists else ""
            return f"Added {track or args.get('query')}" f"{suffix} to the Spotify queue."
        if action == "toggle":
            return "Spotify playback resumed." if result.get("is_playing") else "Spotify playback paused."
        if action == "shuffle":
            return "Spotify shuffle enabled." if args.get("enabled") else "Spotify shuffle disabled."
        if action == "repeat":
            return f"Spotify repeat set to {args.get('mode')}."
        return "Spotify playback updated."

    async def handle_chat_message(self, text: str, *, enabled: bool = True) -> str | None:
        parsed = self.parse_command(text)
        if parsed is None:
            return None
        action, args = parsed
        if not enabled:
            return "Spotify control is disabled. Open Settings → Integrations → Spotify and enable it first."
        if not self.is_authenticated():
            return "Spotify is not connected yet. Open Settings → Integrations → Spotify and connect your account."
        try:
            result = await self.execute_action(action, args)
        except SpotifyError as exc:
            return f"Spotify couldn't complete that: {exc}"
        return self.format_action_response(action, args, result)


spotify_controller = SpotifyController()
