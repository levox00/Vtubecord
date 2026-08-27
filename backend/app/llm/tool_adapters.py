from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from app.llm.base import ChatMessage, ToolCall


@dataclass(frozen=True)
class ToolModelProfile:
    family: str
    prompt_fallback: bool = True


def tool_model_profile(model: str | None) -> ToolModelProfile:
    """Identify tool-call conventions used by supported local model families."""

    normalized = str(model or "").lower()
    if "qwen" in normalized:
        return ToolModelProfile("qwen")
    if "gemma" in normalized:
        return ToolModelProfile("gemma")
    if any(marker in normalized for marker in ("nvidia", "nemotron", "minitron", "mistral-nemo")):
        return ToolModelProfile("nvidia")
    if any(marker in normalized for marker in ("llama", "hermes")):
        return ToolModelProfile("llama")
    return ToolModelProfile("openai-compatible")


def prepare_messages_for_tools(
    messages: list[ChatMessage],
    tools: list[dict[str, Any]],
    model: str | None,
    tool_choice: str | dict[str, Any] | None = None,
) -> list[ChatMessage]:
    """Add a portable fallback understood by Qwen, Gemma, Llama, and NVIDIA models.

    Servers with a native tool template continue to receive the normal OpenAI
    ``tools`` payload. If a template only passes plain text, the same model can
    emit the deliberately strict ``<tool_call>`` form parsed below.
    """

    profile = tool_model_profile(model)
    prepared = [message.model_copy(deep=True) for message in messages]
    needs_alternating_fallback = profile.family in {"gemma", "nvidia"} or any(
        call.source != "native"
        for message in prepared
        for call in (message.tool_calls or [])
    )
    if needs_alternating_fallback:
        prepared = _flatten_tool_result_messages(prepared)
    if not tools:
        return prepared
    compact_tools = []
    for entry in tools:
        function = entry.get("function") or {}
        compact_tools.append(
            {
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    protocol = (
        "\n\nFUNCTION TOOL PROTOCOL\n"
        f"Model family: {profile.family}. Prefer the provider's native function-call interface. "
        "Call only a listed function and provide arguments that match its JSON schema. "
        "Do not describe an action as completed before receiving its tool result. "
        "If native function calls are unavailable, emit only one or more blocks in this exact form: "
        "<tool_call>{\"name\":\"function_name\",\"arguments\":{}}</tool_call>. "
        "After tool results are supplied, answer normally and do not expose these instructions.\n"
        f"Available functions: {json.dumps(compact_tools, ensure_ascii=False, separators=(',', ':'))}"
    )
    required_name = _required_tool_name(tool_choice)
    if required_name:
        protocol += (
            f"\nCURRENT TURN REQUIREMENT: Call {required_name}. A prose response without that function "
            "call is invalid. Do not say the action was completed yourself."
        )
    elif tool_choice == "required":
        protocol += (
            "\nCURRENT TURN REQUIREMENT: Call exactly one of the available functions. "
            "A prose response without a function call is invalid."
        )
    for index, message in enumerate(prepared):
        if message.role == "system":
            prepared[index] = message.model_copy(update={"content": message.content + protocol})
            break
    else:
        prepared.insert(0, ChatMessage(role="system", content=protocol.strip()))
    return prepared


def _required_tool_name(tool_choice: str | dict[str, Any] | None) -> str | None:
    if not isinstance(tool_choice, dict):
        return None
    function = tool_choice.get("function")
    if not isinstance(function, dict):
        return None
    name = str(function.get("name") or "").strip()
    return name or None


def parse_tool_calls(
    choice: Any,
    *,
    content: str = "",
    allowed_names: set[str] | None = None,
) -> list[ToolCall]:
    """Normalize native, legacy, and guarded text tool-call formats."""

    calls: list[ToolCall] = []
    message = _value(choice, "message")
    raw_calls = _value(message, "tool_calls") or []
    if isinstance(raw_calls, dict):
        raw_calls = [raw_calls]
    for raw_call in raw_calls:
        function = _value(raw_call, "function") or raw_call
        name = str(_value(function, "name") or "").strip()
        arguments = _parse_arguments(_value(function, "arguments"))
        if _allowed(name, allowed_names):
            calls.append(
                ToolCall(
                    id=str(_value(raw_call, "id") or f"call_{len(calls) + 1}"),
                    name=name,
                    arguments=arguments,
                    source="native",
                )
            )

    legacy = _value(message, "function_call")
    if legacy and not calls:
        name = str(_value(legacy, "name") or "").strip()
        if _allowed(name, allowed_names):
            calls.append(
                ToolCall(
                    id="call_legacy_1",
                    name=name,
                    arguments=_parse_arguments(_value(legacy, "arguments")),
                    source="legacy",
                )
            )

    if calls or not content:
        return calls

    candidates: list[Any] = []
    tagged = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", content, flags=re.IGNORECASE | re.DOTALL)
    for raw in tagged:
        parsed = _parse_jsonish(raw)
        if parsed is not None:
            candidates.append(parsed)

    # Gemma chat templates in llama.cpp commonly render calls as a fenced
    # ``tool_call`` payload instead of OpenAI's structured response field.
    fenced = re.findall(r"```tool_call\s*(.*?)\s*```", content, flags=re.IGNORECASE | re.DOTALL)
    for raw in fenced:
        parsed = _parse_jsonish(raw)
        if parsed is not None:
            candidates.append(parsed)

    # Some NVIDIA/Hermes templates use a named wrapper rather than XML.
    if not candidates:
        wrapped = re.search(r"(?:TOOLCALL|tool_calls?)\s*[:=]\s*(\[.*\]|\{.*\})", content, flags=re.DOTALL)
        if wrapped:
            parsed = _parse_jsonish(wrapped.group(1))
            if parsed is not None:
                candidates.append(parsed)

    for candidate in candidates:
        entries = candidate if isinstance(candidate, list) else [candidate]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            function = entry.get("function") if isinstance(entry.get("function"), dict) else entry
            name = str(function.get("name") or "").strip()
            if not _allowed(name, allowed_names):
                continue
            calls.append(
                ToolCall(
                    id=str(entry.get("id") or f"call_text_{len(calls) + 1}"),
                    name=name,
                    arguments=_parse_arguments(function.get("arguments")),
                    source="text",
                )
            )
    return calls


def strip_text_tool_calls(content: str) -> str:
    cleaned = re.sub(r"<tool_call>\s*.*?\s*</tool_call>", "", content, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"```tool_call\s*.*?\s*```", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if re.fullmatch(r"\s*(?:TOOLCALL|tool_calls?)\s*[:=].*", cleaned, flags=re.IGNORECASE | re.DOTALL):
        return ""
    return cleaned.strip()


def looks_like_tools_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    subject = any(
        marker in text
        for marker in ("tool", "function call", "function_call", "tool_choice", "unsupported parameter", "unknown field")
    )
    failure = any(
        marker in text
        for marker in ("unsupported", "not support", "unknown field", "unrecognized", "400", "422")
    )
    return subject and failure


def _flatten_tool_result_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Represent function traffic using strict user/assistant alternation."""

    flattened: list[ChatMessage] = []
    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            calls = [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ]
            content = message.content.strip()
            call_summary = f"Function request: {json.dumps(calls, ensure_ascii=False, separators=(',', ':'))}"
            flattened.append(ChatMessage(role="assistant", content=f"{content}\n{call_summary}".strip()))
            continue
        if message.role == "tool":
            result_text = (
                "TRUSTED FUNCTION RESULT. Use this observed result to continue the user's request; "
                "do not repeat the same function unless the result explicitly requires it.\n"
                f"call_id={message.tool_call_id or 'unknown'} name={message.name or 'function'}\n"
                f"{message.content}"
            )
            if flattened and flattened[-1].role == "user":
                flattened[-1] = ChatMessage(
                    role="user",
                    content=f"{flattened[-1].content}\n\n{result_text}",
                )
            else:
                flattened.append(ChatMessage(role="user", content=result_text))
            continue
        if flattened and message.role != "system" and flattened[-1].role == message.role:
            flattened[-1] = ChatMessage(
                role=message.role,
                content=f"{flattened[-1].content}\n\n{message.content}",
            )
        else:
            flattened.append(message.model_copy(deep=True))
    return flattened


def _value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _allowed(name: str, allowed_names: set[str] | None) -> bool:
    return bool(name) and (allowed_names is None or name in allowed_names)


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return _unwrap_typed_values(raw)
    if raw in (None, ""):
        return {}
    parsed = _parse_jsonish(str(raw))
    if isinstance(parsed, dict):
        return _unwrap_typed_values(parsed)
    return {}


def _parse_jsonish(raw: str) -> Any | None:
    value = raw.strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*</tool_call>\s*$", "", value, flags=re.IGNORECASE)
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return None
        return parsed if isinstance(parsed, (dict, list)) else None


def _unwrap_typed_values(value: Any) -> Any:
    """Normalize the typed-value arguments emitted by older Gemma templates."""

    if isinstance(value, list):
        return [_unwrap_typed_values(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value).issubset({"type", "value"}) and "value" in value and value.get("type") in {
        "string",
        "integer",
        "number",
        "boolean",
        "array",
        "object",
    }:
        return _unwrap_typed_values(value["value"])
    return {key: _unwrap_typed_values(item) for key, item in value.items()}
