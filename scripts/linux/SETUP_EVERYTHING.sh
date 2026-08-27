#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "========================================"
echo "  AI VTuber - Full Setup"
echo "========================================"
echo

bash 00_check_prerequisites.sh
bash 01_install_dependencies.sh

read -r -p "Download a local GGUF model now? [y/N]: " a
[[ "$a" =~ ^[Yy]$ ]] && bash 02_download_llm_model.sh

read -r -p "Download Piper voices now? [y/N]: " a
[[ "$a" =~ ^[Yy]$ ]] && bash 03_download_voice_models.sh

echo
echo "For Live2D Shizuku, download from:"
echo "  https://www.live2d.com/en/learn/sample/shizuku/"
echo "  Extract into assets/live2d/shizuku/"
echo
echo "Setup done. Run START_ALL.sh or individual start scripts."