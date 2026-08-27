from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent.voice_brain import parse_brain_decision
from app.character.prompt import build_messages
from app.character.state import CharacterState
from app.llm.base import ChatMessage
from app.memory.context import estimate_tokens, memory_relevance_score, pack_recent_messages
from app.models.character import Memory, Message


def test_brain_decision_accepts_fenced_json_and_clamps_values():
    decision = parse_brain_decision(
        """```json
        {"action":"START_TOPIC","reason":"unfinished thread","topic":"the build",
         "confidence":1.4,"next_wake_seconds":2,"capability":"","arguments":{}}
        ```"""
    )

    assert decision.action == "START_TOPIC"
    assert decision.topic == "the build"
    assert decision.confidence == 1.0
    assert decision.next_wake_seconds == 10.0


def test_invalid_brain_output_fails_closed_to_wait():
    decision = parse_brain_decision("I think I should interrupt now")
    assert decision.action == "WAIT"
    assert decision.confidence == 0.0


def test_memory_retrieval_prefers_relevant_and_pinned_context():
    now = datetime.now(timezone.utc)
    relevant = Memory(
        character_id="character",
        memory_type="semantic",
        content="The user is building a redstone farm in Minecraft",
        importance=0.7,
        pinned=False,
        tags=["minecraft"],
        created_at=now - timedelta(days=2),
    )
    unrelated = Memory(
        character_id="character",
        memory_type="semantic",
        content="The user once ordered green tea",
        importance=0.7,
        pinned=False,
        tags=["drink"],
        created_at=now - timedelta(days=2),
    )
    pinned = Memory(
        character_id="character",
        memory_type="relationship",
        content="Never spoil story games for the user",
        importance=0.9,
        pinned=True,
        tags=["boundary"],
        created_at=now - timedelta(days=90),
    )

    query = "Should I ask about the Minecraft redstone build?"
    assert memory_relevance_score(relevant, query, now=now) > memory_relevance_score(unrelated, query, now=now)
    assert memory_relevance_score(pinned, query, now=now) > memory_relevance_score(unrelated, query, now=now)


def test_history_packer_preserves_the_newest_turn_under_budget():
    rows = [
        Message(conversation_id="conversation", role="user", content="old " * 500),
        Message(conversation_id="conversation", role="assistant", content="middle " * 200),
        Message(conversation_id="conversation", role="user", content="the newest request"),
    ]
    packed = pack_recent_messages(rows, 80)
    assert packed[-1].content == "the newest request"
    assert estimate_tokens("the newest request") > 0
    assert len(packed) < len(rows)


def test_autonomous_prompt_preserves_last_assistant_then_adds_neutral_nudge():
    state = CharacterState(id="character", name="Aiko")
    messages = build_messages(
        state,
        [
            ChatMessage(role="user", content="I am building a castle."),
            ChatMessage(role="assistant", content="That sounds ambitious."),
        ],
        agent_instruction="Follow up naturally about the castle.",
        conversation_summary="The user started a castle build.",
    )

    assert messages[-2].role == "assistant"
    assert messages[-2].content == "That sounds ambitious."
    assert messages[-1].role == "user"
    assert "live voice interaction" in messages[-1].content
    assert "Executive voice-director instruction" in messages[0].content
