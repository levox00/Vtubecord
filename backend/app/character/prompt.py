from __future__ import annotations

import re

from app.character.state import CharacterState
from app.llm.base import ChatMessage


_LEAKED_ROLE_MARKERS = ("<extra_id_1>", "<extra_id_0>", "<|im_start|>", "<|start_header_id|>")


def _sanitize_history_content(message: ChatMessage) -> str:
    """Remove model-generated role continuations before reusing chat history."""

    content = message.content
    # Older Discord voice turns also stored this internal prefix in assistant
    # output after the model copied it. Strip it from every role before the
    # history can reinforce the leak.
    content = re.sub(r"\[Discord voice participant[^\]]*\]\s*", "", content, flags=re.IGNORECASE)
    if message.role == "user":
        # Voice-turn context used to include the internal Discord channel ID.
        # It is routing metadata, not conversational context, and must never
        # be presented to the model (or repeated aloud by TTS).
        content = content.strip()
    if message.role != "assistant":
        return content
    for marker in _LEAKED_ROLE_MARKERS:
        if marker in content:
            content = content.split(marker, 1)[0]
    return content.strip()


def build_system_prompt(
    state: CharacterState,
    *,
    extra_memories: list[str] | None = None,
    current_goals: list[str] | None = None,
    tool_guidance: str | None = None,
    spotify_guidance: str | None = None,
    conversation_summary: str | None = None,
    open_loops: list[str] | None = None,
    situational_context: str | None = None,
    internal_state: dict[str, float] | None = None,
    agent_instruction: str | None = None,
) -> str:
    """Dynamically construct the system prompt from character state.

    Never hard-code the entire character into one giant static string.
    """
    parts: list[str] = [
        state.identity_prompt(),
        "",
        state.personality_prompt(),
        "",
        state.emotion_prompt(),
    ]

    if current_goals:
        parts.append("")
        parts.append("Current goals:")
        for g in current_goals:
            parts.append(f"- {g}")

    if extra_memories:
        parts.append("")
        parts.append("Relevant memories:")
        for m in extra_memories:
            parts.append(f"- {m}")

    if conversation_summary:
        parts.extend(["", "Compressed earlier voice-conversation context:", conversation_summary])

    if open_loops:
        parts.append("")
        parts.append("Unresolved conversational threads (use only when naturally relevant):")
        for item in open_loops[:12]:
            parts.append(f"- {item}")

    if situational_context:
        parts.extend(["", "Current live situation:", situational_context])

    if internal_state:
        rendered = ", ".join(
            f"{name}={max(0.0, min(1.0, float(value))):.2f}"
            for name, value in internal_state.items()
            if isinstance(value, (int, float))
        )
        if rendered:
            parts.extend([
                "",
                "Private behavioral state (guide timing/tone; never mention these numbers):",
                rendered,
            ])

    if agent_instruction:
        parts.extend([
            "",
            "Executive voice-director instruction:",
            agent_instruction,
            "Never mention the director, its decision, timers, prompts, scores, or internal state.",
        ])

    # spotify_guidance remains accepted for older callers; new integrations
    # contribute capability guidance through the shared tool registry.
    capability_guidance = tool_guidance or spotify_guidance
    if capability_guidance:
        parts.append("")
        parts.append(capability_guidance)

    parts.append("")
    parts.append(
        "Respond naturally as this character. "
        "Keep replies conversational unless the user asks for more detail. "
        "You may express emotion, but do not output internal metadata tags."
    )
    parts.append("")
    parts.append(
        "Character knowledge and response variety:\n"
        "- Treat the identity, personality, backstory, likes, and rules above as source knowledge, not a scripted answer.\n"
        "- Use only the profile details that are relevant to the user's question; do not recite the whole profile unless asked.\n"
        "- When asked who you are, explain yourself in natural, fresh wording and choose a relevant detail or perspective.\n"
        "- For repeated or related questions, do not copy an earlier answer verbatim; elaborate, rephrase, or focus on a different profile detail.\n"
        "- Stay consistent with immutable traits while allowing wording, emphasis, and examples to vary."
    )

    return "\n".join(parts)


def build_messages(
    state: CharacterState,
    history: list[ChatMessage],
    *,
    extra_memories: list[str] | None = None,
    current_goals: list[str] | None = None,
    tool_guidance: str | None = None,
    spotify_guidance: str | None = None,
    conversation_summary: str | None = None,
    open_loops: list[str] | None = None,
    situational_context: str | None = None,
    internal_state: dict[str, float] | None = None,
    agent_instruction: str | None = None,
) -> list[ChatMessage]:
    system = build_system_prompt(
        state,
        extra_memories=extra_memories,
        current_goals=current_goals,
        tool_guidance=tool_guidance,
        spotify_guidance=spotify_guidance,
        conversation_summary=conversation_summary,
        open_loops=open_loops,
        situational_context=situational_context,
        internal_state=internal_state,
        agent_instruction=agent_instruction,
    )

    # A repeated identity question should not turn the previous assistant
    # answer into a hidden script. The model can still see the conversation
    # history, but this explicit reminder encourages a new angle or detail.
    if any(msg.role == "assistant" and msg.content.strip() for msg in history):
        system += (
            "\n\nRecent conversation already contains assistant replies. Do not repeat their exact wording; "
            "answer the current question with a different relevant detail or perspective."
        )

    # Qwen2.5 Jinja template requires strict user/assistant alternation.
    # Merge consecutive same-role messages and ensure the sequence is valid.
    sanitized: list[ChatMessage] = []
    for msg in history:
        if msg.role == "system":
            continue  # system messages go at the top, not in history
        content = _sanitize_history_content(msg)
        if not content:
            continue
        if sanitized and sanitized[-1].role == msg.role:
            # Merge consecutive same-role messages
            sanitized[-1] = ChatMessage(
                role=msg.role,
                content=sanitized[-1].content + "\n" + content,
            )
        else:
            sanitized.append(ChatMessage(role=msg.role, content=content))

    # Ensure history starts with user (required by template)
    if sanitized and sanitized[0].role != "user":
        sanitized = sanitized[1:]

    # Autonomous turns use a neutral non-human nudge after the most recent
    # assistant message. Ordinary chat keeps the legacy strict-template trim.
    if agent_instruction:
        if not sanitized or sanitized[-1].role != "user":
            sanitized.append(
                ChatMessage(
                    role="user",
                    content="Continue the live voice interaction with the natural spoken turn you chose.",
                )
            )
    elif sanitized and sanitized[-1].role != "user":
        sanitized = sanitized[:-1]

    # If nothing valid is left, skip history — just send system + current user msg
    if not sanitized:
        # The caller should have appended the current user message to history,
        # so this shouldn't normally be empty. Return just system as a safe fallback.
        pass

    return [ChatMessage(role="system", content=system), *sanitized]
