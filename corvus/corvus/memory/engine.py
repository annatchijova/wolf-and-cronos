"""
CORVUS Memory Engine
SQLite-backed per-user behavioral baseline storage.
Uses Welford's online algorithm for incremental mean/variance computation
without storing all raw observations.
"""

import os
import sqlite3
from fractions import Fraction
from typing import Optional

from corvus.models import AnalysisResult, Verdict
from corvus.memory.audit import AuditChain


# Default baseline for new users — no prior history
_DEFAULT_BASELINE = {
    "nv_ratio_mean": 1.0,
    "nv_ratio_std": 0.5,
    "cli_stress_mean": 0.1,
    "avg_signals_per_message": 0.0,
    "signals_sum": 0,        # exact integer accumulator of active_signals
    "message_count": 0,
}


class MemoryEngine:
    """
    Per-user behavioral memory using SQLite with WAL mode.
    Baselines are maintained with Welford's online algorithm —
    no need to replay all messages to update statistics.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._audit: Optional[AuditChain] = None

    def initialize(self) -> None:
        """
        Open the database connection, enable WAL mode, and create tables.
        Creates parent directories if they do not exist.
        """
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._migrate_schema()
        self._audit = AuditChain(self._conn)

    def _migrate_schema(self) -> None:
        """
        Forward-only, idempotent column migrations for databases created by an
        earlier CORVUS version. CREATE TABLE IF NOT EXISTS never adds columns to
        an existing table, so newly introduced columns are added here.
        """
        # signals_sum: exact integer accumulator for the baseline delta.
        try:
            self._conn.execute(
                "ALTER TABLE baselines ADD COLUMN signals_sum INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            # Column already exists (fresh DB created with it, or prior migration).
            pass

    def _create_tables(self) -> None:
        """Create all CORVUS tables if they do not exist."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         TEXT    NOT NULL,
                channel_id      TEXT    NOT NULL,
                timestamp       TEXT    NOT NULL,
                text_hash       TEXT    NOT NULL,
                nv_ratio        REAL    NOT NULL DEFAULT 0.0,
                cli_stress      TEXT    NOT NULL DEFAULT '0/1',
                active_signals  INTEGER NOT NULL DEFAULT 0,
                verdict_level   TEXT    NOT NULL DEFAULT 'SILENT',
                audit_hash      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_user_id
                ON messages (user_id);

            CREATE INDEX IF NOT EXISTS idx_messages_channel_id
                ON messages (channel_id);

            CREATE TABLE IF NOT EXISTS baselines (
                user_id                 TEXT PRIMARY KEY,
                nv_ratio_mean           REAL    NOT NULL DEFAULT 1.0,
                nv_ratio_std            REAL    NOT NULL DEFAULT 0.5,
                cli_stress_mean         REAL    NOT NULL DEFAULT 0.1,
                avg_signals_per_message REAL    NOT NULL DEFAULT 0.0,
                signals_sum             INTEGER NOT NULL DEFAULT 0,
                message_count           INTEGER NOT NULL DEFAULT 0,
                last_updated            TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS audit_chain (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                operation       TEXT    NOT NULL,
                user_id         TEXT    NOT NULL,
                channel_id      TEXT    NOT NULL,
                payload_summary TEXT    NOT NULL,
                prev_hash       TEXT    NOT NULL,
                entry_hash      TEXT    NOT NULL UNIQUE
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_message(self, result: AnalysisResult, verdict: Verdict) -> None:
        """
        Persist a processed message and update the user's behavioral baseline
        using Welford's online algorithm.

        Welford update:
            n_new = n + 1
            mean_new = mean_old + (x - mean_old) / n_new
            M2_new  = M2_old + (x - mean_old) * (x - mean_new)
            std_new = sqrt(M2_new / n_new)  [population std]

        Parameters
        ----------
        result : AnalysisResult
        verdict : Verdict
        """
        import hashlib

        text_hash = hashlib.sha256(result.text.encode("utf-8")).hexdigest()
        cli_stress_str = (
            f"{result.linguistic.cli_stress.numerator}/{result.linguistic.cli_stress.denominator}"
            if result.linguistic is not None
            else "0/1"
        )
        nv_ratio = result.linguistic.nv_ratio if result.linguistic is not None else 0.0

        self._conn.execute(
            """
            INSERT INTO messages
                (user_id, channel_id, timestamp, text_hash, nv_ratio,
                 cli_stress, active_signals, verdict_level, audit_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.user_id,
                result.channel_id,
                result.timestamp,
                text_hash,
                nv_ratio,
                cli_stress_str,
                result.active_signals,
                verdict.level.value,
                result.audit_hash,
            ),
        )

        # Welford online update for baseline
        self._welford_update(result.user_id, nv_ratio, float(result.linguistic.cli_stress)
                             if result.linguistic else 0.0, result.active_signals)

        # P0 fix: write audit chain BEFORE commit so both succeed or both fail.
        # The audit entry is part of the same logical transaction.
        audit_summary = (
            f"message_id={result.message_id} verdict={verdict.level.value} "
            f"score={verdict.score.numerator}/{verdict.score.denominator} "
            f"signals={result.active_signals}"
        )
        self._audit.append(
            operation="store",
            user_id=result.user_id,
            channel_id=result.channel_id,
            payload_summary=audit_summary,
        )

        self._conn.commit()

    def get_user_baseline(self, user_id: str) -> dict:
        """
        Return the behavioral baseline for a user.
        Falls back to sensible defaults for new users with no history.

        Parameters
        ----------
        user_id : str

        Returns
        -------
        dict with keys:
            nv_ratio_mean, nv_ratio_std, cli_stress_mean,
            avg_signals_per_message, message_count
        """
        cursor = self._conn.execute(
            """
            SELECT nv_ratio_mean, nv_ratio_std, cli_stress_mean,
                   avg_signals_per_message, signals_sum, message_count
            FROM baselines
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return dict(_DEFAULT_BASELINE)
        return {
            "nv_ratio_mean": row[0],
            "nv_ratio_std": row[1],
            "cli_stress_mean": row[2],
            "avg_signals_per_message": row[3],
            "signals_sum": row[4],
            "message_count": row[5],
        }

    def get_user_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """
        Return the last N stored messages for a user.

        Parameters
        ----------
        user_id : str
        limit : int
            Maximum number of records to return (default 20).

        Returns
        -------
        list[dict]
        """
        cursor = self._conn.execute(
            """
            SELECT id, channel_id, timestamp, nv_ratio, cli_stress,
                   active_signals, verdict_level, audit_hash
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "channel_id": row[1],
                "timestamp": row[2],
                "nv_ratio": row[3],
                "cli_stress": row[4],
                "active_signals": row[5],
                "verdict_level": row[6],
                "audit_hash": row[7],
            }
            for row in rows
        ]

    def get_channel_stats(self, channel_id: str) -> dict:
        """
        Aggregate statistics for a channel (for /corvus status command).

        Parameters
        ----------
        channel_id : str

        Returns
        -------
        dict with keys:
            total_messages, unique_users, avg_signals_per_message,
            verdict_counts (dict of level → count),
            highest_risk_user
        """
        cursor = self._conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT user_id), AVG(active_signals)
            FROM messages
            WHERE channel_id = ?
            """,
            (channel_id,),
        )
        agg = cursor.fetchone()
        total_messages = agg[0] or 0
        unique_users = agg[1] or 0
        avg_signals = round(agg[2] or 0.0, 3)

        # Verdict distribution
        cursor = self._conn.execute(
            """
            SELECT verdict_level, COUNT(*) as cnt
            FROM messages
            WHERE channel_id = ?
            GROUP BY verdict_level
            ORDER BY cnt DESC
            """,
            (channel_id,),
        )
        verdict_counts = {row[0]: row[1] for row in cursor.fetchall()}

        # Highest-risk user (most non-SILENT verdicts)
        cursor = self._conn.execute(
            """
            SELECT user_id, COUNT(*) as risk_count
            FROM messages
            WHERE channel_id = ? AND verdict_level != 'SILENT'
            GROUP BY user_id
            ORDER BY risk_count DESC
            LIMIT 1
            """,
            (channel_id,),
        )
        row = cursor.fetchone()
        highest_risk_user = row[0] if row else None

        return {
            "total_messages": total_messages,
            "unique_users": unique_users,
            "avg_signals_per_message": avg_signals,
            "verdict_counts": verdict_counts,
            "highest_risk_user": highest_risk_user,
        }

    def get_last_verdict(self, user_id: str) -> Optional[dict]:
        """
        Return the most recent verdict for a user (for /corvus explain).

        Returns dict with keys: verdict_level, score, rationale, timestamp
        or None if the user has no history.
        """
        cursor = self._conn.execute(
            """
            SELECT verdict_level, timestamp
            FROM messages
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "verdict_level": row[0],
            "timestamp": row[1],
        }

    def get_audit_chain(self) -> AuditChain:
        """Return the AuditChain instance (for /corvus audit)."""
        return self._audit

    def append_audit(
        self,
        operation: str,
        user_id: str,
        channel_id: str,
        payload_summary: str,
    ) -> str:
        """
        Append a standalone entry to the audit chain and commit it.

        AuditChain.append() deliberately does not commit — store_message and the
        consolidator own their transactions. This helper is for events that are
        not part of a store transaction (e.g. sealing a CRITICAL evidence bundle)
        and need the entry durably recorded on its own.
        """
        entry_hash = self._audit.append(
            operation=operation,
            user_id=user_id,
            channel_id=channel_id,
            payload_summary=payload_summary,
        )
        self._conn.commit()
        return entry_hash

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internal: Welford online algorithm
    # ------------------------------------------------------------------

    def _welford_update(
        self,
        user_id: str,
        nv_ratio: float,
        cli_stress: float,
        active_signals: int,
    ) -> None:
        """
        Update the user baseline using Welford's online algorithm.

        Welford (single pass, numerically stable):
            n_new   = n + 1
            delta   = x - mean_old
            mean_new = mean_old + delta / n_new
            delta2  = x - mean_new
            M2_new  = M2_old + delta * delta2
            std_new = sqrt(M2_new / n_new)

        We store mean and std directly; M2 is reconstructed as std² * n.
        """
        import math

        cursor = self._conn.execute(
            """
            SELECT nv_ratio_mean, nv_ratio_std, cli_stress_mean,
                   avg_signals_per_message, signals_sum, message_count
            FROM baselines
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()

        if row is None:
            # First message for this user — seed baseline
            self._conn.execute(
                """
                INSERT INTO baselines
                    (user_id, nv_ratio_mean, nv_ratio_std, cli_stress_mean,
                     avg_signals_per_message, signals_sum, message_count, last_updated)
                VALUES (?, ?, 0.5, ?, ?, ?, 1, datetime('now'))
                """,
                (user_id, nv_ratio, cli_stress, float(active_signals), int(active_signals)),
            )
            return

        (
            old_nv_mean, old_nv_std, old_cli_mean,
            old_signals_mean, old_signals_sum, old_n,
        ) = row
        n_new = old_n + 1
        signals_sum_new = int(old_signals_sum) + int(active_signals)

        # Welford for nv_ratio
        nv_M2_old = (old_nv_std ** 2) * old_n
        nv_delta = nv_ratio - old_nv_mean
        nv_mean_new = old_nv_mean + nv_delta / n_new
        nv_delta2 = nv_ratio - nv_mean_new
        nv_M2_new = nv_M2_old + nv_delta * nv_delta2
        nv_std_new = math.sqrt(max(nv_M2_new / n_new, 0.0))

        # Welford for cli_stress (simple running mean — no std needed for now)
        cli_mean_new = old_cli_mean + (cli_stress - old_cli_mean) / n_new

        # Welford for avg_signals_per_message (running mean)
        signals_mean_new = old_signals_mean + (active_signals - old_signals_mean) / n_new

        self._conn.execute(
            """
            UPDATE baselines
            SET nv_ratio_mean           = ?,
                nv_ratio_std            = ?,
                cli_stress_mean         = ?,
                avg_signals_per_message = ?,
                signals_sum             = ?,
                message_count           = ?,
                last_updated            = datetime('now')
            WHERE user_id = ?
            """,
            (
                nv_mean_new,
                nv_std_new,
                cli_mean_new,
                signals_mean_new,
                signals_sum_new,
                n_new,
                user_id,
            ),
        )
