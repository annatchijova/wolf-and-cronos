"""
CRONOS — test_store.py
Tests for TraceStore persistence layer.
"""

import pytest
from fractions import Fraction

from cronos import CronosTracer, TraceStore
from cronos.models import Trace, StepKind


@pytest.fixture
def store(tmp_path):
    return TraceStore(str(tmp_path / "test.db"))


def _make_trace(store, agent_id="agent-A", channel="C1", user="U1",
                objective="Do X", decision="Done", confidence=Fraction(74, 100)):
    with CronosTracer(store, agent_id, channel, user, objective) as t:
        t.record_recall("M-1", "relevant memory", score=Fraction(80, 100))
        t.call_tool("jira", "Open / Auth / High")
        t.add_hypothesis("h1", "Auth bug")
        t.add_hypothesis("h2", "Cache bug")
        t.add_evidence("Jira says Auth", supports="h1")
        t.discard_hypothesis("h2", "No cache errors")
        t.decide(decision, confidence)
    return store.get_latest_trace()


class TestStepTamperEvidence:
    """The seal must bind the reasoning trace, not only the header fields."""

    def test_forged_evidence_breaks_chain(self, store):
        trace = _make_trace(store)
        ok, errors = store.chain.verify()
        assert ok is True, errors

        # Adversary rewrites a piece of evidence directly in the DB, post-hoc.
        store._conn.execute(
            "UPDATE trace_steps SET payload = ? WHERE trace_id = ? AND kind = 'evidence'",
            ('{"supports": "h1", "text": "FORGED"}', trace.trace_id),
        )
        store._conn.commit()

        ok, errors = store.chain.verify()
        assert ok is False
        assert any("steps_hash mismatch" in e for e in errors)

    def test_untampered_steps_verify_ok(self, store):
        _make_trace(store)
        _make_trace(store, agent_id="agent-B")
        ok, errors = store.chain.verify()
        assert ok is True, errors


class TestConfidenceCorruption:
    """A stored confidence that fails to parse must be flagged, not hidden."""

    def test_corrupt_confidence_is_flagged(self, store):
        trace = _make_trace(store)
        store._conn.execute(
            "UPDATE traces SET confidence = 'not-a-fraction' WHERE trace_id = ?",
            (trace.trace_id,),
        )
        store._conn.commit()
        loaded = store.load_trace(trace.trace_id)
        assert loaded.confidence is None
        assert loaded.confidence_corrupt is True

    def test_valid_confidence_not_flagged(self, store):
        trace = _make_trace(store)
        loaded = store.load_trace(trace.trace_id)
        assert loaded.confidence == Fraction(74, 100)
        assert loaded.confidence_corrupt is False


class TestStoreBasic:
    def test_save_and_load_roundtrip(self, store):
        trace = _make_trace(store)
        loaded = store.load_trace(trace.trace_id)
        assert loaded is not None
        assert loaded.trace_id == trace.trace_id
        assert loaded.objective == "Do X"
        assert loaded.decision == "Done"
        assert loaded.confidence == Fraction(74, 100)

    def test_load_nonexistent_returns_none(self, store):
        assert store.load_trace("does-not-exist") is None

    def test_steps_round_trip(self, store):
        trace = _make_trace(store)
        loaded = store.load_trace(trace.trace_id)
        kinds = [s.kind for s in loaded.steps]
        assert StepKind.RECALL in kinds
        assert StepKind.TOOL in kinds
        assert StepKind.HYPOTHESIS in kinds
        assert StepKind.DISCARD in kinds
        assert StepKind.EVIDENCE in kinds
        assert StepKind.DECISION in kinds

    def test_step_order_preserved(self, store):
        trace = _make_trace(store)
        loaded = store.load_trace(trace.trace_id)
        kinds = [s.kind for s in loaded.steps]
        # OBJECTIVE always first
        assert kinds[0] == StepKind.OBJECTIVE
        # DECISION always last
        assert kinds[-1] == StepKind.DECISION

    def test_chain_ok_after_save(self, store):
        trace = _make_trace(store)
        loaded = store.load_trace(trace.trace_id)
        assert loaded.chain_ok is True
        assert loaded.entry_hash is not None

    def test_confidence_fraction_precision(self, store):
        """Fraction 74/100 must survive the p/q string round-trip exactly."""
        trace = _make_trace(store, confidence=Fraction(74, 100))
        loaded = store.load_trace(trace.trace_id)
        assert loaded.confidence == Fraction(74, 100)
        assert loaded.confidence.numerator == 37   # auto-reduced: 74/100 = 37/50
        assert loaded.confidence.denominator == 50

    def test_confidence_fraction_irreducible(self, store):
        """Fraction 71/100 is already irreducible."""
        trace = _make_trace(store, confidence=Fraction(71, 100))
        loaded = store.load_trace(trace.trace_id)
        assert loaded.confidence == Fraction(71, 100)


class TestStoreQueries:
    def test_get_latest_trace(self, store):
        _make_trace(store, objective="First")
        _make_trace(store, objective="Second")
        latest = store.get_latest_trace()
        assert latest.objective == "Second"

    def test_get_latest_trace_by_agent(self, store):
        _make_trace(store, agent_id="agent-A", objective="A1")
        _make_trace(store, agent_id="agent-B", objective="B1")
        _make_trace(store, agent_id="agent-A", objective="A2")
        latest_a = store.get_latest_trace(agent_id="agent-A")
        assert latest_a.objective == "A2"
        latest_b = store.get_latest_trace(agent_id="agent-B")
        assert latest_b.objective == "B1"

    def test_get_latest_trace_none_when_empty(self, store):
        assert store.get_latest_trace() is None

    def test_get_recent_traces_limit(self, store):
        for i in range(5):
            _make_trace(store, objective=f"Task {i}")
        recent = store.get_recent_traces(limit=3)
        assert len(recent) == 3

    def test_get_recent_traces_by_agent(self, store):
        _make_trace(store, agent_id="agent-A")
        _make_trace(store, agent_id="agent-B")
        _make_trace(store, agent_id="agent-A")
        recent = store.get_recent_traces(agent_id="agent-A")
        assert all(r["agent_id"] == "agent-A" for r in recent)
        assert len(recent) == 2

    def test_get_recent_traces_has_required_keys(self, store):
        _make_trace(store)
        recent = store.get_recent_traces()
        assert len(recent) == 1
        r = recent[0]
        for key in ["trace_id", "agent_id", "objective", "decision", "confidence",
                    "closed_at", "entry_hash", "chain_ok"]:
            assert key in r

    def test_count_traces(self, store):
        assert store.count_traces() == 0
        _make_trace(store, agent_id="a1")
        _make_trace(store, agent_id="a1")
        _make_trace(store, agent_id="a2")
        assert store.count_traces() == 3
        assert store.count_traces(agent_id="a1") == 2
        assert store.count_traces(agent_id="a2") == 1

    def test_chain_verification_passes_after_multiple_saves(self, store):
        for i in range(4):
            _make_trace(store, objective=f"Task {i}")
        ok, errors = store.chain.verify()
        assert ok is True
        assert errors == []


class TestStoreEdgeCases:
    def test_str_to_fraction_malformed_returns_none(self):
        from cronos.store import _str_to_fraction
        assert _str_to_fraction("abc/def") is None

    def test_str_to_fraction_zero_denominator_returns_none(self):
        from cronos.store import _str_to_fraction
        assert _str_to_fraction("1/0") is None

    def test_str_to_fraction_valid(self):
        from cronos.store import _str_to_fraction
        from fractions import Fraction
        assert _str_to_fraction("74/100") == Fraction(74, 100)
        assert _str_to_fraction("0/1") == Fraction(0)
        assert _str_to_fraction(None) is None
        assert _str_to_fraction("") is None

    def test_trace_steps_cascade_on_new_db(self, store):
        """New databases must have ON DELETE CASCADE on trace_steps.trace_id."""
        fk_list = store._conn.execute(
            "PRAGMA foreign_key_list(trace_steps)"
        ).fetchall()
        assert fk_list, "trace_steps must have at least one FK"
        assert any(row[6] == "CASCADE" for row in fk_list), (
            "trace_steps.trace_id FK must have ON DELETE CASCADE"
        )

    def test_migration_runs_on_legacy_db(self, tmp_path):
        """TraceStore must migrate an existing DB that lacks ON DELETE CASCADE."""
        import sqlite3
        from cronos.store import TraceStore as TS

        db_path = str(tmp_path / "legacy.db")
        # Simulate a legacy DB: create trace_steps WITHOUT ON DELETE CASCADE
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("""
            CREATE TABLE traces (
                trace_id            TEXT PRIMARY KEY,
                agent_id            TEXT NOT NULL,
                channel_id          TEXT NOT NULL,
                user_id             TEXT NOT NULL,
                objective           TEXT NOT NULL,
                decision            TEXT,
                confidence          TEXT,
                started_at          TEXT NOT NULL,
                closed_at           TEXT,
                entry_hash          TEXT,
                chain_ok            INTEGER DEFAULT 0,
                quality             TEXT,
                diversity           TEXT,
                contradictions      TEXT,
                confidence_warnings TEXT,
                cronos_version      TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE trace_steps (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id  TEXT NOT NULL REFERENCES traces(trace_id),
                seq       INTEGER NOT NULL,
                kind      TEXT NOT NULL,
                payload   TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        # Open with TraceStore — migration must add CASCADE
        store = TS(db_path)
        fk_list = store._conn.execute(
            "PRAGMA foreign_key_list(trace_steps)"
        ).fetchall()
        assert any(row[6] == "CASCADE" for row in fk_list), (
            "Migration must add ON DELETE CASCADE to trace_steps"
        )
