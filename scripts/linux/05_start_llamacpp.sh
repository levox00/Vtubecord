#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

MODEL=$(find assets/models/gguf -name '*.gguf' 2>/dev/null | head -n1 || true)
if [[ -z "$MODEL" ]]; then
  echo "No .gguf found in assets/models/gguf/"
  echo "Run 02_download_llm_model.sh first."
  exit 1
fi

SERVER=""
if command -v llama-server &>/dev/null; then
  SERVER=$(command -v llama-server)
elif [[ -x tools/llama.cpp/llama-server ]]; then
  SERVER=tools/llama.cpp/llama-server
elif [[ -x tools/llama-server ]]; then
  SERVER=tools/llama-server
fi

if [[ -z "$SERVER" ]]; then
  echo "llama-server not found."
  echo "Install from https://github.com/ggml-org/llama.cpp"
  echo "Or place binary in tools/llama.cpp/"
  exit 1
fi

echo "Model directory : $(dirname "$MODEL")"
echo "Server: $SERVER (router mode, one model in VRAM)"
echo "URL   : http://127.0.0.1:8081"
echo

PYTHON_BIN=""
if [[ -x backend/.venv/bin/python ]]; then
  PYTHON_BIN="$PWD/backend/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON_BIN=$(command -v python3)
elif command -v python &>/dev/null; then
  PYTHON_BIN=$(command -v python)
fi

PERF_ARGS=""
if [[ -n "$PYTHON_BIN" ]]; then
  PERF_ARGS=$("$PYTHON_BIN" scripts/performance_profile.py --root "$PWD" --server "$SERVER" --llama-args --platform posix)
else
  echo "[WARNING] Python not found; using llama.cpp defaults."
fi

if [[ -n "$PERF_ARGS" ]]; then
  echo "Performance: $PERF_ARGS"
  eval "exec \"$SERVER\" --models-dir \"$(dirname \"$MODEL\")\" --models-max 1 --models-autoload --jinja --host 127.0.0.1 --port 8081 -c 16384 -ngl 99 $PERF_ARGS"
else
  exec "$SERVER" --models-dir "$(dirname "$MODEL")" --models-max 1 --models-autoload --jinja --host 127.0.0.1 --port 8081 -c 16384 -ngl 99
fi
