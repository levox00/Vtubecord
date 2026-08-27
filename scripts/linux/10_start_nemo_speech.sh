#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODEL="$ROOT/assets/whisper/nemotron/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
EXE="$ROOT/tools/nemo-speech/nemo-speech"
if [[ ! -f "$MODEL" ]]; then
  echo "[nemo] Default Q8_0 model is not downloaded; use the STT settings download flow."
  exit 0
fi
if [[ ! -x "$EXE" ]]; then EXE="$(command -v nemo-speech || true)"; fi
if [[ -z "$EXE" ]]; then echo "[nemo] nemo-speech executable not found"; exit 0; fi
echo "[nemo] Model: $MODEL | CUDA device: 0 | port: 8092 | chunk: 320 ms"
exec "$EXE" serve --host 127.0.0.1 --port 8092 --asr-model "$MODEL" --asr.backend.gpu 0 --asr.streaming.rnnt_right_context 3
