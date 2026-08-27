# NVIDIA Nemotron streaming ASR notices

This project can optionally run the official Q8_0 GGUF artifacts through
NVIDIA NeMo-Speech.cpp. The weights are never committed or redistributed by
this repository; they are downloaded to `assets/whisper/nemotron/` only after
the user accepts the applicable terms in the Speech-to-text settings.

- `nvidia/nemotron-3.5-asr-streaming-0.6b` — OpenMDW-1.1, multilingual.
  [Model and license](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- `nvidia/nemotron-speech-streaming-en-0.6b` — NVIDIA Open Model License,
  English-only.
  [Model and license](https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b)

Review the complete license text supplied by NVIDIA at the linked source before
using either model. Acceptance is recorded per model revision in
`data/stt-license-acceptance.json` (a local, user-owned file).
