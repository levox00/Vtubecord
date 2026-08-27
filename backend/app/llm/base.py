from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Provider-neutral representation of a requested function call."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    source: str = "native"  # native | legacy | text | controller


class ChatMessage(BaseModel):
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class LLMResponse(BaseModel):
    content: str
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw: Any = None


@runtime_checkable
class LLMProvider(Protocol):
    """Universal LLM interface. Character does not care which provider is used."""

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse:
        """Generate a completion from the given messages."""
        ...

    @property
    def provider_name(self) -> str:
        ...

    @property
    def model_name(self) -> str:
        ...
