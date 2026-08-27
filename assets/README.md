# Assets Directory

| Folder | Contents | How to populate |
|--------|----------|-----------------|
| `models/gguf/` | Local LLM weights (`.gguf`) | `SETUP.bat` → download step, or `02_download_llm_model.bat` |
| `voices/piper/` | Piper TTS `.onnx` + `.onnx.json` | `03_download_voice_models.bat` |
| `live2d/shizuku/` | Live2D Shizuku sample model | Official download (see `04_download_live2d.bat`) |
| `whisper/` | Faster-Whisper models (Phase 2) | Future script |

**Nothing multi-GB is committed to git.**  
All large files are downloaded by the setup scripts after you confirm.