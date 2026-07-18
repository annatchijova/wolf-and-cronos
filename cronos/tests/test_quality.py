"""
CRONOS — test_quality.py
Tests for the 8 VIGÍA-derived quality features in cronos/quality.py.
"""

import pytest
from fractions import Fraction

from cronos import CronosTracer, TraceStore
from cronos.models import TraceQuality, StepKind
from cronos.quality import (
    CRONOS_VERSION,
    diversity_score,
    compute_quality,
    apply_confidence_constraints,
    find_contradictions,
    devils_advocate,
    detect_negation,
    _observation_groups,
)


@pytest.fixture
def store(tmp_path):
    return TraceStore(str(tmp_path / "test.db"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_steps(store, recalls=0, tools=0, hypotheses=0, discards=0, evidence_s=0, evidence_r=0):
    """Build a trace with specific step kinds and return it."""
    with CronosTracer(store, "a", "C1", "U1", "obj") as t:
        for i in range(recalls):
            t.record_recall(f"M-{i}", f"memory {i}")
        for i in range(tools):
            t.call_tool(f"tool{i}", f"result {i}")
        for i in range(hypotheses):
            t.add_hypothesis(f"h{i}", f"desc {i}")
        for i in range(discards):
            t.discard_hypothesis(f"h{i}", f"reason {i}")
        for i in range(evidence_s):
            t.add_evidence(f"fact {i}", supports="h0")
        for i in range(evidence_r):
            t.add_evidence(f"no fact {i}", refutes="h1")
        t.decide("action", Fraction(70, 100))
    return store.get_latest_trace()


# ── 1. Observational diversity score ──────────────────────────────────────────

class TestDiversityScore:
    def test_zero_diversity_no_observations(self, store):
        trace = _make_steps(store)  # only OBJECTIVE + DECISION
        assert trace.diversity == Fraction(0, 3)

    def test_one_group_recall_only(self, store):
        trace = _make_steps(store, recalls=1)
        assert trace.diversity == Fraction(1, 3)

    def test_two_groups_recall_and_tool(self, store):
        trace = _make_steps(store, recalls=1, tools=1)
        assert trace.diversity == Fraction(2, 3)

    def test_three_groups_full(self, store):
        trace = _make_steps(store, recalls=1, tools=1, evidence_s=1)
        assert trace.diversity == Fraction(3, 3)

    def test_hypothesis_counts_as_reasoning_group(self, store):
        # HYPOTHESIS alone (no TOOL, no RECALL) → 1 group
        trace = _make_steps(store, hypotheses=1)
        assert trace.diversity == Fraction(1, 3)

    def test_multiple_recalls_still_one_group(self, store):
        trace = _make_steps(store, recalls=3)
        assert trace.diversity == Fraction(1, 3)

    def test_diversity_score_function_directly(self):
        from cronos.models import TraceStep
        steps = [
            TraceStep(kind=StepKind.RECALL,    payload={}, timestamp=""),
            TraceStep(kind=StepKind.TOOL,      payload={}, timestamp=""),
            TraceStep(kind=StepKind.EVIDENCE,  payload={}, timestamp=""),
        ]
        assert diversity_score(steps) == Fraction(3, 3)


# ── 7. Trace quality level ─────────────────────────────────────────────────────

class TestTraceQuality:
    def test_empty_quality_no_observations(self, store):
        trace = _make_steps(store)
        assert trace.quality == TraceQuality.EMPTY

    def test_minimal_quality_one_group(self, store):
        trace = _make_steps(store, recalls=1)
        assert trace.quality == TraceQuality.MINIMAL

    def test_partial_quality_two_groups(self, store):
        trace = _make_steps(store, recalls=1, tools=1)
        assert trace.quality == TraceQuality.PARTIAL

    def test_full_quality_three_groups(self, store):
        trace = _make_steps(store, recalls=1, tools=1, evidence_s=1)
        assert trace.quality == TraceQuality.FULL

    def test_quality_persists_through_store(self, store):
        trace = _make_steps(store, recalls=1, tools=1, evidence_s=1)
        loaded = store.load_trace(trace.trace_id)
        assert loaded.quality == TraceQuality.FULL

    def test_compute_quality_function(self):
        from cronos.models import TraceStep
        full_steps = [
            TraceStep(StepKind.RECALL,   {}, ""),
            TraceStep(StepKind.TOOL,     {}, ""),
            TraceStep(StepKind.EVIDENCE, {}, ""),
        ]
        assert compute_quality(full_steps) == TraceQuality.FULL
        assert compute_quality([]) == TraceQuality.EMPTY


# ── 2 & 3. Confidence ceiling + floor ─────────────────────────────────────────

class TestConfidenceConstraints:
    def test_ceiling_capped_at_empty_diversity(self, store):
        # 0 observation groups → ceiling = 1/5
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("action", Fraction(95, 100))  # raw: 0.95, ceiling: 0.20
        trace = store.get_latest_trace()
        assert trace.confidence <= Fraction(1, 5)
        assert len(trace.confidence_warnings) >= 1
        assert "ceiling" in trace.confidence_warnings[0]

    def test_ceiling_capped_at_minimal_diversity(self, store):
        # 1 group (RECALL only) → ceiling = 3/5 = 0.60
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.record_recall("M-1", "memory")
            t.decide("action", Fraction(90, 100))  # raw: 0.90, ceiling: 0.60
        trace = store.get_latest_trace()
        assert trace.confidence <= Fraction(3, 5)

    def test_no_ceiling_at_full_diversity(self, store):
        # 3 groups → ceiling = 1 (no cap)
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.record_recall("M-1", "memory")
            t.call_tool("jira", "result")
            t.add_evidence("fact", supports="h1")
            t.decide("action", Fraction(90, 100))
        trace = store.get_latest_trace()
        assert trace.confidence == Fraction(9, 10)
        assert trace.confidence_warnings == []

    def test_floor_applied_with_supporting_evidence(self, store):
        # If supporting evidence exists, confidence cannot go below 1/10
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_evidence("fact", supports="h1")
            t.decide("action", Fraction(0))  # raw: 0, but evidence exists → floor = 1/10
        trace = store.get_latest_trace()
        assert trace.confidence >= Fraction(1, 10)

    def test_no_floor_without_evidence(self, store):
        # No supporting evidence → floor = 0
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("action", Fraction(0))
        trace = store.get_latest_trace()
        assert trace.confidence == Fraction(0)

    def test_confidence_warnings_persisted(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("action", Fraction(99, 100))  # no observations → ceiling = 1/5
        trace = store.get_latest_trace()
        loaded = store.load_trace(trace.trace_id)
        assert len(loaded.confidence_warnings) >= 1

    def test_apply_confidence_constraints_function(self):
        from cronos.models import TraceStep
        # Empty steps: ceiling = 1/5, floor = 0
        steps: list = []
        adj, warnings = apply_confidence_constraints(Fraction(9, 10), steps)
        assert adj == Fraction(1, 5)
        assert any("ceiling" in w for w in warnings)


# ── 5. Contradiction detection ─────────────────────────────────────────────────

class TestContradictionDetection:
    def test_no_contradictions_clean_trace(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "auth bug")
            t.add_evidence("Jira says Auth", supports="h1")
            t.decide("fix", Fraction(70, 100))
        trace = store.get_latest_trace()
        assert trace.contradictions == []

    def test_type_a_contradiction(self, store):
        """Evidence both supports and refutes the same hypothesis."""
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "auth bug")
            t.add_evidence("Jira says Auth", supports="h1")
            t.add_evidence("No auth errors found", refutes="h1")  # Type A
            t.decide("fix", Fraction(70, 100))
        trace = store.get_latest_trace()
        assert any("Type A" in c for c in trace.contradictions)
        assert any("h1" in c for c in trace.contradictions)

    def test_type_b_contradiction(self, store):
        """Hypothesis has supporting evidence but was discarded."""
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "auth bug")
            t.add_evidence("Jira confirms Auth", supports="h1")
            t.discard_hypothesis("h1", "decided to try cache fix instead")  # Type B
            t.decide("fix cache", Fraction(60, 100))
        trace = store.get_latest_trace()
        assert any("Type B" in c for c in trace.contradictions)

    def test_contradictions_persisted(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "auth bug")
            t.add_evidence("fact", supports="h1")
            t.add_evidence("counter", refutes="h1")
            t.decide("fix", Fraction(60, 100))
        trace = store.get_latest_trace()
        loaded = store.load_trace(trace.trace_id)
        assert len(loaded.contradictions) >= 1

    def test_find_contradictions_function(self):
        from cronos.models import TraceStep
        steps = [
            TraceStep(StepKind.HYPOTHESIS, {"label": "h1", "description": "d"}, ""),
            TraceStep(StepKind.EVIDENCE,   {"text": "a", "supports": "h1"},      ""),
            TraceStep(StepKind.EVIDENCE,   {"text": "b", "refutes":  "h1"},      ""),
        ]
        result = find_contradictions(steps)
        assert any("Type A" in r for r in result)


# ── 4. Devil's advocate synthesis ─────────────────────────────────────────────

class TestDevilsAdvocate:
    def test_devils_advocate_no_hypotheses(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("fix", Fraction(70, 100))
        trace = store.get_latest_trace()
        from cronos.narrator import Narrator
        n = Narrator(trace)
        da = n.devils_advocate()
        assert "No alternative" in da

    def test_devils_advocate_uses_discarded_hypothesis(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "auth bug")
            t.add_hypothesis("h2", "cache bug")
            t.discard_hypothesis("h2", "no cache errors in logs")
            t.decide("fix auth", Fraction(74, 100))
        trace = store.get_latest_trace()
        from cronos.narrator import Narrator
        n = Narrator(trace)
        da = n.devils_advocate()
        assert "h2" in da
        assert "no cache errors" in da.lower() or "rejected" in da.lower()

    def test_devils_advocate_prefers_hypothesis_with_evidence(self, store):
        """If a discarded hypothesis had supporting evidence, it should be the primary alternative."""
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "auth bug")
            t.add_hypothesis("h2", "cache bug")
            t.add_evidence("cache log shows error", supports="h2")   # h2 had support!
            t.discard_hypothesis("h2", "decided auth was more likely")
            t.decide("fix auth", Fraction(70, 100))
        trace = store.get_latest_trace()
        from cronos.narrator import Narrator
        n = Narrator(trace)
        da = n.devils_advocate()
        assert "h2" in da  # strongest alternative is the one with evidence
        assert "cache log" in da.lower() or "supporting" in da.lower()

    def test_devils_advocate_includes_cannot_exclude_disclaimer(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_hypothesis("h1", "bug")
            t.discard_hypothesis("h1", "no evidence")
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        from cronos.narrator import Narrator
        n = Narrator(trace)
        da = n.devils_advocate()
        assert "cannot be fully excluded" in da


# ── 6. Negation context detection ─────────────────────────────────────────────

class TestNegationDetection:
    @pytest.mark.parametrize("text,expected", [
        ("No cache errors in Jira log",       True),
        ("Not found in database",             True),
        ("Never seen this pattern before",    True),
        ("Absence of auth logs confirmed",    True),
        ("Failed to connect to service",      True),
        ("Jira confirms Auth category",       False),
        ("Cache was successfully invalidated",False),
        ("Three matching commits found",      False),
    ])
    def test_negation_patterns(self, text, expected):
        assert detect_negation(text) == expected

    def test_negation_tagged_in_evidence_payload(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_evidence("No cache errors in logs", refutes="h1")
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        ev = [s for s in trace.steps if s.kind == StepKind.EVIDENCE][0]
        assert ev.payload.get("negation_detected") is True

    def test_positive_evidence_not_tagged(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.add_evidence("Jira confirms Auth category", supports="h1")
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        ev = [s for s in trace.steps if s.kind == StepKind.EVIDENCE][0]
        assert "negation_detected" not in ev.payload


# ── 8. Version sentinel ────────────────────────────────────────────────────────

class TestVersionSentinel:
    def test_version_recorded_in_trace(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        assert trace.cronos_version == CRONOS_VERSION

    def test_version_in_objective_step_payload(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        obj_step = trace.steps[0]
        assert obj_step.kind == StepKind.OBJECTIVE
        assert obj_step.payload.get("cronos_version") == CRONOS_VERSION

    def test_version_persisted_through_store(self, store):
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.decide("action", Fraction(70, 100))
        trace = store.get_latest_trace()
        loaded = store.load_trace(trace.trace_id)
        assert loaded.cronos_version == CRONOS_VERSION

    def test_version_is_non_empty_string(self):
        assert isinstance(CRONOS_VERSION, str)
        assert len(CRONOS_VERSION) > 0
        # Semver format: digits.digits.digits
        parts = CRONOS_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)
