"""
CRONOS — SQLite persistence layer.
WAL mode enables concurrent reads while a trace is being written.
All writes to traces + steps + chain land in a single atomic commit.
"""

import json
import logging
import sqlite3
from fractions import Fraction
from typing import Optional

log = logging.getLogger("cronos.store")

from .chain import TraceChain, _steps_hash
from .models import Trace, TraceStep, StepKind, TraceQuality


def _fraction_to_str(f: Optional[Fraction]) -> str:
    if f is None:
        return "0/1"
    return f"{f.numerator}/{f.denominator}"


def _str_to_fraction(s: Optional[str]) -> Optional[Fraction]:
    if not s:
        return None
    try:
        p, q = s.split("/")
        return Fraction(int(p), int(q))
    except (ValueError, ZeroDivisionError):
        log.warning("Malformed fraction string in DB: %r — treating as None", s)
        return None


class TraceStore:
    """
    Persists Trace objects (header + steps) to SQLite.
    Each save_trace() call also appends one entry to the TraceChain,
    and everything lands in a single conn.commit().
    """

    def __init__(self, db_path: str = "cronos.db") -> None:
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_tables()
        self.chain = TraceChain(self._conn)

    def _ensure_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS traces (
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
            );

            CREATE TABLE IF NOT EXISTS trace_steps (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id    TEXT NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
                seq         INTEGER NOT NULL,
                kind        TEXT NOT NULL,
                payload     TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_steps_trace
                ON trace_steps(trace_id, seq);
            CREATE INDEX IF NOT EXISTS idx_traces_agent
                ON traces(agent_id);
            CREATE INDEX IF NOT EXISTS idx_traces_channel
                ON traces(channel_id);
            CREATE INDEX IF NOT EXISTS idx_traces_closed
                ON traces(closed_at DESC);
        """)
        self._conn.commit()
        self._migrate_trace_steps_cascade()

    def _migrate_trace_steps_cascade(self) -> None:
        """
        One-time migration: recreate trace_steps with ON DELETE CASCADE if the
        existing table was created without it.  SQLite does not support ALTER TABLE
        to modify FK actions, so we rename + recreate + copy.
        """
        fk_list = self._conn.execute(
            "PRAGMA foreign_key_list(trace_steps)"
        ).fetchall()
        if not fk_list:
            return  # table does not exist yet — CREATE TABLE already has CASCADE
        has_cascade = any(row[6] == "CASCADE" for row in fk_list)
        if has_cascade:
            return  # already correct
        log.info("Migrating trace_steps → adding ON DELETE CASCADE (one-time)")
        self._conn.executescript("""
            ALTER TABLE trace_steps RENAME TO _trace_steps_old;
            CREATE TABLE trace_steps (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id  TEXT    NOT NULL REFERENCES traces(trace_id) ON DELETE CASCADE,
                seq       INTEGER NOT NULL,
                kind      TEXT    NOT NULL,
                payload   TEXT    NOT NULL,
                timestamp TEXT    NOT NULL
            );
            INSERT INTO trace_steps SELECT * FROM _trace_steps_old;
            DROP TABLE _trace_steps_old;
            CREATE INDEX IF NOT EXISTS idx_steps_trace ON trace_steps(trace_id, seq);
        """)
        self._conn.commit()
        log.info("trace_steps migration complete")

    def save_trace(self, trace: Trace) -> None:
        """
        Atomically persist a closed Trace:
          1. Append to hash chain (no internal commit)
          2. Insert trace header
          3. Insert all steps
          4. Single conn.commit() — all or nothing
        """
        conf_str = _fraction_to_str(trace.confidence)
        decision  = trace.decision or ""

        # Serialize every step exactly once.  The same JSON string is both
        # hashed into the seal and persisted to trace_steps, so seal-time and
        # verify-time inputs are byte-identical (no re-serialization drift).
        step_rows = [
            (
                seq,
                step.kind.value,
                json.dumps(step.payload, ensure_ascii=False, sort_keys=True),
                step.timestamp,
            )
            for seq, step in enumerate(trace.steps)
        ]
        steps_hash = _steps_hash(step_rows)

        try:
            # Chain append — no commit, we own the transaction.  steps_hash
            # binds the reasoning trace into the tamper-evident seal.
            entry_hash = self.chain.append(
                trace.trace_id, trace.agent_id,
                trace.objective, decision, conf_str,
                steps_hash=steps_hash,
            )
            trace.entry_hash = entry_hash
            trace.chain_ok   = True

            self._conn.execute("""
                INSERT OR REPLACE INTO traces
                    (trace_id, agent_id, channel_id, user_id, objective,
                     decision, confidence, started_at, closed_at, entry_hash, chain_ok,
                     quality, diversity, contradictions, confidence_warnings, cronos_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, (
                trace.trace_id, trace.agent_id, trace.channel_id, trace.user_id,
                trace.objective, decision, conf_str,
                trace.started_at, trace.closed_at, entry_hash,
                trace.quality.value if trace.quality else None,
                (f"{trace.diversity.numerator}/{trace.diversity.denominator}"
                 if trace.diversity is not None else None),
                json.dumps(trace.contradictions or [], ensure_ascii=False),
                json.dumps(trace.confidence_warnings or [], ensure_ascii=False),
                trace.cronos_version or None,
            ))

            for (seq, kind, payload_json, timestamp) in step_rows:
                self._conn.execute("""
                    INSERT INTO trace_steps (trace_id, seq, kind, payload, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (trace.trace_id, seq, kind, payload_json, timestamp))

            self._conn.commit()  # single commit: chain + header + steps

        except Exception:
            self._conn.rollback()  # no partial traces — all or nothing
            raise

    def load_trace(self, trace_id: str) -> Optional[Trace]:
        """Load a full Trace including all steps."""
        row = self._conn.execute(
            """SELECT trace_id, agent_id, channel_id, user_id, objective,
                      decision, confidence, started_at, closed_at, entry_hash, chain_ok,
                      quality, diversity, contradictions, confidence_warnings, cronos_version
               FROM traces WHERE trace_id = ?""",
            (trace_id,),
        ).fetchone()
        if not row:
            return None

        (tid, agent_id, channel_id, user_id, objective,
         decision, confidence, started_at, closed_at, entry_hash, chain_ok,
         quality_str, diversity_str, contradictions_json,
         conf_warnings_json, cronos_version) = row

        step_rows = self._conn.execute(
            "SELECT kind, payload, timestamp FROM trace_steps "
            "WHERE trace_id = ? ORDER BY seq",
            (tid,),
        ).fetchall()

        steps = [
            TraceStep(
                kind=StepKind(r[0]),
                payload=json.loads(r[1]),
                timestamp=r[2],
            )
            for r in step_rows
        ]

        quality = TraceQuality(quality_str) if quality_str else None
        diversity = _str_to_fraction(diversity_str)
        contradictions = json.loads(contradictions_json) if contradictions_json else []
        conf_warnings = json.loads(conf_warnings_json) if conf_warnings_json else []

        # Honest degradation (§5.3): a stored confidence that is present but
        # unparseable must be surfaced, not silently mimicked as "no confidence".
        # A non-empty string that _str_to_fraction cannot parse is corruption.
        confidence_val = _str_to_fraction(confidence)
        confidence_corrupt = bool(confidence) and confidence_val is None
        if confidence_corrupt:
            log.warning(
                "Trace %s: stored confidence %r is corrupt — flagging, not hiding",
                tid, confidence,
            )

        return Trace(
            trace_id=tid,
            agent_id=agent_id,
            channel_id=channel_id,
            user_id=user_id,
            objective=objective,
            steps=steps,
            decision=decision or None,
            confidence=confidence_val,
            confidence_corrupt=confidence_corrupt,
            started_at=started_at,
            closed_at=closed_at,
            entry_hash=entry_hash,
            chain_ok=bool(chain_ok),
            closed=True,
            quality=quality,
            diversity=diversity,
            contradictions=contradictions,
            confidence_warnings=conf_warnings,
            cronos_version=cronos_version or "",
        )

    def get_latest_trace(
        self,
        agent_id: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> Optional[Trace]:
        """Return the most recently closed trace, optionally filtered."""
        if agent_id and channel_id:
            row = self._conn.execute(
                "SELECT trace_id FROM traces "
                "WHERE agent_id = ? AND channel_id = ? ORDER BY closed_at DESC LIMIT 1",
                (agent_id, channel_id),
            ).fetchone()
        elif agent_id:
            row = self._conn.execute(
                "SELECT trace_id FROM traces WHERE agent_id = ? ORDER BY closed_at DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT trace_id FROM traces ORDER BY closed_at DESC LIMIT 1"
            ).fetchone()
        return self.load_trace(row[0]) if row else None

    def get_recent_traces(
        self,
        agent_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return lightweight headers (no steps) for listing."""
        if agent_id:
            rows = self._conn.execute("""
                SELECT trace_id, agent_id, objective, decision, confidence,
                       closed_at, entry_hash, chain_ok
                FROM traces WHERE agent_id = ? ORDER BY closed_at DESC LIMIT ?
            """, (agent_id, limit)).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT trace_id, agent_id, objective, decision, confidence,
                       closed_at, entry_hash, chain_ok
                FROM traces ORDER BY closed_at DESC LIMIT ?
            """, (limit,)).fetchall()

        keys = [
            "trace_id", "agent_id", "objective", "decision", "confidence",
            "closed_at", "entry_hash", "chain_ok",
        ]
        return [dict(zip(keys, r)) for r in rows]

    def count_traces(self, agent_id: Optional[str] = None) -> int:
        if agent_id:
            return self._conn.execute(
                "SELECT COUNT(*) FROM traces WHERE agent_id = ?", (agent_id,)
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
