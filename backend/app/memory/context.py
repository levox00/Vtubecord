from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.base import ChatMessage
from app.models.character import Memory, Message, VoiceBrainSession


_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Cheap multilingual-safe estimate used for deterministic prompt packing."""

    value = str(text or "")
    if not value:
        return 0
    words = len(_WORD_RE.findall(value))
    # Character count catches CJK/code where whitespace word counts are weak.
    return max(1, math.ceil(max(words * 1.32, len(value) / 3.7)))


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in _WORD_RE.findall(str(text or "")) if len(item) > 2}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def memory_relevance_score(memory: Memory, query: str, *, now: datetime | None = None) -> float:
    """Blend lexical relevance, importance, recency and deliberate pinning."""

    now = now or datetime.now(timezone.utc)
    query_terms = _terms(query)
    memory_terms = _terms(" ".join([memory.content, *[str(tag) for tag in (memory.tags or [])]]))
    overlap = len(query_terms & memory_terms) / max(1, len(query_terms))
    created = _aware(memory.created_at) or now
    age_days = max(0.0, (now - created).total_seconds() / 86400.0)
    recency = 1.0 / (1.0 + age_days / 14.0)
    importance = max(0.0, min(1.0, float(memory.importance or 0.0)))
    pin_bonus = 0.65 if bool(memory.pinned) else 0.0
    return overlap * 1.8 + importance * 0.72 + recency * 0.28 + pin_bonus


def pack_recent_messages(messages: Sequence[Message], token_budget: int) -> list[ChatMessage]:
    """Keep the newest coherent turns while respecting an approximate budget."""

    selected: list[ChatMessage] = []
    used = 0
    for item in reversed(messages):
        cost = estimate_tokens(item.content) + 6
        if selected and used + cost > max(128, token_budget):
            break
        if not selected and cost > token_budget:
            # Preserve the newest turn even when it needs truncation.
            char_budget = max(160, int(token_budget * 3.7))
            content = item.content[-char_budget:]
        else:
            content = item.content
        selected.append(ChatMessage(role=item.role, content=content))
        used += min(cost, token_budget)
    selected.reverse()
    return selected


@dataclass
class VoiceContextPack:
    history: list[ChatMessage] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    summary: str = ""
    open_loops: list[str] = field(default_factory=list)
    internal_state: dict[str, float] = field(default_factory=dict)
    estimated_tokens: int = 0


async def assemble_voice_context(
    db: AsyncSession,
    *,
    character_id: str,
    conversation_messages: Sequence[Message],
    current_text: str,
    session_id: str | None,
) -> VoiceContextPack:
    """Assemble hierarchical context for Discord/web live voice turns."""

    cfg = settings.memory
    row: VoiceBrainSession | None = None
    if session_id:
        result = await db.execute(
            select(VoiceBrainSession).where(VoiceBrainSession.id == session_id)
        )
        row = result.scalar_one_or_none()

    history = pack_recent_messages(conversation_messages, cfg.recent_history_tokens)
    query_parts = [current_text]
    query_parts.extend(message.content for message in history[-6:])
    if row and row.conversation_summary:
        query_parts.append(row.conversation_summary)
    query = "\n".join(query_parts)

    candidates_result = await db.execute(
        select(Memory)
        .where(Memory.character_id == character_id)
        .order_by(Memory.pinned.desc(), Memory.importance.desc(), Memory.created_at.desc())
        .limit(max(cfg.retrieval_candidates, cfg.retrieval_top_k))
    )
    candidates = list(candidates_result.scalars().all())
    ranked = sorted(candidates, key=lambda item: memory_relevance_score(item, query), reverse=True)
    chosen: list[Memory] = []
    memory_text: list[str] = []
    used = 0
    for memory in ranked:
        if len(chosen) >= cfg.retrieval_top_k and not memory.pinned:
            continue
        rendered = f"[{memory.memory_type}] {memory.content}"
        cost = estimate_tokens(rendered) + 4
        if memory_text and used + cost > cfg.memory_tokens and not memory.pinned:
            continue
        chosen.append(memory)
        memory_text.append(rendered)
        used += cost
        if len(chosen) >= max(cfg.retrieval_top_k, 1) and used >= cfg.memory_tokens:
            break

    accessed_at = datetime.now(timezone.utc)
    for memory in chosen:
        memory.last_accessed = accessed_at

    summary = str(row.conversation_summary or "") if row else ""
    if estimate_tokens(summary) > cfg.summary_tokens:
        summary = summary[: max(320, int(cfg.summary_tokens * 3.7))]
    open_loops = [str(item) for item in (row.open_loops or [])][:12] if row else []
    internal = dict(row.internal_state or {}) if row else {}
    total = sum(estimate_tokens(item.content) + 6 for item in history)
    total += sum(estimate_tokens(item) + 4 for item in memory_text)
    total += estimate_tokens(summary)
    return VoiceContextPack(
        history=history,
        memories=memory_text,
        summary=summary,
        open_loops=open_loops,
        internal_state=internal,
        estimated_tokens=total,
    )
