"""
CRONOS — test_chain.py
Tests for TraceChain SHA-256 hash integrity.
"""

import hashlib
import json
import sqlite3
import pytest

from cronos.chain import TraceChain, _compute_entry_hash


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA journal_mode=WAL")
    yield c
    c.close()


@pytest.fixture
def chain(conn):
    return TraceChain(conn)


class TestChainAppend:
    def test_first_entry_uses_genesis_hash(self, chain, conn):
        h = chain.append("t1", "agent-A", "Do X", "Done", "74/100")
        conn.commit()
        row = conn.execute("SELECT prev_hash FROM trace_chain WHERE trace_id='t1'").fetchone()
        assert row[0] == "0" * 64

    def test_second_entry_links_to_first(self, chain, conn):
        h1 = chain.append("t1", "agent-A", "Do X", "Done", "74/100")
        conn.commit()
        h2 = chain.append("t2", "agent-A", "Do Y", "Done", "80/100")
        conn.commit()
        row = conn.execute("SELECT prev_hash FROM trace_chain WHERE trace_id='t2'").fetchone()
        assert row[0] == h1

    def test_returns_sha256_hex(self, chain, conn):
        h = chain.append("t1", "agent-A", "obj", "dec", "50/100")
        conn.commit()
        assert len(h) == 64
        int(h, 16)  # must be valid hex

    def test_unique_hash_per_entry(self, chain, conn):
        h1 = chain.append("t1", "agent-A", "obj", "dec1", "50/100")
        conn.commit()
        h2 = chain.append("t2", "agent-A", "obj", "dec2", "50/100")
        conn.commit()
        assert h1 != h2

    def test_empty_chain_verify_ok(self, chain):
        ok, errors = chain.verify()
        assert ok is True
        assert errors == []

    def test_single_entry_verify_ok(self, chain, conn):
        chain.append("t1", "agent-A", "obj", "dec", "74/100")
        conn.commit()
        ok, errors = chain.verify()
        assert ok is True
        assert errors == []

    def test_multiple_entries_verify_ok(self, chain, conn):
        for i in range(5):
            chain.append(f"t{i}", "agent-A", f"obj {i}", f"dec {i}", f"{i*10}/100")
            conn.commit()
        ok, errors = chain.verify()
        assert ok is True
        assert errors == []


class TestChainTampering:
    def test_tampered_decision_breaks_hash(self, chain, conn):
        chain.append("t1", "agent-A", "obj", "original decision", "74/100")
        conn.commit()
        # Modify decision directly in DB
        conn.execute(
            "UPDATE trace_chain SET decision='TAMPERED' WHERE trace_id='t1'"
        )
        conn.commit()
        ok, errors = chain.verify()
        assert ok is False
        assert any("hash mismatch" in e for e in errors)

    def test_tampered_prev_hash_breaks_chain(self, chain, conn):
        chain.append("t1", "agent-A", "obj", "dec", "74/100")
        conn.commit()
        chain.append("t2", "agent-A", "obj2", "dec2", "80/100")
        conn.commit()
        # Break the prev_hash linkage of t2
        conn.execute(
            "UPDATE trace_chain SET prev_hash='0'*64 WHERE trace_id='t2'"
        )
        conn.commit()
        ok, errors = chain.verify()
        assert ok is False

    def test_deleted_entry_breaks_chain(self, chain, conn):
        chain.append("t1", "agent-A", "obj", "dec", "74/100")
        conn.commit()
        chain.append("t2", "agent-A", "obj2", "dec2", "80/100")
        conn.commit()
        conn.execute("DELETE FROM trace_chain WHERE trace_id='t1'")
        conn.commit()
        # t2's prev_hash now doesn't match genesis
        ok, errors = chain.verify()
        assert ok is False


class TestChainExport:
    def test_export_empty(self, chain):
        assert chain.export() == []

    def test_export_contains_all_fields(self, chain, conn):
        chain.append("t1", "agent-A", "obj", "dec", "74/100")
        conn.commit()
        entries = chain.export()
        assert len(entries) == 1
        e = entries[0]
        for key in ["id", "timestamp", "trace_id", "agent_id", "objective",
                    "decision", "confidence", "prev_hash", "entry_hash"]:
            assert key in e

    def test_export_ordered_by_id(self, chain, conn):
        for i in range(3):
            chain.append(f"t{i}", "agent-A", f"obj{i}", f"dec{i}", "50/100")
            conn.commit()
        entries = chain.export()
        ids = [e["id"] for e in entries]
        assert ids == sorted(ids)


class TestComputeHash:
    def test_deterministic(self):
        h1 = _compute_entry_hash("ts", "tid", "aid", "obj", "dec", "74/100", "prev")
        h2 = _compute_entry_hash("ts", "tid", "aid", "obj", "dec", "74/100", "prev")
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        h1 = _compute_entry_hash("ts", "t1", "aid", "obj", "dec", "74/100", "prev")
        h2 = _compute_entry_hash("ts", "t2", "aid", "obj", "dec", "74/100", "prev")
        assert h1 != h2

    def test_compact_json_no_spaces(self):
        """
        Hash must be byte-identical to an independent implementation that also uses
        compact JSON separators.  Any space in the serialized canonical dict would
        silently break cross-implementation verification.
        """
        canonical = {
            "agent_id":   "aid",
            "confidence": "74/100",
            "decision":   "dec",
            "objective":  "obj",
            "prev_hash":  "prev",
            "timestamp":  "ts",
            "trace_id":   "tid",
        }
        raw = (
            json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            + "prev"
        ).encode("utf-8")
        expected = hashlib.sha256(raw).hexdigest()
        assert _compute_entry_hash("ts", "tid", "aid", "obj", "dec", "74/100", "prev") == expected

    def test_hash_differs_from_spaced_json(self):
        """Verify that the old (spaced) serialization would give a DIFFERENT hash."""
        canonical = {
            "agent_id":   "aid",
            "confidence": "74/100",
            "decision":   "dec",
            "objective":  "obj",
            "prev_hash":  "prev",
            "timestamp":  "ts",
            "trace_id":   "tid",
        }
        # Old format had default separators (with spaces)
        raw_spaced = (
            json.dumps(canonical, sort_keys=True, ensure_ascii=False)
            + "prev"
        ).encode("utf-8")
        spaced_hash = hashlib.sha256(raw_spaced).hexdigest()
        actual = _compute_entry_hash("ts", "tid", "aid", "obj", "dec", "74/100", "prev")
        assert actual != spaced_hash
