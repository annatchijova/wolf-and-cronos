"""
CRONOS — SHA-256 tamper-evident trace chain.
Adapted from the CORVUS AuditChain (VIGÍA AI Collective, Apache 2.0).

Each closed trace appends one entry whose SHA-256 hash incorporates:
  - all trace metadata (agent_id, objective, decision, confidence)
  - a steps_hash binding the full reasoning trace (recalls, tools,
    hypotheses, discards, evidence, decision) — see _steps_hash
  - the entry timestamp (see the design note below)
  - the hash of the preceding entry

Any retroactive modification of a trace — header field OR reasoning step —
breaks every subsequent hash. The chain can be exported and verified
independently of the running process.

Design note — timestamp is sealed on purpose.
  CLAUDE.md §5.2 records chain-of-custody timestamps *outside* the sealed
  payload, because that rule targets a *reproducible result seal* (same
  inputs must yield identical bytes). This is an append-only *audit* chain,
  where each entry is already unique (prev_hash linkage + UUID trace_id), and
  binding *when* a decision was sealed is a feature: it makes the recorded
  time itself tamper-evident. Moving the timestamp outside the seal would let
  an attacker backdate an entry without breaking the hash — strictly weaker.
  The deviation from §5.2 is therefore deliberate and scoped to this file.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# Version of the steps canonicalization used inside the seal.  Stamped into the
# hashed bytes so a future change to the encoding is itself tamper-evident and
# cannot silently produce two hashes for one input.
CANONICALIZE_VERSION = 1


def _steps_hash(step_rows: list[tuple]) -> str:
    """
    SHA-256 over the canonical serialization of a trace's steps.

    Binds the full reasoning trace — recalls, tools, hypotheses, discards,
    evidence, decision — into the sealed chain entry, so that any post-hoc
    edit of a *step* is detectable, not just an edit of the header fields.

    step_rows is a list of ``(seq, kind, payload_json, timestamp)`` tuples in
    seq order.  ``payload_json`` is the exact JSON string persisted in
    trace_steps (json.dumps with sort_keys), so the seal-time and verify-time
    inputs are byte-identical by construction — no re-serialization drift.
    """
    canonical = [
        {"seq": seq, "kind": kind, "payload": payload_json, "timestamp": ts}
        for (seq, kind, payload_json, ts) in step_rows
    ]
    raw = json.dumps(
        {"v": CANONICALIZE_VERSION, "steps": canonical},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compute_entry_hash(
    timestamp: str,
    trace_id: str,
    agent_id: str,
    objective: str,
    decision: str,
    confidence: str,
    prev_hash: str,
    steps_hash: str = "",
) -> str:
    canonical: dict[str, Any] = {
        "timestamp":  timestamp,
        "trace_id":   trace_id,
        "agent_id":   agent_id,
        "objective":  objective,
        "decision":   decision,
        "confidence": confidence,
        "prev_hash":  prev_hash,
    }
    # steps_hash binds the reasoning trace into the seal.  It is added only when
    # present so that legacy entries sealed before this field existed still
    # recompute to their original hash (backward-compatible verification).
    if steps_hash:
        canonical["steps_hash"] = steps_hash
    # separators=(',', ':') removes all whitespace from JSON output so the hash
    # is byte-for-byte identical across Python versions and across independent
    # verifier implementations.  json.dumps default includes spaces after
    # separators, which would silently break cross-implementation verification.
    #
    # NOTE: prev_hash is intentionally counted twice — once inside the canonical
    # JSON and once appended to `raw`. It is redundant (the JSON copy alone fully
    # binds the linkage), but harmless. It is kept as-is deliberately: removing
    # either occurrence would change every existing entry hash and invalidate
    # already-sealed chains, for zero security gain. Any independent verifier
    # must reproduce both occurrences to match.
    raw = (
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        + prev_hash
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class TraceChain:
    """
    Append-only SHA-256 hash chain backed by SQLite.
    One row per closed Trace. Callers own the transaction and must commit.
    """

    _GENESIS_HASH = "0" * 64

    def __init__(self, db_conn) -> None:
        self._conn = db_conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trace_chain (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                trace_id    TEXT    NOT NULL UNIQUE,
                agent_id    TEXT    NOT NULL,
                objective   TEXT    NOT NULL,
                decision    TEXT    NOT NULL,
                confidence  TEXT    NOT NULL,
                prev_hash   TEXT    NOT NULL,
                entry_hash  TEXT    NOT NULL UNIQUE,
                steps_hash  TEXT
            )
        """)
        self._conn.commit()
        self._migrate_add_steps_hash()

    def _migrate_add_steps_hash(self) -> None:
        """
        One-time migration: add the steps_hash column to chains created before
        the reasoning trace was bound into the seal.  Legacy rows keep
        steps_hash = NULL and continue to verify against their original hash.
        """
        cols = {row[1] for row in self._conn.execute(
            "PRAGMA table_info(trace_chain)"
        ).fetchall()}
        if "steps_hash" not in cols:
            self._conn.execute("ALTER TABLE trace_chain ADD COLUMN steps_hash TEXT")
            self._conn.commit()

    def _get_last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT entry_hash FROM trace_chain ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else self._GENESIS_HASH

    def append(
        self,
        trace_id: str,
        agent_id: str,
        objective: str,
        decision: str,
        confidence: str,   # fraction string "p/q"
        steps_hash: str = "",
    ) -> str:
        """
        Append a new trace to the chain.
        Returns the SHA-256 hash of the new entry.
        NOTE: does NOT commit — caller owns the transaction.

        steps_hash, when supplied, is the SHA-256 of the trace's steps
        (see _steps_hash). It is folded into the entry hash so that a
        retroactive edit of any reasoning step breaks verification.
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        prev_hash = self._get_last_hash()
        entry_hash = _compute_entry_hash(
            timestamp, trace_id, agent_id, objective, decision, confidence,
            prev_hash, steps_hash,
        )
        self._conn.execute("""
            INSERT INTO trace_chain
                (timestamp, trace_id, agent_id, objective, decision,
                 confidence, prev_hash, entry_hash, steps_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (timestamp, trace_id, agent_id, objective, decision,
              confidence, prev_hash, entry_hash, steps_hash or None))
        return entry_hash

    def verify(self) -> tuple[bool, list[str]]:
        """
        Recompute all hashes and verify chain linkage.
        Returns (True, []) if intact; (False, [error…]) otherwise.
        """
        rows = self._conn.execute("""
            SELECT id, timestamp, trace_id, agent_id, objective,
                   decision, confidence, prev_hash, entry_hash, steps_hash
            FROM trace_chain ORDER BY id ASC
        """).fetchall()

        errors: list[str] = []
        expected_prev = self._GENESIS_HASH

        for row in rows:
            (id_, ts, trace_id, agent_id, obj,
             dec, conf, prev_hash, stored_hash, stored_steps_hash) = row

            if prev_hash != expected_prev:
                errors.append(
                    f"Entry {id_} ({trace_id[:8]}…): "
                    f"prev_hash mismatch — chain is broken here"
                )

            computed = _compute_entry_hash(
                ts, trace_id, agent_id, obj, dec, conf, prev_hash,
                stored_steps_hash or "",
            )
            if computed != stored_hash:
                errors.append(
                    f"Entry {id_} ({trace_id[:8]}…): "
                    f"hash mismatch — entry may have been tampered with. "
                    f"Stored: {stored_hash[:16]}…, Computed: {computed[:16]}…"
                )

            # Recompute the steps hash from the actual trace_steps rows so an
            # edit to the *reasoning trace* (evidence, hypotheses, recalls) is
            # caught — not only edits to the header fields.  Skipped for legacy
            # entries sealed before steps were bound (stored_steps_hash NULL).
            if stored_steps_hash:
                actual_steps_hash = self._recompute_steps_hash(trace_id)
                if actual_steps_hash != stored_steps_hash:
                    errors.append(
                        f"Entry {id_} ({trace_id[:8]}…): "
                        f"steps_hash mismatch — the reasoning trace was "
                        f"modified after sealing."
                    )

            expected_prev = stored_hash

        return len(errors) == 0, errors

    def _recompute_steps_hash(self, trace_id: str) -> str:
        """
        Recompute the steps hash for one trace from the persisted trace_steps
        rows.  Returns "" if the steps table is absent (chain used standalone).
        """
        try:
            step_rows = self._conn.execute(
                "SELECT seq, kind, payload, timestamp FROM trace_steps "
                "WHERE trace_id = ? ORDER BY seq",
                (trace_id,),
            ).fetchall()
        except Exception:
            return ""  # no trace_steps table — chain verified on its own
        return _steps_hash([tuple(r) for r in step_rows])

    def export(self) -> list[dict]:
        """Export all chain entries in chronological order."""
        rows = self._conn.execute("""
            SELECT id, timestamp, trace_id, agent_id, objective,
                   decision, confidence, prev_hash, entry_hash
            FROM trace_chain ORDER BY id ASC
        """).fetchall()
        keys = [
            "id", "timestamp", "trace_id", "agent_id", "objective",
            "decision", "confidence", "prev_hash", "entry_hash",
        ]
        return [dict(zip(keys, row)) for row in rows]
