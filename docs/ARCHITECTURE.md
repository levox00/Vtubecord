# Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (React + Vite)                       │
│  Live2D Canvas │ Chat │ Status Bar │ Memory UI │ Goals │ Settings   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ WebSocket + REST
┌───────────────────────────────▼─────────────────────────────────────┐
│                     FastAPI Backend (Modular Monolith)               │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ Character   │  │ Agent        │  │ Memory      │  │ Emotion   │ │
│  │ Engine      │  │ Controller   │  │ System      │  │ System    │ │
│  └─────────────┘  └──────────────┘  └─────────────┘  └───────────┘ │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │ LLM         │  │ Tool         │  │ Goal        │  │ Event Bus │ │
│  │ Providers   │  │ System       │  │ System      │  │           │ │
│  └─────────────┘  └──────────────┘  └─────────────┘  └───────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    Database Layer (SQLAlchemy)                 │ │
│  │  SQLite (dev)  /  PostgreSQL + pgvector (prod)                 │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Rule: The LLM is Not the Character

```
Character State (Database)
    ├── Identity
    ├── Personality Traits (numeric + descriptive)
    ├── Emotional State
    ├── Relationships
    ├── Memories (multi-type)
    ├── Goals
    ├── Skills
    ├── Experiences
    └── Conversation History

         │
         ▼
   Prompt Builder
         │
         ▼
   LLM Provider (replaceable)
         │
         ▼
   Structured Response
         │
         ▼
   Action Executor + State Updater
```

The character survives model swaps because all durable state lives outside the LLM.

## Major Subsystems

### 1. Character Engine
Owns the persistent identity and state.  
Never lets the LLM rewrite core identity or personality without going through the controlled evolution pipeline.

### 2. Memory System
- Short-term (conversation context)
- Episodic
- Semantic
- Relationship
- Skill
- Experience (games)

Retrieval is selective + embedding-based.  
Consolidation happens after conversations via MemoryExtractor.

### 3. Agent Controller
Perceive → Remember → Reason → Plan → Act → Observe → Reflect → Learn

Supports both reactive and proactive behavior.

### 4. LLM Abstraction
```python
class LLMProvider(Protocol):
    async def generate(...) -> LLMResponse: ...
```

Implementations:
- OpenAI-compatible
- Anthropic
- Gemini
- Ollama
- llama.cpp server
- Generic OpenAI-compatible endpoints

### 5. Event Bus
Internal pub/sub for:
- USER_MESSAGE
- AI_RESPONSE
- MEMORY_CREATED
- GOAL_CREATED / COMPLETED
- EMOTION_CHANGED
- TOOL_CALLED
- etc.

### 6. Tool System
Permissioned tools with levels:
- READ_ONLY
- SAFE_ACTIONS
- USER_APPROVAL_REQUIRED
- FULL_CONTROL

### 7. Avatar Layer (Phase 2+)
Live2D Cubism Web.  
Emotion → expression mapping.  
Mouth sync driven by TTS.

## Data Flow (Chat Turn)

```
User Message
    → WebSocket
    → Agent Controller
        → Retrieve relevant memories + current state
        → Build dynamic prompt (identity + personality + emotion + memories + goals + tools)
        → Call LLM Provider
        → Parse structured response (speech + emotion + animation + tools)
        → Execute tools (if any)
        → Update emotional state
        → Stream speech + avatar updates
        → Store message
        → (async) Memory extraction & consolidation
```

## Database Philosophy

- All character state is relational + vector.
- Foreign keys and timestamps everywhere.
- Alembic migrations from day one.
- SQLite for zero-config local use.
- PostgreSQL + pgvector when you need scale / advanced retrieval.

## Extensibility

- New LLM → implement LLMProvider
- New game → implement GameAdapter
- New tool → implement Tool interface + register with permission
- New TTS/ASR → implement provider protocol

## Security Boundaries

- API keys never in database (env / OS credential store)
- Tools require explicit user-enabled permissions
- Dangerous actions require confirmation
- Audit log for all tool executions
- No unrestricted shell from the LLM

---

See also:
- DEVELOPMENT.md for phased roadmap
- MEMORY.md for memory architecture details
- PERSONALITY.md for evolution rules