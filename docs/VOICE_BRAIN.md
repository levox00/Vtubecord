# Autonomous Live Voice Brain

## Purpose and scope

The voice brain turns the AI from a request/response chatbot into an event-driven participant in live voice rooms. It is deliberately scoped to:

- the web UI Live Mode voice room;
- an actively connected Discord voice call.

Normal text chat does not create an autonomous session. Discord text routing remains controlled by its existing prefix/channel/user settings.

This is a Neuro-style architectural pattern—perception, memory, executive decision, character generation, tools, and delivery—not a claim about Neuro-sama's private implementation.

## What changed from the old proactive timer

The previous Live Mode implementation checked a browser timer every three seconds and randomly called `/chat/proactive` after roughly 12–25 seconds. It had no persistent state, no Discord equivalent, no real relevance decision, and its history-level system instruction was removed by prompt sanitization.

The replacement is owned by the backend:

```text
Live voice surface
      |
      v
Perception event queue  <---- timer wake / future game events
      |
      v
Persistent session + internal state
      |
      v
Executive LLM decision
  WAIT | OBSERVE | REFLECT | SPEAK | START_TOPIC | ACT
      |                              |
      |                              v
      |                     allowlisted capability
      v
Hierarchical context + character generation
      |
      +----> web Live Mode WebSocket -> browser TTS
      |
      +----> Discord voice adapter -> VB-CABLE -> call
```

The executive decides **whether and why** to act. The character generation pass decides **how to express the selected thought**. The animation, TTS, Discord, and future game adapters remain responsible for execution.

## Runtime components

### Persistent voice sessions

Every live surface receives an independent session ID and persistent state:

- surface and channel key;
- conversation ID;
- enabled/active state and current phase;
- last user/AI activity;
- proactive hourly budget;
- internal motivation state;
- compressed conversation summary;
- unresolved conversational threads;
- turns since the last reflection.

Discord sessions use `discord_voice:<channel>` internally. Web sessions use an isolated `web_voice:<channel>:<uuid>` identity so separate rooms/tabs cannot race each other.

### Perception events

Events contain:

- event type;
- source;
- priority from 0–100;
- structured payload;
- creation time and processing decision.

The in-memory queue is bounded and expires stale perceptions. The database retains an audit record for debugging and future evaluation datasets.

Currently produced events include session start and user speech. The public event API is also the future ingress point for:

- Minecraft/game state and rewards;
- player damage/death/inventory changes;
- screen/vision observations;
- a human joining/leaving the call;
- music/application state;
- calendar or stream events.

### Internal state

The controller maintains bounded 0–1 behavioral variables:

- curiosity;
- social drive;
- boredom;
- energy;
- focus;
- uncertainty.

These are behavioral control signals, not claims of human emotion. They evolve from silence and events and are private prompt context. The spoken character is explicitly told never to mention the values, director, timers, or scoring.

### Executive decisions

The decision model returns one structured JSON action:

- `WAIT`: nothing worth doing;
- `OBSERVE`: retain attention and wake sooner;
- `REFLECT`: refresh summary/open loops/memory candidates;
- `SPEAK`: make a relevant comment/reaction;
- `START_TOPIC`: begin a specific worthwhile topic;
- `ACT`: execute an explicitly allowlisted autonomous capability.

`ACT` includes `speak_after_action`. It defaults to false, so future Minecraft actions can continue without requiring the user to speak and without the character narrating every movement. Important results are fed back as perception events; the executive may separately decide that a reaction is worth saying.

Invalid output fails closed to `WAIT`. A low-confidence speaking decision is downgraded to `WAIT`.

The executive prompt penalizes generic check-ins and repeated topics. It prefers specific memories, unfinished threads, salient world/game changes, and meaningful reactions. A timer wake alone is not a reason to talk.

## Anti-spam and interruption safety

The backend enforces gates outside the LLM:

- minimum silence before a normal decision;
- minimum cooldown after AI speech;
- maximum proactive turns per rolling hour;
- no decisions while listening is muted, a participant is speaking, STT is processing, the LLM is generating, reflection is running, or TTS is speaking;
- only one decision at a time per voice session;
- one global local-model decision semaphore;
- bounded and priority-aware event queues;
- web sessions require a live WebSocket subscriber and recent heartbeat;
- Discord sessions exist only while actually connected to voice.

Default values are intentionally conservative: 45 seconds of silence, 75 seconds between autonomous turns, and at most eight proactive turns per hour. The LLM may still choose `WAIT` indefinitely.

## Hierarchical memory and context

Voice turns no longer select memories only by global importance or include history only by message count.

### Context tiers

1. Character identity, immutable rules, user profile, and current emotion.
2. Recent verbatim turns packed newest-first into a token budget.
3. A compressed rolling summary of older live conversation.
4. Unresolved follow-ups/open loops.
5. Relevant long-term memories ranked by lexical similarity, importance, recency, and pinning.
6. Active goals.
7. Current live observations and private behavioral state.
8. Tool capability guidance for user-requested turns.

The default approximate input allocation is:

```text
Total voice context target       12,000 tokens
Recent verbatim history           6,200 tokens
Retrieved long-term memories      2,600 tokens
Rolling summary                   1,400 tokens
Remaining space                   character, goals, tools, observations
```

Budgets are configurable up to much larger model contexts. Packing uses a deterministic multilingual character/word estimate and always preserves the newest turn. Output tokens remain controlled separately by `llm.max_tokens`.

The bundled llama.cpp launchers now allocate a 16,384-token context so the default 12,000-token voice input target plus character/tool instructions and output reserve fit in one request. The router uses port 8081 because Discord/Chromium CEF remote debugging occupied port 8080 on the live Windows installation.

### Retrieval

The candidate pool is ranked with a blended score:

```text
query overlap
+ importance
+ recency decay
+ pinned-memory bonus
```

Selected memories update `last_accessed`. Pinned memories can survive a normal top-k cutoff, while irrelevant high-importance memories no longer crowd every prompt.

### Reflection and automatic memory extraction

After a configurable number of live voice messages, a background reflection pass produces:

- an updated compact summary;
- unresolved threads worth following up later;
- conservative memory candidates explicitly supported by user speech.

Automatic memory candidates require minimum confidence and importance scores, use a restricted memory-type allowlist, and are normalized/deduplicated before storage. They are tagged as auto-extracted for auditability.

No prompt or model weights are modified automatically.

## Evaluator and future training data

Every autonomous spoken interaction stores:

- triggering event IDs;
- the executive decision and reason;
- spoken output;
- delivery result;
- optional evaluation.

The optional evaluator grades relevance, timing, specificity, personality, and non-repetition. It is disabled by default because it adds another LLM pass. These records can later be exported as decision/critique data for supervised training or LoRA work.

The runtime deliberately does not self-edit prompts or auto-train/replace a model. Any future training pipeline should benchmark a candidate against a fixed evaluation set and require explicit acceptance before deployment.

## Future Minecraft/game autonomy

Game support should connect through two separate interfaces.

### Game perception

The game adapter publishes structured observations without asking the AI to talk:

```http
POST /api/voice-brain/sessions/{session_id}/events
Content-Type: application/json

{
  "event_type": "minecraft.player_damaged",
  "source": "minecraft_adapter",
  "priority": 85,
  "payload": {
    "health": 4.0,
    "attacker": "creeper",
    "nearby_hostiles": 2,
    "position": {"x": 12, "y": 64, "z": -40}
  }
}
```

Low-level telemetry should be aggregated before publishing. Do not send every game tick to the LLM. Publish state changes, important threats, task completion/failure, inventory milestones, chat, and periodic compact snapshots.

### Game capabilities

The game controller registers bounded named capabilities in Python:

```python
from app.agent.voice_brain import voice_brain

voice_brain.register_capability(
    "minecraft.move_to",
    "Move toward a reachable block position using the navigation controller.",
    move_to_handler,
    autonomous_safe=True,
)
```

Registration alone is insufficient. The capability must also be present in:

```yaml
voice_brain:
  allowed_autonomous_capabilities:
    - minecraft.move_to
```

This double gate prevents installing a game/OBS/Discord tool from silently making it autonomous. Spotify, Discord administration, and OBS controls are not autonomous by default.

Recommended Minecraft capabilities are goal-level rather than raw key presses:

- `minecraft.observe_state`
- `minecraft.set_goal`
- `minecraft.move_to`
- `minecraft.look_at`
- `minecraft.interact_block`
- `minecraft.attack_target`
- `minecraft.use_item`
- `minecraft.craft`
- `minecraft.stop`

A deterministic game controller should translate these into navigation and input. It must enforce reachability, rate limits, an emergency stop, forbidden actions/areas, action timeouts, and observed-result verification. The LLM must never receive unrestricted keyboard/mouse execution.

## API

### Settings

- `GET /api/voice-brain/settings`
- `PATCH /api/voice-brain/settings`

### Runtime

- `GET /api/voice-brain/status`
- `GET /api/voice-brain/status?session_id=...`
- `POST /api/voice-brain/sessions/open`
- `POST /api/voice-brain/sessions/{id}/heartbeat`
- `POST /api/voice-brain/sessions/{id}/events`
- `POST /api/voice-brain/sessions/{id}/close`
- `WS /api/ws/voice-brain/{id}`

WebSocket event types:

- `voice_brain_state`
- `voice_brain_event`
- `voice_brain_decision`
- `voice_brain_message`

## Configuration

The defaults live in `config/config.yaml` under `voice_brain` and the context limits under `memory`.

Important controls:

- `enabled`
- `min_silence_seconds`
- `min_speak_cooldown_seconds`
- `max_proactive_turns_per_hour`
- `minimum_speak_confidence`
- `reflection_enabled`
- `auto_memory_enabled`
- `evaluator_enabled`
- `allowed_autonomous_capabilities`

Live Mode also exposes a per-session **Autonomy** toggle and current brain phase next to the voice connection badge.

## Main files

```text
backend/app/agent/voice_brain.py       Executive runtime, decisions, state, reflection
backend/app/memory/context.py          Token packing and memory relevance retrieval
backend/app/models/character.py        Persistent session/event/interaction tables
backend/app/api/voice_brain.py         Settings, session, event, status and WebSocket API
backend/app/api/routes.py              Hierarchical voice context and proactive generation
backend/app/api/discord_bridge.py      Discord voice session and delivery adapter
frontend/src/components/LiveMode.tsx   Web session, heartbeat, WebSocket and autonomy UI
frontend/src/lib/api.ts                Voice-brain client API
backend/tests/test_voice_brain.py      Decision/context/prompt unit coverage
```
