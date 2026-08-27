from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.llm.base import ToolCall

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]
AvailabilityCheck = Callable[[], bool]


class ToolExecutionError(RuntimeError):
    """A safe, user-facing error raised by a tool implementation."""


@dataclass(frozen=True)
class ToolSpec:
    """A named action, its JSON schema, and the local code that executes it."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    category: str = "general"
    guidance: str = ""
    intent_hints: tuple[str, ...] = ()
    available: AvailabilityCheck = field(default=lambda: True, compare=False, repr=False)
    max_calls_per_turn: int = 1

    def openai_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolExecution:
    call: ToolCall
    ok: bool
    result: Any = None
    error: str | None = None

    def message_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok, "tool": self.call.name}
        if self.ok:
            payload["result"] = self.result
        else:
            payload["error"] = self.error or "The tool could not complete the action."
        return payload


class ToolRegistry:
    """Central allowlist and executor for every action an LLM may request."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if not spec.name or not spec.name.replace("_", "").isalnum():
            raise ValueError(f"Invalid tool name: {spec.name!r}")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        if spec.parameters.get("type") != "object":
            raise ValueError(f"Tool parameters must use an object schema: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def available_specs(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for spec in self._tools.values():
            try:
                enabled = bool(spec.available())
            except Exception:
                enabled = False
            if enabled:
                specs.append(spec)
        return specs

    def definitions(self) -> list[dict[str, Any]]:
        return [spec.openai_definition() for spec in self.available_specs()]

    def candidate_specs(self, text: str) -> list[ToolSpec]:
        """Return the smallest useful tool directory for a possible action.

        Integrations declare broad, non-authoritative wake hints. A hint only
        decides whether the semantic model router should run; it never chooses
        or executes a tool. Once one hint matches, all tools in that category
        are included so the model can distinguish (for example) play, queue,
        next, and resume.
        """

        available = self.available_specs()
        normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
        matched_categories = {
            spec.category
            for spec in available
            if any(_contains_hint(normalized, hint) for hint in spec.intent_hints)
        }
        if matched_categories:
            return [spec for spec in available if spec.category in matched_categories]
        return []

    def looks_actionable(self, text: str) -> bool:
        """Cheap wake gate that keeps ordinary chat off the routing path."""

        if self.candidate_specs(text):
            return True
        normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
        if not normalized:
            return False
        # This catches future action integrations whose first version forgot a
        # synonym. The semantic router still has an explicit no-action choice,
        # so matching this gate cannot itself trigger a side effect.
        return bool(
            re.search(
                r"\b(?:please|can you|could you|would you|will you|"
                r"start|stop|open|close|join|leave|switch|change|set|turn)\b",
                normalized,
            )
        )

    def guidance(self) -> str | None:
        guidance = list(dict.fromkeys(spec.guidance.strip() for spec in self.available_specs() if spec.guidance.strip()))
        if not guidance:
            return None
        return (
            "Available actions are exposed as function tools. Use a tool when an action is requested; "
            "never claim an external action succeeded before its result reports ok=true.\n"
            + "\n".join(f"- {item}" for item in guidance)
        )

    def get(self, name: str) -> ToolSpec | None:
        spec = self._tools.get(name)
        if spec is None:
            return None
        try:
            return spec if spec.available() else None
        except Exception:
            return None

    async def execute(self, call: ToolCall) -> ToolExecution:
        spec = self.get(call.name)
        if spec is None:
            return ToolExecution(call=call, ok=False, error=f"Unknown or unavailable tool: {call.name}")

        validation_error = _validate_value(call.arguments, spec.parameters, path="arguments")
        if validation_error:
            return ToolExecution(call=call, ok=False, error=validation_error)

        try:
            result = spec.handler(dict(call.arguments))
            if inspect.isawaitable(result):
                result = await result
            # Convert Pydantic models and other JSON-friendly objects while
            # guaranteeing that tool messages can always be serialized.
            if hasattr(result, "model_dump"):
                result = result.model_dump()
            result = json.loads(json.dumps(result, ensure_ascii=False, default=str))
            return ToolExecution(call=call, ok=True, result=result)
        except ToolExecutionError as exc:
            return ToolExecution(call=call, ok=False, error=_safe_error(exc))
        except Exception:
            # Do not leak tokens, URLs, stack traces, or integration secrets to
            # either the model or the user-facing conversation.
            logger.exception("Tool %s failed unexpectedly", call.name)
            return ToolExecution(call=call, ok=False, error=f"{call.name} failed unexpectedly.")


def _safe_error(exc: Exception) -> str:
    return str(exc).strip()[:500] or "The tool could not complete the action."


def _contains_hint(text: str, hint: str) -> bool:
    value = re.sub(r"\s+", " ", str(hint or "").lower()).strip()
    if not value:
        return False
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text) is not None


def _validate_value(value: Any, schema: dict[str, Any], *, path: str) -> str | None:
    """Validate the JSON-schema subset used by local function tools."""

    expected = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)
    if not type_ok:
        return f"{path} must be {expected}."

    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of: {', '.join(map(str, schema['enum']))}."

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for required_name in schema.get("required") or []:
            if required_name not in value:
                return f"Missing required argument: {required_name}."
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(value) - set(properties))
            if unexpected:
                return f"Unexpected argument: {unexpected[0]}."
        for name, child in value.items():
            if name in properties:
                error = _validate_value(child, properties[name], path=f"{path}.{name}")
                if error:
                    return error

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            error = _validate_value(child, schema["items"], path=f"{path}[{index}]")
            if error:
                return error

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}."
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path} must be at most {schema['maximum']}."

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            return f"{path} is too short."
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{path} is too long."
    return None
