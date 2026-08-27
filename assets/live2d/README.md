# Installed Live2D models

The source archives are retained beside six normalized model folders. Runtime
copies are published under `frontend/public/live2d`, where Vite and OBS browser
sources can load them.

| Model | Source folder | Public `.model3.json` URL |
| --- | --- | --- |
| Shizuku | `shizuku_ja` | `/live2d/shizuku_ja/runtime/shizuku.model3.json` |
| Hiyori Pro | `hiyori_pro` | `/live2d/hiyori_pro/runtime/hiyori_pro_t11.model3.json` |
| Hiyori Free | `hiyori_free` | `/live2d/hiyori_free/runtime/hiyori_free_t08.model3.json` |
| Niziiro Mao Pro | `mao_pro` | `/live2d/mao_pro/runtime/mao_pro.model3.json` |
| Miku Pro | `miku_pro` | `/live2d/miku_pro/runtime/miku_sample_t04.model3.json` |
| Miku Free | `miku_free` | `/live2d/miku_free/runtime/miku.model3.json` |

Keep each `runtime` directory intact: its model JSON uses relative paths for
textures, physics, expressions, and motions. The model picker and animation
director catalog live in `frontend/src/lib/live2dModels.ts`.

These are Live2D sample assets. Read the `ReadMe.txt` included with each model
and comply with the Live2D Free Material License Agreement and applicable terms.
