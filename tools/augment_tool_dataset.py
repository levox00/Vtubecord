"""Migrate and expand the local SFT dataset with the current tool registry.

The dataset is intentionally kept as JSONL.  This script removes stale tool
examples, maps legacy names to the canonical runtime names, and adds a small
balanced set of examples for every currently registered Spotify, Discord, and
OBS tool.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "datasets" / "neuro_mikudes_sft.jsonl"
TEMP_DATASET = DATASET.with_suffix(".jsonl.tmp")

sys.path.insert(0, str(ROOT / "backend"))

from app.tools.discord import register_discord_tools  # noqa: E402
from app.tools.obs import register_obs_tools  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402
from app.tools.spotify import register_spotify_tools  # noqa: E402


def registry_definitions() -> list[dict[str, Any]]:
    registry = ToolRegistry()
    register_spotify_tools(registry)
    register_discord_tools(registry)
    register_obs_tools(registry)
    return [spec.openai_definition() for spec in registry._tools.values()]


TOOL_DEFINITIONS = registry_definitions()
TOOL_NAMES = {item["function"]["name"] for item in TOOL_DEFINITIONS}


def parse_arguments(call: dict[str, Any]) -> dict[str, Any]:
    value = call.get("function", {}).get("arguments", {})
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def track_query(arguments: dict[str, Any]) -> str:
    song = str(arguments.get("song") or arguments.get("title") or "").strip()
    artist = str(arguments.get("artist") or "").strip()
    if song and artist:
        return f"{song} by {artist}"
    return song or artist


def migrate_legacy_call(call: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    old_name = str(call.get("function", {}).get("name") or "")
    arguments = parse_arguments(call)
    if old_name in TOOL_NAMES:
        return old_name, arguments
    if old_name == "play_music":
        return "spotify_play", {"query": track_query(arguments)}
    if old_name == "queue_song":
        return "spotify_queue", {"query": track_query(arguments)}
    if old_name == "set_volume":
        level = arguments.get("level", arguments.get("volume", 50))
        try:
            level = max(0, min(100, int(level)))
        except (TypeError, ValueError):
            level = 50
        return "spotify_set_volume", {"volume": level}
    if old_name == "send_discord":
        content = str(arguments.get("message") or arguments.get("content") or "").strip()
        return "discord_send_message", {"content": content} if content else None
    # get_weather, web_search, set_timer, set_reminder, get_osu_stats, and
    # clip_stream do not have registered handlers in this project yet.  Do
    # not teach the model to call tools that the runtime rejects.
    return None


def migrated_result(old_name: str, arguments: dict[str, Any], result: Any) -> dict[str, Any]:
    value = result if isinstance(result, dict) else {}
    if old_name in {"play_music", "queue_song"}:
        title = str(value.get("song") or arguments.get("song") or arguments.get("title") or "requested track")
        artist = str(value.get("artist") or arguments.get("artist") or "")
        if old_name == "queue_song":
            return {"ok": True, "queued": True, "track": {"title": title, "artists": [artist] if artist else []}}
        return {"ok": True, "playing": True, "track": {"title": title, "artists": [artist] if artist else []}}
    if old_name == "set_volume":
        return {"ok": True, "volume": arguments.get("level", arguments.get("volume", 50))}
    if old_name == "send_discord":
        return {"ok": True, "sent": True, "content": arguments.get("message") or arguments.get("content") or ""}
    return value


def migrate_row(row: dict[str, Any]) -> dict[str, Any] | None:
    calls = [message for message in row.get("messages", []) if message.get("tool_calls")]
    if not calls:
        # A few legacy rows carried a tool directory without actually making a
        # call.  Remove that stale directory so old names cannot be learned.
        row.pop("tools", None)
        return row
    if len(calls) != 1 or len(calls[0].get("tool_calls") or []) != 1:
        return None
    assistant = calls[0]
    original_call = assistant["tool_calls"][0]
    migrated = migrate_legacy_call(original_call)
    if migrated is None:
        return None
    canonical_name, arguments = migrated
    call = dict(original_call)
    function = dict(call.get("function") or {})
    old_name = str(function.get("name") or "")
    function["name"] = canonical_name
    function["arguments"] = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
    call["function"] = function
    assistant["tool_calls"] = [call]
    for message in row.get("messages", []):
        if message.get("role") == "tool" and message.get("tool_call_id") == call.get("id"):
            try:
                old_result = json.loads(message.get("content") or "{}")
            except (TypeError, json.JSONDecodeError):
                old_result = {}
            message["content"] = json.dumps(migrated_result(old_name, arguments, old_result), ensure_ascii=False, separators=(",", ":"))
    row["tools"] = TOOL_DEFINITIONS
    return row


SYSTEM = (
    "You are Neuro, a digital AI companion and streamer created by Mikudes. "
    "Be casual, warm, concise, and honest. Use one registered function tool when "
    "the user directly requests an external action. Never claim an action worked "
    "before the tool result confirms it, and never expose internal IDs or routing metadata."
)


def sample(user: str, tool: str, arguments: dict[str, Any], result: dict[str, Any], reply: str, index: int) -> dict[str, Any]:
    call_id = f"aug_{tool}_{index:03d}"
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": call_id, "type": "function", "function": {"name": tool, "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))}}],
            },
            {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, separators=(",", ":"))},
            {"role": "assistant", "content": reply},
        ],
        "tools": TOOL_DEFINITIONS,
    }


def examples() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    add = rows.append
    # Spotify playback and player controls.
    add(sample("play Little Angel by Onokami", "spotify_play", {"query": "Little Angel by Onokami"}, {"ok": True, "playing": True, "track": {"title": "Little Angel", "artists": ["Onokami"]}}, "got it — Little Angel by Onokami is playing now.", 1))
    add(sample("put on the song Blinding Lights", "spotify_play", {"query": "Blinding Lights"}, {"ok": True, "playing": True, "track": {"title": "Blinding Lights", "artists": ["The Weeknd"]}}, "there it goes. Blinding Lights is on.", 2))
    add(sample("play some music from Porter Robinson", "spotify_play_artist", {"artist": "Porter Robinson"}, {"ok": True, "playing": True, "context": {"artist": "Porter Robinson"}}, "starting a Porter Robinson mix for you.", 3))
    add(sample("play songs by the artist Aimer", "spotify_play_artist", {"artist": "Aimer"}, {"ok": True, "playing": True, "context": {"artist": "Aimer"}}, "Aimer mix loaded. enjoy the feelings.", 4))
    add(sample("pause the music", "spotify_pause", {}, {"ok": True, "is_playing": False}, "paused.", 5))
    add(sample("resume playback", "spotify_resume", {}, {"ok": True, "is_playing": True}, "back to it.", 6))
    add(sample("skip this track", "spotify_next", {}, {"ok": True, "skipped": True}, "skipping to the next one.", 7))
    add(sample("go back one song", "spotify_previous", {}, {"ok": True, "previous": True}, "going back one track.", 8))
    add(sample("set Spotify to 35 percent", "spotify_set_volume", {"volume": 35}, {"ok": True, "volume": 35}, "volume set to 35 percent.", 9))
    add(sample("turn the music up by 10", "spotify_adjust_volume", {"delta": 10}, {"ok": True, "volume": 60, "delta": 10}, "bumped it up a little.", 10))
    add(sample("lower Spotify volume by 20 percent", "spotify_adjust_volume", {"delta": -20}, {"ok": True, "volume": 40, "delta": -20}, "lowered it by 20.", 11))
    add(sample("queue Never Gonna Give You Up by Rick Astley", "spotify_queue", {"query": "Never Gonna Give You Up by Rick Astley"}, {"ok": True, "queued": True, "position": 3, "track": {"title": "Never Gonna Give You Up", "artists": ["Rick Astley"]}}, "queued it next-ish. the rickroll is waiting.", 12))
    add(sample("put some lo-fi in the queue", "spotify_queue", {"query": "lo-fi"}, {"ok": True, "queued": True, "position": 4}, "lo-fi added to the queue.", 13))
    add(sample("turn shuffle on", "spotify_set_shuffle", {"enabled": True}, {"ok": True, "shuffle": True}, "shuffle is on.", 14))
    add(sample("disable shuffle", "spotify_set_shuffle", {"enabled": False}, {"ok": True, "shuffle": False}, "shuffle is off.", 15))
    add(sample("repeat this whole playlist", "spotify_set_repeat", {"mode": "context"}, {"ok": True, "repeat": "context"}, "repeating the current context.", 16))
    add(sample("repeat the current song", "spotify_set_repeat", {"mode": "track"}, {"ok": True, "repeat": "track"}, "this track is getting the encore.", 17))
    add(sample("turn repeat off", "spotify_set_repeat", {"mode": "off"}, {"ok": True, "repeat": "off"}, "repeat is off.", 18))
    add(sample("toggle Spotify playback", "spotify_toggle", {}, {"ok": True, "is_playing": False}, "toggled playback.", 19))
    add(sample("play my favorite songs", "spotify_play_favorites", {"count": 10, "shuffle": True}, {"ok": True, "playing": True, "selected_count": 10, "source": "liked_songs"}, "playing a shuffled set from your Spotify Liked Songs.", 43))
    add(sample("play my saved tracks in order", "spotify_play_favorites", {"count": 10, "shuffle": False}, {"ok": True, "playing": True, "selected_count": 10, "source": "liked_songs"}, "playing your saved tracks in order.", 44))
    add(sample("what song is playing right now", "spotify_current_track", {}, {"ok": True, "is_playing": True, "track": {"title": "Little Angel", "artists": ["Onokami"], "album": "Little Angel"}}, "right now it is Little Angel by Onokami.", 20))
    add(sample("what am I listening to", "spotify_status", {}, {"ok": True, "is_playing": False, "track": {"title": "Numb", "artists": ["Linkin Park"]}}, "you are paused on Numb by Linkin Park.", 21))
    # Discord bridge and voice controls.
    add(sample("is the Discord voice bridge connected", "discord_voice_status", {}, {"ok": True, "bridge_connected": True, "voice_state": {"connected": True, "self_mute": False, "self_deaf": False}}, "the Discord bridge is connected and I am in the voice call.", 22))
    add(sample("send this to Discord: raid starts in five", "discord_send_message", {"content": "raid starts in five"}, {"ok": True, "sent": True, "content": "raid starts in five"}, "sent it to Discord.", 23))
    add(sample("stop replying to every Discord message", "discord_set_auto_reply", {"enabled": False}, {"ok": True, "auto_reply": False}, "automatic Discord replies are off now.", 24))
    add(sample("join my Discord voice call", "discord_join_voice", {}, {"ok": True, "joined": True}, "joining your voice call.", 25))
    add(sample("leave the Discord call", "discord_leave_voice", {}, {"ok": True, "left": True}, "leaving the call.", 26))
    add(sample("mute yourself in Discord", "discord_set_mute", {"enabled": True}, {"ok": True, "self_mute": True}, "I muted my own Discord mic.", 27))
    add(sample("unmute your Discord mic", "discord_set_mute", {"enabled": False}, {"ok": True, "self_mute": False}, "my Discord mic is unmuted.", 28))
    add(sample("deafen yourself in the call", "discord_set_deafen", {"enabled": True}, {"ok": True, "self_deaf": True}, "I deafened my own Discord client.", 29))
    add(sample("undeafen yourself", "discord_set_deafen", {"enabled": False}, {"ok": True, "self_deaf": False}, "I am listening again.", 30))
    add(sample("say welcome everyone in the voice call", "discord_speak_voice", {"text": "Welcome everyone to the voice call."}, {"ok": True, "spoken_text": "Welcome everyone to the voice call."}, "I said it in the call.", 31))
    add(sample("announce in voice that dinner is ready", "discord_speak_voice", {"text": "Dinner is ready."}, {"ok": True, "spoken_text": "Dinner is ready."}, "announced it in voice.", 32))
    # OBS controls.
    add(sample("what is OBS doing", "obs_get_status", {}, {"ok": True, "current_scene": "Starting Soon", "stream": {"active": False}, "recording": {"active": False}, "virtual_camera": {"active": False}, "discord_camera": {"active": False}}, "OBS is on Starting Soon and is currently offline.", 33))
    add(sample("switch OBS to the gameplay scene", "obs_set_scene", {"scene": "Gameplay"}, {"ok": True, "current_scene": "Gameplay"}, "switched OBS to Gameplay.", 34))
    add(sample("start the OBS livestream", "obs_start_stream", {}, {"ok": True, "stream": {"active": True}}, "the OBS livestream is live.", 35))
    add(sample("stop the OBS stream", "obs_stop_stream", {}, {"ok": True, "stream": {"active": False}}, "the OBS stream is stopped.", 36))
    add(sample("start recording locally", "obs_start_recording", {}, {"ok": True, "recording": {"active": True}}, "local OBS recording started.", 37))
    add(sample("stop recording", "obs_stop_recording", {}, {"ok": True, "recording": {"active": False}}, "recording stopped.", 38))
    add(sample("turn on the OBS virtual camera", "obs_start_virtual_camera", {}, {"ok": True, "virtual_camera": {"active": True}}, "OBS Virtual Camera is on.", 39))
    add(sample("turn off the virtual camera", "obs_stop_virtual_camera", {}, {"ok": True, "virtual_camera": {"active": False}}, "OBS Virtual Camera is off.", 40))
    add(sample("turn on my camera in Discord", "obs_start_discord_camera", {}, {"ok": True, "virtual_camera": {"active": True}, "discord_camera": {"active": True}}, "my OBS camera is now active in Discord.", 41))
    add(sample("stop sharing the Discord camera", "obs_stop_discord_camera", {}, {"ok": True, "virtual_camera": {"active": False}, "discord_camera": {"active": False}}, "the Discord camera is off.", 42))
    return rows


def additional_examples() -> list[dict[str, Any]]:
    """Add two differently worded examples for every current tool."""

    cases: dict[str, list[tuple[str, dict[str, Any], dict[str, Any], str]]] = {
        "spotify_play": [
            ("start music", {}, {"ok": True, "playing": True}, "resuming the current Spotify context."),
            ("play the track Bad Habit by Steve Lacy", {"query": "Bad Habit by Steve Lacy"}, {"ok": True, "playing": True, "track": {"title": "Bad Habit", "artists": ["Steve Lacy"]}}, "Bad Habit is playing."),
        ],
        "spotify_play_artist": [
            ("put on an artist radio for YOASOBI", {"artist": "YOASOBI"}, {"ok": True, "playing": True, "context": {"artist": "YOASOBI"}}, "starting a YOASOBI mix."),
            ("play music from https://open.spotify.com/artist/example", {"artist": "https://open.spotify.com/artist/example"}, {"ok": True, "playing": True}, "starting that artist profile."),
        ],
        "spotify_pause": [
            ("hold the current song", {}, {"ok": True, "is_playing": False}, "holding the track."),
            ("stop the music for a second", {}, {"ok": True, "is_playing": False}, "music paused."),
        ],
        "spotify_resume": [
            ("continue the song", {}, {"ok": True, "is_playing": True}, "continuing playback."),
            ("unpause Spotify", {}, {"ok": True, "is_playing": True}, "Spotify is playing again."),
        ],
        "spotify_next": [
            ("next track please", {}, {"ok": True, "skipped": True}, "next track coming up."),
            ("skip this song", {}, {"ok": True, "skipped": True}, "skipped."),
        ],
        "spotify_previous": [
            ("play the previous track", {}, {"ok": True, "previous": True}, "back to the previous track."),
            ("one song back please", {}, {"ok": True, "previous": True}, "going one song back."),
        ],
        "spotify_set_volume": [
            ("make Spotify quiet at 15", {"volume": 15}, {"ok": True, "volume": 15}, "volume is 15 percent."),
            ("set music volume to 80 percent", {"volume": 80}, {"ok": True, "volume": 80}, "volume set to 80 percent."),
        ],
        "spotify_adjust_volume": [
            ("make it a little louder", {"delta": 5}, {"ok": True, "volume": 55, "delta": 5}, "raised the volume by 5."),
            ("turn it down ten points", {"delta": -10}, {"ok": True, "volume": 45, "delta": -10}, "lowered it by 10."),
        ],
        "spotify_queue": [
            ("add Resonance by Home to the queue", {"query": "Resonance by Home"}, {"ok": True, "queued": True, "track": {"title": "Resonance", "artists": ["Home"]}}, "queued Resonance."),
            ("queue something by Paramore", {"query": "Paramore"}, {"ok": True, "queued": True, "query": "Paramore"}, "added Paramore to the queue."),
        ],
        "spotify_set_shuffle": [
            ("shuffle my music", {"enabled": True}, {"ok": True, "shuffle": True}, "shuffle enabled."),
            ("play the queue in order", {"enabled": False}, {"ok": True, "shuffle": False}, "shuffle disabled."),
        ],
        "spotify_set_repeat": [
            ("loop the current track", {"mode": "track"}, {"ok": True, "repeat": "track"}, "looping this track."),
            ("repeat the playlist", {"mode": "context"}, {"ok": True, "repeat": "context"}, "repeating the current context."),
        ],
        "spotify_toggle": [
            ("switch playback state", {}, {"ok": True, "is_playing": True}, "toggled playback."),
            ("pause or resume Spotify", {}, {"ok": True, "is_playing": False}, "toggled Spotify playback."),
        ],
        "spotify_play_favorites": [
            ("play my liked songs", {"count": 10, "shuffle": True}, {"ok": True, "playing": True, "selected_count": 10, "source": "liked_songs"}, "playing a shuffled set from your Liked Songs."),
            ("put on five saved tracks", {"count": 5, "shuffle": True}, {"ok": True, "playing": True, "selected_count": 5, "source": "liked_songs"}, "five saved tracks are playing."),
        ],
        "spotify_current_track": [
            ("tell me the exact current track", {}, {"ok": True, "is_playing": True, "track": {"title": "Shelter", "artists": ["Porter Robinson"]}}, "it is Shelter by Porter Robinson."),
            ("which song is on right now", {}, {"ok": True, "is_playing": True, "track": {"title": "After Dark", "artists": ["Mr.Kitty"]}}, "After Dark by Mr.Kitty is playing."),
        ],
        "spotify_status": [
            ("show my Spotify status", {}, {"ok": True, "is_playing": False, "track": None}, "Spotify is currently paused."),
            ("is music playing", {}, {"ok": True, "is_playing": True, "track": {"title": "Shelter", "artists": ["Porter Robinson"]}}, "yes, Shelter is playing."),
        ],
        "discord_voice_status": [
            ("check the Discord call status", {}, {"ok": True, "bridge_connected": True, "voice_state": {"connected": False}}, "the Discord bridge is connected but not in voice."),
            ("are you connected to my voice channel", {}, {"ok": True, "bridge_connected": True, "voice_state": {"connected": True}}, "yes, I am connected to the voice channel."),
        ],
        "discord_send_message": [
            ("tell Discord that I will be late", {"content": "I will be late."}, {"ok": True, "sent": True, "content": "I will be late."}, "sent that message."),
            ("post 'good game everyone' to Discord", {"content": "good game everyone"}, {"ok": True, "sent": True, "content": "good game everyone"}, "posted it to Discord."),
        ],
        "discord_set_auto_reply": [
            ("enable replies to every Discord message", {"enabled": True}, {"ok": True, "auto_reply": True}, "automatic Discord replies are on."),
            ("disable automatic Discord responses", {"enabled": False}, {"ok": True, "auto_reply": False}, "automatic Discord responses are off."),
        ],
        "discord_join_voice": [
            ("join voice with me", {}, {"ok": True, "joined": True}, "joining your voice channel."),
            ("connect to the configured Discord call", {}, {"ok": True, "joined": True}, "connected to the Discord call."),
        ],
        "discord_leave_voice": [
            ("disconnect from voice", {}, {"ok": True, "left": True}, "leaving voice."),
            ("get out of the Discord call", {}, {"ok": True, "left": True}, "I left the call."),
        ],
        "discord_set_mute": [
            ("silence your own Discord mic", {"enabled": True}, {"ok": True, "self_mute": True}, "my own Discord mic is muted."),
            ("turn your Discord microphone back on", {"enabled": False}, {"ok": True, "self_mute": False}, "my Discord mic is back on."),
        ],
        "discord_set_deafen": [
            ("deafen your own Discord client", {"enabled": True}, {"ok": True, "self_deaf": True}, "I deafened myself."),
            ("listen to the call again", {"enabled": False}, {"ok": True, "self_deaf": False}, "I am listening again."),
        ],
        "discord_speak_voice": [
            ("say 'hello from Neuro' in voice", {"text": "Hello from Neuro."}, {"ok": True, "spoken_text": "Hello from Neuro."}, "said it in the voice call."),
            ("announce that the stream starts now", {"text": "The stream starts now."}, {"ok": True, "spoken_text": "The stream starts now."}, "announced it in voice."),
        ],
        "obs_get_status": [
            ("is the OBS camera running", {}, {"ok": True, "virtual_camera": {"active": True}, "discord_camera": {"active": False}}, "the OBS Virtual Camera is running."),
            ("check stream and recording state", {}, {"ok": True, "stream": {"active": True}, "recording": {"active": True}}, "OBS is streaming and recording."),
        ],
        "obs_set_scene": [
            ("change OBS to Just Chatting", {"scene": "Just Chatting"}, {"ok": True, "current_scene": "Just Chatting"}, "switched OBS to Just Chatting."),
            ("use the BRB scene in OBS", {"scene": "BRB"}, {"ok": True, "current_scene": "BRB"}, "OBS is now on BRB."),
        ],
        "obs_start_stream": [
            ("go live through OBS", {}, {"ok": True, "stream": {"active": True}}, "OBS is live."),
            ("start broadcasting", {}, {"ok": True, "stream": {"active": True}}, "broadcasting started."),
        ],
        "obs_stop_stream": [
            ("end the livestream", {}, {"ok": True, "stream": {"active": False}}, "the livestream is offline."),
            ("take the stream offline", {}, {"ok": True, "stream": {"active": False}}, "stream stopped."),
        ],
        "obs_start_recording": [
            ("record this session in OBS", {}, {"ok": True, "recording": {"active": True}}, "recording started."),
            ("begin local recording", {}, {"ok": True, "recording": {"active": True}}, "OBS is recording locally."),
        ],
        "obs_stop_recording": [
            ("finish the local recording", {}, {"ok": True, "recording": {"active": False}}, "recording finished."),
            ("stop recording in OBS now", {}, {"ok": True, "recording": {"active": False}}, "OBS recording stopped."),
        ],
        "obs_start_virtual_camera": [
            ("enable the OBS camera", {}, {"ok": True, "virtual_camera": {"active": True}}, "OBS Virtual Camera is enabled."),
            ("start virtual cam", {}, {"ok": True, "virtual_camera": {"active": True}}, "virtual camera started."),
        ],
        "obs_stop_virtual_camera": [
            ("disable OBS Virtual Camera", {}, {"ok": True, "virtual_camera": {"active": False}}, "virtual camera disabled."),
            ("stop the virtual cam", {}, {"ok": True, "virtual_camera": {"active": False}}, "virtual camera stopped."),
        ],
        "obs_start_discord_camera": [
            ("show your camera in the Discord call", {}, {"ok": True, "discord_camera": {"active": True}}, "my camera is on in Discord."),
            ("enable Discord video through OBS", {}, {"ok": True, "discord_camera": {"active": True}}, "Discord video is enabled."),
        ],
        "obs_stop_discord_camera": [
            ("hide your camera from Discord", {}, {"ok": True, "discord_camera": {"active": False}}, "my Discord camera is off."),
            ("stop Discord video", {}, {"ok": True, "discord_camera": {"active": False}}, "Discord video stopped."),
        ],
    }
    rows: list[dict[str, Any]] = []
    index = 100
    for tool, tool_cases in cases.items():
        for user, arguments, result, reply in tool_cases:
            rows.append(sample(user, tool, arguments, result, reply, index))
            index += 1
    return rows


def row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def main() -> None:
    original_rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    migrated_rows: list[dict[str, Any]] = []
    dropped = 0
    migrated = 0
    for original in original_rows:
        row = json.loads(json.dumps(original, ensure_ascii=False))
        had_tool_call = any(message.get("tool_calls") for message in row.get("messages", []))
        converted = migrate_row(row)
        if converted is None:
            if had_tool_call:
                dropped += 1
            continue
        if had_tool_call:
            migrated += 1
        migrated_rows.append(converted)

    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    generated = [*examples(), *additional_examples()]
    for row in [*migrated_rows, *generated]:
        digest = row_hash(row)
        if digest not in seen:
            seen.add(digest)
            output.append(row)
    TEMP_DATASET.write_text("\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in output) + "\n", encoding="utf-8")
    TEMP_DATASET.replace(DATASET)
    print(f"rows_before={len(original_rows)} rows_after={len(output)} migrated_tool_rows={migrated} dropped_unsupported_tool_rows={dropped} added_samples={len(generated)} current_tools={len(TOOL_NAMES)}")


if __name__ == "__main__":
    main()
