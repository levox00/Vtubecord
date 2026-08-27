"""Benchmark the already-running local LLM/TTS HTTP services.

The benchmark is deliberately dependency-light and never downloads models. It
reports cold and warmed request latency so acceleration changes can be compared
without changing application behavior.
"""
from __future__ import annotations

import argparse
import io
import json
import statistics
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any


LLM_PROMPTS = [
    "Say hello in one short sentence.",
    "Explain why caching a repeated system prompt can reduce local LLM latency in three sentences.",
    "Write a friendly 120-word response to a user asking for game recommendations, with a short numbered list.",
]
TTS_TEXTS = [
    "Hello there.",
    "This is a medium length speech benchmark for the local voice model.",
    "This longer benchmark measures steady state synthesis latency while preserving the same voice and expressive settings used by the application.",
]


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[bytes, float]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    return data, time.perf_counter() - started


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def benchmark_llm(base_url: str, repeats: int, timeout: float) -> dict[str, Any]:
    results = []
    endpoint = base_url.rstrip("/") + "/chat/completions"
    for prompt in LLM_PROMPTS:
        latencies: list[float] = []
        tokens_per_second: list[float] = []
        for _ in range(max(1, repeats)):
            body, elapsed = _post_json(
                endpoint,
                {
                    "model": "local-model",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 96,
                    "stream": False,
                    "cache_prompt": True,
                },
                timeout,
            )
            payload = json.loads(body.decode("utf-8"))
            usage = payload.get("usage") or {}
            completion_tokens = int(usage.get("completion_tokens") or 0)
            latencies.append(elapsed)
            tokens_per_second.append(completion_tokens / elapsed if elapsed and completion_tokens else 0.0)
        results.append(
            {
                "prompt_chars": len(prompt),
                "latency_seconds": _summary(latencies),
                "decode_tokens_per_second": _summary(tokens_per_second),
            }
        )
    return {"endpoint": endpoint, "cases": results}


def benchmark_tts(endpoint: str, voice_ref: str | None, repeats: int, timeout: float) -> dict[str, Any]:
    results = []
    for text in TTS_TEXTS:
        latencies: list[float] = []
        realtime_factors: list[float] = []
        audio_seconds: list[float] = []
        for _ in range(max(1, repeats)):
            payload: dict[str, Any] = {"text": text}
            if voice_ref:
                payload["voice_ref"] = voice_ref
            body, elapsed = _post_json(endpoint, payload, timeout)
            with wave.open(io.BytesIO(body), "rb") as wav:
                duration = wav.getnframes() / float(wav.getframerate() or 1)
                channels = wav.getnchannels()
            latencies.append(elapsed)
            audio_seconds.append(duration)
            realtime_factors.append(elapsed / duration if duration else 0.0)
        results.append(
            {
                "text_chars": len(text),
                "latency_seconds": _summary(latencies),
                "audio_seconds": _summary(audio_seconds),
                "real_time_factor": _summary(realtime_factors),
                "channels": channels,
            }
        )
    return {"endpoint": endpoint, "cases": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("llm", "tts", "all"), default="all")
    parser.add_argument("--llm-url", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--tts-url", default="http://127.0.0.1:8091/tts")
    parser.add_argument("--voice-ref", default="")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repeats": max(1, args.repeats),
    }
    if args.mode in {"llm", "all"}:
        report["llm"] = benchmark_llm(args.llm_url, args.repeats, args.timeout)
    if args.mode in {"tts", "all"}:
        report["tts"] = benchmark_tts(args.tts_url, args.voice_ref or None, args.repeats, args.timeout)

    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
