# Local Models

## Recommended Approach

Use **llama.cpp** with its OpenAI-compatible server.  
This gives you a stable, high-performance local endpoint that the rest of the application treats identically to any hosted OpenAI-compatible API.

## Starting llama.cpp Server

```bash
# Example with a GGUF file
./llama-server \
  -m /path/to/gemma-3-4b-it-Q4_K_M.gguf \
  --host 127.0.0.1 \
  --port 8081 \
  -c 16384 \
  -ngl 99 \
  --flash-attn auto \
  --jinja
```

Then configure:

```yaml
llm:
  provider: openai_compatible
  base_url: "http://127.0.0.1:8081/v1"
  model: "local-model"   # or the actual model name the server reports
  api_key: "not-needed"
```

## Ollama

```yaml
llm:
  provider: ollama
  base_url: "http://127.0.0.1:11434"
  model: "gemma3:4b"
```

## Model Manager (Future UI)

The application will provide a UI that shows:
- Installed GGUF models
- Parameter count / quantization / size
- Estimated RAM / VRAM
- Context length
- Activate / Test / Delete

**Never** auto-download multi-GB models. User must explicitly choose.

## Gemma 3 (Recommended Starting Point)

Gemma 3 GGUF models are well-supported by llama.cpp.  
Download from Hugging Face (check the model card license before commercial use).

Example sources (verify current availability):
- ggml-org / unsloth quantized Gemma 3 GGUFs

Choose quantization according to your hardware:
- Q4_K_M — good balance
- Q5_K_M / Q6_K — higher quality
- Q8_0 / F16 — maximum quality (more VRAM)

## Local inference acceleration

The project keeps acceleration settings in `config/config.yaml` under
`performance`. The default profile is conservative: Flash Attention and
prompt reuse are automatic, while KV-cache quantization and speculative
decoding remain opt-in.

The Windows and Linux launchers translate that profile into llama.cpp flags.
The packaged server supports Flash Attention (`--flash-attn`), separate K/V
cache types (`--cache-type-k` / `--cache-type-v`), prompt caching, and
speculative decoding with a compatible draft model.

For TTS, Zonos uses PyTorch scaled-dot-product attention, guarded
`torch.compile`, and inference warm-up when the installed CUDA/PyTorch stack
supports them. Index-TTS additionally uses its optional FlashAttention,
fused CUDA kernels, and compile paths. If an optional kernel fails to load, the
server automatically retries with the eager/portable path.

To compare configurations against the same fixed prompts and phrases while
the services are running:

```bash
python scripts/benchmark_local_inference.py --mode all --repeats 3
```

The benchmark reports request latency, LLM decode tokens/sec, and TTS real-time
factor. It never downloads models.

## Important

The character’s memories, personality, and identity are stored in the application database.  
Switching the model only changes the reasoning engine.
