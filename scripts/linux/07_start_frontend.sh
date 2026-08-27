#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

cd frontend
if [[ ! -d node_modules ]]; then
  npm install
fi
echo "Frontend: http://localhost:5173"
exec npm run dev