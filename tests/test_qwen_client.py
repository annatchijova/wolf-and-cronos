"""
tests/test_qwen_client.py
==========================
Tests for QwenClient — offline mode only (no API key required).

Verifies:
1. Correct endpoint constant (dashscope-intl.aliyuncs.com, not dashscope.aliyuncs.com)
2. available == False when no key is set
3. offline fallback returns a string (not an exception)
4. narrator produces a non-empty string in offline mode
"""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from qwen_client import QwenClient, QWEN_BASE_URL


class TestQwenClientConstants(unittest.TestCase):

    def test_endpoint_uses_international_dashscope(self):
        """Must use dashscope-intl.aliyuncs.com — not the mainland endpoint."""
        self.assertIn("dashscope-intl.aliyuncs.com", QWEN_BASE_URL)

    def test_endpoint_does_not_use_mainland(self):
        self.assertNotIn("dashscope.aliyuncs.com/compatible", QWEN_BASE_URL.replace(
            "dashscope-intl.aliyuncs.com", ""))

    def test_endpoint_uses_compatible_mode(self):
        self.assertIn("compatible-mode/v1", QWEN_BASE_URL)


class TestQwenClientOffline(unittest.TestCase):

    def setUp(self):
        # Ensure no key is set for offline tests
        self._saved = os.environ.pop("DASHSCOPE_API_KEY", None)
        self._client = QwenClient(api_key="")

    def tearDown(self):
        self._client.close()
        if self._saved is not None:
            os.environ["DASHSCOPE_API_KEY"] = self._saved

    def test_available_false_without_key(self):
        self.assertFalse(self._client.available)

    def test_complete_returns_string_offline(self):
        result = self._client.complete("test message")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_offline_response_contains_offline_marker(self):
        result = self._client.complete("test message")
        self.assertIn("OFFLINE", result.upper())

    def test_context_manager(self):
        with QwenClient(api_key="") as c:
            self.assertIsInstance(c, QwenClient)


class TestNarratorOffline(unittest.TestCase):
    """Narrator fallback when no Qwen key is available."""

    def setUp(self):
        self._saved = os.environ.pop("DASHSCOPE_API_KEY", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["DASHSCOPE_API_KEY"] = self._saved

    def test_narrator_fallback_returns_string(self):
        import tempfile
        for _lib in ("corvus", "cronos"):
            import os as _os
            _p = _os.path.abspath(_os.path.join(_ROOT, "..", _lib))
            if _p not in sys.path:
                sys.path.insert(0, _p)

        from bridge import CorvosCronosBridge
        from narrator import QwenNarrator
        from qwen_client import QwenClient

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            bridge = CorvosCronosBridge(db_path=db_path)
            result = bridge.analyze("Hi, please review the PR.", artifact_id="narrator-test")
            bridge.close()

            client = QwenClient(api_key="")
            narrator = QwenNarrator(client=client)
            transcript = narrator.narrate(result, "Hi, please review the PR.")
            narrator.close()

            self.assertIsInstance(transcript, str)
            self.assertGreater(len(transcript.strip()), 0)
        finally:
            import os as _os
            if _os.path.exists(db_path):
                _os.unlink(db_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
