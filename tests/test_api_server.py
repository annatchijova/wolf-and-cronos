"""
tests/test_api_server.py
=========================
API server tests — offline (no DASHSCOPE_API_KEY, no network).

Verifies:
1. /health reports offline narration and open auth in the test env.
2. /analyze returns a sealed verdict with trace ids and a valid chain,
   and the offline narration note when no key is configured.
3. Manipulative multi-tactic text escalates above SILENT; benign text
   stays SILENT.
4. Token auth: when BRIDGE_API_TOKEN is set, requests without the header
   are rejected with 401 and requests with it succeed.
5. /verify and /traces respond consistently after analyses.
6. Unsupported narration language is rejected with 422.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi.testclient import TestClient

MANIPULATIVE = (
    "URGENT: as your senior director I must insist. Everyone on the "
    "leadership team already approved this. If you do not wire the "
    "deposit in the next two hours the deal collapses and it will be "
    "your fault. Do not tell anyone — this is strictly confidential "
    "and only you can save it now."
)
BENIGN = "Hi! Attaching the meeting notes from Tuesday. No rush at all."


def _build_app(tmpdir: str, token: str = ""):
    """Import a fresh api_server module bound to a temp DB and given token."""
    os.environ["BRIDGE_DB_PATH"] = os.path.join(tmpdir, "negotiation.db")
    os.environ["BRIDGE_MEMORY_DB_PATH"] = os.path.join(tmpdir, "memory.db")
    os.environ["BRIDGE_API_TOKEN"] = token
    os.environ.pop("DASHSCOPE_API_KEY", None)
    import api_server
    importlib.reload(api_server)
    return api_server


class OpenModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.mod = _build_app(cls._tmp.name, token="")
        cls.client = TestClient(cls.mod.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["qwen_narration"], "offline")
        self.assertEqual(data["auth"], "open")

    def test_dashboard_served_at_root(self) -> None:
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("CORVUS × CRONOS — Live Console", r.text)

    def test_chat_page_served(self) -> None:
        r = self.client.get("/chat")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("Chat (Qwen live)", r.text)

    def test_chat_offline_returns_note_not_fake_reply(self) -> None:
        # No DASHSCOPE_API_KEY in the test env → honest offline note, never a
        # fabricated reply.
        r = self.client.post("/chat", json={"message": "How does the gate work?"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIsNone(data["reply"])
        self.assertIn("DASHSCOPE_API_KEY", data["note"])

    def test_chat_unsupported_lang_rejected(self) -> None:
        r = self.client.post("/chat", json={"message": "hi", "lang": "fr"})
        self.assertEqual(r.status_code, 422)

    def test_chat_empty_message_rejected(self) -> None:
        r = self.client.post("/chat", json={"message": ""})
        self.assertEqual(r.status_code, 422)

    def test_analyze_manipulative_text_seals_verdict(self) -> None:
        r = self.client.post("/analyze", json={
            "text": MANIPULATIVE, "user_id": "wolf", "lang": "es",
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn(data["verdict"], ("WATCH", "ALERT", "CRITICAL"))
        self.assertGreaterEqual(len(data["active_agents"]), 2)
        self.assertTrue(data["audit"]["chain_valid"])
        self.assertIn("GATE", data["audit"]["trace_ids"])
        self.assertEqual(len(data["audit"]["signal_hash"]), 64)
        # Offline narration is a flagged absence, not a fake success.
        self.assertIsNone(data["narration"]["text"])
        self.assertIn("DASHSCOPE_API_KEY", data["narration"]["note"])

    def test_analyze_benign_text_stays_silent(self) -> None:
        r = self.client.post("/analyze", json={
            "text": BENIGN, "user_id": "friend", "narrate": False,
        })
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["verdict"], "SILENT")
        self.assertNotIn("text", data["narration"])

    def test_unsupported_lang_rejected(self) -> None:
        r = self.client.post("/analyze", json={"text": BENIGN, "lang": "fr"})
        self.assertEqual(r.status_code, 422)

    def test_empty_text_rejected(self) -> None:
        r = self.client.post("/analyze", json={"text": ""})
        self.assertEqual(r.status_code, 422)

    def test_verify_and_traces_after_analyses(self) -> None:
        self.client.post("/analyze", json={"text": BENIGN, "narrate": False})
        r = self.client.get("/verify")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["chain_ok"])
        r = self.client.get("/traces", params={"limit": 5})
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["count"], 0)


class TokenAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.mod = _build_app(cls._tmp.name, token="secret-token-123")
        cls.client = TestClient(cls.mod.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls._tmp.cleanup()
        os.environ.pop("BRIDGE_API_TOKEN", None)

    def test_missing_token_rejected(self) -> None:
        r = self.client.post("/analyze", json={"text": BENIGN})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/verify")
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_rejected(self) -> None:
        r = self.client.get("/verify", headers={"X-API-Token": "nope"})
        self.assertEqual(r.status_code, 401)

    def test_correct_token_accepted(self) -> None:
        r = self.client.get("/verify", headers={"X-API-Token": "secret-token-123"})
        self.assertEqual(r.status_code, 200)

    def test_health_stays_open(self) -> None:
        # Liveness must work for the load balancer without credentials.
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["auth"], "token")


if __name__ == "__main__":
    unittest.main()
