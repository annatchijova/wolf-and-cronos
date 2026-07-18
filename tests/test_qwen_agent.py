"""
tests/test_qwen_agent.py
=========================
Tests for the Qwen-native CRONOS agent driver — no network required.

A scripted fake transport plays the model side of the DashScope
function-calling protocol. Verifies:

1. A full open -> hypothesis -> evidence -> discard -> close cycle seals a
   real trace in the CRONOS chain, and the chain verifies afterward.
2. The sealed trace is indistinguishable in the store from an MCP-driven
   trace (steps, decision, quality all present).
3. Unknown tool names and malformed arguments return errors to the model
   instead of crashing the loop.
4. A model that never closes its trace triggers the honest-degradation
   auto-close (confidence 0, explicit UNSEALED marker).
5. Constructing without API key and without transport raises immediately.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from corvus_cronos.qwen_agent import (
    AgentOutcome,
    CronosToolExecutor,
    QwenCronosAgent,
)


def _assistant_tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    """One chat/completions response containing a single tool call."""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }],
            },
        }],
    }


def _assistant_text(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class ScriptedTransport:
    """Plays back a fixed sequence of model responses; records payloads."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if not self._responses:
            return _assistant_text("(script exhausted)")
        return self._responses.pop(0)


class FullCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "cronos_test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_full_cycle(self) -> AgentOutcome:
        script: list[dict] = []
        # The model opens a trace. It does not know the trace_id yet, so the
        # scripted turns after this one use the id captured from tool output —
        # handled by _DynamicScript below.
        transport = _DynamicScript()
        agent = QwenCronosAgent(db_path=self.db, transport=transport)
        outcome = agent.run("Why did the export job produce 0 rows?",
                            agent_id="qwen-test-agent")
        agent.close()
        return outcome

    def test_full_cycle_seals_trace_and_chain_verifies(self) -> None:
        outcome = self._run_full_cycle()
        self.assertEqual(len(outcome.sealed_trace_ids), 1)
        self.assertEqual(outcome.unsealed_trace_ids, [])
        self.assertTrue(outcome.chain_ok)
        self.assertIn("filter regression", outcome.answer)

    def test_sealed_trace_matches_store_shape(self) -> None:
        outcome = self._run_full_cycle()
        executor = CronosToolExecutor(self.db)
        trace = executor.execute(
            "cronos_explain_trace", {"trace_id": outcome.sealed_trace_ids[0]}
        )
        executor.close()
        self.assertEqual(trace["agent_id"], "qwen-test-agent")
        kinds = [s["kind"] for s in trace["steps"]]
        self.assertIn("hypothesis", kinds)
        self.assertIn("evidence", kinds)
        self.assertIn("discard", kinds)
        self.assertTrue(trace["decision"].startswith("Root cause"))
        self.assertTrue(trace["chain_ok"])


class _DynamicScript:
    """
    Model script that threads the real trace_id through subsequent calls.
    Sequence: open -> hypothesis A -> hypothesis B -> evidence(refutes B)
    -> discard B -> evidence(supports A) -> close -> final text.
    """

    def __init__(self) -> None:
        self.trace_id: str | None = None
        self.step = 0

    def __call__(self, payload: dict) -> dict:
        # Capture trace_id from the tool result the driver appended.
        for msg in reversed(payload["messages"]):
            if msg.get("role") == "tool" and self.trace_id is None:
                data = json.loads(msg["content"])
                if "trace_id" in data:
                    self.trace_id = data["trace_id"]
                break

        steps = [
            lambda: _assistant_tool_call("cronos_open_trace", {
                "agent_id": "qwen-test-agent",
                "objective": "Why did the export job produce 0 rows?",
            }),
            lambda: _assistant_tool_call("cronos_add_hypothesis", {
                "trace_id": self.trace_id, "label": "filter_regression",
                "description": "A date filter regression excludes all rows.",
            }),
            lambda: _assistant_tool_call("cronos_add_hypothesis", {
                "trace_id": self.trace_id, "label": "empty_source",
                "description": "The upstream table was empty at run time.",
            }),
            lambda: _assistant_tool_call("cronos_add_evidence", {
                "trace_id": self.trace_id,
                "text": "Upstream table had 40k rows at job start.",
                "refutes": "empty_source",
            }),
            lambda: _assistant_tool_call("cronos_discard_hypothesis", {
                "trace_id": self.trace_id, "label": "empty_source",
                "reason": "Source contained 40k rows — emptiness refuted.",
            }),
            lambda: _assistant_tool_call("cronos_add_evidence", {
                "trace_id": self.trace_id,
                "text": "Commit abc123 changed the date comparison to exclusive.",
                "supports": "filter_regression",
            }),
            lambda: _assistant_tool_call("cronos_close_trace", {
                "trace_id": self.trace_id,
                "decision": "Root cause: filter regression in commit abc123.",
                "confidence_num": 80, "confidence_den": 100,
            }),
            lambda: _assistant_text(
                "The export produced 0 rows because of a filter regression "
                "in commit abc123."
            ),
        ]
        response = steps[self.step]()
        self.step += 1
        return response


class ErrorHandlingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "cronos_test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unknown_tool_returns_error_not_crash(self) -> None:
        transport = ScriptedTransport([
            _assistant_tool_call("cronos_delete_everything", {}),
            _assistant_text("done"),
        ])
        agent = QwenCronosAgent(db_path=self.db, transport=transport)
        outcome = agent.run("task")
        agent.close()
        # The error travelled back to the model as a tool message.
        tool_msgs = [m for m in outcome.transcript if m.get("role") == "tool"]
        self.assertIn("Unknown tool", tool_msgs[0]["content"])
        self.assertEqual(outcome.answer, "done")

    def test_malformed_arguments_return_error(self) -> None:
        bad_call = {
            "choices": [{
                "message": {
                    "role": "assistant", "content": None,
                    "tool_calls": [{
                        "id": "c1", "type": "function",
                        "function": {"name": "cronos_open_trace",
                                     "arguments": "{not json"},
                    }],
                },
            }],
        }
        transport = ScriptedTransport([bad_call, _assistant_text("ok")])
        agent = QwenCronosAgent(db_path=self.db, transport=transport)
        outcome = agent.run("task")
        agent.close()
        tool_msgs = [m for m in outcome.transcript if m.get("role") == "tool"]
        self.assertIn("Malformed tool arguments", tool_msgs[0]["content"])

    def test_operating_on_unopened_trace_returns_error(self) -> None:
        transport = ScriptedTransport([
            _assistant_tool_call("cronos_add_evidence", {
                "trace_id": "nonexistent", "text": "fact",
            }),
            _assistant_text("ok"),
        ])
        agent = QwenCronosAgent(db_path=self.db, transport=transport)
        outcome = agent.run("task")
        agent.close()
        tool_msgs = [m for m in outcome.transcript if m.get("role") == "tool"]
        self.assertIn("No open trace", tool_msgs[0]["content"])


class HonestDegradationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "cronos_test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_model_never_closes_trace_triggers_autoclose(self) -> None:
        transport = ScriptedTransport([
            _assistant_tool_call("cronos_open_trace", {
                "agent_id": "sloppy-agent", "objective": "some task",
            }),
            _assistant_text("I am done."),   # never called close_trace
        ])
        agent = QwenCronosAgent(db_path=self.db, transport=transport)
        outcome = agent.run("task", agent_id="sloppy-agent")

        self.assertEqual(outcome.sealed_trace_ids, [])
        self.assertEqual(len(outcome.unsealed_trace_ids), 1)
        self.assertTrue(outcome.chain_ok)

        trace = agent.executor.execute(
            "cronos_explain_trace", {"trace_id": outcome.unsealed_trace_ids[0]}
        )
        agent.close()
        self.assertIn("UNSEALED-BY-MODEL", trace["decision"])
        self.assertEqual(trace["confidence"], "0/1")


class ConstructionTest(unittest.TestCase):
    def test_missing_key_and_transport_raises(self) -> None:
        env_backup = os.environ.pop("DASHSCOPE_API_KEY", None)
        try:
            with self.assertRaises(RuntimeError):
                QwenCronosAgent(db_path=":memory:")
        finally:
            if env_backup is not None:
                os.environ["DASHSCOPE_API_KEY"] = env_backup


if __name__ == "__main__":
    unittest.main()
