"""
CRONOS — test_narrator.py
Tests for the Narrator (natural language synthesis).
"""

import pytest
from fractions import Fraction

from cronos import CronosTracer, TraceStore
from cronos.narrator import Narrator, _confidence_pct, _confidence_label


@pytest.fixture
def store(tmp_path):
    return TraceStore(str(tmp_path / "test.db"))


def _full_trace(store):
    with CronosTracer(store, "support-resolver", "C1", "U1",
                      "Resolve ticket #42") as t:
        t.record_recall("M-22", "Auth timeout 2024 incident", score=Fraction(91, 100))
        t.record_recall("M-81", "JWT expiry cascade 2024",     score=Fraction(74, 100))
        t.call_tool("jira",   "ticket #42 → Open / Auth / High")
        t.call_tool("github", "3 commits in auth-service match")
        t.add_hypothesis("auth_bug",  "Authentication token expired")
        t.add_hypothesis("cache_bug", "Cache invalidation failure")
        t.add_evidence("Jira confirms Auth category",       supports="auth_bug")
        t.add_evidence("Memory M-22 matches auth pattern",  supports="auth_bug")
        t.add_evidence("No cache errors in Jira log",       refutes="cache_bug")
        t.discard_hypothesis("cache_bug", "No cache errors in Jira or GitHub")
        t.decide("Rotate auth token and restart auth-service", Fraction(74, 100))
    return store.get_latest_trace()


def _empty_trace(store):
    with CronosTracer(store, "agent-X", "C1", "U1", "Do something") as t:
        pass
    return store.get_latest_trace()


class TestNarratorShort:
    def test_short_returns_decision(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        assert "Rotate auth token" in s["decision"]

    def test_short_has_required_keys(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        for key in ["decision", "why_lines", "confidence_pct",
                    "confidence_label", "hash_short", "chain_ok",
                    "agent_id", "trace_id", "objective"]:
            assert key in s

    def test_short_why_lines_has_recalls(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        texts = [line for _, line in s["why_lines"]]
        assert any("M-22" in t for t in texts)

    def test_short_why_lines_has_tool(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        texts = [line for _, line in s["why_lines"]]
        assert any("jira" in t.lower() for t in texts)

    def test_short_why_lines_has_discard(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        symbols = [sym for sym, _ in s["why_lines"]]
        assert "✗" in symbols

    def test_short_confidence_pct_format(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        assert s["confidence_pct"] == "74%"

    def test_short_hash_short_length(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        # hash_short is first 7 chars of SHA-256 hex
        assert len(s["hash_short"]) == 7

    def test_short_chain_ok_true(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        s = n.short()
        assert s["chain_ok"] is True

    def test_short_empty_trace(self, store):
        trace = _empty_trace(store)
        n = Narrator(trace)
        s = n.short()
        assert s["decision"] == "(no decision recorded)"
        assert s["why_lines"] == []

    def test_short_matching_incident_year(self, store):
        """A memory summary containing a year triggers 'matching incident' line."""
        with CronosTracer(store, "a", "C1", "U1", "obj") as t:
            t.record_recall("M-22", "Auth timeout in service A — 2024-03 incident")
            t.decide("fix", Fraction(1))
        trace = store.get_latest_trace()
        n = Narrator(trace)
        s = n.short()
        texts = " ".join(line for _, line in s["why_lines"])
        assert "matching incident" in texts


class TestNarratorFull:
    def test_full_has_memories_list(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        f = n.full()
        assert len(f["memories"]) == 2
        assert f["memories"][0]["id"] == "M-22"

    def test_full_has_tools_list(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        f = n.full()
        assert len(f["tools"]) == 2
        assert f["tools"][0]["name"] == "jira"

    def test_full_hypotheses_status(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        f = n.full()
        labels = {h["label"]: h["status"] for h in f["hypotheses"]}
        assert labels["auth_bug"]  == "kept"
        assert labels["cache_bug"] == "discarded"

    def test_full_discard_reason_in_hypothesis(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        f = n.full()
        cache_h = next(h for h in f["hypotheses"] if h["label"] == "cache_bug")
        assert "No cache errors" in (cache_h.get("discard_reason") or "")

    def test_full_evidence_list(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        f = n.full()
        assert len(f["evidence"]) == 3
        support_texts = [e["text"] for e in f["evidence"] if e.get("supports")]
        assert any("Jira" in t for t in support_texts)

    def test_full_includes_timestamps(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        f = n.full()
        assert f["started_at"] is not None
        assert f["closed_at"] is not None


class TestNarratorNatural:
    def test_natural_contains_decision(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        prose = n.natural()
        assert "Rotate auth token" in prose

    def test_natural_mentions_memories(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        prose = n.natural()
        assert "M-22" in prose

    def test_natural_mentions_tool(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        prose = n.natural()
        assert "jira" in prose.lower()

    def test_natural_mentions_discard(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        prose = n.natural()
        assert "cache_bug" in prose

    def test_natural_contains_confidence(self, store):
        trace = _full_trace(store)
        n = Narrator(trace)
        prose = n.natural()
        assert "74%" in prose

    def test_natural_empty_trace_is_graceful(self, store):
        trace = _empty_trace(store)
        n = Narrator(trace)
        prose = n.natural()
        assert "Decision:" in prose
        assert "0%" in prose


class TestConfidenceHelpers:
    @pytest.mark.parametrize("frac,expected", [
        (Fraction(74, 100), "74%"),
        (Fraction(0), "0%"),
        (Fraction(1), "100%"),
        (Fraction(1, 2), "50%"),
        (None, "unknown"),
    ])
    def test_confidence_pct(self, frac, expected):
        assert _confidence_pct(frac) == expected

    @pytest.mark.parametrize("frac,label", [
        (Fraction(90, 100), "very high confidence"),
        (Fraction(75, 100), "high confidence"),
        (Fraction(60, 100), "moderate confidence"),
        (Fraction(35, 100), "low confidence"),
        (Fraction(10, 100), "very low confidence"),
    ])
    def test_confidence_label(self, frac, label):
        assert _confidence_label(frac) == label
