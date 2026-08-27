# Development Roadmap & Guidelines

## Development Principles

1. **Incremental** — One phase at a time. Make it work, then make it better.
2. **Tested** — Pytest for every major subsystem.
3. **Typed** — Strict type hints in Python. TypeScript strict mode.
4. **Modular** — Clear interfaces. Replaceable providers.
5. **Honest** — If a feature is not implemented, mark it `NOT IMPLEMENTED`. Never fake learning or memory.
6. **Single-developer maintainable** — Prefer modular monolith over microservices for now.

## Tooling

```bash
# Backend
uv sync
uv run ruff check .
uv run ruff format .
uv run pytest

# Frontend
cd frontend && npm install && npm run dev
```

## Phase 1 — Basic Character (Current Target)

**Goal:** A functioning anime character chat application with persistent identity.

Deliverables:
- [x] Repository structure
- [x] Architecture documentation
- [ ] FastAPI backend with character profile
- [ ] LLM provider abstraction (OpenAI-compatible + llama.cpp)
- [ ] SQLite database + basic models
- [ ] WebSocket chat
- [ ] React frontend with basic layout + chat
- [ ] Character state loaded from DB into prompt
- [ ] Ability to switch LLM provider without losing character

## Phase 2 — Voice + Avatar

- ASR abstraction (Faster-Whisper default)
- TTS abstraction (Piper default)
- Streaming sentence-by-sentence speech
- Interruption support
- Live2D Shizuku integration
- Emotion → expression mapping
- Mouth animation

## Phase 3 — Memory

- Multi-type memory (episodic, semantic, relationship, skill)
- Embedding + retrieval (pgvector / simple cosine for SQLite)
- MemoryExtractor after conversations
- Conflict detection & resolution
- Memory UI (search, edit, pin, delete)

## Phase 4 — Autonomy

- Goal system
- Internal scheduler
- Proactive messages (with cooldowns & quiet hours)
- Self-reflection
- Personality evolution pipeline (observation → candidate → accepted)

## Phase 5 — Computer Interaction

- Screenshot + VisionProvider
- Permissioned mouse/keyboard/browser tools
- Audit log

## Phase 6 — Games (One Game First)

- GameAgent + GameAdapter interface
- One concrete adapter (e.g. Chess or simple desktop game)
- Strategic LLM layer + low-level controller

## Phase 7 — Game Learning

- Experience recording
- Baseline RL policy (one algorithm)
- Skill tracking
- No full LLM fine-tuning

## Phase 8 — Long-term Character Development

- Historical personality dashboard
- Relationship development over months
- Self-generated goals
- Interest evolution

## Coding Standards

### Python
- Python 3.12+
- Strict typing (`from __future__ import annotations`)
- Pydantic models for all external data
- Async everywhere practical
- Ruff for lint + format

### Frontend
- Functional components + hooks
- Zustand for global state
- Tailwind for styling
- Real-time updates via WebSocket

### Commits
- Small, focused commits
- Tests with every major subsystem

## Testing Strategy

- Unit tests for memory extraction, retrieval scoring, personality updates, emotion decay, LLM abstraction
- Integration tests for chat flow + DB
- Manual testing checklist per phase

## What Not To Do

- Do not hard-code character memories into a giant system prompt
- Do not let the LLM rewrite identity without the evolution pipeline
- Do not auto-download multi-GB models
- Do not implement fake “learning”
- Do not start with RL or complex multi-game support
- Do not use Electron if Tauri is practical later

---

Next step after this document: implement Phase 1 foundation.