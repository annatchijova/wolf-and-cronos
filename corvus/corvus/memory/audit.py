"""
CORVUS Audit Chain
Tamper-evident hash chain for all CORVUS operations.
Each entry chains its SHA-256 hash to the previous entry,
creating a verifiable audit log.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class AuditEntry:
    timestamp: str
    operation: str       # "store" | "recall" | "consolidate" | "verdict"
    user_id: str
    channel_id: str
    payload_summary: str
    prev_hash: str
    entry_hash: str      # SHA-256(canonical_json(this entry except entry_hash) + prev_hash)


def _compute_entry_hash(
    timestamp: str,
    operation: str,
    user_id: str,
    channel_id: str,
    payload_summary: str,
    prev_hash: str,
) -> str:
    """
    Compute SHA-256 hash for an audit entry.
    Canonical: sorted JSON of all fields except entry_hash, concatenated with prev_hash.
    """
    canonical: dict[str, Any] = {
        "timestamp": timestamp,
        "operation": operation,
        "user_id": user_id,
        "channel_id": channel_id,
        "payload_summary": payload_summary,
        "prev_hash": prev_hash,
    }
    canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    raw = (canonical_json + prev_hash).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class AuditChain:
    """
    Tamper-evident append-only audit chain backed by SQLite.
    Entries form a hash chain: each entry's hash depends on the previous entry's hash.
    """

    _GENESIS_HASH = "0" * 64  # Initial previous hash for the first entry

    def __init__(self, db_conn) -> None:
        """
        Parameters
        ----------
        db_conn : sqlite3.Connection
            Open SQLite connection (WAL mode recommended).
        """
        self._conn = db_conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create the audit_chain table if it does not exist."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_chain (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TEXT    NOT NULL,
                operation       TEXT    NOT NULL,
                user_id         TEXT    NOT NULL,
                channel_id      TEXT    NOT NULL,
                payload_summary TEXT    NOT NULL,
                prev_hash       TEXT    NOT NULL,
                entry_hash      TEXT    NOT NULL UNIQUE
            )
            """
        )
        self._conn.commit()

    def _get_last_hash(self) -> str:
        """Return the hash of the most recent audit entry, or genesis hash."""
        cursor = self._conn.execute(
            "SELECT entry_hash FROM audit_chain ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else self._GENESIS_HASH

    def append(
        self,
        operation: str,
        user_id: str,
        channel_id: str,
        payload_summary: str,
    ) -> str:
        """
        Append a new entry to the audit chain.

        Parameters
        ----------
        operation : str
            One of: "store", "recall", "consolidate", "verdict".
        user_id : str
        channel_id : str
        payload_summary : str
            Human-readable summary of what happened.

        Returns
        -------
        str
            The SHA-256 hash of the newly created entry.
        """
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        prev_hash = self._get_last_hash()
        entry_hash = _compute_entry_hash(
            timestamp, operation, user_id, channel_id, payload_summary, prev_hash
        )
        self._conn.execute(
            """
            INSERT INTO audit_chain
                (timestamp, operation, user_id, channel_id, payload_summary, prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, operation, user_id, channel_id, payload_summary, prev_hash, entry_hash),
        )
        # NOTE: intentionally no self._conn.commit() here.
        # Callers (engine.py store_message, consolidator.py) own the transaction
        # and issue the final commit themselves. This ensures message + baseline +
        # audit land atomically in a single commit, or not at all.
        return entry_hash

    def verify(self) -> tuple[bool, list[str]]:
        """
        Verify the integrity of the entire audit chain.

        Recomputes all hashes from the stored data and checks:
        1. Each entry's hash matches its stored entry_hash.
        2. Each entry's prev_hash matches the previous entry's entry_hash.

        Returns
        -------
        tuple[bool, list[str]]
            (True, []) if chain is intact.
            (False, [error, ...]) if tampering or corruption detected.
        """
        cursor = self._conn.execute(
            """
            SELECT id, timestamp, operation, user_id, channel_id,
                   payload_summary, prev_hash, entry_hash
            FROM audit_chain
            ORDER BY id ASC
            """
        )
        rows = cursor.fetchall()
        errors: list[str] = []
        expected_prev = self._GENESIS_HASH

        for row in rows:
            (
                entry_id, timestamp, operation, user_id, channel_id,
                payload_summary, prev_hash, stored_hash,
            ) = row

            # Check prev_hash linkage
            if prev_hash != expected_prev:
                errors.append(
                    f"Entry {entry_id}: prev_hash mismatch "
                    f"(expected {expected_prev[:16]}…, got {prev_hash[:16]}…)"
                )

            # Recompute entry hash
            computed_hash = _compute_entry_hash(
                timestamp, operation, user_id, channel_id, payload_summary, prev_hash
            )
            if computed_hash != stored_hash:
                errors.append(
                    f"Entry {entry_id}: hash mismatch — entry may have been tampered with. "
                    f"Stored: {stored_hash[:16]}…, Computed: {computed_hash[:16]}…"
                )

            expected_prev = stored_hash

        ok = len(errors) == 0
        return ok, errors

    def export(self) -> list[dict]:
        """
        Export all audit chain entries as a list of dicts.
        Used for CISO export and /corvus audit command.

        Returns
        -------
        list[dict]
            All entries in chronological order.
        """
        cursor = self._conn.execute(
            """
            SELECT id, timestamp, operation, user_id, channel_id,
                   payload_summary, prev_hash, entry_hash
            FROM audit_chain
            ORDER BY id ASC
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "operation": row[2],
                "user_id": row[3],
                "channel_id": row[4],
                "payload_summary": row[5],
                "prev_hash": row[6],
                "entry_hash": row[7],
            }
            for row in rows
        ]
