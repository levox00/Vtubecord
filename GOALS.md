# Project Goals

## Rules for Goal Completion

1. **Only the user marks goals as done.** The AI must NEVER mark a goal as complete on its own. A goal is only done when the user explicitly says "mark [goal] as done" or equivalent.
2. **The AI must ask the user about progress regularly.** After each session or significant chunk of work, the AI should check in with the user about which goals are in progress and what needs attention.
3. **The user reports progress.** When asked, the user describes how much is done and what still needs refinement or adjustment.
4. **The AI updates goals accordingly.** Based on the user's feedback, the AI updates the status, notes, and sub-tasks in this file.

## Goal Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done (confirmed by user only)
- `[!]` Blocked
- `[-]` Cancelled

---

## Core AI Brain

- [x] Local LLM backend via llama.cpp (Qwen2.5-14B-Instruct-Q4_K_M)
- [~] Character state system (personality, emotions, memories, goals, skills)
- [~] Emotional state with 8-axis model (happiness, excitement, sadness, anger, fear, curiosity, confidence, frustration)
- [~] Expressive emotion detection from text (high-intensity triggers + subtle keywords + negation awareness)
- [x] Prompt building with role alternation sanitization for Qwen2.5 Jinja template
- [~] Chat history persistence via SQLite (SQLAlchemy async)
- [~] Per-channel message history (general, character, live channels have separate conversations)
- [~] AI brain (character state, memories, emotions) shared globally across all channels

## Voice Pipeline

- [~] Index-TTS engine integration (Chinese voice synthesis)
- [~] Zonos TTS engine integration (voice cloning with reference audio)
- [x] Edge-TTS as fallback engine
- [x] Engine priority chain (Index-TTS > Zonos > Edge-TTS)
- [x] Whisper STT via faster-whisper (local transcription)
- [x] Voice reference "onakami" extracted and set as default
- [~] Live voice conversation mode (VAD + STT + LLM + TTS loop)
  - [x] VAD stale closure fix — use refs for handleSend and processRecordedAudio
  - [x] Mute fix — stop recording but let in-progress STT/LLM/TTS complete
  - [x] Live channel routing fix — App.tsx now renders LiveMode for "live" channel
  - [ ] Voice quality tuning and latency optimization

## Live2D Avatar

- [~] Live2D model loading (Shizuku)
- [ ] Reusable `useLive2d` hook (init, resize, emotion motions, lip sync, mouse tracking)
- [ ] 8 base emotion face presets (happy, sad, angry, surprised, fearful, confident, curious, frustrated)
- [ ] 7 high-intensity expressive face presets (laughing, crying, shocked, yelling, panicking, blushing, smug)
- [ ] Voice state face overrides (listening, thinking, speaking, user_speaking)
- [ ] Live2DCanvas component with emotion/voiceState/expressiveLabel props
- [ ] Avatar/Orb toggle mode in LiveMode

## UI / Frontend

- [x] Discord-style UI (server sidebar, channel sidebar, content area)
- [x] Per-channel message scoping (channelMessages record in store)
- [x] UI Sound Effects module (13 Web Audio API synthesized sounds)
- [x] Chat panel with message history
- [x] Live mode panel with VAD controls, transcript overlay, chat sidebar
- [x] Settings panels (LLM, TTS, STT, Avatar, Character, Memory, Skills, Goals)
- [x] Master presets panel
- [x] Logs panel
- [x] Games panel
- [x] Memory panel (episodic, semantic, relationships)
- [x] Goals panel
- [x] Skills panel
- [~] Channel sidebar — clicking empty space accidentally creates new channels

## Integrations

- [x] Discord bot config UI
- [x] Discord Bridge (WebSocket + REST, Equicord AIBridge userplugin)
- [x] Discord deep links for voice channel joining
- [x] Bridge bidirectional sync — real-time WebSocket events (Plugin → UI + UI → Plugin)
- [x] Bridge messages display in DiscordSettingsPanel
- [x] Spotify config
- [x] Twitch config
- [x] Process detection and auto-start scripts (START_ALL.bat with 5-layer kill)

## Backend Infrastructure

- [x] FastAPI server with async endpoints
- [x] SQLite database with SQLAlchemy async ORM
- [x] Character state management (load/save from DB)
- [x] Memory system (episodic, semantic, relationships)
- [x] Goal tracking system
- [x] Skill/proficiency system
- [x] Proactive AI speech endpoint
- [x] WebSocket support
- [x] Health/status endpoints

---

## Next Up (Unordered)

These are known issues and features that need work. The AI should ask the user which to prioritize.

1. ~~**Fix LiveMode VAD stale closures**~~ — DONE
2. ~~**Fix mute behavior**~~ — DONE
3. ~~**Fix live channel routing**~~ — DONE
4. ~~**Fix empty-space channel creation**~~ — DONE (pointer-events-none)
5. ~~**AI bridge bidirectional sync**~~ — DONE (WebSocket events + store)
6. **Per-channel backend isolation** — verify that general and character channels actually get separate conversation_ids on the backend
7. **Voice latency optimization** — reduce STT + LLM + TTS round-trip time
8. **Memory consolidation** — automatic memory pruning and importance scoring
9. **Multi-character support** — ability to switch between different AI personas
10. **Image generation integration** — ComfyUI or partner API for image generation in chat
