from app.character.prompt import build_messages
from app.character.state import CharacterState
from app.llm.base import ChatMessage


def test_identity_prompt_treats_profile_as_knowledge_not_a_canned_answer():
    prompt = build_messages(
        CharacterState(
            name="Neuro Sama",
            description="A playful digital companion.",
            backstory="She woke up inside a computer.",
        ),
        [ChatMessage(role="user", content="Who are you?")],
    )[0].content

    assert "source knowledge, not a scripted answer" in prompt
    assert "natural, fresh wording" in prompt
    assert "do not recite the whole profile" in prompt


def test_prompt_warns_against_verbatim_replies_when_history_exists():
    prompt = build_messages(
        CharacterState(name="Neuro Sama"),
        [
            ChatMessage(role="user", content="Who are you?"),
            ChatMessage(role="assistant", content="I am Neuro Sama, a digital character."),
            ChatMessage(role="user", content="Tell me who you are again."),
        ],
    )[0].content

    assert "Do not repeat their exact wording" in prompt


def test_voice_channel_id_context_is_not_sent_to_the_model():
    messages = build_messages(
        CharacterState(name="Neuro Sama"),
        [
            ChatMessage(
                role="user",
                content="[Discord voice participant | channel_id=1522327446572110006]\nwhat is playing?",
            )
        ],
    )
    assert "1522327446572110006" not in messages[-1].content
    assert messages[-1].content == "what is playing?"


def test_old_voice_metadata_is_removed_from_assistant_history():
    messages = build_messages(
        CharacterState(name="Neuro Sama"),
        [
            ChatMessage(role="user", content="next song"),
            ChatMessage(
                role="assistant",
                content="Skipped to a track.\n[Discord voice participant | channel_id=1522327446572110006]",
            ),
            ChatMessage(role="user", content="what is playing now?"),
        ],
    )
    assert "1522327446572110006" not in messages[0].content
    assert "1522327446572110006" not in messages[2].content
