#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/backend"

if [[ ! -x .venv/bin/python ]]; then
  echo "Run scripts/linux/01_install_dependencies.sh first."
  exit 1
fi

mkdir -p data
export PYTHONPATH="$PWD"
echo "Backend: http://127.0.0.1:8000"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
