from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import ChatMessage, LLMProvider, LLMResponse, ToolCall
from app.tools.registry import ToolExecution, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ToolConversationResult:
    response: LLMResponse
    executions: list[ToolExecution] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)


async def run_tool_conversation(
    llm: LLMProvider,
    messages: list[ChatMessage],
    registry: ToolRegistry,
    *,
    max_rounds: int = 4,
    max_total_calls: int = 8,
    required_tool: str | None = None,
    required_arguments: dict[str, Any] | None = None,
    initial_call: ToolCall | None = None,
    initial_model: str | None = None,
) -> ToolConversationResult:
    """Run the complete LLM -> tool -> result -> LLM conversation loop."""

    definitions = registry.definitions()
    if not definitions:
        response = await llm.generate(messages)
        return ToolConversationResult(response=response, messages=list(messages))

    conversation = list(messages)
    executions: list[ToolExecution] = []
    per_tool_count: dict[str, int] = {}
    seen_calls: set[str] = set()

    required_definition = next(
        (
            definition
            for definition in definitions
            if str((definition.get("function") or {}).get("name") or "") == required_tool
        ),
        None,
    )
    if required_tool and required_definition is None:
        required_tool = None

    pending_initial_call = initial_call if initial_call and registry.get(initial_call.name) else None

    for _round in range(max(1, max_rounds)):
        must_call = required_tool if _round == 0 and not executions else None
        if pending_initial_call is not None and not executions:
            candidate = LLMResponse(
                content="",
                model=initial_model or llm.model_name,
                finish_reason="tool_calls",
                tool_calls=[pending_initial_call],
            )
            pending_initial_call = None
        else:
            round_definitions = [required_definition] if must_call and required_definition else definitions
            tool_choice: str | dict[str, object] = (
                {"type": "function", "function": {"name": must_call}}
                if must_call
                else "auto"
            )
            try:
                # Keep tool selection deterministic, but let the post-tool
                # character response use the configured sampling temperature.
                # A fixed 0.2 here made small local models reuse one stock
                # confirmation (for example, "Just enjoying the music with
                # you") after every Spotify action.
                generation_temperature = 0.0 if must_call else (0.2 if not executions else None)
                candidate = await llm.generate(
                    conversation,
                    temperature=generation_temperature,
                    tools=round_definitions,
                    tool_choice=tool_choice,
                )
            except Exception:
                # The external action may already have completed. Never retry
                # it merely because the model failed while wording the final
                # answer; return the observed tool confirmation instead.
                if executions:
                    fallback = _fallback_response(
                        LLMResponse(
                            content="",
                            model=initial_model or llm.model_name,
                            finish_reason="tool_result",
                        ),
                        executions,
                    )
                    return ToolConversationResult(
                        response=fallback,
                        executions=executions,
                        messages=conversation,
                    )
                raise
        if must_call:
            selected_call = next(
                (call for call in candidate.tool_calls if call.name == must_call),
                None,
            )
            # The agent/controller has already classified this explicit action
            # request. Small local models can ignore a forced native choice or
            # invent details in its arguments. Keep the real model call when it
            # chose the required function, but ground its arguments in the
            # user's parsed request. If it refused the call entirely, create the
            # required registered call so prose can never fake success.
            grounded_call = (
                selected_call.model_copy(update={"arguments": dict(required_arguments)})
                if selected_call is not None and required_arguments is not None
                else selected_call
            )
            if grounded_call is None:
                grounded_call = ToolCall(
                    id="call_controller_required_1",
                    name=must_call,
                    arguments=dict(required_arguments or {}),
                    source="controller",
                )
            candidate = candidate.model_copy(
                update={
                    "content": "",
                    "finish_reason": "tool_calls",
                    "tool_calls": [grounded_call],
                }
            )
        if not candidate.tool_calls:
            if executions and not candidate.content.strip():
                candidate = _fallback_response(candidate, executions)
            return ToolConversationResult(response=candidate, executions=executions, messages=conversation)

        conversation.append(
            ChatMessage(role="assistant", content=candidate.content, tool_calls=candidate.tool_calls)
        )
        for call in candidate.tool_calls:
            model_name = str(candidate.model or llm.model_name or "unknown-model")
            logger.info("Tool calling feature %s used by %s", call.name, model_name)
            spec = registry.get(call.name)
            fingerprint = json.dumps(
                {"name": call.name, "arguments": call.arguments},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if len(executions) >= max_total_calls:
                execution = ToolExecution(call=call, ok=False, error="Tool call limit reached for this turn.")
            elif fingerprint in seen_calls:
                execution = ToolExecution(call=call, ok=False, error="Duplicate tool call blocked.")
            elif spec is not None and per_tool_count.get(call.name, 0) >= spec.max_calls_per_turn:
                execution = ToolExecution(call=call, ok=False, error=f"{call.name} was already used this turn.")
            else:
                seen_calls.add(fingerprint)
                per_tool_count[call.name] = per_tool_count.get(call.name, 0) + 1
                execution = await registry.execute(call)
            executions.append(execution)
            conversation.append(
                ChatMessage(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=json.dumps(execution.message_payload(), ensure_ascii=False),
                )
            )

        if len(executions) >= max_total_calls:
            break

    # Give the model one tool-free turn to summarize completed work instead of
    # letting a confused local model loop forever.
    final = await llm.generate(conversation)
    if not final.content.strip():
        final = _fallback_response(final, executions)
    return ToolConversationResult(response=final, executions=executions, messages=conversation)


def _fallback_response(response: LLMResponse, executions: list[ToolExecution]) -> LLMResponse:
    messages: list[str] = []
    for execution in executions:
        if not execution.ok:
            messages.append(execution.error or "One requested action failed.")
            continue
        result = execution.result if isinstance(execution.result, dict) else {}
        confirmation = str(result.get("confirmation") or "").strip()
        if confirmation:
            messages.append(confirmation)
    content = " ".join(dict.fromkeys(messages)) or "The requested action completed."
    return LLMResponse(
        content=content,
        model=response.model,
        finish_reason=response.finish_reason or "tool_result",
        usage=response.usage,
        raw=response.raw,
    )
