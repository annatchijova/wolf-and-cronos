"""
CRONOS — test_output.py
Tests for Block Kit formatters (output.py).
"""

import pytest
from fractions import Fraction

from cronos import CronosTracer, TraceStore
from slack.output import (
    format_trace_card,
    format_trace_explain,
    format_trace_list,
    format_audit_export,
    format_status,
    _confidence_bar,
    _escape,
)


@pytest.fixture
def store(tmp_path):
    return TraceStore(str(tmp_path / "test.db"))


def _make_trace(store):
    with CronosTracer(store, "support-resolver", "C1", "U1",
                      "Resolve ticket #99") as t:
        t.record_recall("M-22", "Auth timeout 2024 incident", score=Fraction(91, 100))
        t.call_tool("jira", "ticket #99 → Open / Auth / High")
        t.add_hypothesis("auth_bug",  "Token expired")
        t.add_hypothesis("cache_bug", "Cache stale")
        t.add_evidence("Jira confirms Auth", supports="auth_bug")
        t.discard_hypothesis("cache_bug", "No cache errors")
        t.decide("Rotate auth token", Fraction(74, 100))
    return store.get_latest_trace()


class TestFormatTraceCard:
    def test_returns_list_of_blocks(self, store):
        trace = _make_trace(store)
        blocks = format_trace_card(trace)
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_contains_decision_text(self, store):
        trace = _make_trace(store)
        blocks = format_trace_card(trace)
        text = _blocks_text(blocks)
        assert "Rotate auth token" in text

    def test_contains_agent_id(self, store):
        trace = _make_trace(store)
        blocks = format_trace_card(trace)
        text = _blocks_text(blocks)
        assert "support-resolver" in text

    def test_contains_confidence(self, store):
        trace = _make_trace(trace=None, store=store) if False else _make_trace(store)
        blocks = format_trace_card(trace)
        text = _blocks_text(blocks)
        assert "74%" in text

    def test_no_raw_angle_brackets_in_user_text(self, store):
        """User-supplied text must be escaped."""
        with CronosTracer(store, "ag", "C1", "U1", "Do <script>") as t:
            t.decide("Fix <xss>", Fraction(50, 100))
        trace = store.get_latest_trace()
        blocks = format_trace_card(trace)
        text = _blocks_text(blocks)
        assert "<script>" not in text
        assert "<xss>" not in text
        assert "&lt;" in text or "Fix" in text  # escaped or no user text shown directly


class TestFormatTraceExplain:
    def test_returns_list_of_blocks(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_contains_objective(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        text = _blocks_text(blocks)
        assert "Resolve ticket #99" in text

    def test_contains_memories_section(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        text = _blocks_text(blocks)
        assert "M-22" in text

    def test_contains_tool_section(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        text = _blocks_text(blocks)
        assert "jira" in text.lower()

    def test_contains_hypotheses_section(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        text = _blocks_text(blocks)
        assert "auth_bug" in text
        assert "cache_bug" in text

    def test_contains_natural_language_prose(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        text = _blocks_text(blocks)
        assert "plain language" in text.lower() or "Because" in text

    def test_contains_chain_badge(self, store):
        trace = _make_trace(store)
        blocks = format_trace_explain(trace)
        text = _blocks_text(blocks)
        assert "verified" in text.lower() or "chain" in text.lower()


class TestFormatTraceList:
    def test_empty_returns_empty_message(self, store):
        blocks = format_trace_list([])
        text = _blocks_text(blocks)
        assert "No traces" in text

    def test_shows_agent_id_and_decision(self, store):
        trace = _make_trace(store)
        recent = store.get_recent_traces()
        blocks = format_trace_list(recent)
        text = _blocks_text(blocks)
        assert "support-resolver" in text
        assert "Rotate auth token" in text

    def test_has_explain_button(self, store):
        _make_trace(store)
        recent = store.get_recent_traces()
        blocks = format_trace_list(recent)
        # Look for accessory buttons
        buttons = [
            b.get("accessory")
            for b in blocks
            if b.get("type") == "section" and b.get("accessory")
        ]
        assert len(buttons) >= 1
        assert buttons[0]["action_id"] == "cronos_explain_trace"


class TestFormatAuditExport:
    def test_ok_chain(self, store):
        _make_trace(store)
        entries = store.chain.export()
        blocks = format_audit_export(entries, True, [])
        text = _blocks_text(blocks)
        assert "intact" in text.lower() or "verified" in text.lower()

    def test_broken_chain_shows_errors(self, store):
        blocks = format_audit_export([], False, ["Entry 1: hash mismatch"])
        text = _blocks_text(blocks)
        assert "failure" in text.lower() or "error" in text.lower()


class TestFormatStatus:
    def test_shows_total_and_agents(self, store):
        _make_trace(store)
        recent = store.get_recent_traces()
        blocks = format_status(1, recent)
        text = _blocks_text(blocks)
        assert "1" in text
        assert "support-resolver" in text


class TestOutputLimits:
    def test_explain_blocks_never_exceed_slack_limit(self, store):
        """format_trace_explain must never return > 50 blocks (Slack hard limit)."""
        # Build a trace with many steps to stress the block count
        with CronosTracer(store, "ag", "C1", "U1", "Big trace") as t:
            for i in range(15):
                t.record_recall(f"M-{i}", f"memory {i}", score=Fraction(50 + i, 100))
            for i in range(10):
                t.call_tool(f"tool{i}", f"result {i}")
            for i in range(10):
                t.add_hypothesis(f"h{i}", f"desc {i}")
            for i in range(5):
                t.add_evidence(f"evidence {i}", supports="h0")
            for i in range(5):
                t.add_evidence(f"counter {i}", refutes="h1")
            t.decide("complex action", Fraction(70, 100))
        trace = store.get_latest_trace()
        blocks = format_trace_explain(trace)
        assert len(blocks) <= 50, f"Got {len(blocks)} blocks — exceeds Slack limit"

    def test_trunc_short_text_unchanged(self):
        from slack.output import _trunc
        assert _trunc("hello") == "hello"

    def test_trunc_long_text_cut(self):
        from slack.output import _trunc
        text = "x" * 4000
        result = _trunc(text, max_len=3000)
        assert len(result) == 3000
        assert result.endswith("…")


class TestHelpers:
    @pytest.mark.parametrize("pct,expected", [
        ("0%",   "[░░░░░░░░░░]"),
        ("100%", "[██████████]"),
        ("50%",  "[█████░░░░░]"),
        ("74%",  "[███████░░░]"),
    ])
    def test_confidence_bar(self, pct, expected):
        assert _confidence_bar(pct) == expected

    def test_escape_angle_brackets(self):
        assert _escape("<script>") == "&lt;script&gt;"

    def test_escape_ampersand(self):
        assert _escape("a & b") == "a &amp; b"

    def test_escape_clean_text(self):
        assert _escape("hello world") == "hello world"


# ── Helper ───────────────────────────────────────────────────────────────────

def _blocks_text(blocks: list[dict]) -> str:
    """Extract all text from a Block Kit block list."""
    parts = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("text")
        if isinstance(t, dict):
            parts.append(t.get("text", ""))
        elif isinstance(t, str):
            parts.append(t)
        # header text
        if b.get("type") == "header":
            ht = b.get("text", {})
            parts.append(ht.get("text", ""))
        # fields
        for f in b.get("fields", []):
            parts.append(f.get("text", ""))
        # context elements
        for e in b.get("elements", []):
            if isinstance(e, dict):
                parts.append(e.get("text", ""))
        # accessory
        acc = b.get("accessory", {})
        if isinstance(acc, dict):
            at = acc.get("text", {})
            if isinstance(at, dict):
                parts.append(at.get("text", ""))
    return "\n".join(parts)
