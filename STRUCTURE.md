# Project Structure

## AI Instructions

**When making structural changes** (adding new files, moving files, creating new modules, renaming directories):

1. **Update this file** — add/remove/rename entries to match the actual structure.
2. **Keep this file accurate** — it is the source of truth for AI agents navigating the codebase.
3. **Update GOALS.md** — if the structural change relates to a goal, update the goal status or notes.
4. **Verify imports** — after moving/renaming files, check that all imports across the project still resolve.
5. **Check for orphaned references** — grep for old filenames/paths that may reference moved files.

---

## Root

```
ai-vtuber/
├── GOALS.md              # Project goals, status tracking, AI check-in rules
├── STRUCTURE.md          # This file — project layout and AI update instructions
├── README.md             # User-facing setup and usage guide
├── SETUP.bat             # First-time setup (Windows)
├── START.bat             # Quick start (Windows)
├── .gitignore
├── assets/               # Static assets (images, references, etc.)
├── config/               # Runtime configuration
│   ├── config.yaml       # Active config
│   └── config.example.yaml
├── data/                 # Runtime data (SQLite DB, logs, etc.)
│   └── character-profiles/ # Markdown personas and editable trait library
├── docs/                 # Documentation
├── tests/                # Test files
└── tools/                # External tool binaries/repos
    ├── index-tts/        # Index-TTS engine
    ├── llama.cpp/        # llama.cpp server binary
    └── zonos/            # Zonos TTS + reference voices
        └── reference_voices/
            └── onakami.wav
```

---

## Backend (`backend/`)

Python FastAPI server. Runs on port 8000.

```
backend/
├── pyproject.toml
├── requirements.txt
├── .env.example
├── data/                 # Backend-specific data files
├── logs/                 # Application logs
├── tests/                # Backend tests
└── app/
    ├── __init__.py
    ├── main.py           # FastAPI app entry point, middleware, startup
    │
    ├── api/              # HTTP routes and integrations
    │   ├── routes.py     # ALL REST endpoints: /chat, /tts, /stt, /status,
    │   │                 #   /memories, /goals, /skills, /conversations, etc.
    │   │                 #   Also: emotion detection (_update_emotions_from_text),
    │   │                 #   expressive triggers, smart emotion computation
    │   ├── integrations.py  # Integration config endpoints (Discord/Spotify/Twitch settings)
    │   └── discord_bridge.py  # Discord voice bridge (WebSocket + REST)
    │
    ├── character/        # Character state and prompt management
    │   ├── profiles.py   # Markdown profile parsing, migration, and activation
    │   ├── prompt.py     # build_messages() — assembles LLM prompt from character state,
    │   │                 #   history, memories, goals. Handles role alternation sanitization.
    │   ├── service.py    # load_character_state() — loads full character from DB
    │   └── state.py      # CharacterState, EmotionSnapshot (8-axis), Personality dataclasses
    │
    ├── core/
    │   └── config.py     # Pydantic settings (env vars, config.yaml loading)
    │
    ├── db/
    │   ├── base.py       # SQLAlchemy declarative base
    │   └── session.py    # Async engine + session factory (SQLite)
    │
    ├── llm/              # LLM provider abstraction
    │   ├── base.py       # BaseLLM protocol, ChatMessage dataclass
    │   └── openai_compatible.py  # OpenAI-compatible client (llama.cpp, OpenAI, etc.)
    │
    ├── models/           # SQLAlchemy ORM models
    │   └── character.py  # Character, Conversation, Message, Memory, EmotionalState,
    │                     #   Goal, Skill, Proficiency tables
    │
    ├── schemas/          # Pydantic request/response schemas
    │   └── chat.py       # ChatRequest, ChatResponse (with expressive_label),
    │                     #   StatusResponse, MemoryCreate, GoalCreate, SkillCreate, etc.
    │
    ├── memory/           # (Reserved) Memory retrieval and consolidation logic
    │
    ├── agent/            # (Reserved) Autonomous agent behaviors
    │
    └── integrations/
        └── discord_worker.py  # Background Discord worker process
```

### Key Backend Patterns

- **Emotion detection** lives in `routes.py`: `_EMOTION_KEYWORDS` (~100 patterns), `_EXPRESSIVE_TRIGGERS` (40+ high-intensity patterns), `_EXPRESSIVE_FACE_MODIFIERS`, `_NEGATION_PREFIXES`
- **`_update_emotions_from_text()`** — returns `str | None` (expressive label), processes both subtle and high-intensity triggers
- **`_compute_smart_emotions()`** — returns `dict[str, Any]` including `expressive_label` for frontend Live2D
- **`build_messages()`** in `prompt.py` — handles role alternation sanitization for Qwen2.5 Jinja template
- **Chat flow**: `/chat` → `_process_chat()` → build prompt → LLM generate → update emotions → save to DB → return `ChatResponse`

---

## Frontend (`frontend/`)

React + Vite + TypeScript. Runs on port 5173 (dev server).

```
frontend/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── postcss.config.js
├── dist/                 # Built output
├── public/
│   └── live2d/           # Live2D model files (Shizuku)
│       └── shizuku_ja/runtime/
│           ├── shizuku.model3.json
│           └── shizuku.cdi3.json  # 43+ parameter definitions
└── src/
    ├── main.tsx           # React entry point
    ├── App.tsx            # Root component, polling, channel routing
    │                     #   ChannelContent routes: chat → ChatPanel,
    │                     #   live → LiveMode, settings → SettingsPanel, etc.
    ├── index.css          # Global styles
    ├── types.ts           # Shared TypeScript types (ChatMessage, ChatResponse, etc.)
    ├── vite-env.d.ts      # Vite type declarations
    │
    ├── stores/
    │   └── appStore.ts    # Zustand store — ALL application state:
    │                     #   activeServer, activeChannel, channelMessages (per-channel),
    │                     #   channelConversations (per-channel), character, emotions,
    │                     #   liveMode, avatarMode, chatEmotion, expressiveLabel,
    │                     #   isThinking, isMuted, isDeafened, channels, servers, etc.
    │                     #   Migration: old flat messages/conversationId → per-channel
    │
    ├── hooks/
    │   ├── useLive2d.ts   # Live2D hook — init, resize, emotion→face presets (8 base + 7 expressive),
    │   │                 #   voiceState overrides, lip sync, mouse tracking, animation loop
    │   └── useBridgeEvents.ts  # WebSocket hook for real-time Discord bridge events
    │                         #   Connects to /api/ws/bridge-events, dispatches to store
    │
    ├── lib/
    │   ├── api.ts         # ALL API functions: sendChat, sendProactiveChat, fetchSTT,
    │   │                 #   fetchTTS, fetchMemories, createMemory, fetchMessages, etc.
    │   └── sounds.ts      # UI Sound Effects (13 Web Audio API synthesized sounds):
    │                     #   sfxClick, sfxMessage, sfxError, sfxConnect, sfxDisconnect,
    │                     #   sfxToggleOn, sfxToggleOff, sfxSend, sfxNotification, etc.
    │
    └── components/        # React components
        ├── ChannelSidebar.tsx   # Discord-style channel list, categories, context menu,
        │                       #   add/rename/delete channels
        ├── ChannelHeader.tsx    # Top bar showing current channel name
        ├── ServerSidebar.tsx    # Server icon list (chat, memory, goals, skills, games, settings, discord)
        ├── Header.tsx           # Top-level header bar
        ├── StatusBar.tsx        # Connection status indicator
        │
        ├── ChatPanel.tsx        # Text chat — message list, input, voice recording,
        │                       #   uses per-channel state (channelMessages[activeChannel])
        ├── LiveMode.tsx         # Live voice conversation — VAD, STT, LLM, TTS loop,
        │                       #   Live2D/Orb display, transcript overlay, chat sidebar,
        │                       #   mute/deafen/disconnect controls. Channel: "live"
        │
        ├── Live2DCanvas.tsx     # Live2D rendering canvas — accepts emotion, voiceState, expressiveLabel
        ├── OrbAnimation.tsx     # CSS orb animation (fallback for Live2D)
        ├── AvatarPanel.tsx      # Avatar settings and controls
        │
        ├── SmartBar.tsx         # Smart input bar (command palette)
        ├── ContextMenu.tsx      # Right-click context menu component
        ├── RenameModal.tsx      # Modal for renaming channels
        │
        ├── SettingsPanel.tsx    # Settings hub — routes to sub-panels by section
        ├── DiscordSettingsPanel.tsx  # Discord bot config + bridge control panel
        ├── IntegrationsPanel.tsx     # Spotify/Twitch integration config
        ├── MasterPresets.tsx    # Master preset management
        ├── LogsPanel.tsx        # Application logs viewer
        ├── MemoryPanel.tsx      # Memory management (episodic, semantic, relationships)
        ├── GoalsPanel.tsx       # Goal tracking UI
        ├── SkillsPanel.tsx      # Skill/proficiency UI
        └── GamesPanel.tsx       # Games (20 Questions, Trivia, Tic-Tac-Toe, etc.)
```

### Key Frontend Patterns

- **Zustand store** (`appStore.ts`) is the single source of truth. All state flows through it.
- **Per-channel state**: `channelMessages: Record<string, ChatMessage[]>`, `channelConversations: Record<string, string | null>`. Messages scoped by `addMessage(channelId, msg)`.
- **Bridge state**: `bridgeConnected`, `bridgeMessages: BridgeMessage[]`, `bridgeVoiceState`. Updated by `useBridgeEvents` WebSocket hook in real-time.
- **Stable selectors**: Never use `?? []` or `?? null` inside Zustand selectors — creates new references each render, causing infinite loops. Use `const msgs = value ?? []` outside the selector instead.
- **`useLive2d` hook**: Accepts `emotion`, `voiceState`, `expressiveLabel`. Animation loop checks expressiveLabel first (overrides base emotion), falls back to emotion.
- **Emotion flow**: Backend `_update_emotions_from_text()` → `ChatResponse.expressive_label` → frontend `setExpressiveLabel()` → `useLive2d` → face preset selection.
- **UI sounds**: All synthesized via Web Audio API (no audio files). Import from `lib/sounds.ts`.

---

## Scripts (`scripts/windows/`)

Startup and setup scripts for Windows:

```
scripts/windows/
├── 00_check_prerequisites.bat   # Check Python, Node, git
├── 01_install_dependencies.bat  # pip install + npm install
├── 02_download_llm_model.bat    # Download Qwen2.5-14B-Instruct GGUF
├── 03_download_voice_models.bat # Download Index-TTS / Zonos models
├── 04_download_live2d.bat       # Download Live2D model files
├── 05_start_llamacpp.bat        # Start llama.cpp server (port 8081)
├── 06_start_backend.bat         # Start FastAPI backend (port 8000)
├── 07_start_frontend.bat        # Start Vite dev server (port 5173)
├── SETUP_EVERYTHING.bat         # Run all setup steps
└── START_ALL.bat                # Kill old processes + start all services
                                #   5-layer kill: port kill, window title, process name,
                                #   command line, final port sweep
```

---

## Runtime Architecture

```
User Browser (localhost:5173)
    │
    ├─→ Vite Dev Server (port 5173)
    │       └─→ React App (ChatPanel, LiveMode, Live2D, etc.)
    │
    ├─→ FastAPI Backend (port 8000)
    │       ├─→ llama.cpp LLM (port 8081)
    │       ├─→ Index-TTS (port 8090)
    │       ├─→ Zonos TTS (port 8091)
    │       ├─→ faster-whisper (local, no port)
    │       └─→ SQLite database (data/)
    │
    └─→ Live2D (WebGL, in-browser)
```

### Service Ports

| Service | Port | Notes |
|---------|------|-------|
| Vite dev server | 5173 | Frontend |
| FastAPI backend | 8000 | REST API |
| llama.cpp | 8081 | Local LLM inference |
| Index-TTS | 8090 | Chinese TTS engine |
| Zonos TTS | 8091 | Voice cloning TTS |

---

## Environment

- **OS**: Windows (win32)
- **Python**: 3.14.5 (`.venv` in `backend/`)
- **Node**: via npm
- **GPU**: NVIDIA RTX 5070, driver 610.88, CUDA UMD 13.3
- **LLM Model**: Qwen2.5-14B-Instruct-Q4_K_M.gguf (8.37GB)
- **uv**: `C:\Users\leand\AppData\Local\hermes\bin\uv.exe`

### Backend Start Command
```
PYTHONPATH=backend && cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Note: Do NOT use `--reload` — causes SQLite "database is locked" errors.

### Frontend Build Check
```
cd frontend && npx tsc --noEmit && npx vite build
```

---

## Known Gotchas

1. **Zustand selectors**: Never use `?? []` or `?? null` inside a selector — creates infinite re-render loops. Return `undefined` and default at usage site.
2. **SQLite locking**: No `--reload` flag on uvicorn. Kill and restart the backend process instead.
3. **PowerShell**: Use `;` not `&&` for command chaining.
4. **LiveMode stale closures**: VAD interval captures functions from first render. Use refs for any function called from `setInterval`.
5. **Voice reference**: Default is `tools/zonos/reference_voices/onakami.wav`. Cloud `LoadAudio` can't see uploaded files — generate audio in-graph.
6. **Qwen2.5 template**: `build_messages()` must sanitize role alternation (no consecutive same-role messages).
