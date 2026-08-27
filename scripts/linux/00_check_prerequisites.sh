#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "========================================"
echo "  AI VTuber - Prerequisites Check"
echo "========================================"
echo

MISSING=0

if command -v python3 &>/dev/null; then
  echo "[OK] Python: $(python3 --version)"
else
  echo "[X] python3 not found"
  MISSING=1
fi

if command -v node &>/dev/null; then
  echo "[OK] Node.js: $(node --version)"
else
  echo "[X] Node.js not found"
  MISSING=1
fi

if command -v npm &>/dev/null; then
  echo "[OK] npm: $(npm --version)"
else
  echo "[X] npm not found"
  MISSING=1
fi

if command -v curl &>/dev/null; then
  echo "[OK] curl"
else
  echo "[!] curl not found (needed for model downloads)"
fi

if command -v git &>/dev/null; then
  echo "[OK] git"
else
  echo "[!] git not found (optional)"
fi

echo
if [[ "$MISSING" -eq 1 ]]; then
  echo "Install missing tools, then re-run."
  exit 1
fi
echo "All basic prerequisites OK."
echo "Next: ./scripts/linux/01_install_dependencies.sh"