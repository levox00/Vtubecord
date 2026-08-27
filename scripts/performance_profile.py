"""Resolve the shared local-inference performance profile.

This module intentionally has a small dependency surface so it can be used by
the Windows/Linux launchers as well as the optional Python TTS servers.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - launchers can still use defaults
    yaml = None


ROOT = Path(__file__).resolve().parents[1]

_FLASH_VALUES = {"auto", "on", "off"}
_CACHE_TYPES = {"f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"}
_SPEC_TYPES = {
    "none",
    "draft-simple",
    "draft-eagle3",
    "draft-mtp",
    "draft-dflash",
    "draft-dspark",
    "ngram-simple",
    "ngram-map-k",
    "ngram-map-k4v",
    "ngram-mod",
    "ngram-cache",
}
_MODE_VALUES = {"auto", "on", "off"}


def _read_yaml(root: Path) -> dict[str, Any]:
    path = root / "config" / "config.yaml"
    if yaml is None or not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle) or {}
        return value if isinstance(value, dict) else {}
    except Exception as exc:  # malformed user config must not block startup
        print(f"[performance] Could not read {path}: {exc}; using safe defaults.", file=sys.stderr)
        return {}


def _choice(value: Any, allowed: set[str], default: str, name: str) -> str:
    candidate = str(value or default).strip().lower()
    if candidate not in allowed:
        print(f"[performance] Invalid {name}={candidate!r}; using {default!r}.", file=sys.stderr)
        return default
    return candidate


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def load_profile(root: Path | None = None) -> dict[str, Any]:
    root = root or ROOT
    raw = _read_yaml(root).get("performance", {})
    if not isinstance(raw, dict):
        raw = {}
    raw_llm = raw.get("llm", {}) if isinstance(raw.get("llm", {}), dict) else {}
    raw_tts = raw.get("tts", {}) if isinstance(raw.get("tts", {}), dict) else {}
    raw_spec = raw_llm.get("speculative", {}) if isinstance(raw_llm.get("speculative", {}), dict) else {}

    max_draft = raw_spec.get("max_draft_tokens", 3)
    try:
        max_draft = max(1, min(64, int(max_draft)))
    except (TypeError, ValueError):
        max_draft = 3

    return {
        "llm": {
            "flash_attention": _choice(raw_llm.get("flash_attention"), _FLASH_VALUES, "auto", "llm.flash_attention"),
            "cache_type_k": _choice(raw_llm.get("cache_type_k"), _CACHE_TYPES, "f16", "llm.cache_type_k"),
            "cache_type_v": _choice(raw_llm.get("cache_type_v"), _CACHE_TYPES, "f16", "llm.cache_type_v"),
            "prompt_cache": _bool(raw_llm.get("prompt_cache"), True),
            "speculative": {
                "enabled": _bool(raw_spec.get("enabled"), False),
                "type": _choice(raw_spec.get("type"), _SPEC_TYPES, "draft-simple", "llm.speculative.type"),
                "draft_model": str(raw_spec.get("draft_model") or "").strip(),
                "max_draft_tokens": max_draft,
            },
        },
        "tts": {
            "attention": _choice(raw_tts.get("attention"), {"auto", "flash", "eager"}, "auto", "tts.attention"),
            "dtype": _choice(raw_tts.get("dtype"), {"auto", "bf16", "fp16", "fp32"}, "auto", "tts.dtype"),
            "torch_compile": _choice(raw_tts.get("torch_compile"), _MODE_VALUES, "auto", "tts.torch_compile"),
            "cuda_graphs": _choice(raw_tts.get("cuda_graphs"), _MODE_VALUES, "auto", "tts.cuda_graphs"),
            "fused_kernels": _choice(raw_tts.get("fused_kernels"), _MODE_VALUES, "auto", "tts.fused_kernels"),
            "warmup": _bool(raw_tts.get("warmup"), True),
            "deepspeed": _bool(raw_tts.get("deepspeed"), False),
        },
    }


def _server_help(server: str | None) -> str:
    if not server:
        return ""
    try:
        completed = subprocess.run(
            [server, "--help"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        return f"{completed.stdout}\n{completed.stderr}"
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_llama(root: Path | None = None, server: str | None = None) -> dict[str, Any]:
    root = root or ROOT
    profile = load_profile(root)["llm"]
    help_text = _server_help(server)

    args: list[str] = [
        "--flash-attn",
        profile["flash_attention"],
        "--cache-type-k",
        profile["cache_type_k"],
        "--cache-type-v",
        profile["cache_type_v"],
    ]
    if profile["prompt_cache"] and (not help_text or "--cache-prompt" in help_text):
        args.append("--cache-prompt")

    spec = profile["speculative"]
    draft_model = spec["draft_model"]
    draft_path = Path(draft_model)
    if draft_model and not draft_path.is_absolute():
        draft_path = root / draft_path
    spec_enabled = bool(spec["enabled"] and draft_model)
    if spec["enabled"] and not draft_model:
        print("[performance] Speculative decoding enabled but no draft_model is configured; disabling it.", file=sys.stderr)
    if spec_enabled and draft_path.exists():
        spec_args = [
            "--spec-type",
            spec["type"],
            "--model-draft",
            str(draft_path),
            "--spec-draft-n-max",
            str(spec["max_draft_tokens"]),
        ]
        if not help_text or all(flag in help_text for flag in ("--spec-type", "--model-draft", "--spec-draft-n-max")):
            args.extend(spec_args)
    elif spec_enabled:
        print(f"[performance] Draft model not found at {draft_model!r}; disabling speculative decoding.", file=sys.stderr)

    return {"profile": profile, "args": args, "speculative_active": spec_enabled and draft_path.exists()}


def resolve_tts(root: Path | None = None, *, cuda_available: bool = False, has_compile: bool = False,
                has_flash_attention: bool = False, has_fused_kernels: bool = False) -> dict[str, Any]:
    profile = load_profile(root)["tts"]

    dtype = profile["dtype"]
    if dtype == "auto":
        dtype = "bf16" if cuda_available else "fp32"
    if not cuda_available and dtype in {"bf16", "fp16"}:
        dtype = "fp32"

    compile_mode = profile["torch_compile"]
    compile_enabled = compile_mode == "on" or (compile_mode == "auto" and cuda_available and has_compile)
    if compile_mode == "on" and not has_compile:
        print("[performance] torch_compile=on but compile dependencies are unavailable; using eager mode.", file=sys.stderr)
        compile_enabled = False

    attention = profile["attention"]
    attention_enabled = cuda_available and (
        attention == "flash" or (attention == "auto" and has_flash_attention)
    )
    if attention == "flash" and (not cuda_available or not has_flash_attention):
        print("[performance] attention=flash requested but FlashAttention/SDPA support is unavailable; using automatic attention.", file=sys.stderr)
        attention_enabled = False

    fused_mode = profile["fused_kernels"]
    fused_enabled = cuda_available and (
        fused_mode == "on" or (fused_mode == "auto" and has_fused_kernels)
    )
    if fused_mode == "on" and (not cuda_available or not has_fused_kernels):
        print("[performance] fused_kernels=on requested but the CUDA extension is unavailable; using PyTorch kernels.", file=sys.stderr)
        fused_enabled = False

    graphs_mode = profile["cuda_graphs"]
    graphs_enabled = graphs_mode == "on" or (graphs_mode == "auto" and cuda_available)

    return {
        "profile": profile,
        "dtype": dtype,
        "attention_enabled": attention_enabled,
        "compile_enabled": compile_enabled,
        "cuda_graphs_enabled": graphs_enabled,
        "fused_kernels_enabled": fused_enabled,
        "warmup": profile["warmup"],
        "deepspeed": profile["deepspeed"],
    }


def _format_args(args: list[str], platform: str) -> str:
    if platform == "windows":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--server", default="")
    parser.add_argument("--llama-args", action="store_true")
    parser.add_argument("--platform", choices=("windows", "posix"), default="posix")
    args = parser.parse_args()

    if args.llama_args:
        resolved = resolve_llama(args.root, args.server or None)
        print(_format_args(resolved["args"], args.platform))
    else:
        print(json.dumps(load_profile(args.root), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
