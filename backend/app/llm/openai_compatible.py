from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.paths import data_root
from app.llm.base import ChatMessage, LLMProvider, LLMResponse, ToolCall
from app.llm.tool_adapters import (
    looks_like_tools_unsupported,
    parse_tool_calls,
    prepare_messages_for_tools,
    strip_text_tool_calls,
)

logger = logging.getLogger(__name__)

_local_model_lock = asyncio.Lock()
_active_local_model: str | None = None
_router_supported: bool | None = None


# Mistral-NeMo-Minitron GGUF files use ``<extra_id_1>`` as the boundary
# between an assistant answer and the next user turn.  llama.cpp applies the
# model's chat template, but it does not infer a stop sequence from every
# template.  Without these stops the model can continue by generating a
# complete, synthetic conversation (including the internal role markers).
_MINITRON_STOP_SEQUENCES = ("<extra_id_1>", "<extra_id_0>", "</s>")


def _model_uses_minitron_template(model: str | None) -> bool:
    normalized = str(model or "").lower()
    return "minitron" in normalized or "mistral-nemo" in normalized


def _default_stop_sequences(model: str | None) -> list[str] | None:
    """Return safe template stops for known local model families.

    Other providers/models keep their server-side defaults.  This is kept
    deliberately narrow because stop strings are part of a model's prompt
    contract and should not be guessed for arbitrary hosted models.
    """

    if _model_uses_minitron_template(model):
        return list(_MINITRON_STOP_SEQUENCES)
    return None


def _clean_generated_content(content: str, model: str | None) -> str:
    """Remove leaked Minitron role markers from user-visible text.

    The stop list prevents this in normal operation.  The cleanup is a
    defensive layer for older llama.cpp builds, cached generations, or a
    provider that ignores the stop field.
    """

    if not content or not _model_uses_minitron_template(model):
        return content

    cleaned = content
    for marker in _MINITRON_STOP_SEQUENCES:
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0]
    # A malformed response may begin with a marker before the actual answer.
    cleaned = re.sub(r"^\s*(?:<extra_id_[01]>\s*)+", "", cleaned)
    return cleaned.strip()


def _serialize_message(message: ChatMessage) -> dict[str, Any]:
    """Serialize our provider-neutral message into OpenAI's wire format."""

    payload = message.model_dump(exclude_none=True, exclude={"tool_calls"})
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _normalize_tool_calls(
    choice: Any,
    content: str = "",
    allowed_names: set[str] | None = None,
) -> list[ToolCall]:
    """Backward-compatible facade around the multi-family tool parser."""

    return parse_tool_calls(choice, content=content, allowed_names=allowed_names)


def _is_local_server(base_url: str, provider: str | None = None) -> bool:
    host = urlparse(base_url).hostname
    return host in {"127.0.0.1", "localhost", "::1"} and (provider or "").lower() in {
        "openai_compatible", "openai", "llama_cpp", "llamacpp", "ollama", ""
    }


def _resolve_local_model_name(model: str) -> str:
    """Turn the UI's model value into the llama.cpp router model identifier."""
    requested = str(model or "").strip()
    project_root = data_root()
    gguf_dir = project_root / "assets" / "models" / "gguf"
    if requested in {"", "local-model"}:
        candidates = sorted(gguf_dir.glob("*.gguf")) if gguf_dir.exists() else []
        return candidates[0].stem if candidates else (requested or "local-model")
    candidate = Path(requested)
    if candidate.suffix.lower() == ".gguf":
        # The router launcher registers models by their filename stem (for
        # example ``gemma-2-2b-it-Q4_K_M``), while the settings and download
        # APIs intentionally keep the on-disk ``.gguf`` filename.  Sending
        # the filename to ``/v1/chat/completions`` makes llama.cpp reject the
        # request with ``model ... not found`` even though the file exists.
        return candidate.stem
    return requested


def _server_root(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


async def _ensure_local_model(base_url: str, model: str) -> str:
    """Switch llama.cpp router models at the point a chat is generated.

    The lock is held by ``generate`` for the complete request, which prevents
    an unload from racing with an in-flight generation.  Older single-model
    llama-server instances return 404 for the router management endpoints; in
    that case we keep the normal request path working and ask the user to
    restart once with the updated router launcher.
    """
    global _active_local_model, _router_supported
    selected = _resolve_local_model_name(model)
    root = _server_root(base_url)

    if _active_local_model == selected:
        return selected

    logger.info(
        "Switching local LLM model%s to %s",
        f" from {_active_local_model}" if _active_local_model else "",
        selected,
    )

    # Loading a multi-gigabyte GGUF can legitimately take a few minutes on
    # first use, so keep the connection timeout short but allow the management
    # request to wait for the model to become ready.
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=1.0)) as client:
        if _router_supported is not False:
            if _active_local_model:
                try:
                    await client.post(f"{root}/models/unload", json={"model": _active_local_model})
                except Exception as exc:
                    logger.debug("Could not unload previous llama.cpp model: %s", exc)

            try:
                response = await client.post(f"{root}/models/load", json={"model": selected})
                if response.status_code == 404:
                    _router_supported = False
                    logger.warning(
                        "llama.cpp does not expose router model management; restart it with the "
                        "project's router launcher to enable model unloading."
                    )
                elif response.status_code >= 400:
                    logger.warning("llama.cpp failed to load model %r (HTTP %s)", selected, response.status_code)
                else:
                    _router_supported = True
            except Exception as exc:
                # The regular OpenAI request below provides the useful error if
                # the server itself is offline; do not mask it with management
                # API failures.
                logger.debug("llama.cpp model management unavailable: %s", exc)

    _active_local_model = selected
    return selected


class OpenAICompatibleProvider:
    """Works with OpenAI, llama.cpp server, Ollama (OpenAI mode), Groq, etc."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        cfg = settings.llm
        self._base_url = base_url or cfg.base_url
        self._model = model or cfg.model
        self._temperature = temperature if temperature is not None else cfg.temperature
        self._max_tokens = max_tokens if max_tokens is not None else cfg.max_tokens

        key = api_key
        if key is None and cfg.api_key_env:
            key = os.environ.get(cfg.api_key_env)
        if not key:
            key = "not-needed"  # local servers often ignore the key

        self._client = AsyncOpenAI(base_url=self._base_url, api_key=key)

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model

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
        request_model = self._model
        model_lock = _local_model_lock if _is_local_server(self._base_url, settings.llm.provider) else None
        if model_lock is not None:
            await model_lock.acquire()
            try:
                request_model = await _ensure_local_model(self._base_url, self._model)
            except Exception:
                model_lock.release()
                raise

        prepared_messages = prepare_messages_for_tools(
            messages,
            tools or [],
            request_model,
            tool_choice=tool_choice,
        )
        payload: dict[str, Any] = {
            "model": request_model,
            "messages": [_serialize_message(m) for m in prepared_messages],
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
        }
        # llama.cpp understands this extension and can reuse the common system
        # prompt/history prefix. Do not send provider-specific fields to hosted
        # OpenAI-compatible services.
        parsed_base = urlparse(self._base_url)
        is_local = parsed_base.hostname in {"127.0.0.1", "localhost", "::1"}
        if settings.performance.llm.prompt_cache and is_local:
            payload["extra_body"] = {"cache_prompt": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        effective_stop = stop if stop is not None else _default_stop_sequences(request_model)
        if effective_stop:
            payload["stop"] = effective_stop

        try:
            try:
                response = await self._client.chat.completions.create(**payload)
            except Exception as exc:
                # Older llama.cpp/Ollama endpoints can reject OpenAI's tools
                # fields even though the model itself can follow a textual
                # function protocol. Retry locally with the same allowlisted
                # schemas in the system prompt, never for unrelated failures.
                if not (tools and is_local and looks_like_tools_unsupported(exc)):
                    raise
                fallback_payload = dict(payload)
                fallback_payload.pop("tools", None)
                fallback_payload.pop("tool_choice", None)
                logger.info("Native tools unavailable; using local prompt tool protocol for %s", request_model)
                response = await self._client.chat.completions.create(**fallback_payload)
        finally:
            if model_lock is not None:
                model_lock.release()
        if not response.choices:
            raise ValueError(
                f"LLM returned empty response (no choices). "
                f"Check that the model '{request_model}' is loaded on the server."
            )
        choice = response.choices[0]
        content = _clean_generated_content(choice.message.content or "", request_model)
        allowed_names = {
            str((entry.get("function") or {}).get("name") or "") for entry in (tools or [])
        }
        allowed_names.discard("")
        # An empty allowlist means this request exposed no tools. Do not accept
        # a hallucinated native/text call from a normal completion.
        tool_calls = _normalize_tool_calls(choice, content, allowed_names)
        if tool_calls:
            content = strip_text_tool_calls(content)

        usage: dict[str, int] = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }

        return LLMResponse(
            content=content,
            model=response.model,
            finish_reason=choice.finish_reason,
            usage=usage,
            tool_calls=tool_calls,
            raw=response,
        )


def create_llm_provider() -> LLMProvider:
    """Factory based on current config."""
    provider = settings.llm.provider.lower()

    if provider in ("openai_compatible", "openai", "llama_cpp", "llamacpp"):
        return OpenAICompatibleProvider()

    if provider == "ollama":
        # Ollama has an OpenAI-compatible endpoint
        return OpenAICompatibleProvider(
            base_url=settings.llm.base_url.rstrip("/") + "/v1"
            if not settings.llm.base_url.endswith("/v1")
            else settings.llm.base_url,
        )

    # Fallback
    return OpenAICompatibleProvider()
