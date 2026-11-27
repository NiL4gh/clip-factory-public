import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch, MagicMock
from shorts_generator.enhancer import add_smart_background_music
from shorts_generator.highlights import _parse_json_loose, query_llm_json, _parse_llm_target


class TestPipelineAuditFixes(unittest.TestCase):

    def test_enhancer_filter_asplit(self):
        """Verify that add_smart_background_music uses asplit=2 to prevent filter pad double-consumption."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            clip_data = {"start_time": 10.0, "end_time": 20.0, "peak_moment": 15.0}
            add_smart_background_music("dummy.mp4", "dummy.mp3", "dummy_out.mp4", clip_data)
            
            cmd = mock_run.call_args[0][0]
            filter_idx = cmd.index("-filter_complex") + 1
            filter_str = cmd[filter_idx]
            
            self.assertIn("asplit=2", filter_str)
            self.assertIn("[a0_side]", filter_str)
            self.assertIn("[a0_mix]", filter_str)
            self.assertIn("[a1d]amix=", filter_str)

    def test_parse_json_loose_nested_array(self):
        """Verify that dictionary containing arrays parses as dict, not as nested array."""
        raw = '```json\n{"genre": "Tech", "tags": ["coding", "ai"]}\n```'
        parsed = _parse_json_loose(raw)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("genre"), "Tech")

    def test_parse_json_loose_conversational_markdown(self):
        """Verify markdown blocks wrapped with preamble and postscript parse correctly."""
        raw = 'Thinking: done.\n```json\n[{"title": "Clip 1", "start_timestamp": 5.0, "end_timestamp": 15.0}]\n```\nHope you like this!'
        parsed = _parse_json_loose(raw)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Clip 1")

    def test_query_llm_json_export(self):
        """Verify query_llm_json is callable and exports cleanly."""
        with patch("shorts_generator.highlights._execute_with_fallback") as mock_exec:
            mock_exec.return_value = {"custom_system_prompt": "Test Prompt", "focus_topics": ["AI"]}
            res = query_llm_json("Test prompt", llm_path="api:groq:llama-3.3-70b-versatile")
            self.assertIsInstance(res, dict)
            self.assertEqual(res["custom_system_prompt"], "Test Prompt")

    def test_parse_llm_target(self):
        """Verify provider target parsing for all supported providers."""
        prov, model = _parse_llm_target("api:groq:llama-3.3-70b-versatile")
        self.assertEqual(prov, "groq")
        self.assertEqual(model, "llama-3.3-70b-versatile")
        
        prov, model = _parse_llm_target("api:gemini:gemini-2.5-flash")
        self.assertEqual(prov, "gemini")
        self.assertEqual(model, "gemini-2.5-flash")

        prov, model = _parse_llm_target("openrouter:meta-llama/llama-3.3-70b-instruct")
        self.assertEqual(prov, "openrouter")
        self.assertEqual(model, "meta-llama/llama-3.3-70b-instruct")

        prov, model = _parse_llm_target("deepseek/deepseek-chat")
        self.assertEqual(prov, "openrouter")
        self.assertEqual(model, "deepseek/deepseek-chat")

    def test_high_tier_catalog_no_small_models(self):
        """Verify LLM_CATALOG contains only high-tier models (no 8b models)."""
        from shorts_generator.config import LLM_CATALOG
        for entry in LLM_CATALOG:
            self.assertNotIn("8b", entry["filename"].lower(), f"Low-tier model found in catalog: {entry['filename']}")
            self.assertNotIn("8b", entry["label"].lower(), f"Low-tier model label found: {entry['label']}")

    def test_provider_semaphores_configured(self):
        """Verify provider semaphores are initialized to prevent concurrent rate limit bursts."""
        from shorts_generator.highlights import _PROVIDER_SEMAPHORES
        self.assertIn("nvidia", _PROVIDER_SEMAPHORES)
        self.assertIn("openrouter", _PROVIDER_SEMAPHORES)
        self.assertIn("groq", _PROVIDER_SEMAPHORES)
        self.assertIn("gemini", _PROVIDER_SEMAPHORES)


if __name__ == "__main__":
    unittest.main()
