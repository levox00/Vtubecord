import asyncio

import pytest

from app.integrations.spotify import (
    SPOTIFY_SEARCH_LIMIT,
    SPOTIFY_TOOL_DEFINITIONS,
    SpotifyController,
    SpotifyError,
    _spotify_artist_id,
    _split_track_and_artist,
)
from app.llm.base import ChatMessage, ToolCall
from app.llm.openai_compatible import _serialize_message
from app.tools.factory import create_tool_registry


def test_spotify_playback_commands_are_parsed():
    assert SpotifyController.parse_command("pause") == ("pause", {})
    assert SpotifyController.parse_command("resume the music") == ("resume", {})
    assert SpotifyController.parse_command("skip song") == ("next", {})
    assert SpotifyController.parse_command("go back a song") == ("previous", {})


def test_natural_navigation_phrases_are_parsed():
    assert SpotifyController.parse_command("Play the next song") == ("next", {})
    assert SpotifyController.parse_command("Playback the next song") == ("next", {})
    assert SpotifyController.parse_command("please skip to the next track") == ("next", {})
    assert SpotifyController.parse_command("start music") == ("resume", {})
    assert SpotifyController.parse_command("play music") == ("resume", {})
    assert SpotifyController.parse_command("resume playback") == ("resume", {})
    assert SpotifyController.parse_command("1 song back") == ("previous", {})
    assert SpotifyController.parse_command("one track back") == ("previous", {})
    assert SpotifyController.parse_command("go back one track") == ("previous", {})


def test_liked_song_requests_use_the_favorites_tool_instead_of_a_fake_track_search():
    assert SpotifyController.parse_command("Play my favorite songs") == (
        "play_favorites",
        {"count": 10, "shuffle": True},
    )


def test_current_track_favorite_requests_use_the_save_tool():
    for phrase in (
        "favorit this song",
        "favorite this song",
        "favourite the current playing song",
        "like the current track",
        "save what is playing",
        "add this song to my liked songs",
    ):
        assert SpotifyController.parse_command(phrase) == ("save_current", {}), phrase
    assert SpotifyController.tool_from_action("save_current") == (
        "spotify_save_current",
        {},
    )
    assert SpotifyController.action_from_tool("spotify_save_current") == (
        "save_current",
        {},
    )


def test_save_current_track_likes_the_exact_current_spotify_item():
    asyncio.run(_test_save_current_track_likes_the_exact_current_spotify_item())


async def _test_save_current_track_likes_the_exact_current_spotify_item():
    controller = SpotifyController()
    controller._load_tokens = lambda: {"access_token": "test", "scope": "user-read-playback-state user-library-modify"}  # type: ignore[method-assign]
    requests: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, path: str, **kwargs):
        requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/me/player"):
            return {
                "is_playing": True,
                "item": {
                    "id": "current-id",
                    "uri": "spotify:track:current-id",
                    "name": "Current Song",
                    "artists": [{"name": "Current Artist"}],
                    "album": {"name": "Album", "images": []},
                },
                "device": {},
            }
        return None

    controller._request = fake_request  # type: ignore[method-assign]
    result = await controller.save_current_track()
    assert result["saved_track"]["id"] == "current-id"
    assert requests[-1][0:2] == ("PUT", "/me/tracks")
    assert requests[-1][2]["params"] == {"ids": "current-id"}
    assert controller.format_action_response("save_current", {}, result) == (
        "Saved “Current Song” by Current Artist to your Spotify Liked Songs."
    )
    assert SpotifyController.parse_command("put on my liked tracks") == (
        "play_favorites",
        {"count": 10, "shuffle": True},
    )
    assert SpotifyController.parse_command("play my saved songs in order") == (
        "play_favorites",
        {"count": 10, "shuffle": False},
    )
    assert SpotifyController.tool_from_action("play_favorites", {"count": 5, "shuffle": True}) == (
        "spotify_play_favorites",
        {"count": 5, "shuffle": True},
    )


def test_favorites_tool_is_exposed_and_never_confirms_an_invented_track_title():
    names = {definition["function"]["name"] for definition in SPOTIFY_TOOL_DEFINITIONS}
    assert "spotify_play_favorites" in names
    assert SpotifyController.action_from_tool("spotify_play_favorites", {}) == (
        "play_favorites",
        {"count": 10, "shuffle": True},
    )
    assert SpotifyController.format_action_response(
        "play_favorites",
        {"count": 2, "shuffle": True},
        {"selected_count": 2, "favorite_tracks": [{"name": "Actual song"}, {"name": "Another song"}]},
    ) == "Playing 2 tracks from your Spotify Liked Songs."


def test_play_favorites_reads_saved_tracks_and_starts_them():
    asyncio.run(_test_play_favorites_reads_saved_tracks_and_starts_them())


async def _test_play_favorites_reads_saved_tracks_and_starts_them():
    controller = SpotifyController()
    controller._load_tokens = lambda: {"scope": "user-read-playback-state user-library-read"}  # type: ignore[method-assign]
    requests: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, path: str, **kwargs):
        requests.append((method, path, kwargs))
        if (method, path) == ("GET", "/me/tracks"):
            return {
                "items": [
                    {"track": {"uri": "spotify:track:first", "name": "First", "artists": [{"name": "A"}], "album": {"name": "Album", "images": []}}},
                    {"track": {"uri": "spotify:track:second", "name": "Second", "artists": [{"name": "B"}], "album": {"name": "Album", "images": []}}},
                ]
            }
        if (method, path) == ("GET", "/me/player"):
            return {"is_playing": True, "item": {}, "device": {}}
        return None

    controller._request = fake_request  # type: ignore[method-assign]
    result = await controller.play_favorites(count=2, shuffle=False)
    assert result["selected_count"] == 2
    assert [track["uri"] for track in result["favorite_tracks"]] == [
        "spotify:track:first",
        "spotify:track:second",
    ]
    assert requests[0][0:2] == ("GET", "/me/tracks")
    assert requests[1][0:2] == ("PUT", "/me/player/play")
    assert requests[1][2]["json"] == {"uris": ["spotify:track:first", "spotify:track:second"]}


def test_current_track_questions_are_parsed_as_read_only_status_requests():
    for phrase in (
        "what is playing",
        "what's currently playing right now",
        "what is the current song",
        "current song playing",
        "which track is currently playing",
        "what are we listening to",
        "what am I listening to",
        "tell me what is currently playing",
        "now playing",
        "current track",
    ):
        assert SpotifyController.parse_command(phrase) == ("status", {}), phrase


def test_current_track_tool_is_exposed_and_maps_to_status():
    names = {definition["function"]["name"] for definition in SPOTIFY_TOOL_DEFINITIONS}
    assert "spotify_current_track" in names
    assert SpotifyController.tool_from_action("status") == ("spotify_current_track", {})
    assert SpotifyController.action_from_tool("spotify_current_track") == ("status", {})
    assert SpotifyController.arguments_for_tool_request(
        "spotify_current_track", "what song is currently playing?"
    ) == {}


def test_voice_transcription_variants_extract_song_and_artist():
    assert SpotifyController.parse_command(
        "pllayyyy something called Little Angel from the artist onokami"
    ) == ("play", {"query": "little angel by onokami"})


def test_polite_character_address_extracts_spotify_request():
    assert SpotifyController.parse_command(
        "hi neuro sama could you play sailor song for me please"
    ) == ("play", {"query": "sailor song"})


def test_parser_action_selects_required_function_tool():
    assert SpotifyController.tool_from_action("play", {"query": "sailor song"}) == (
        "spotify_play",
        {"query": "sailor song"},
    )


def test_semantically_routed_song_arguments_are_grounded_from_natural_requests():
    assert SpotifyController.arguments_for_tool_request(
        "spotify_play",
        "phi neuro can you play me hide away by daya",
    ) == {"query": "hide away by daya"}
    assert SpotifyController.arguments_for_tool_request(
        "spotify_play",
        "phi neuro can you play me the song hide away by daya",
    ) == {"query": "hide away by daya"}
    assert SpotifyController.arguments_for_tool_request(
        "spotify_play",
        "hello could you play the song in the sea by the dreamer piano",
    ) == {"query": "in the sea by the dreamer piano"}
    assert SpotifyController.arguments_for_tool_request(
        "spotify_play",
        "could you play Sailor Song on Spotify for me please?",
    ) == {"query": "Sailor Song"}
    assert SpotifyController.tool_from_action("next", {}) == ("spotify_next", {})
    assert SpotifyController.parse_command(
        "play something called Little Angel by artist Onokami"
    ) == ("play", {"query": "little angel by onokami"})


def test_tool_actions_are_mapped_and_validated():
    assert SpotifyController.action_from_tool("spotify_next") == ("next", {})
    assert SpotifyController.action_from_tool("spotify_play", {}) == ("resume", {})
    assert SpotifyController.action_from_tool("spotify_play", {"query": "Daft Punk"}) == (
        "play",
        {"query": "Daft Punk"},
    )
    assert SpotifyController.action_from_tool("spotify_set_volume", {"volume": 75}) == (
        "volume",
        {"volume": 75},
    )


def test_tool_calls_use_openai_assistant_wire_shape():
    payload = _serialize_message(
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="call_1", name="spotify_next", arguments={})],
        )
    )
    assert payload["tool_calls"][0]["type"] == "function"
    assert payload["tool_calls"][0]["function"]["name"] == "spotify_next"
    assert payload["tool_calls"][0]["function"]["arguments"] == "{}"


def test_spotify_volume_and_search_commands_are_parsed():
    assert SpotifyController.parse_command("set volume to 75%") == ("volume", {"volume": 75})
    assert SpotifyController.parse_command("Volume a hundred percent") == ("volume", {"volume": 100})
    assert SpotifyController.parse_command("set volume to fifty") == ("volume", {"volume": 50})
    assert SpotifyController.parse_command("turn the volume down") == ("volume_relative", {"delta": -10})
    assert SpotifyController.parse_command("play Daft Punk on Spotify") == (
        "play",
        {"query": "daft punk"},
    )


def test_short_volume_followups_use_recent_volume_context_only():
    assert SpotifyController.parse_contextual_command(
        "Make it fifty",
        ["Volume a hundred percent.", "Volume is now 100% for the current track."],
    ) == ("volume", {"volume": 50})
    assert SpotifyController.parse_contextual_command(
        "Make it fifty",
        ["That song has a great chorus."],
    ) is None
    assert SpotifyController.parse_command("queue Numb to the queue") == (
        "queue",
        {"query": "numb"},
    )


def test_ambiguous_transcripts_are_not_treated_as_song_searches():
    # A short name-like transcript must stay ordinary chat unless it includes
    # an explicit playback/search request.
    assert SpotifyController.parse_command("William Seventy") is None
    assert SpotifyController.parse_command("William Seventy, how are you?") is None
    assert create_tool_registry().looks_actionable("William Seventy") is False


def test_artist_profile_playback_requests_are_distinct_from_track_searches():
    for phrase in (
        "play songs from Bruno Mars",
        "play music by Bruno Mars",
        "put on the artist profile for Bruno Mars",
        "play Bruno Mars from his Spotify profile",
    ):
        assert SpotifyController.parse_command(phrase) == (
            "play_artist",
            {"query": "bruno mars"},
        ), phrase

    assert SpotifyController.tool_from_action("play_artist", {"query": "Bruno Mars"}) == (
        "spotify_play_artist",
        {"query": "Bruno Mars"},
    )
    assert SpotifyController.action_from_tool(
        "spotify_play_artist", {"artist": "Bruno Mars"}
    ) == ("play_artist", {"query": "Bruno Mars"})
    assert SpotifyController.arguments_for_tool_request(
        "spotify_play_artist", "please play songs from Bruno Mars for me"
    ) == {"artist": "Bruno Mars"}


def test_artist_profile_urls_are_recognized():
    artist_id = "0du5cEVh5yTK9QJze8zA0C"
    assert _spotify_artist_id(f"spotify:artist:{artist_id}") == artist_id
    assert _spotify_artist_id(
        f"https://open.spotify.com/artist/{artist_id}?si=example"
    ) == artist_id
    assert SpotifyController.parse_command(
        f"play https://open.spotify.com/artist/{artist_id}?si=example"
    ) == (
        "play_artist",
        {"query": f"https://open.spotify.com/artist/{artist_id}?si=example"},
    )


def test_unrelated_messages_are_not_spotify_commands():
    assert SpotifyController.parse_command("what is playing") == ("status", {})
    assert SpotifyController.parse_command("tell me a joke") is None


def test_current_track_confirmation_reports_title_artist_and_state():
    assert SpotifyController.format_action_response(
        "status",
        {},
        {
            "is_playing": True,
            "item": {"name": "Little Angel", "artists": ["Onokami"]},
        },
    ) == "Spotify is playing: Little Angel by Onokami."


def test_track_artist_extraction_accepts_by_and_from():
    assert _split_track_and_artist("Little Angel by Onokami") == ("Little Angel", "Onokami")
    assert _split_track_and_artist("Little Angel from Onokami on Spotify") == ("Little Angel", "Onokami")
    assert _split_track_and_artist("something called Little Angel from the artist Onokami") == (
        "Little Angel",
        "Onokami",
    )
    assert _split_track_and_artist("Daft Punk") == ("Daft Punk", None)


def test_track_resolver_corrects_small_artist_typo_and_returns_canonical_track():
    asyncio.run(_test_track_resolver_corrects_small_artist_typo_and_returns_canonical_track())


async def _test_track_resolver_corrects_small_artist_typo_and_returns_canonical_track():
    controller = SpotifyController()
    queries: list[str] = []

    async def fake_request(method: str, path: str, **kwargs):
        assert kwargs["params"]["limit"] == SPOTIFY_SEARCH_LIMIT == 10
        queries.append(kwargs["params"]["q"])
        if len(queries) == 1:
            return {"tracks": {"items": []}}
        return {
            "tracks": {
                "items": [
                    {
                        "id": "onokami-track",
                        "uri": "spotify:track:onokami-track",
                        "name": "Little Angel",
                        "artists": [{"name": "Onokami"}],
                        "album": {"name": "Angels", "images": []},
                    },
                    {
                        "id": "wrong-artist-track",
                        "uri": "spotify:track:wrong-artist-track",
                        "name": "Little Angel",
                        "artists": [{"name": "Another Artist"}],
                        "album": {"name": "Other", "images": []},
                    },
                ]
            }
        }

    controller._request = fake_request  # type: ignore[method-assign]
    resolved = await controller.resolve_track("Little Angel by Onokamy")

    assert queries == ["track:Little Angel artist:Onokamy", "track:Little Angel"]
    assert resolved["name"] == "Little Angel"
    assert resolved["artists"] == ["Onokami"]
    assert resolved["uri"] == "spotify:track:onokami-track"
    assert resolved["match_score"] >= 0.7


def test_track_resolver_retries_if_spotify_reduces_search_limit_again():
    asyncio.run(_test_track_resolver_retries_if_spotify_reduces_search_limit_again())


async def _test_track_resolver_retries_if_spotify_reduces_search_limit_again():
    controller = SpotifyController()
    params_seen: list[dict] = []

    async def fake_request(method: str, path: str, **kwargs):
        params = dict(kwargs["params"])
        params_seen.append(params)
        if "limit" in params:
            raise SpotifyError("Invalid limit")
        return {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:fallback",
                        "name": "When I Close My Eyes",
                        "artists": [{"name": "Example Artist"}],
                        "album": {"name": "Example Album", "images": []},
                    }
                ]
            }
        }

    controller._request = fake_request  # type: ignore[method-assign]
    resolved = await controller.resolve_track("When I Close My Eyes")

    assert resolved["name"] == "When I Close My Eyes"
    assert params_seen[0]["limit"] == 10
    assert any("limit" not in params for params in params_seen)


def test_track_resolver_rejects_exact_title_from_wrong_artist():
    asyncio.run(_test_track_resolver_rejects_exact_title_from_wrong_artist())


async def _test_track_resolver_rejects_exact_title_from_wrong_artist():
    controller = SpotifyController()

    async def fake_request(method: str, path: str, **kwargs):
        return {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:wrong",
                        "name": "Little Angel",
                        "artists": [{"name": "Another Artist"}],
                        "album": {"name": "Other", "images": []},
                    }
                ]
            }
        }

    controller._request = fake_request  # type: ignore[method-assign]
    with pytest.raises(SpotifyError, match="close Spotify match"):
        await controller.resolve_track("Little Angel by Onokami")


def test_track_resolver_keeps_artist_only_searches_working():
    asyncio.run(_test_track_resolver_keeps_artist_only_searches_working())


async def _test_track_resolver_keeps_artist_only_searches_working():
    controller = SpotifyController()

    async def fake_request(method: str, path: str, **kwargs):
        return {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:daft-punk",
                        "name": "Get Lucky",
                        "artists": [{"name": "Daft Punk"}],
                        "album": {"name": "Random Access Memories", "images": []},
                    }
                ]
            }
        }

    controller._request = fake_request  # type: ignore[method-assign]
    resolved = await controller.resolve_track("Daft Punk")
    assert resolved["artists"] == ["Daft Punk"]
    assert resolved["uri"] == "spotify:track:daft-punk"


def test_artist_resolver_uses_artist_results_and_profile_context():
    asyncio.run(_test_artist_resolver_uses_artist_results_and_profile_context())


async def _test_artist_resolver_uses_artist_results_and_profile_context():
    controller = SpotifyController()
    requests: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, path: str, **kwargs):
        requests.append((method, path, kwargs))
        if method == "GET" and path == "/search":
            return {
                "artists": {
                    "items": [
                        {
                            "id": "bruno-id",
                            "uri": "spotify:artist:bruno-id",
                            "name": "Bruno Mars",
                            "images": [],
                            "external_urls": {
                                "spotify": "https://open.spotify.com/artist/bruno-id"
                            },
                        },
                        {
                            "id": "bruno-reibold",
                            "uri": "spotify:artist:bruno-reibold",
                            "name": "Bruno Reibold",
                            "images": [],
                        },
                    ]
                }
            }
        if method == "PUT" and path == "/me/player/play":
            return None
        if method == "GET" and path == "/me/player":
            return {
                "is_playing": True,
                "device": {"id": "device", "name": "Desktop", "is_active": True},
                "item": {},
            }
        raise AssertionError((method, path, kwargs))

    controller._request = fake_request  # type: ignore[method-assign]
    result = await controller.execute_action("play_artist", {"query": "Bruno Mars"})

    play_request = next(item for item in requests if item[0:2] == ("PUT", "/me/player/play"))
    assert play_request[2]["json"] == {"context_uri": "spotify:artist:bruno-id"}
    assert result["matched_artist"]["name"] == "Bruno Mars"
    assert result["matched_artist"]["uri"] == "spotify:artist:bruno-id"
    assert SpotifyController.format_action_response("play_artist", {}, result) == (
        "Playing songs from Bruno Mars's Spotify artist profile."
    )


def test_generic_play_accepts_a_pasted_artist_profile_url():
    asyncio.run(_test_generic_play_accepts_a_pasted_artist_profile_url())


async def _test_generic_play_accepts_a_pasted_artist_profile_url():
    controller = SpotifyController()
    artist_id = "0du5cEVh5yTK9QJze8zA0C"
    play_bodies: list[dict] = []

    async def fake_request(method: str, path: str, **kwargs):
        if method == "GET" and path == f"/artists/{artist_id}":
            return {
                "id": artist_id,
                "uri": f"spotify:artist:{artist_id}",
                "name": "Bruno Mars",
                "images": [],
            }
        if method == "PUT" and path == "/me/player/play":
            play_bodies.append(kwargs["json"])
            return None
        if method == "GET" and path == "/me/player":
            return None
        raise AssertionError((method, path, kwargs))

    controller._request = fake_request  # type: ignore[method-assign]
    await controller.control(
        "play",
        query=f"https://open.spotify.com/artist/{artist_id}?si=example",
    )
    assert play_bodies == [{"context_uri": f"spotify:artist:{artist_id}"}]


def test_exact_title_keeps_spotify_ranking_instead_of_artist_name_similarity():
    asyncio.run(_test_exact_title_keeps_spotify_ranking_instead_of_artist_name_similarity())


async def _test_exact_title_keeps_spotify_ranking_instead_of_artist_name_similarity():
    controller = SpotifyController()

    async def fake_request(method: str, path: str, **kwargs):
        return {
            "tracks": {
                "items": [
                    {
                        "uri": "spotify:track:gigi",
                        "name": "Sailor Song",
                        "artists": [{"name": "Gigi Perez"}],
                        "album": {"name": "Sailor Song", "images": []},
                    },
                    {
                        "uri": "spotify:track:manil",
                        "name": "Sailor Song",
                        "artists": [{"name": "Manil"}],
                        "album": {"name": "Sailor Song", "images": []},
                    },
                ]
            }
        }

    controller._request = fake_request  # type: ignore[method-assign]
    resolved = await controller.resolve_track("Sailor Song")

    assert resolved["uri"] == "spotify:track:gigi"
    assert resolved["artists"] == ["Gigi Perez"]


def test_spotify_confirmation_uses_resolved_track_not_stale_player_item():
    result = {
        "item": {"name": "Previous Track", "artists": ["Other Artist"]},
        "matched_track": {"name": "Little Angel", "artists": ["Onokami"]},
    }
    assert SpotifyController.format_action_response("play", {}, result) == (
        "Playing Little Angel by Onokami."
    )
