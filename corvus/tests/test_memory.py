"""
CORVUS Memory Layer Tests
Tests SQLite engine, Welford baseline, audit chain, and sleep consolidation.
"""
import pytest
import tempfile
import os
from fractions import Fraction

from corvus.memory.engine import MemoryEngine
from corvus.memory.consolidator import SleepConsolidator
from corvus.models import (
    AnalysisResult, VerdictLevel, Verdict,
)


def make_analysis_result(user_id="U001", active_signals=2, baseline_delta=Fraction(1, 2)):
    return AnalysisResult(
        message_id=f"msg_{user_id}_{active_signals}",
        user_id=user_id,
        channel_id="C001",
        text="test message",
        timestamp="2026-06-19T10:00:00",
        grice=None,
        influence=None,
        aristotle=None,
        berne=None,
        linguistic=None,
        peirce=None,
        active_signals=active_signals,
        baseline_delta=baseline_delta,
        audit_hash="a" * 64,
    )


def make_verdict(level=VerdictLevel.ALERT, score=Fraction(1, 2)):
    return Verdict(
        level=level,
        score=score,
        rationale="test rationale",
        signals_fired=["influence", "grice"],
        recommendation="review message",
        audit_hash="b" * 64,
    )


@pytest.fixture
def memory():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = MemoryEngine(db_path)
    engine.initialize()
    yield engine
    os.unlink(db_path)


class TestMemoryEngine:
    def test_initialize_creates_tables(self, memory):
        baseline = memory.get_user_baseline("U_new")
        assert "nv_ratio_mean" in baseline
        assert "avg_signals_per_message" in baseline
        assert baseline["message_count"] == 0

    def test_store_message(self, memory):
        result = make_analysis_result("U001", active_signals=2)
        verdict = make_verdict()
        memory.store_message(result, verdict)
        history = memory.get_user_history("U001")
        assert len(history) == 1

    def test_baseline_updates_after_store(self, memory):
        for i in range(5):
            result = make_analysis_result("U002", active_signals=i % 3)
            verdict = make_verdict()
            memory.store_message(result, verdict)
        baseline = memory.get_user_baseline("U002")
        assert baseline["message_count"] == 5
        assert baseline["avg_signals_per_message"] >= 0

    def test_welford_online_update(self, memory):
        """Welford mean should converge to correct value."""
        # Store 10 messages with active_signals always 2
        for i in range(10):
            result = make_analysis_result("U003", active_signals=2)
            verdict = make_verdict()
            memory.store_message(result, verdict)
        baseline = memory.get_user_baseline("U003")
        # Mean should be close to 2.0
        assert abs(baseline["avg_signals_per_message"] - 2.0) < 0.01

    def test_user_history_limit(self, memory):
        for i in range(25):
            result = make_analysis_result("U004", active_signals=1)
            verdict = make_verdict()
            memory.store_message(result, verdict)
        history = memory.get_user_history("U004", limit=10)
        assert len(history) <= 10

    def test_channel_stats(self, memory):
        for i in range(5):
            result = make_analysis_result(f"U{i:03d}", active_signals=i % 4)
            result.channel_id = "C_TEST"
            verdict = make_verdict()
            memory.store_message(result, verdict)
        stats = memory.get_channel_stats("C_TEST")
        assert "total_messages" in stats
        assert stats["total_messages"] == 5

    def test_signals_sum_is_exact_integer_accumulator(self, memory):
        # signals_sum must track the exact integer total of active_signals so the
        # baseline delta can be computed as an exact Fraction (no float, no floor).
        counts = [0, 1, 2, 0, 1]  # sum = 4 over 5 messages → true avg 0.8
        for c in counts:
            memory.store_message(make_analysis_result("U_SUM", active_signals=c),
                                 make_verdict())
        baseline = memory.get_user_baseline("U_SUM")
        assert baseline["signals_sum"] == sum(counts)
        assert baseline["message_count"] == len(counts)

    def test_get_last_verdict(self, memory):
        result = make_analysis_result("U005")
        verdict = make_verdict(level=VerdictLevel.CRITICAL, score=Fraction(4, 5))
        memory.store_message(result, verdict)
        last = memory.get_last_verdict("U005")
        assert last is not None
        assert last["verdict_level"] == "CRITICAL"


class TestAuditChain:
    def test_empty_chain_verifies(self, memory):
        chain = memory.get_audit_chain()
        ok, errors = chain.verify()
        assert ok
        assert errors == []

    def test_append_and_verify(self, memory):
        chain = memory.get_audit_chain()
        chain.append("store", "U001", "C001", "message stored")
        chain.append("verdict", "U001", "C001", "ALERT emitted")
        ok, errors = chain.verify()
        assert ok
        assert errors == []

    def test_chain_grows(self, memory):
        chain = memory.get_audit_chain()
        for i in range(5):
            chain.append("store", f"U{i:03d}", "C001", f"op {i}")
        entries = chain.export()
        assert len(entries) == 5

    def test_export_has_required_fields(self, memory):
        chain = memory.get_audit_chain()
        chain.append("store", "U001", "C001", "test")
        entries = chain.export()
        assert len(entries) == 1
        entry = entries[0]
        assert "timestamp" in entry
        assert "operation" in entry
        assert "entry_hash" in entry
        assert "prev_hash" in entry

    def test_hash_length(self, memory):
        chain = memory.get_audit_chain()
        chain.append("store", "U001", "C001", "test")
        entries = chain.export()
        assert len(entries[0]["entry_hash"]) == 64


class TestSleepConsolidator:
    def test_consolidate_empty_db(self, memory):
        consolidator = SleepConsolidator(memory)
        result = consolidator.consolidate()
        assert "users_updated" in result
        assert "messages_pruned" in result
        assert result["errors"] == []

    def test_consolidate_recomputes_baseline(self, memory):
        # Store 60 messages for one user
        for i in range(60):
            result = make_analysis_result("U_CONSOL", active_signals=3)
            verdict = make_verdict()
            memory.store_message(result, verdict)

        baseline_before = memory.get_user_baseline("U_CONSOL")
        consolidator = SleepConsolidator(memory)
        summary = consolidator.consolidate()

        baseline_after = memory.get_user_baseline("U_CONSOL")
        # baseline should still reflect the data
        assert abs(baseline_after["avg_signals_per_message"] - 3.0) < 0.1
        assert summary["users_updated"] >= 1
        # signals_sum must be rebuilt exactly by the batch recompute: 60 × 3.
        assert baseline_after["signals_sum"] == 60 * 3
