# Persistent AI Character / Autonomous AI VTuber

An open-source, modular system for creating **persistent anime-style AI characters** with long-term memory, personality evolution, voice interaction, Live2D avatar, tools, and optional game agents.

**Core Principle:** The LLM is **not** the character.  
The character is a persistent state owned by this application.  
You can switch between local LLMs (llama.cpp, Ollama) and hosted APIs (OpenAI, Anthropic, Gemini, etc.) without losing identity, memories, relationships, goals, or personality.

## UI preview

The Discord-inspired workspace includes a Live2D preview, smart-emotion
controls, and configurable idle animation presets:

![Vtubecord Avatar and Live2D settings](docs/media/vtubecord-avatar-settings.jpg)

The short animated walkthrough below shows the same settings surface with
different idle presets selected:

![Vtubecord Live2D settings walkthrough](docs/media/live2d-ui.gif)

[Download the MP4 walkthrough](docs/media/live2d-ui.mp4)

---

## Quick Philosophy

- Static character persona profiles live in editable Markdown files; live emotions,
  adaptive personality, memories, and conversations live in the database.
- LLM is a replaceable reasoning engine.
- Memory is multi-type, retrieved selectively, and consolidated.
- Personality evolves slowly through reflection, never silently overwritten.
- Everything is modular and permissioned.

---

## Technology Stack

### Backend
- Python 3.12+
- FastAPI + asyncio
- Pydantic v2
- SQLAlchemy 2.0 + Alembic
- PostgreSQL + pgvector (production) / SQLite (local/dev)
- uv for dependency management
- Ruff + Pytest

### Frontend
- TypeScript + React + Vite
- Tailwind CSS
- Zustand
- WebSocket for real-time updates

### Avatar & Voice (later phases)
- Live2D Cubism Web SDK (Shizuku sample for development)
- Faster-Whisper / Whisper-compatible ASR
- Piper TTS (local default)

### Local LLM
- llama.cpp OpenAI-compatible server
- Ollama
- Any OpenAI-compatible endpoint

---

## Project Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | In Progress | Backend, Frontend, Chat, LLM abstraction, Character Profile |
| Phase 2 | Planned | Voice pipeline + Live2D |
| Phase 3 | Planned | Full memory system |
| Phase 4 | Planned | Autonomy, goals, proactive behavior |
| Phase 5 | Planned | Computer control & vision |
| Phase 6 | Planned | Game adapter (one game) |
| Phase 7 | Planned | Game learning / RL baseline |
| Phase 8 | Planned | Long-term personality evolution |

---

## Easy Setup

### Windows
1. Install [Python 3.12+](https://www.python.org/downloads/) (check “Add to PATH”) and [Node.js 20+](https://nodejs.org/)
2. Double-click **`SETUP.bat`** — guided install + optional model downloads
3. (Optional) Put `llama-server.exe` in `tools\\llama.cpp\\` from [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)
4. Double-click **`START.bat`**
5. Open http://localhost:5173

For an installed desktop application, use the Vtubecord target in
[`desktop/README.md`](desktop/README.md). It builds `Vtubecord.exe` and a
Windows installer that embeds the UI and starts the backend without terminal
windows.

### Linux / macOS
```bash
chmod +x scripts/linux/*.sh
./scripts/linux/SETUP_EVERYTHING.sh
./scripts/linux/START_ALL.sh
```

See [INSTALLATION.md](docs/INSTALLATION.md) for full details, paths, and troubleshooting.

---

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [INSTALLATION.md](docs/INSTALLATION.md)
- [LOCAL_MODELS.md](docs/LOCAL_MODELS.md)
- [HOSTED_MODELS.md](docs/HOSTED_MODELS.md)
- [MEMORY.md](docs/MEMORY.md)
- [PERSONALITY.md](docs/PERSONALITY.md)
- [THIRD_PARTY_LICENSES.md](docs/THIRD_PARTY_LICENSES.md)

---

## License

This project is intended to be open-source friendly.  
All third-party models, voices, and avatars have their own licenses — see `THIRD_PARTY_LICENSES.md`.

**Important:** Never redistribute multi-GB models or Live2D assets without checking their licenses.

---

## Disclaimer

This is **not** a clone of Neuro-sama or any proprietary VTuber system.  
It is an original architecture inspired by the technical concept of a persistent AI character.
