# Current Implementation Status

**Snapshot date:** 2026-08-23 (Europe/Berlin)  
**Project:** AI VTuber  
**Scope:** Current code, assets, configuration schemas, installed Equicord bridge, live backend state, and verification results.

> This is a current-state inventory, not a Git changelog. It is versioned with the project so implementation details can be compared against tagged releases. Secrets, tokens, and Discord IDs are intentionally omitted.

## Executive summary

The project is now substantially beyond the original chat-only prototype. It currently includes:

- provider-neutral LLM tool calling for Qwen, Gemma, Llama/Hermes, NVIDIA/Nemotron/Minitron/Mistral-Nemo, and generic OpenAI-compatible models;
- semantic tool selection with native tool calling, prompt-protocol fallbacks, schema validation, duplicate protection, and safe result handling;
- a working Spotify integration with OAuth, playback tools, tolerant track resolution, and a compatibility parser fallback;
- a hybrid Discord integration supporting Equicord/client mode and bot mode, channel-triggered AI replies, message delivery, voice join/leave, and two-way Discord voice audio;
- six normalized Live2D models with multiple idle animations, gestures, expressions, voice states, lip sync, and AI-selected semantic avatar actions;
- visible tool-use badges beside message emotions and focused console logging for tool calls;
- persistent character profiles, conversations, emotions, memories, goals, and skills;
- a browser-based dataset editor for importing, filtering, editing, and exporting training data.

The live backend was healthy during this inventory. Spotify and Discord were connected, the Equicord bridge had one active connection, and Discord voice input was listening. The most important remaining integration defect is that the backend exposes Discord mute/deafen tools, but the installed Equicord AIBridge does not yet implement their command names reliably.

## Live runtime snapshot

The following describes the running application at the time of the snapshot, rather than hard-coded defaults.

### Core services

- Backend: online at `127.0.0.1:8000`.
- LLM provider: OpenAI-compatible local endpoint at `http://127.0.0.1:8081/v1` (moved from 8080 to avoid Discord/Chromium remote-debugging conflicts).
- Active model: `Mistral-NeMo-Minitron-8B-Instruct-Q4_K_M.gguf`.
- Generation settings: temperature `0.85`, maximum output `1024` tokens.
- Active avatar: `/live2d/mao_pro/runtime/mao_pro.model3.json`.
- Smart avatar expressions: enabled.
- Active TTS: Edge TTS, `en-US`, smart emotion mode, fixed seed.
- Active STT: NVIDIA NeMo/Nemotron streaming ASR on CUDA, using `nemotron-3.5-asr-streaming-0.6b` and 80 ms chunks.

### Integration state

- Discord: enabled, configured, and connected.
- Spotify: enabled, configured, authenticated, and connected.
- Twitch: disabled and not configured.
- Equicord Discord bridge: connected with one active client connection.
- Discord voice output: ready on a 48 kHz VB-CABLE device; bridge and Discord voice state connected.
- Discord voice input: running and listening; NeMo sidecar ready; queue empty and no current error.
- Spotify playback: connected, but no active track or playback device was present at the instant of the snapshot. Playback commands still require an active Spotify device.

### Active Discord behavior

- Discord client transport is active against Discord PTB.
- A server, text-speaking channel, and voice channel are configured.
- Command prefix: `ai!`.
- Respond-to-every-message and automatic replies: enabled.
- Channel mode: all channels; channel and user filter lists are empty.
- Live voice join: enabled.
- Auto-join and follow-message-author voice behavior: currently disabled.
- AI voice output: enabled through `CABLE-B Input`.
- Discord voice capture: enabled through `CABLE-A Output`.
- Voice transcripts and generated text are currently mirrored into the web UI.

## Architecture now implemented

```text
Discord / Spotify / Web UI / Microphone
                 |
          Integration events
                 |
       Conversation + agent route
                 |
        OpenAI-compatible LLM
                 |
      Semantic/native tool loop
          /              \
 Spotify/Discord tools   Avatar action
          |                 |
 External service      Animation director
          |                 |
     Result to LLM      Live2D renderer
          \                 /
            TTS + UI output
```

The LLM chooses a bounded, named action and supplies structured arguments. Integration and animation code remains responsible for validating the request and performing it. The model is not given arbitrary Live2D parameters, Discord API access, or Spotify API access.

## LLM tool-calling system

### Model compatibility

The tool layer is provider-neutral internally and supports these OpenAI-compatible model families:

- Qwen;
- Gemma;
- Llama and Hermes-style templates;
- NVIDIA Nemotron, Minitron, and Mistral-Nemo variants;
- generic OpenAI-compatible servers and models.

The adapter accepts several response formats because local servers and chat templates do not all emit tool calls the same way:

- native OpenAI `tool_calls`;
- legacy `function_call`;
- strict `<tool_call>...</tool_call>` blocks;
- fenced `tool_call` JSON;
- NVIDIA/Hermes `TOOLCALL:` wrappers;
- typed-value argument objects produced by some older Gemma templates.

Tool-result messages can also be flattened for strict templates that require alternating user and assistant roles.

### Selection and fallback flow

1. Tool schemas are sent natively to servers that accept OpenAI-compatible `tools` and `tool_choice` fields.
2. If a local server rejects those fields, the request is retried with a prompt-based structured tool protocol.
3. A semantic action router can make a deterministic, zero-temperature tool decision from a reduced set of intent-relevant candidates.
4. The older command parser remains a final compatibility safety net; it is not the primary decision system.
5. Tool results are sent back to the LLM before a success response is generated.

The router includes an explicit no-action option, so ordinary conversation is not forced into a tool call.

### Safety and reliability

- Tools live in an explicit allowlisted registry.
- Arguments are checked against JSON schemas.
- Integration availability is checked before execution.
- Tool errors are converted into safe, model-readable failures.
- A single turn is limited to four tool rounds and eight total tool executions.
- Duplicate calls are blocked to prevent loops and repeated external actions.
- The assistant does not claim success before receiving a successful tool result.

### Tool visibility

Every executed tool is recorded in message metadata as `tools_used`.

- Backend console format: `Tool calling feature {tool} used by {llm model}`.
- Web UI: a wrench/tool badge appears beside the emotion badge on the assistant message and names each tool used.
- Discord-originated responses preserve the same metadata when mirrored into the web UI.

### Extension point

New integrations can be added without rewriting model adapters or the semantic router:

1. create a module that defines schemas and execution functions;
2. expose a `register_*_tools` function;
3. call that registration function from the central tool factory.

This is the intended path for OBS scene/source controls, additional Discord actions, Twitch moderation, game controls, or future services.

### Main files

- `backend/app/llm/base.py`
- `backend/app/llm/tool_adapters.py`
- `backend/app/llm/openai_compatible.py`
- `backend/app/tools/registry.py`
- `backend/app/tools/router.py`
- `backend/app/tools/runtime.py`
- `backend/app/tools/factory.py`
- `frontend/src/components/ChatPanel.tsx`

## Spotify integration

### Authentication and control

Spotify supports OAuth connect, callback handling, token refresh, disconnect, and the scopes needed to inspect and modify playback.

The tool registry currently exposes:

- `spotify_play`
- `spotify_pause`
- `spotify_resume`
- `spotify_next`
- `spotify_previous`
- `spotify_set_volume`
- `spotify_adjust_volume`
- `spotify_queue`
- `spotify_set_shuffle`
- `spotify_set_repeat`
- `spotify_toggle`
- `spotify_current_track`
- `spotify_status`

The Integrations UI includes connect/disconnect controls, authorization popup handling, current-player information, previous/play-pause/next controls, and a volume slider.

### Track resolution improvements

Track requests are resolved in application code rather than trusting the model's guessed Spotify result.

- Requests such as `title by artist` are split into title and artist fields.
- A Spotify fielded search is tried first, followed by a broader fallback query.
- Candidate comparison tolerates punctuation, accents, word order, and small spelling differences.
- Title and artist thresholds prevent weak matches.
- Exact-title matches preserve Spotify ordering, avoiding cases where a famous song title is paired with the wrong artist.
- The canonical title and artist returned by Spotify are used in the final response.

The previous `Invalid limit` failure is handled in two ways: the normal search limit is a bounded numeric constant, and the integration retries without an explicit limit if Spotify still rejects that parameter.

### Parser compatibility

The command parser remains available only when native/semantic tool selection does not produce a tool call. It handles polite wrappers and common STT/typing variations for play, pause, resume, next, previous, queue, volume, toggle, and current-status commands.

### Operational note

Successful authentication does not guarantee that Spotify can start playback. Spotify must have an active playback device associated with the account. If no device is active, the UI or tool result should report that condition instead of claiming the song is playing.

### Main files

- `backend/app/integrations/spotify.py`
- `backend/app/tools/spotify.py`
- `frontend/src/components/IntegrationsPanel.tsx`
- `backend/tests/test_spotify_commands.py`

## Discord text integration

### Supported transports

- **Client/Equicord mode:** communicates with the installed AIBridge plugin over WebSocket.
- **Bot mode:** uses the configured Discord bot transport.

The backend exposes Discord bridge WebSockets and REST operations for status, sending, reactions, joining/leaving voice, channel/guild discovery, voice state, and recent events.

### Incoming message routing

Discord messages pass through server, channel, user, prefix, and bot-author filters before reaching the LLM.

- A configured server restriction can limit the integration to one guild.
- Channel mode supports all, allowlist, and blocklist behavior.
- An empty channel list in all-channel mode means all channels.
- An empty allowed-user list means all non-bot users.
- With **respond to every message** enabled, the prefix is optional.
- With that setting disabled, a non-empty prefix such as `ai!` is required.
- Leaving the prefix blank while every-message mode is disabled turns off command-style triggering.

Per-channel locks and conversation IDs keep context separated while allowing different channels to operate independently. Long outgoing responses are split below Discord's message limit. Fingerprints for outgoing client messages prevent the AI from replying to its own sent or mirrored content.

### Message delivery fix

The installed Equicord AIBridge now uses Equicord's supported `sendMessage` utility, passes the required options object, awaits the returned promise, and only acknowledges success after Discord has accepted the send operation. This fixes the case where the AI generated a reply but it never appeared in the channel because Discord PTB received an undefined message nonce/options value.

The installed development loader points to:

`C:\Users\leand\Equicord\dist\desktop`

The AIBridge implementation is located at:

`C:\Users\leand\Equicord\src\userplugins\AIBridge\bridge.ts`

### Discord tools

The backend registry currently contains:

- `discord_voice_status`
- `discord_send_message`
- `discord_set_auto_reply`
- `discord_join_voice`
- `discord_leave_voice`
- `discord_set_mute`
- `discord_set_deafen`
- `discord_speak_voice`

Voice join uses the configured voice channel, or the requesting author's channel when follow-author mode is enabled. It enables live join, verifies the actual Discord voice state, and includes a guarded retry if the connection drops.

### Equicord bridge capabilities

The installed AIBridge currently implements commands for:

- send, edit, delete, react, and typing;
- join and leave voice;
- fetch channels, guilds, members, voice members, voice state, and the current user;
- synchronize integration configuration.

It forwards message-create, voice-state, and typing events to the backend.

### Known mute/deafen compatibility gap

The backend exposes mute and deafen tools and tries several command-name aliases. The installed Equicord AIBridge command switch does not currently implement those voice-state commands.

There is also a response-semantics problem: an unknown command can be returned inside an error payload while the outer bridge response is still marked successful. That can make the backend treat an unsupported mute/deafen command as accepted but unverified, even though Discord state did not change.

Until the bridge is updated, `discord_set_mute` and `discord_set_deafen` should be considered unreliable. The bridge should implement the supported command names and return `ok: false` or throw for unknown actions; the backend should continue verifying the resulting Discord voice state before reporting success.

### Main files

- `backend/app/api/discord_bridge.py`
- `backend/app/integrations/discord_worker.py`
- `backend/app/tools/discord.py`
- `backend/app/api/integrations.py`
- `frontend/src/components/DiscordSettingsPanel.tsx`
- `frontend/src/hooks/useBridgeEvents.ts`

## Discord two-way voice

The project now implements the complete two-cable Discord audio route:

```text
Discord call audio
  -> CABLE-A Input
  -> CABLE-A Output
  -> Nemotron streaming STT
  -> LLM

LLM response
  -> TTS
  -> CABLE-B Input
  -> CABLE-B Output as Discord microphone
  -> Discord call
```

### Voice input behavior

- Streaming NeMo/Nemotron ASR is the active path.
- Faster-Whisper is available as a fallback.
- Interim transcripts can be mirrored into the web UI.
- Finalized phrases become LLM turns.
- Short fragments are merged to avoid unnatural partial requests.
- A per-channel FIFO queue preserves conversational order.
- Pending turns are bounded to avoid an unbounded backlog.

### Voice output behavior

- TTS playback is serialized so responses do not overlap.
- AI-speaking state suppresses self-transcription and echo loops.
- `discord_speak_voice` speaks its exact requested phrase once and suppresses automatic duplicate TTS for that turn.
- Text and transcript mirroring can be configured independently.

### Main files

- `backend/app/discord_voice.py`
- `backend/app/api/discord_bridge.py`
- `frontend/src/components/DiscordSettingsPanel.tsx`
- `docs/discord-voice-output.md`

## Live2D models and animation director

### Normalized models

Six models are available from `frontend/public/live2d` and have corresponding source folders under `assets/live2d`:

- Shizuku: 4 native motions.
- Hiyori Pro: 10 native motions.
- Hiyori Free: 8 native motions.
- Niziiro Mao Pro: 7 native motions and 8 model expressions.
- Miku Pro: 8 native motions.
- Miku Free: 8 native motions.

The original archives remain retained for provenance/re-extraction, including the Hiyori, Mao, Miku, and nested Shizuku archives. Each published model has a loadable `.model3.json` entry point.

### Expressions and states

Base facial states:

- happiness, excitement, sadness, anger;
- fear, curiosity, confidence, frustration.

Additional expressive states:

- laughing, crying, shocked, yelling;
- panicking, blushing, smug.

Voice/activity states:

- idle, listening, user speaking;
- processing, thinking, speaking.

### Idle and action animation

The renderer provides four portable idle variants—calm, curious, dreamy, and attentive—which rotate roughly every 5–10 seconds. Native model `Idle` motions rotate roughly every 7–12 seconds when available, with portable parameter animation as a fallback.

The animation director exposes bounded semantic gestures:

- wave, warm nod, celebrate, dance, bow;
- wink, look down, firm shake, recoil;
- head tilt, lean in, look away, laugh.

The backend selects a semantic action. The frontend maps it to model-specific motion groups or safe parameter overlays, so the LLM never manipulates raw Cubism parameters directly.

### Runtime animation features

- parameter aliases for compatibility across differently authored models;
- Mao mouth blend-shape fallback;
- autonomous blinking;
- breathing and body sway;
- pointer-based eye/head tracking;
- serialized WebGL model loading;
- audio-amplitude lip sync with a subtle speaking fallback when amplitude data is unavailable.

### Main files

- `assets/live2d/README.md`
- `frontend/src/lib/live2dModels.ts`
- `frontend/src/hooks/useLive2d.ts`
- `frontend/src/components/Live2DCanvas.tsx`
- `backend/app/avatar/actions.py`
- `frontend/public/live2d/`

## Speech systems

### Text to speech

Implemented engines:

- Zonos;
- Index-TTS;
- Edge TTS.

The requested engine is tried first. Local engines have a fallback chain, and non-selected local models are unloaded to reduce VRAM use. Reference voices are stored within the project. Edge TTS is the currently selected runtime engine.

### Speech to text

- NVIDIA NeMo/Nemotron streaming sidecar is installed and ready.
- CUDA is the active compute path.
- Current streaming chunk size is 80 ms.
- Faster-Whisper remains available as a fallback.

## Character, conversations, and memory

Character definitions use Markdown profiles and a reusable trait library. Runtime state is stored in SQLite and includes:

- conversations and per-channel conversation IDs;
- message history and metadata;
- eight-axis emotion state;
- memories, goals, and skills;
- character profile metadata;
- avatar actions and tool-use records.

The prompt builder includes character identity, user information, current state, relevant history, and tool instructions. Channel master presets are applied per request and do not overwrite the global character configuration.

The project now has a production-oriented autonomous director for live voice rooms. Broader multimodal attention across desktop vision, Twitch, games, and general non-voice activity is still future work.

### Autonomous live voice brain (added 2026-08-23)

Discord and web Live Mode voice calls now use a backend-owned event-driven executive rather than the old browser random timer. It provides persistent per-room state, structured WAIT/SPEAK/START_TOPIC/OBSERVE/REFLECT/ACT decisions, anti-spam budgets, private motivation variables, hierarchical token-budgeted context, relevance-ranked memories, rolling summaries/open loops, conservative automatic memory extraction, interaction audit records, and deny-by-default future game capabilities. Normal text chat remains non-autonomous. See `docs/VOICE_BRAIN.md`.

## Web UI

The frontend now includes:

- Discord-style server and channel navigation;
- chat and live modes;
- separated channel conversations;
- text and voice channel types;
- custom categories/channels with rename and delete operations;
- per-channel master presets;
- Live2D avatar and smart expressions;
- message emotion and tool-use indicators;
- Spotify and Discord integration controls;
- model, TTS, STT, and avatar settings;
- logs/resource monitoring;
- memory, goals, skills, and game-related surfaces.

## Dataset editor

A standalone `Dataswipe` workspace is now available in the web UI.

### Import

- Public Hugging Face datasets through the datasets-server API.
- Local folders containing JSON, JSONL, NDJSON, CSV, TSV, tab-separated, PSV, TXT, Markdown, or YAML data.

### Editing workflow

- Structured leaf-value editor.
- Hover-to-edit behavior.
- Keep/drop swipe decisions.
- Keyboard shortcuts: `Y` keep, `N` drop, `E` edit.
- Undo, reset, and history.
- Browser-local sessions and up to 20 history entries.

### Export

- Kept records can be exported as JSONL, JSON, or CSV.
- User/AI display-name replacement is applied only during export.
- Original imported data and saved source profile remain unchanged.

The editor is frontend-only and processes local files in the browser. Browsers do not persist reusable folder handles in this implementation, so resuming a local-folder session requires selecting the folder again.

Main file: `frontend/src/components/DatasetEditorPanel.tsx`.

## Verification results

### Frontend production build

`npm run build` completed successfully:

- TypeScript compilation passed.
- Vite transformed 2,558 modules.
- Production assets were generated successfully.
- The only reported concern was Vite's large-chunk warning; two generated chunks were approximately 642 kB and 738 kB before compression.

### Backend tests

Scoped backend test run:

```text
96 passed
```

The former voice-input default failure was fixed by isolating the test's intended 320 ms schema default from the user's active low-latency 80 ms runtime setting.

A full collection from the backend directory also reaches the repository-level performance-profile test and can fail to import `scripts` because the repository root is not on `PYTHONPATH`/test paths. Additionally, the backend virtual environment does not currently include pytest, so the successful scoped run used the system Python installation.

### Runtime checks

- Backend status endpoint responded successfully.
- Discord and Spotify reported connected/configured.
- Equicord reported one active bridge connection.
- Discord voice input reported listening with a ready ASR sidecar.
- Discord voice output reported a ready selected device and connected voice state.

## Known gaps and remaining work

### Confirmed defects or maintenance items

1. Implement mute/deafen command handling in Equicord AIBridge and make unknown commands fail at the outer response level.
2. Fix root/backend pytest import paths and install the test tooling in the backend virtual environment.
3. Split large frontend bundles with dynamic imports/manual chunks where practical.
4. Update older project documentation that still describes Live2D and voice as planned rather than implemented.

### Architecture still to add

- OBS tool module for scenes, sources, recording, streaming, and transitions.
- Twitch chat ingestion and moderation tools.
- Screen capture/vision model pipeline.
- Structured game-state and game-control tools.
- Embedding/vector retrieval, explicit memory-conflict history, and cross-stream multimodal attention beyond the current lexical/summary-based live voice memory system.

These should be added through the existing integration and tool registry boundaries instead of giving the LLM direct access to external APIs or raw UI/avatar parameters.

## Documentation notes

- `README.md` contains the user-facing release status and current goals.
- `STRUCTURE.md` still focuses on the earlier Shizuku layout and does not include
  every current tool, model, Discord voice, or dataset-editor path.

This file remains the detailed technical handoff; the README is the shorter
release-oriented overview.

## Key file map

```text
backend/app/llm/                  Model providers and tool-call adapters
backend/app/tools/                Registry, router, runtime, Spotify/Discord tools
backend/app/integrations/         Spotify and Discord integration services
backend/app/api/discord_bridge.py Equicord bridge and Discord event transport
backend/app/discord_voice.py      Two-way Discord voice orchestration
backend/app/avatar/actions.py     Semantic avatar action selection
frontend/src/components/         Chat, integrations, Discord, Dataset editor UI
frontend/src/hooks/useLive2d.ts   Live2D runtime animation behavior
frontend/src/lib/live2dModels.ts  Model catalog and normalization
frontend/public/live2d/           Browser-loadable Live2D assets
assets/live2d/                    Source models, retained archives, asset notes
docs/discord-voice-output.md      Discord audio routing guide
```
