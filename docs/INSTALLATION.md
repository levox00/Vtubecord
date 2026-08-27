# Installation & Easy Setup

## Quick Start (Windows)

1. Install [Python 3.12+](https://www.python.org/downloads/)  
   - Check **"Add python.exe to PATH"**
2. Install [Node.js 20+ LTS](https://nodejs.org/)
3. Double-click:

```
SETUP.bat
```

This runs the full wizard:
- Checks prerequisites
- Creates Python venv + installs backend packages
- Installs frontend (`npm install`)
- Optionally downloads a GGUF LLM model
- Optionally downloads Piper TTS voices
- Opens Live2D Shizuku download page

4. (Optional) Download [llama.cpp Windows release](https://github.com/ggml-org/llama.cpp/releases)  
   Extract `llama-server.exe` into `tools\llama.cpp\`

5. Start everything:

```
START.bat
```

Then open **http://localhost:5173**

---

## Quick Start (Linux / macOS)

```bash
# Prerequisites: python3, node, npm, curl
chmod +x scripts/linux/*.sh
./scripts/linux/SETUP_EVERYTHING.sh

# Optional: install llama.cpp and put binary in PATH or tools/llama.cpp/
./scripts/linux/START_ALL.sh
```

Open **http://localhost:5173**

---

## What Gets Installed Where

| Component | Path |
|-----------|------|
| Python venv | `backend/.venv/` |
| Node modules | `frontend/node_modules/` |
| App config | `config/config.yaml` |
| SQLite DB | `backend/data/character.db` |
| GGUF models | `assets/models/gguf/*.gguf` |
| Piper voices | `assets/voices/piper/*.onnx` |
| Live2D model | `assets/live2d/shizuku/` |
| llama.cpp binary | `tools/llama.cpp/llama-server(.exe)` |

---

## Script Reference (Windows)

| Script | Purpose |
|--------|---------|
| `SETUP.bat` | Full guided setup |
| `START.bat` | Launch llama.cpp + backend + frontend |
| `scripts\windows\00_check_prerequisites.bat` | Check Python / Node |
| `scripts\windows\01_install_dependencies.bat` | venv + pip + npm |
| `scripts\windows\02_download_llm_model.bat` | Download GGUF (interactive) |
| `scripts\windows\03_download_voice_models.bat` | Piper voices |
| `scripts\windows\04_download_live2d.bat` | Opens official Shizuku page |
| `scripts\windows\05_start_llamacpp.bat` | Start local LLM server |
| `scripts\windows\06_start_backend.bat` | FastAPI |
| `scripts\windows\07_start_frontend.bat` | Vite dev server |

Linux equivalents live under `scripts/linux/`.

---

## Local LLM (llama.cpp)

1. Put a `.gguf` file in `assets/models/gguf/`
2. Start the server:

```bat
scripts\windows\05_start_llamacpp.bat
```

Default endpoint: `http://127.0.0.1:8081/v1`

`config/config.yaml` is pre-configured for this.

### Hosted API instead

Edit `config/config.yaml` and set `OPENAI_API_KEY` (or other) in the environment. Never commit API keys.

---

## Model Download Notes

- **No multi-GB model is auto-downloaded** without you choosing it.
- GGUF filenames on Hugging Face can change — if a download fails, open the repo page, accept the license if required, and use “Custom URL”.
- Always check the model card license before commercial use.
- Live2D Shizuku must be downloaded from the official Live2D site (sample license).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not found | Reinstall Python with “Add to PATH” |
| venv creation fails | Avoid OneDrive-locked folders; run as normal user |
| llama-server not found | Download release → put binary in `tools\llama.cpp\` |
| Frontend can’t reach backend | Backend must be on port 8000 |
| Download fails (HF) | Accept model license on Hugging Face first |
| Port in use | Change ports in start scripts / config |
