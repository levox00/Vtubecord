#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "Starting components..."

if find assets/models/gguf -name '*.gguf' 2>/dev/null | grep -q .; then
  echo "Launching llama.cpp..."
  # shellcheck disable=SC1091
  bash scripts/linux/05_start_llamacpp.sh &
  sleep 2
else
  echo "No local GGUF — skipping llama.cpp"
fi

bash scripts/linux/06_start_backend.sh &
sleep 2
bash scripts/linux/10_start_nemo_speech.sh &
bash scripts/linux/07_start_frontend.sh &

echo
echo "Backend  → http://127.0.0.1:8000"
echo "Frontend → http://localhost:5173"
echo "STT sidecar → http://127.0.0.1:8092 (when installed and downloaded)"
echo "Press Ctrl+C in each terminal / kill jobs to stop."
wait
