"""
CRONOS — test_tracer.py
Tests for CronosTracer context manager and step recording.
"""

import pytest
from fractions import Fraction

from cronos import CronosTracer, TraceStore
from cronos.models import StepKind


@pytest.fixture
def store(tmp_path):
    return TraceStore(str(tmp_path / "test.db"))


class TestTracerBasic:
    def test_trace_created_with_objective_step(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "Do X") as t:
            pass
        trace = store.get_latest_trace()
        assert trace is not None
        assert trace.objective == "Do X"
        assert trace.steps[0].kind == StepKind.OBJECTIVE

    def test_trace_has_started_and_closed_at(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "Do X") as t:
            pass
        trace = store.get_latest_trace()
        assert trace.started_at is not None
        assert trace.closed_at is not None
        assert trace.closed_at >= trace.started_at

    def test_trace_sealed_with_entry_hash(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "Do X") as t:
            t.decide("Fix it", Fraction(80, 100))
        trace = store.get_latest_trace()
        assert trace.entry_hash is not None
        assert len(trace.entry_hash) == 64  # SHA-256 hex
        assert trace.chain_ok is True

    def test_no_decision_defaults_gracefully(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "Do X") as t:
            t.record_recall("M-1", "some memory")
        trace = store.get_latest_trace()
        assert trace.decision == "(no decision recorded)"
        assert trace.confidence == Fraction(0)


class TestTracerRecording:
    def test_record_recall(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.record_recall("M-22", "Auth timeout", score=Fraction(91, 100))
        trace = store.get_latest_trace()
        recalls = [s for s in trace.steps if s.kind == StepKind.RECALL]
        assert len(recalls) == 1
        assert recalls[0].payload["memory_id"] == "M-22"
        assert recalls[0].payload["score"] == "91/100"

    def test_record_recall_without_score(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.record_recall("M-1", "summary")
        trace = store.get_latest_trace()
        recalls = [s for s in trace.steps if s.kind == StepKind.RECALL]
        assert "score" not in recalls[0].payload

    def test_call_tool(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.call_tool("jira", "ticket #42 → Open / Auth")
        trace = store.get_latest_trace()
        tools = [s for s in trace.steps if s.kind == StepKind.TOOL]
        assert len(tools) == 1
        assert tools[0].payload["tool"] == "jira"
        assert "Auth" in tools[0].payload["result"]

    def test_add_hypothesis(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "Token expired")
            t.add_hypothesis("h2", "Cache stale")
        trace = store.get_latest_trace()
        hyps = [s for s in trace.steps if s.kind == StepKind.HYPOTHESIS]
        assert len(hyps) == 2
        assert hyps[0].payload["label"] == "h1"

    def test_discard_hypothesis(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.add_hypothesis("h2", "Cache stale")
            t.discard_hypothesis("h2", "No cache errors in logs")
        trace = store.get_latest_trace()
        discards = [s for s in trace.steps if s.kind == StepKind.DISCARD]
        assert len(discards) == 1
        assert discards[0].payload["label"] == "h2"
        assert discards[0].payload["reason"] == "No cache errors in logs"

    def test_add_evidence_supports(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.add_evidence("Jira says Auth", supports="h1")
        trace = store.get_latest_trace()
        evs = [s for s in trace.steps if s.kind == StepKind.EVIDENCE]
        assert evs[0].payload["supports"] == "h1"
        assert "refutes" not in evs[0].payload

    def test_add_evidence_refutes(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.add_evidence("No cache errors", refutes="h2")
        trace = store.get_latest_trace()
        evs = [s for s in trace.steps if s.kind == StepKind.EVIDENCE]
        assert evs[0].payload["refutes"] == "h2"

    def test_decide_records_fraction(self, store):
        # Full-diversity trace so the ceiling (quality.py) doesn't clamp the value.
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.record_recall("M-1", "memory")
            t.call_tool("jira", "result")
            t.add_evidence("fact", supports="h1")
            t.decide("Apply fix", Fraction(74, 100))
        trace = store.get_latest_trace()
        assert trace.decision == "Apply fix"
        # Full diversity → ceiling = 1, no clamping
        assert trace.confidence == Fraction(74, 100)
        assert trace.confidence_warnings == []
        decisions = [s for s in trace.steps if s.kind == StepKind.DECISION]
        conf_str = decisions[0].payload["confidence"]
        p, q = conf_str.split("/")
        assert Fraction(int(p), int(q)) == Fraction(74, 100)

    def test_decide_rejects_float(self, store):
        with pytest.raises(TypeError, match="fractions.Fraction"):
            with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
                t.decide("Apply fix", 0.74)  # float — must raise

    def test_step_order_preserved(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.record_recall("M-1", "memory")
            t.call_tool("jira", "result")
            t.add_hypothesis("h1", "desc")
            t.discard_hypothesis("h1", "reason")
            t.add_evidence("fact", supports="h1")
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        kinds = [s.kind for s in trace.steps]
        assert kinds == [
            StepKind.OBJECTIVE,
            StepKind.RECALL,
            StepKind.TOOL,
            StepKind.HYPOTHESIS,
            StepKind.DISCARD,
            StepKind.EVIDENCE,
            StepKind.DECISION,
        ]

    def test_multiple_recalls(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            for i in range(3):
                t.record_recall(f"M-{i}", f"memory {i}", score=Fraction(50 + i * 10, 100))
        trace = store.get_latest_trace()
        recalls = [s for s in trace.steps if s.kind == StepKind.RECALL]
        assert len(recalls) == 3

    def test_context_manager_stores_even_on_exception(self, store):
        """Trace must be stored even if the agent code raises."""
        try:
            with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
                t.record_recall("M-1", "memory")
                raise RuntimeError("simulated agent failure")
        except RuntimeError:
            pass
        trace = store.get_latest_trace()
        assert trace is not None
        recalls = [s for s in trace.steps if s.kind == StepKind.RECALL]
        assert len(recalls) == 1


class TestTracerValidation:
    def test_decide_rejects_confidence_above_one(self, store):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
                t.decide("action", Fraction(3, 2))

    def test_decide_rejects_negative_confidence(self, store):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
                t.decide("action", Fraction(-1, 10))

    def test_decide_accepts_zero_and_one(self, store):
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.decide("nothing", Fraction(0))
        with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
            t.add_evidence("certain", supports="h1")
            t.decide("certain action", Fraction(1))
        assert store.get_latest_trace() is not None

    def test_add_evidence_rejects_both_supports_and_refutes(self, store):
        with pytest.raises(ValueError, match="cannot both support and refute"):
            with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
                t.add_evidence("ambiguous", supports="h1", refutes="h1")


class TestTracerIds:
    def test_each_trace_has_unique_id(self, store):
        ids = set()
        for _ in range(5):
            with CronosTracer(store, "a1", "C1", "U1", "obj") as t:
                t.decide("action", Fraction(1))
            trace = store.get_latest_trace()
            ids.add(trace.trace_id)
        assert len(ids) == 5
