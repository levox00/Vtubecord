from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.llm.base import ChatMessage, LLMProvider, ToolCall
from app.tools.registry import ToolRegistry

NO_ACTION_TOOL = "no_external_action"


@dataclass(frozen=True)
class ToolRoute:
    """Result of the side-effect-free semantic routing pass."""

    status: Literal["skipped", "selected", "none", "failed"]
    call: ToolCall | None = None
    model: str | None = None


async def route_tool_request(
    llm: LLMProvider,
    user_text: str,
    registry: ToolRegistry,
) -> ToolRoute:
    """Ask the active model to select one registered action without running it.

    The model receives real function schemas plus a no-action sentinel. This
    keeps semantic understanding in the LLM while execution remains in the
    validated registry. Newly registered integrations participate by adding
    their own ``ToolSpec`` and intent hints; this module has no provider or
    Spotify-specific branch.
    """

    if not registry.looks_actionable(user_text):
        return ToolRoute(status="skipped")

    candidates = registry.candidate_specs(user_text)
    if not candidates:
        candidates = registry.available_specs()
    if not candidates:
        return ToolRoute(status="skipped")

    definitions = [spec.openai_definition() for spec in candidates]
    definitions.append(
        {
            "type": "function",
            "function": {
                "name": NO_ACTION_TOOL,
                "description": (
                    "Choose this only when the user is chatting, asking a factual question, "
                    "discussing an action hypothetically, or has not directly requested any "
                    "available external action. This performs no action."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    )
    allowed_names = {spec.name for spec in candidates}
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You are the action router for an AI character. Inspect only the current user "
                "message and call exactly one supplied function. If the user directly asks to "
                "change or control an external service, choose the single best matching real "
                "tool and preserve names, titles, numbers, and other arguments from the user's "
                "words. If no listed external action was directly requested, call "
                f"{NO_ACTION_TOOL}. Do not answer the user and do not claim anything happened."
            ),
        ),
        ChatMessage(role="user", content=user_text),
    ]
    response = await llm.generate(
        messages,
        temperature=0.0,
        max_tokens=160,
        tools=definitions,
        tool_choice="required",
    )
    for call in response.tool_calls:
        if call.name == NO_ACTION_TOOL:
            return ToolRoute(status="none", model=response.model or llm.model_name)
        if call.name in allowed_names and registry.get(call.name) is not None:
            return ToolRoute(status="selected", call=call, model=response.model or llm.model_name)
    return ToolRoute(status="failed", model=response.model or llm.model_name)
