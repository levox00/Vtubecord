# Third-Party Licenses

This document tracks third-party packages, models, avatars, and voices used by the project.

**Always verify licenses before commercial use or redistribution.**

## Application Dependencies (Python)

| Package        | License   | Source                                      |
|----------------|-----------|---------------------------------------------|
| FastAPI        | MIT       | https://github.com/tiangolo/fastapi         |
| Uvicorn        | BSD       | https://github.com/encode/uvicorn           |
| Pydantic       | MIT       | https://github.com/pydantic/pydantic        |
| SQLAlchemy     | MIT       | https://github.com/sqlalchemy/sqlalchemy    |
| Alembic        | MIT       | https://github.com/sqlalchemy/alembic       |
| httpx          | BSD       | https://github.com/encode/httpx             |
| openai         | Apache-2.0| https://github.com/openai/openai-python     |
| PyYAML         | MIT       | https://github.com/yaml/pyyaml              |
| NumPy          | BSD       | https://github.com/numpy/numpy              |

## Application Dependencies (Frontend)

| Package        | License   | Source                                      |
|----------------|-----------|---------------------------------------------|
| React          | MIT       | https://github.com/facebook/react           |
| Vite           | MIT       | https://github.com/vitejs/vite              |
| Tailwind CSS   | MIT       | https://github.com/tailwindlabs/tailwindcss |
| Zustand        | MIT       | https://github.com/pmndrs/zustand           |

## Local Inference

| Component      | License / Notes                          | Source                                      |
|----------------|------------------------------------------|---------------------------------------------|
| llama.cpp      | MIT                                      | https://github.com/ggml-org/llama.cpp       |
| Ollama         | MIT                                      | https://github.com/ollama/ollama            |

## Models (NOT bundled)

GGUF models (Gemma, Llama, etc.) have their own licenses.  
Check the model card on Hugging Face before download or commercial use.  
This project does **not** redistribute model weights.

## Avatar

| Asset          | License                                  | Source                                      |
|----------------|------------------------------------------|---------------------------------------------|
| Live2D Shizuku | Live2D Sample License (see official site)| https://www.live2d.com/en/learn/sample/shizuku/ |
| Cubism Web SDK | Live2D Proprietary / Free for non-commercial (check current terms) | https://www.live2d.com / CubismWebSamples |

**Do not use Neuro-sama or any other copyrighted VTuber model.**

## Voice (Phase 2+)

| Component      | License                                  | Source                                      |
|----------------|------------------------------------------|---------------------------------------------|
| Piper          | MIT                                      | https://github.com/rhasspy/piper            |
| Piper voices   | Varies per voice – check each voice card | https://rhasspy.github.io/piper-samples/    |

## Reference Projects (inspiration only)

| Project            | Notes                                      |
|--------------------|--------------------------------------------|
| Open-LLM-VTuber    | Reference for Live2D/LLM/voice integration patterns. Not used as the architecture of this project. https://github.com/Open-LLM-VTuber/Open-LLM-VTuber |

---

Update this file whenever a new significant dependency or model is added.