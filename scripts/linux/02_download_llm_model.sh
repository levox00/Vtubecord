#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

OUTDIR="assets/models/gguf"
mkdir -p "$OUTDIR"

echo "========================================"
echo "  Download Local LLM (GGUF)"
echo "========================================"
echo
echo "Models go to: $OUTDIR"
echo
echo "1) Gemma 3 4B Instruct Q4_K_M  (~2.5-3.5 GB)"
echo "2) Gemma 3 4B Instruct Q5_K_M  (~3.5-4.5 GB)"
echo "3) Gemma 3 12B Instruct Q4_K_M (~7-8 GB)"
echo "4) Custom URL"
echo "5) Skip"
echo
read -r -p "Choice [1-5]: " CHOICE

download_hf() {
  local repo="$1"
  local file="$2"
  local url="https://huggingface.co/${repo}/resolve/main/${file}"
  echo "Downloading: $url"
  echo "Target: $OUTDIR/$file"
  read -r -p "Proceed? [y/N]: " conf
  [[ "$conf" =~ ^[Yy]$ ]] || return 0
  curl -L --fail -o "$OUTDIR/$file" "$url"
  echo "[OK] $OUTDIR/$file"
  ls -lh "$OUTDIR/$file"
}

case "$CHOICE" in
  1) download_hf "unsloth/gemma-3-4b-it-GGUF" "gemma-3-4b-it-Q4_K_M.gguf" ;;
  2) download_hf "unsloth/gemma-3-4b-it-GGUF" "gemma-3-4b-it-Q5_K_M.gguf" ;;
  3) download_hf "unsloth/gemma-3-12b-it-GGUF" "gemma-3-12b-it-Q4_K_M.gguf" ;;
  4)
    read -r -p "Full URL to .gguf: " URL
    read -r -p "Save as filename: " NAME
    curl -L --fail -o "$OUTDIR/$NAME" "$URL"
    echo "[OK] $OUTDIR/$NAME"
    ;;
  5) echo "Skipped." ;;
  *) echo "Invalid"; exit 1 ;;
esac

echo
echo "Next: start llama.cpp with scripts/linux/05_start_llamacpp.sh"
echo "Or install from https://github.com/ggml-org/llama.cpp"