from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.base import ChatMessage, LLMResponse, ToolCall
from app.llm.tool_adapters import (
    parse_tool_calls,
    prepare_messages_for_tools,
    strip_text_tool_calls,
    tool_model_profile,
)
from app.tools.registry import ToolRegistry, ToolSpec
from app.tools.router import NO_ACTION_TOOL, route_tool_request
from app.tools.runtime import run_tool_conversation


def _definition(name: str = "demo_action") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Run a demo action.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "integer", "minimum": 0, "maximum": 10}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }


@pytest.mark.parametrize(
    ("model", "family"),
    [
        ("Qwen2.5-14B-Instruct", "qwen"),
        ("gemma-3-12b-it", "gemma"),
        ("Meta-Llama-3.1-8B-Instruct", "llama"),
        ("NVIDIA-Nemotron-Nano-9B-v2", "nvidia"),
        ("Mistral-NeMo-Minitron-8B", "nvidia"),
    ],
)
def test_supported_local_model_families_are_detected(model: str, family: str):
    assert tool_model_profile(model).family == family


def test_native_openai_tool_calls_are_normalized():
    choice = SimpleNamespace(
        message=SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id="call_native",
                    function=SimpleNamespace(name="demo_action", arguments='{"value":4}'),
                )
            ]
        )
    )
    assert parse_tool_calls(choice, allowed_names={"demo_action"}) == [
        ToolCall(id="call_native", name="demo_action", arguments={"value": 4}, source="native")
    ]


@pytest.mark.parametrize(
    "content",
    [
        '<tool_call>{"name":"demo_action","arguments":{"value":5}}</tool_call>',
        '```tool_call\n{"name":"demo_action","arguments":{"value":5}}\n```',
        '```tool_call{"name":"demo_action","arguments":{"value":{"type":"integer","value":5}}}</tool_call>\n```',
        'TOOLCALL: [{"name":"demo_action","arguments":{"value":5}}]',
    ],
)
def test_qwen_gemma_llama_nvidia_text_protocol_is_guarded(content: str):
    choice = SimpleNamespace(message=SimpleNamespace(tool_calls=[]))
    calls = parse_tool_calls(choice, content=content, allowed_names={"demo_action"})
    assert calls[0].name == "demo_action"
    assert calls[0].arguments == {"value": 5}
    assert calls[0].source == "text"
    assert strip_text_tool_calls(content) == ""


def test_text_protocol_cannot_invoke_an_unregistered_name():
    choice = SimpleNamespace(message=SimpleNamespace(tool_calls=[]))
    content = '<tool_call>{"name":"delete_everything","arguments":{}}</tool_call>'
    assert parse_tool_calls(choice, content=content, allowed_names={"demo_action"}) == []


def test_tool_prompt_contains_portable_schema_and_family():
    prepared = prepare_messages_for_tools(
        [ChatMessage(role="system", content="persona"), ChatMessage(role="user", content="do it")],
        [_definition()],
        "gemma-3-12b-it",
    )
    assert "Model family: gemma" in prepared[0].content
    assert '"name":"demo_action"' in prepared[0].content
    assert "<tool_call>" in prepared[0].content


def test_forced_tool_choice_is_in_portable_prompt():
    prepared = prepare_messages_for_tools(
        [ChatMessage(role="system", content="persona"), ChatMessage(role="user", content="play it")],
        [_definition("spotify_play")],
        "Mistral-NeMo-Minitron-8B",
        tool_choice={"type": "function", "function": {"name": "spotify_play"}},
    )
    assert "CURRENT TURN REQUIREMENT: Call spotify_play" in prepared[0].content


def test_required_tool_selection_is_in_portable_prompt():
    prepared = prepare_messages_for_tools(
        [ChatMessage(role="user", content="please do the action")],
        [_definition()],
        "gemma-3-12b-it",
        tool_choice="required",
    )
    assert "Call exactly one of the available functions" in prepared[0].content


def test_gemma_tool_results_are_converted_to_strict_alternating_turns():
    prepared = prepare_messages_for_tools(
        [
            ChatMessage(role="system", content="persona"),
            ChatMessage(role="user", content="do it"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_text_1",
                        name="demo_action",
                        arguments={"value": 5},
                        source="text",
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                name="demo_action",
                tool_call_id="call_text_1",
                content='{"ok":true,"result":{"accepted":5}}',
            ),
        ],
        [_definition()],
        "gemma-3-12b-it",
    )
    assert [message.role for message in prepared] == ["system", "user", "assistant", "user"]
    assert "TRUSTED FUNCTION RESULT" in prepared[-1].content


def test_registry_validates_arguments_before_execution():
    asyncio.run(_test_registry_validates_arguments_before_execution())


async def _test_registry_validates_arguments_before_execution():
    called = False

    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        nonlocal called
        called = True
        return arguments

    registry = ToolRegistry()
    definition = _definition()["function"]
    registry.register(
        ToolSpec(
            name="demo_action",
            description=definition["description"],
            parameters=definition["parameters"],
            handler=handler,
        )
    )
    execution = await registry.execute(
        ToolCall(id="bad", name="demo_action", arguments={"value": 99, "extra": True})
    )
    assert execution.ok is False
    assert called is False


class _TwoTurnLLM:
    provider_name = "test"
    model_name = "Qwen2.5"

    def __init__(self) -> None:
        self.requests: list[tuple[list[ChatMessage], list[dict[str, Any]] | None, Any]] = []

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
        self.requests.append((messages, tools, tool_choice))
        if len(self.requests) == 1:
            return LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[ToolCall(id="call_1", name="demo_action", arguments={"value": 7})],
            )
        return LLMResponse(content="Done with 7.", finish_reason="stop")


def test_multi_turn_runtime_returns_tool_result_to_model(caplog):
    caplog.set_level(logging.INFO, logger="app.tools.runtime")
    asyncio.run(_test_multi_turn_runtime_returns_tool_result_to_model())
    assert "Tool calling feature demo_action used by Qwen2.5" in caplog.messages


async def _test_multi_turn_runtime_returns_tool_result_to_model():
    registry = ToolRegistry()
    definition = _definition()["function"]
    registry.register(
        ToolSpec(
            name="demo_action",
            description=definition["description"],
            parameters=definition["parameters"],
            handler=lambda arguments: {"accepted": arguments["value"]},
        )
    )
    llm = _TwoTurnLLM()
    result = await run_tool_conversation(
        llm,
        [ChatMessage(role="user", content="run it with seven")],
        registry,
    )
    assert result.response.content == "Done with 7."
    assert result.executions[0].ok is True
    second_messages = llm.requests[1][0]
    assert second_messages[-2].role == "assistant"
    assert second_messages[-1].role == "tool"
    assert '"accepted": 7' in second_messages[-1].content
    assert llm.requests[0][2] == "auto"


def test_runtime_forces_a_recognized_tool_on_first_round():
    asyncio.run(_test_runtime_forces_a_recognized_tool_on_first_round())


async def _test_runtime_forces_a_recognized_tool_on_first_round():
    registry = ToolRegistry()
    definition = _definition("spotify_play")["function"]
    registry.register(
        ToolSpec(
            name="spotify_play",
            description=definition["description"],
            parameters=definition["parameters"],
            handler=lambda arguments: {"accepted": arguments["value"]},
        )
    )
    llm = _TwoTurnLLM()
    await run_tool_conversation(
        llm,
        [ChatMessage(role="user", content="play it with seven")],
        registry,
        required_tool="spotify_play",
    )
    assert llm.requests[0][2] == {
        "type": "function",
        "function": {"name": "spotify_play"},
    }
    assert len(llm.requests[0][1] or []) == 1


class _RefusingToolLLM:
    provider_name = "test"
    model_name = "Mistral-NeMo-Minitron-8B"

    def __init__(self) -> None:
        self.requests = 0

    async def generate(self, messages, **kwargs):
        self.requests += 1
        if self.requests == 1:
            return LLMResponse(content="Sure, I am playing it now.", model=self.model_name)
        return LLMResponse(content="The requested song is playing.", model=self.model_name)


def test_required_action_cannot_be_replaced_by_hallucinated_confirmation():
    asyncio.run(_test_required_action_cannot_be_replaced_by_hallucinated_confirmation())


async def _test_required_action_cannot_be_replaced_by_hallucinated_confirmation():
    seen: list[dict[str, Any]] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="spotify_play",
            description="Play a song.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda arguments: seen.append(arguments) or {"confirmation": "Playing Sailor Song."},
        )
    )
    result = await run_tool_conversation(
        _RefusingToolLLM(),
        [ChatMessage(role="user", content="play Sailor Song")],
        registry,
        required_tool="spotify_play",
        required_arguments={"query": "sailor song"},
    )
    assert seen == [{"query": "sailor song"}]
    assert result.executions[0].call.source == "controller"
    assert result.executions[0].ok is True


class _HallucinatingToolArgumentsLLM(_RefusingToolLLM):
    async def generate(self, messages, **kwargs):
        self.requests += 1
        if self.requests == 1:
            return LLMResponse(
                content="",
                model=self.model_name,
                tool_calls=[
                    ToolCall(
                        id="call_model_1",
                        name="spotify_play",
                        arguments={"query": "Sailor Song by AWOLNATION"},
                        source="text",
                    )
                ],
            )
        return LLMResponse(content="The requested song is playing.", model=self.model_name)


def test_required_tool_arguments_stay_grounded_in_user_request():
    asyncio.run(_test_required_tool_arguments_stay_grounded_in_user_request())


async def _test_required_tool_arguments_stay_grounded_in_user_request():
    seen: list[dict[str, Any]] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="spotify_play",
            description="Play a song.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda arguments: seen.append(arguments) or {"confirmation": "Playing Sailor Song."},
        )
    )
    result = await run_tool_conversation(
        _HallucinatingToolArgumentsLLM(),
        [ChatMessage(role="user", content="play Sailor Song")],
        registry,
        required_tool="spotify_play",
        required_arguments={"query": "sailor song"},
    )
    assert seen == [{"query": "sailor song"}]
    assert result.executions[0].call.source == "text"


class _RoutingLLM:
    provider_name = "test"
    model_name = "Qwen2.5-8B-Instruct"

    def __init__(self, selected_name: str, arguments: dict[str, Any] | None = None) -> None:
        self.selected_name = selected_name
        self.arguments = arguments or {}
        self.request: dict[str, Any] | None = None

    async def generate(self, messages, **kwargs):
        self.request = {"messages": messages, **kwargs}
        return LLMResponse(
            content="",
            model=self.model_name,
            finish_reason="tool_calls",
            tool_calls=[
                ToolCall(
                    id="route_1",
                    name=self.selected_name,
                    arguments=self.arguments,
                    source="native",
                )
            ],
        )


def _routable_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="spotify_play",
            description="Play a requested song.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=lambda arguments: arguments,
            category="spotify",
            intent_hints=("play", "song", "music"),
        )
    )
    registry.register(
        ToolSpec(
            name="spotify_next",
            description="Skip to the next song.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: arguments,
            category="spotify",
            intent_hints=("play", "song", "music"),
        )
    )
    return registry


def test_semantic_router_selects_a_real_registered_tool():
    asyncio.run(_test_semantic_router_selects_a_real_registered_tool())


async def _test_semantic_router_selects_a_real_registered_tool():
    llm = _RoutingLLM("spotify_play", {"query": "Hide Away by Daya"})
    route = await route_tool_request(
        llm,
        "phi neuro can you play me hide away by daya",
        _routable_registry(),
    )
    assert route.status == "selected"
    assert route.call is not None
    assert route.call.name == "spotify_play"
    assert route.call.arguments == {"query": "Hide Away by Daya"}
    assert llm.request is not None
    assert llm.request["tool_choice"] == "required"
    exposed = {
        definition["function"]["name"]
        for definition in llm.request["tools"]
    }
    assert exposed == {"spotify_play", "spotify_next", NO_ACTION_TOOL}


def test_semantic_router_can_explicitly_choose_no_action():
    asyncio.run(_test_semantic_router_can_explicitly_choose_no_action())


async def _test_semantic_router_can_explicitly_choose_no_action():
    route = await route_tool_request(
        _RoutingLLM(NO_ACTION_TOOL),
        "could you tell me what kind of music you like?",
        _routable_registry(),
    )
    assert route.status == "none"
    assert route.call is None


class _FinalAfterInitialCallLLM:
    provider_name = "test"
    model_name = "Llama-3.1-8B-Instruct"

    def __init__(self) -> None:
        self.requests: list[list[ChatMessage]] = []

    async def generate(self, messages, **kwargs):
        self.requests.append(messages)
        return LLMResponse(content="The song is now playing.", model=self.model_name)


class _FailingFinalAfterInitialCallLLM(_FinalAfterInitialCallLLM):
    async def generate(self, messages, **kwargs):
        self.requests.append(messages)
        raise RuntimeError("final wording failed")


def _initial_execution_registry(seen: list[dict[str, Any]]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="spotify_play",
            description="Play a requested song.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
            handler=lambda arguments: seen.append(arguments) or {"confirmation": "Playing Hide Away."},
            category="spotify",
            intent_hints=("play", "song", "music"),
        )
    )
    return registry


def test_runtime_executes_the_router_model_call_without_reselecting_it():
    asyncio.run(_test_runtime_executes_the_router_model_call_without_reselecting_it())


async def _test_runtime_executes_the_router_model_call_without_reselecting_it():
    seen: list[dict[str, Any]] = []
    registry = _initial_execution_registry(seen)
    llm = _FinalAfterInitialCallLLM()
    result = await run_tool_conversation(
        llm,
        [ChatMessage(role="user", content="play Hide Away by Daya")],
        registry,
        initial_call=ToolCall(
            id="route_1",
            name="spotify_play",
            arguments={"query": "Hide Away by Daya"},
            source="native",
        ),
        initial_model=llm.model_name,
    )
    assert seen == [{"query": "Hide Away by Daya"}]
    assert len(llm.requests) == 1
    assert llm.requests[0][-1].role == "tool"
    assert result.executions[0].call.source == "native"


def test_completed_action_is_not_retried_when_final_wording_fails():
    asyncio.run(_test_completed_action_is_not_retried_when_final_wording_fails())


async def _test_completed_action_is_not_retried_when_final_wording_fails():
    seen: list[dict[str, Any]] = []
    llm = _FailingFinalAfterInitialCallLLM()
    result = await run_tool_conversation(
        llm,
        [ChatMessage(role="user", content="play Hide Away by Daya")],
        _initial_execution_registry(seen),
        initial_call=ToolCall(
            id="route_1",
            name="spotify_play",
            arguments={"query": "Hide Away by Daya"},
            source="native",
        ),
        initial_model=llm.model_name,
    )
    assert seen == [{"query": "Hide Away by Daya"}]
    assert result.response.content == "Playing Hide Away."
