# Discord voice routing and transcription with two VB-CABLEs

The desktop Equicord integration can now do both directions without
Voicemeeter:

```text
Discord call output (Neuro account)
        ↓
  VB-CABLE A Input
        ↓
  VB-CABLE A Output → Nemotron streaming transcription

AI TTS → VB-CABLE B Input
        ↓
  VB-CABLE B Output → Discord microphone (Neuro account)
```

Your second Discord account can keep normal headphones as its output, so you
hear Neuro through the call. The capture path intentionally has no speaker or
content filter: everyone on the call shares one FIFO conversation. If people
talk over one another, the ASR model receives the mixed signal.

## Setup on Windows

1. Install the VB-Audio Virtual Cable A+B package so Windows exposes Cable A
   and Cable B independently, then restart the project.
2. On the Neuro Discord account, set **Output Device** to `CABLE-A Input` and
   **Input Device** to `CABLE-B Output`.
3. Keep the other Discord account's output on your normal headphones.
4. In the project Discord settings, enable **Discord Voice Transcription** and
   select the matching `CABLE-A Output` capture endpoint.
5. Enable **Discord Voice Output** and select `CABLE-B Input` as the playback
   endpoint.
6. Join a voice channel through the Equicord bridge. The capture status should
   become `listening` once the Nemotron sidecar is ready.

The project transmits interim words to the UI, but only finalized utterances
reach the LLM. While Neuro is speaking, new finalized utterances are queued
and answered in order. TTS responses are serialized so they cannot overlap.

## Voice-state tools

When the AI is connected through the Equicord desktop bridge, its function
tools can control only Neuro's own Discord client:

- `discord_set_mute({"enabled": true|false})` mutes or unmutes Neuro's microphone.
- `discord_set_deafen({"enabled": true|false})` deafens or undeafens Neuro's client.

The backend first checks that Neuro is in a voice channel, sends the
`set_voice_state` bridge command, and verifies the returned `self_mute` or
`self_deaf` state when the bridge reports it. These commands never change
another participant. The Equicord plugin must support the `set_voice_state`
command; older compatible builds may use the separate `set_self_mute` or
`set_self_deaf` (or the shorter `set_mute`/`set_deafen`) fallback actions.

The chat route also recognizes direct phrases such as “mute yourself”, “turn
your microphone back on”, “deafen your own client”, and “undeafen yourself”
when native tool calling is unavailable.

The `discord_speak_voice` tool lets the AI say an exact user-requested sentence
once in the active call. It uses the same TTS engine and VB-CABLE device as
normal Discord speech, and the automatic reply TTS is suppressed for that
turn so the sentence is not spoken twice. Discord Voice Output must be enabled
and the Equicord client must be connected to voice.

## Message routing modes

The Discord settings now separate these modes:

- **Respond to every eligible message** on: every eligible message is sent to
  the AI; a configured prefix is optional.
- **Respond to every eligible message** off: command mode is active and a
  non-empty prefix is required. An empty prefix disables command-mode replies.

Channel and user filters still apply in both modes.

The **Mirror voice replies** option is disabled by default. Enable it only if
you also want voice responses copied to the configured Discord text channel.

If a cable is missing or the names differ, choose the exact Windows endpoint
from the device dropdowns. The status panel reports the selected device,
bridge/voice connection, Nemotron readiness, current turn state, and queue
depth.
