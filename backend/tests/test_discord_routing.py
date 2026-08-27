from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.api import discord_bridge
from app.core.config import settings
from app.tools import create_tool_registry
from app.tools import discord as discord_tools


def _policy(**overrides):
    values = {
        "enabled": True,
        "server_id": "",
        "channel_id": "",
        "channel_mode": "all",
        "channel_list": [],
        "allowed_user_ids": [],
        "command_prefix": "ai!",
        "auto_reply": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_prefix_is_optional_but_enforced_when_configured():
    prefixed = _policy(command_prefix="ai!")
    assert discord_bridge._prompt_from_discord_message(prefixed, "ai! hello there") == "hello there"
    assert discord_bridge._prompt_from_discord_message(prefixed, "AI! join the call") == "join the call"
    assert discord_bridge._prompt_from_discord_message(prefixed, "   ai! hello") == "hello"
    assert discord_bridge._prompt_from_discord_message(prefixed, "hello there") is None

    invisible_spaces = _policy(command_prefix="   ")
    assert discord_bridge._prompt_from_discord_message(invisible_spaces, "hello there") == "hello there"

    no_prefix = _policy(command_prefix="")
    assert discord_bridge._prompt_from_discord_message(no_prefix, "hello there") == "hello there"
    assert discord_bridge._prompt_from_discord_message(
        _policy(command_prefix="", auto_reply=False),
        "hello there",
    ) is None


def test_every_message_toggle_is_separate_from_command_prefix_mode():
    prompt, status, _detail = discord_bridge._route_discord_prompt(
        _policy(command_prefix="", auto_reply=True, respond_to_every_message=False),
        "hello there",
    )
    assert prompt is None
    assert status == "prefix_disabled"

    prompt, status, _detail = discord_bridge._route_discord_prompt(
        _policy(command_prefix="ai!", auto_reply=False, respond_to_every_message=True),
        "hello there",
    )
    assert prompt == "hello there"
    assert status == "accepted"


def test_routing_decision_explains_why_a_message_was_not_answered():
    prompt, status, detail = discord_bridge._route_discord_prompt(
        _policy(command_prefix="ai!"),
        "hello there",
    )
    assert prompt is None
    assert status == "needs_prefix"
    assert "ai!" in detail

    prompt, status, _detail = discord_bridge._route_discord_prompt(
        _policy(command_prefix=""),
        "hello there",
    )
    assert prompt == "hello there"
    assert status == "accepted"


def test_empty_channel_and_user_lists_mean_everyone_everywhere():
    allowlist = _policy(channel_mode="allowlist", channel_list=[])
    assert discord_bridge._channel_is_eligible(allowlist, "channel-2", None) is True
    assert discord_bridge._author_is_eligible(allowlist, "user-2") is True

    restricted = _policy(
        channel_mode="allowlist",
        channel_list=["channel-1"],
        allowed_user_ids=["user-1"],
    )
    assert discord_bridge._channel_is_eligible(restricted, "channel-1", None) is True
    assert discord_bridge._channel_is_eligible(restricted, "channel-2", None) is False
    assert discord_bridge._author_is_eligible(restricted, "user-1") is True
    assert discord_bridge._author_is_eligible(restricted, "user-2") is False


def test_discord_long_messages_are_split_below_the_platform_limit():
    chunks = discord_bridge._split_discord_content("word " * 1000, limit=200)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ").strip() == ("word " * 1000).strip()


def test_equicord_reply_uses_the_compatible_send_payload(monkeypatch):
    asyncio.run(_test_equicord_reply_uses_the_compatible_send_payload(monkeypatch))


async def _test_equicord_reply_uses_the_compatible_send_payload(monkeypatch):
    calls = []

    async def fake_send(action, payload, timeout=10.0):
        calls.append((action, payload, timeout))
        return {"ok": True}

    monkeypatch.setattr(discord_bridge, "_send_command", fake_send)
    result = await discord_bridge.send_discord_text(
        "hello",
        channel_id="channel-1",
        reply_to="message-1",
        transport="client",
    )
    assert result["ok"] is True
    assert calls[0][0] == "send_message"
    assert calls[0][1] == {"channel_id": "channel-1", "content": "hello"}


def test_client_echo_of_mirrored_message_is_not_routed_back_to_ai(monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("outgoing bridge echo reached the AI")

    async def test_echo():
        discord_bridge._recent_outgoing_client_messages.clear()
        discord_bridge._remember_outgoing_client_message("channel-1", "Whispered transcript")
        monkeypatch.setattr(discord_bridge, "_respond_to_discord_message", fail_if_called)
        await discord_bridge._on_message_create(
            {
                "id": "echo-message-1",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "content": "  Whispered   transcript ",
                # Some plugin builds omit self/author metadata.
                "author": {},
            },
            transport="client",
        )

    asyncio.run(test_echo())


def test_short_voice_fragments_are_merged_before_queueing(monkeypatch):
    async def test_merge():
        from app.discord_voice import VoiceTranscript

        received = []

        async def fake_queue(transcript):
            received.append(transcript)

        monkeypatch.setattr(discord_bridge, "_queue_discord_voice_transcript", fake_queue)
        discord_bridge._voice_merge_buffers.clear()
        discord_bridge._voice_merge_tasks.clear()
        await discord_bridge._on_discord_voice_transcript(
            VoiceTranscript(channel_id="voice-1", text="He..."),
        )
        assert received == []
        await discord_bridge._on_discord_voice_transcript(
            VoiceTranscript(channel_id="voice-1", text="How are you?"),
        )
        assert [item.text for item in received] == ["He... How are you?"]

    asyncio.run(test_merge())


def test_bridge_message_processing_does_not_block_command_responses(monkeypatch):
    asyncio.run(_test_bridge_message_processing_does_not_block_command_responses(monkeypatch))


async def _test_bridge_message_processing_does_not_block_command_responses(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_message(_payload, *, transport):
        assert transport == "client"
        started.set()
        await release.wait()

    monkeypatch.setattr(discord_bridge, "_on_message_create", slow_message)
    await discord_bridge._handle_discord_event("message_create", {"id": "message-1"})
    await asyncio.wait_for(started.wait(), timeout=1)
    assert any(not task.done() for task in discord_bridge._event_tasks)
    release.set()
    await asyncio.gather(*list(discord_bridge._event_tasks))


def test_client_typing_indicator_starts_immediately_and_stops_with_generation(monkeypatch):
    asyncio.run(_test_client_typing_indicator_starts_immediately_and_stops_with_generation(monkeypatch))


async def _test_client_typing_indicator_starts_immediately_and_stops_with_generation(monkeypatch):
    monkeypatch.setattr(settings.integrations.discord, "typing_indicator", True)
    monkeypatch.setattr(discord_bridge, "_active_connections", [object()])
    calls = []
    started = asyncio.Event()

    async def fake_send(action, payload, timeout=10.0):
        calls.append((action, payload, timeout))
        started.set()
        return {"ok": True}

    monkeypatch.setattr(discord_bridge, "_send_command", fake_send)
    async with discord_bridge._discord_typing_indicator("channel-typing", "client"):
        await asyncio.wait_for(started.wait(), timeout=1)
        assert calls == [("typing", {"channel_id": "channel-typing"}, 3.0)]
        assert any(task.get_name() == "discord-typing-channel-typing" for task in asyncio.all_tasks())

    assert not any(task.get_name() == "discord-typing-channel-typing" for task in asyncio.all_tasks())


def test_typing_indicator_can_be_disabled(monkeypatch):
    asyncio.run(_test_typing_indicator_can_be_disabled(monkeypatch))


async def _test_typing_indicator_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings.integrations.discord, "typing_indicator", False)

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("typing command should not be sent while disabled")

    monkeypatch.setattr(discord_bridge, "_send_command", fail_if_called)
    async with discord_bridge._discord_typing_indicator("channel-typing", "client"):
        await asyncio.sleep(0)


def test_bot_typing_indicator_uses_discord_worker(monkeypatch):
    asyncio.run(_test_bot_typing_indicator_uses_discord_worker(monkeypatch))


async def _test_bot_typing_indicator_uses_discord_worker(monkeypatch):
    from app.integrations import discord_worker

    channels = []

    async def fake_typing(channel_id):
        channels.append(channel_id)
        return {"ok": True, "channel_id": channel_id}

    monkeypatch.setattr(discord_worker, "send_typing", fake_typing)
    result = await discord_bridge._send_discord_typing_once("bot-channel", "bot")
    assert result["ok"] is True
    assert channels == ["bot-channel"]


def test_eligible_prefixed_message_reaches_the_ai_pipeline(monkeypatch):
    asyncio.run(_test_eligible_prefixed_message_reaches_the_ai_pipeline(monkeypatch))


async def _test_eligible_prefixed_message_reaches_the_ai_pipeline(monkeypatch):
    discord = settings.integrations.discord
    monkeypatch.setattr(discord, "enabled", True)
    monkeypatch.setattr(discord, "server_id", "guild-1")
    monkeypatch.setattr(discord, "channel_mode", "all")
    monkeypatch.setattr(discord, "channel_list", [])
    monkeypatch.setattr(discord, "allowed_user_ids", ["user-1"])
    monkeypatch.setattr(discord, "bridge_user_id", "bridge-user")
    monkeypatch.setattr(discord, "command_prefix", "ai!")
    monkeypatch.setattr(discord, "auto_reply", True)

    routed = []
    recorded = []

    async def fake_respond(content, channel_id, message_id, guild_id, **kwargs):
        routed.append((content, channel_id, message_id, guild_id, kwargs["transport"]))

    async def fake_record(_message, *, routing_status, routing_detail):
        recorded.append((routing_status, routing_detail))

    monkeypatch.setattr(discord_bridge, "_respond_to_discord_message", fake_respond)
    monkeypatch.setattr(discord_bridge, "_record_incoming_message", fake_record)
    await discord_bridge._on_message_create(
        {
            "id": "routing-message-unique-1",
            "guild_id": "guild-1",
            "channel_id": "channel-1",
            "content": "ai! hello there",
            "author": {"id": "user-1", "username": "tester"},
        },
        transport="client",
    )

    assert routed == [("hello there", "channel-1", "routing-message-unique-1", "guild-1", "client")]
    assert recorded[0][0] == "accepted"


def test_ai_join_uses_verified_bridge_path_and_enables_live_join(monkeypatch):
    asyncio.run(_test_ai_join_uses_verified_bridge_path_and_enables_live_join(monkeypatch))


async def _test_ai_join_uses_verified_bridge_path_and_enables_live_join(monkeypatch):
    discord = settings.integrations.discord
    monkeypatch.setattr(discord, "enabled", True)
    monkeypatch.setattr(discord, "mode", "client")
    monkeypatch.setattr(discord, "voice_channel_id", "voice-1")
    monkeypatch.setattr(discord, "live_join_enabled", False)
    monkeypatch.setattr(discord_tools, "save_config", lambda _settings: None)
    monkeypatch.setattr(discord_bridge, "_active_connections", [object()])

    calls = []

    async def fake_join(channel_id):
        calls.append(("join", channel_id))
        return {"ok": True, "verified": True}

    def fake_guard(channel_id):
        calls.append(("guard", channel_id))

    monkeypatch.setattr(discord_bridge, "join_voice_verified", fake_join)
    monkeypatch.setattr(discord_bridge, "schedule_voice_join_guard", fake_guard)

    result = await discord_tools._join({})
    assert result["joined"] is True
    assert discord.live_join_enabled is True
    assert calls == [("join", "voice-1"), ("guard", "voice-1")]


def test_discord_registry_exposes_text_and_voice_actions(monkeypatch):
    discord = settings.integrations.discord
    monkeypatch.setattr(discord, "enabled", True)
    # An explicit AI join request must be available even when Live Join is
    # currently off; the tool enables it just like the working UI button.
    monkeypatch.setattr(discord, "live_join_enabled", False)
    monkeypatch.setattr(discord, "voice_channel_id", "123")
    names = {spec.name for spec in create_tool_registry().available_specs()}
    assert {
        "discord_voice_status",
        "discord_send_message",
        "discord_set_auto_reply",
        "discord_join_voice",
        "discord_leave_voice",
        "discord_set_mute",
        "discord_set_deafen",
        "discord_speak_voice",
    } <= names


def test_discord_voice_speech_tool_uses_the_explicit_text(monkeypatch):
    asyncio.run(_test_discord_voice_speech_tool_uses_the_explicit_text(monkeypatch))


async def _test_discord_voice_speech_tool_uses_the_explicit_text(monkeypatch):
    spoken = []

    async def fake_speak(text):
        spoken.append(text)
        return {"ok": True, "channel_id": "voice-1", "confirmation": "played"}

    monkeypatch.setattr(discord_bridge, "speak_discord_voice", fake_speak)
    result = await discord_tools._speak_voice({"text": "Hello from the voice channel."})
    assert spoken == ["Hello from the voice channel."]
    assert result["ok"] is True
    assert result["spoken_text"] == "Hello from the voice channel."
    assert "current Discord voice call" in result["confirmation"]


def test_self_voice_state_requires_a_call_and_verifies_the_requested_flag(monkeypatch):
    asyncio.run(_test_self_voice_state_requires_a_call_and_verifies_the_requested_flag(monkeypatch))


async def _test_self_voice_state_requires_a_call_and_verifies_the_requested_flag(monkeypatch):
    monkeypatch.setattr(discord_bridge, "_active_connections", [object()])
    states = [
        {"ok": True, "connected": True, "channel_id": "voice-1", "self_mute": False, "self_deaf": False},
        {"ok": True, "connected": True, "channel_id": "voice-1", "self_mute": True, "self_deaf": False},
    ]

    async def fake_state():
        return states.pop(0) if states else {
            "ok": True,
            "connected": True,
            "channel_id": "voice-1",
            "self_mute": True,
            "self_deaf": False,
        }

    calls = []

    async def fake_send(action, payload, timeout=10.0):
        calls.append((action, payload, timeout))
        return {"ok": True, "payload": {"accepted": True}}

    monkeypatch.setattr(discord_bridge, "current_voice_state", fake_state)
    monkeypatch.setattr(discord_bridge, "_send_command", fake_send)
    result = await discord_bridge.set_self_voice_state(mute=True)

    assert result["ok"] is True
    assert result["verified"] is True
    assert result["requested"] == {"mute": True}
    assert calls == [("set_voice_state", {"mute": True}, 10.0)]


def test_self_voice_state_supports_legacy_bridge_action(monkeypatch):
    asyncio.run(_test_self_voice_state_supports_legacy_bridge_action(monkeypatch))


async def _test_self_voice_state_supports_legacy_bridge_action(monkeypatch):
    monkeypatch.setattr(discord_bridge, "_active_connections", [object()])
    states = [
        {"ok": True, "connected": True, "channel_id": "voice-1", "self_mute": False, "self_deaf": False},
        {"ok": True, "connected": True, "channel_id": "voice-1", "self_mute": True, "self_deaf": False},
    ]

    async def fake_state():
        return states.pop(0) if states else {
            "ok": True,
            "connected": True,
            "channel_id": "voice-1",
            "self_mute": True,
            "self_deaf": False,
        }

    calls = []

    async def fake_send(action, payload, timeout=10.0):
        calls.append((action, payload))
        if action == "set_voice_state":
            return {"ok": False, "error": "Unknown action set_voice_state"}
        if action == "set_self_mute":
            return {"ok": False, "error": "Unknown action set_self_mute"}
        return {"ok": True}

    monkeypatch.setattr(discord_bridge, "current_voice_state", fake_state)
    monkeypatch.setattr(discord_bridge, "_send_command", fake_send)
    result = await discord_bridge.set_self_voice_state(mute=True)

    assert result["ok"] is True
    assert result["command"] == "set_mute"
    assert calls == [
        ("set_voice_state", {"mute": True}),
        ("set_self_mute", {"enabled": True}),
        ("set_mute", {"enabled": True}),
    ]


def test_self_voice_state_tool_rejects_non_boolean_arguments(monkeypatch):
    asyncio.run(_test_self_voice_state_tool_rejects_non_boolean_arguments(monkeypatch))


async def _test_self_voice_state_tool_rejects_non_boolean_arguments(monkeypatch):
    try:
        await discord_tools._set_mute({"enabled": "yes"})
    except Exception as exc:
        assert "muted or unmuted" in str(exc)
    else:
        raise AssertionError("non-boolean mute state should be rejected")


def test_discord_voice_parser_only_accepts_self_controls():
    assert discord_tools.parse_discord_voice_command("say I like femboys in the call") is None
    assert discord_tools.parse_discord_voice_command("say hi in voice") is None


def test_discord_voice_tts_drops_internal_channel_metadata():
    spoken = discord_bridge._sanitize_discord_voice_tts_text(
        "Playing your song in the Discord channel ID 1522327446572110006.",
        "1522327446572110006",
    )
    assert "1522327446572110006" not in spoken
    assert "current voice call" in spoken
    assert "1522327446572110006" not in discord_bridge._sanitize_discord_voice_tts_text(
        "The Discord channel ID is 1522327446572110006.",
        "1522327446572110006",
    )
    assert discord_tools.parse_discord_voice_command("say I like femboys") is None
    assert discord_tools.parse_discord_voice_command("please mute yourself") == (
        "discord_set_mute",
        {"enabled": True},
    )
    assert discord_tools.parse_discord_voice_command("could you please mute yourself") == (
        "discord_set_mute",
        {"enabled": True},
    )
    assert discord_tools.parse_discord_voice_command("turn your microphone back on") == (
        "discord_set_mute",
        {"enabled": False},
    )
    assert discord_tools.parse_discord_voice_command("could you deafen your own client?") == (
        "discord_set_deafen",
        {"enabled": True},
    )
    assert discord_tools.parse_discord_voice_command("undeafen yourself") == (
        "discord_set_deafen",
        {"enabled": False},
    )
    assert discord_tools.parse_discord_voice_command("mute Niklas") is None
