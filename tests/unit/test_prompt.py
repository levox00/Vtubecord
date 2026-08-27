"""Unit tests for dynamic prompt construction."""

from datetime import datetime, timezone

from app.character.prompt import build_system_prompt
from app.character.state import CharacterState, EmotionSnapshot, PersonalitySnapshot


def make_state() -> CharacterState:
    return CharacterState(
        id="test-id",
        name="Aiko",
        description="A curious AI companion",
        response_style="Professional",
        style_modifiers=["Detailed"],
        style_guidance="Explain trade-offs clearly.",
        traits=["analytical"],
        dere_types=["kuudere"],
        behavior_rules="Respect boundaries.",
        custom_instructions="Use short section headings when useful.",
        backstory="She woke up inside a computer.",
        core_values=["curiosity", "friendship"],
        immutable_traits=["Never pretends to be human"],
        personality=PersonalitySnapshot(
            traits={"playfulness": 0.85, "curiosity": 0.92},
            descriptions={"playfulness": "Enjoys jokes"},
        ),
        emotion=EmotionSnapshot(happiness=0.7, curiosity=0.8),
        created_at=datetime.now(timezone.utc),
    )


def test_identity_included():
    state = make_state()
    prompt = build_system_prompt(state)
    assert "Aiko" in prompt
    assert "Never pretends to be human" in prompt
    assert "curiosity" in prompt.lower()


def test_personality_included():
    state = make_state()
    prompt = build_system_prompt(state)
    assert "playfulness: 0.85" in prompt
    assert "curiosity: 0.92" in prompt


def test_profile_guidance_included():
    prompt = build_system_prompt(make_state())
    assert "Communication style: Professional" in prompt
    assert "Style modifiers: Detailed" in prompt
    assert "analytical" in prompt
    assert "kuudere" in prompt
    assert "Respect boundaries." in prompt
    assert "Use short section headings" in prompt


def test_emotion_included():
    state = make_state()
    prompt = build_system_prompt(state)
    assert "happiness: 0.70" in prompt or "happiness: 0.7" in prompt
    assert "Dominant emotion" in prompt


def test_memories_appended():
    state = make_state()
    prompt = build_system_prompt(
        state, extra_memories=["User likes Minecraft", "User dislikes horror"]
    )
    assert "User likes Minecraft" in prompt
    assert "Relevant memories" in prompt


def test_goals_appended():
    state = make_state()
    prompt = build_system_prompt(state, current_goals=["Improve combat"])
    assert "Improve combat" in prompt
    assert "Current goals" in prompt
