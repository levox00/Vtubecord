from __future__ import annotations

import unittest

from app.api.resource_monitor import _model_record, _process_role


class ResourceMonitorTests(unittest.TestCase):
    def test_model_server_roles_are_detected(self) -> None:
        self.assertEqual(_process_role("tools\\llama.cpp\\llama-server.exe --model model.gguf"), "llm")
        self.assertEqual(_process_role("python tools/zonos/server.py"), "tts-zonos")
        self.assertEqual(_process_role("python tools/index-tts/server.py"), "tts-indextts")
        self.assertIsNone(_process_role("python scripts/unrelated_worker.py"))

    def test_model_record_uses_process_measurements(self) -> None:
        process = {
            "role": "llm",
            "pid": 42,
            "name": "llama-server.exe",
            "ram_mb": 2048.0,
            "vram_mb": 8192.0,
            "cpu_percent": 12.5,
        }
        record = _model_record("llm", "Language model", "local.gguf", "llama.cpp", {"llm"}, [process])
        self.assertEqual(record["status"], "active")
        self.assertEqual(record["pid"], 42)
        self.assertEqual(record["ram_mb"], 2048.0)
        self.assertEqual(record["vram_mb"], 8192.0)

    def test_model_record_marks_unstarted_model_as_configured(self) -> None:
        record = _model_record("llm", "Language model", "local.gguf", "llama.cpp", {"llm"}, [])
        self.assertEqual(record["status"], "configured")
        self.assertIsNone(record["ram_mb"])


if __name__ == "__main__":
    unittest.main()
