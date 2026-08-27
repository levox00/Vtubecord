from app.character.prompt import _sanitize_history_content
from app.llm.base import ChatMessage
from app.llm.openai_compatible import (
    _clean_generated_content,
    _default_stop_sequences,
)


def test_minitron_uses_its_role_boundary_as_a_stop_sequence():
    assert _default_stop_sequences("Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M") == [
        "<extra_id_1>",
        "<extra_id_0>",
        "</s>",
    ]


def test_other_models_keep_server_default_stops():
    assert _default_stop_sequences("Qwen2.5-14B-Instruct-Q4_K_M") is None


def test_minitron_role_markers_are_not_shown_to_the_user():
    generated = "Hello!\n<extra_id_1>User\nWhat is next?\n<extra_id_1>Answer\n"
    assert _clean_generated_content(generated, "Mistral-NeMo-Minitron-8B-Instruct") == "Hello!"


def test_non_minitron_content_is_unchanged():
    generated = "A normal answer with <extra_id_1> as literal text."
    assert _clean_generated_content(generated, "Qwen2.5-14B-Instruct") == generated


def test_leaked_role_continuations_are_removed_from_reused_history():
    message = ChatMessage(
        role="assistant",
        content="The actual answer.<extra_id_1>User\nfake next turn<extra_id_1>Assistant\nfake reply",
    )
    assert _sanitize_history_content(message) == "The actual answer."
