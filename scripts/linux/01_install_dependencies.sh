#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "========================================"
echo "  AI VTuber - Install Dependencies"
echo "========================================"
echo "Project root: $ROOT"
echo

echo "[1/3] Python backend..."
cd "$ROOT/backend"
if [[ ! -f app/main.py ]]; then
  echo "[ERROR] backend/app/main.py not found"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "    Creating virtual environment..."
  python3 -m venv .venv
fi

echo "    Upgrading pip..."
.venv/bin/python -m pip install --upgrade pip
echo "    Installing requirements.txt ..."
.venv/bin/python -m pip install -r requirements.txt
echo "[OK] Backend ready."

echo
echo "[2/3] Frontend..."
cd "$ROOT/frontend"
npm install
echo "[OK] Frontend ready."

echo
echo "[3/3] Config & directories..."
cd "$ROOT"
if [[ ! -f config/config.yaml ]]; then
  cp config/config.example.yaml config/config.yaml
  echo "[OK] Created config/config.yaml"
else
  echo "[OK] config.yaml exists"
fi

mkdir -p backend/data assets/models/gguf assets/voices/piper assets/live2d/shizuku assets/whisper tools/llama.cpp

echo
echo "========================================"
echo "  Dependencies installed."
echo "========================================"
