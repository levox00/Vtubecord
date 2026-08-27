#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

OUTDIR="assets/voices/piper"
mkdir -p "$OUTDIR"

echo "========================================"
echo "  Download Piper TTS Voices"
echo "========================================"
echo
echo "1) en_US-lessac-medium"
echo "2) en_US-amy-medium"
echo "3) Both"
echo "4) Skip"
read -r -p "Choice [1-4]: " CHOICE

download_voice() {
  local name="$1"
  local path="$2"
  local base="https://huggingface.co/rhasspy/piper-voices/resolve/main/${path}"
  echo "Downloading $name ..."
  curl -L --fail -o "$OUTDIR/${name}.onnx" "${base}/${name}.onnx"
  curl -L --fail -o "$OUTDIR/${name}.onnx.json" "${base}/${name}.onnx.json"
  echo "[OK] $name"
}

case "$CHOICE" in
  1) download_voice "en_US-lessac-medium" "en/en_US/lessac/medium" ;;
  2) download_voice "en_US-amy-medium" "en/en_US/amy/medium" ;;
  3)
    download_voice "en_US-lessac-medium" "en/en_US/lessac/medium"
    download_voice "en_US-amy-medium" "en/en_US/amy/medium"
    ;;
  4) echo "Skipped." ;;
  *) echo "Invalid"; exit 1 ;;
esac

echo "Done."