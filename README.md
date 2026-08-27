# Persistent AI Character / Autonomous AI VTuber

An open-source, modular system for creating **persistent anime-style AI characters** with long-term memory, personality evolution, voice interaction, Live2D avatar, tools, and optional game agents.

**Current release:** `0.1.0` · **Status:** active alpha development · **Platform:** Windows desktop/portable and browser-based local development

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

### Avatar & Voice
- Live2D Cubism Web SDK with six normalized models, expressions, gestures, idle animation, and lip sync
- NVIDIA NeMo/Nemotron streaming ASR on CUDA, with Faster-Whisper fallback
- Zonos, Index-TTS, Edge TTS, and OpenRouter/Fish Audio-compatible TTS paths

### Local LLM
- llama.cpp OpenAI-compatible server
- Ollama
- Any OpenAI-compatible endpoint

---

## Project Status

The project is beyond the original chat-only prototype. The current `0.1.0`
release is usable for local development and packaged Windows testing; model
weights and third-party assets remain user-managed.

| Area | Status | Current implementation |
|------|--------|-----------------------|
| Core chat and LLM abstraction | Implemented | OpenAI-compatible local/hosted providers, model switching, per-channel history, and explicit preset management |
| Tool calling | Implemented | Validated native/prompt fallbacks for Spotify, Discord, avatar actions, and integration tools |
| Character and memory | Implemented | Markdown persona profiles plus SQLite conversations, emotions, memories, goals, and skills |
| Voice pipeline | Implemented | Nemotron/NeMo streaming STT on CUDA, Faster-Whisper fallback, TTS engine fallback, voice references, and model unloading |
| Live2D avatar | Implemented | Six normalized models, smart expressions, semantic gestures, lip sync, speaking states, and varied idle animation |
| Discord integration | Implemented | Equicord/client and bot transports, channel routing, tool calls, voice join, two-way voice audio, and VB-CABLE output |
| Spotify integration | Implemented | OAuth, track resolution, playback/queue/volume/favorites/status tools, and parser compatibility fallback |
| Dataset editing | Beta | Standalone Dataswipe workspace with card swiping, structured editing, name replacement, history, and export |
| Desktop application | Implemented | `Vtubecord.exe`, terminal-free bundled server, portable ZIP, NSIS/MSI installer, and GitHub updater |
| Memory retrieval and autonomy | In progress | Autonomous live-voice brain is available; richer vector retrieval and multimodal attention remain future work |

## Current goals

- Harden the Discord/Equicord bridge contract, especially reliable mute/deafen
  commands and strict error reporting for unsupported bridge actions.
- Improve model lifecycle and performance: smaller frontend chunks, predictable
  sidecar startup, and continued GPU/VRAM-aware model unloading.
- Expand the integration tool registry with OBS controls, Twitch ingestion and
  moderation, screen/vision tools, and structured game adapters.
- Strengthen memory quality with embeddings/vector retrieval, conflict history,
  and better cross-channel summaries while preserving per-channel privacy.
- Keep the Windows installer, portable build, updater, documentation, and model
  license/attribution flow reproducible for each tagged release.

See [CURRENT_IMPLEMENTATION_STATUS.md](docs/CURRENT_IMPLEMENTATION_STATUS.md)
for the detailed implementation inventory and verification notes.

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

The latest tagged Windows artifacts are published on the
[Vtubecord GitHub releases page](https://github.com/levox00/Vtubecord/releases).
The portable build keeps writable runtime data under
`%LOCALAPPDATA%\\Vtubecord`; it does not include model weights.

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
- [CURRENT_IMPLEMENTATION_STATUS.md](docs/CURRENT_IMPLEMENTATION_STATUS.md)
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
