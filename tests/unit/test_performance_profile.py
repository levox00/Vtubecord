from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.performance_profile import load_profile, resolve_llama, resolve_tts


class PerformanceProfileTests(unittest.TestCase):
    def test_defaults_are_quality_safe(self) -> None:
        profile = load_profile(Path(__file__).resolve().parents[2])
        self.assertEqual(profile["llm"]["flash_attention"], "auto")
        self.assertEqual(profile["llm"]["cache_type_k"], "f16")
        self.assertFalse(profile["llm"]["speculative"]["enabled"])
        self.assertEqual(profile["tts"]["torch_compile"], "auto")

    def test_invalid_values_fall_back(self) -> None:
        with patch(
            "scripts.performance_profile._read_yaml",
            return_value={
                "performance": {
                    "llm": {"flash_attention": "invalid", "cache_type_k": "invalid"},
                    "tts": {"dtype": "invalid"},
                }
            },
        ):
            root = Path("unused")
            profile = load_profile(root)
            self.assertEqual(profile["llm"]["flash_attention"], "auto")
            self.assertEqual(profile["llm"]["cache_type_k"], "f16")
            self.assertEqual(profile["tts"]["dtype"], "auto")

    def test_missing_speculative_model_is_disabled(self) -> None:
        with patch(
            "scripts.performance_profile._read_yaml",
            return_value={
                "performance": {
                    "llm": {"speculative": {"enabled": True, "draft_model": "missing.gguf"}}
                }
            },
        ):
            root = Path("unused")
            resolved = resolve_llama(root)
            self.assertFalse(resolved["speculative_active"])
            self.assertNotIn("--model-draft", resolved["args"])

    def test_tts_cpu_resolution_disables_cuda_paths(self) -> None:
        resolved = resolve_tts(cuda_available=False, has_compile=True, has_flash_attention=True, has_fused_kernels=True)
        self.assertEqual(resolved["dtype"], "fp32")
        self.assertFalse(resolved["compile_enabled"])
        self.assertFalse(resolved["attention_enabled"])
        self.assertFalse(resolved["fused_kernels_enabled"])


if __name__ == "__main__":
    unittest.main()
