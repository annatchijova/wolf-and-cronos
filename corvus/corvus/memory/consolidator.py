"""
CORVUS Sleep Consolidator
Nightly batch process that resets user baselines from stored messages,
prunes old data, and updates the audit chain.

Analogous to sleep memory consolidation in neuroscience —
the system reviews all recent evidence and forms a clean, stable baseline.
"""

import math
import logging
from datetime import datetime, timezone, timedelta

from corvus.memory.engine import MemoryEngine

logger = logging.getLogger(__name__)

_CONSOLIDATION_THRESHOLD = 50    # Minimum messages before recomputing baseline
_PRUNE_DAYS = 30                 # Remove messages older than this


class SleepConsolidator:
    """
    Nightly baseline recomputation and data pruning.
    Runs atomically under BEGIN IMMEDIATE transaction to prevent
    concurrent reads seeing a partially-updated baseline.
    """

    def __init__(self, engine: MemoryEngine) -> None:
        self._engine = engine

    def consolidate(self) -> dict:
        """
        Run the full consolidation process.

        Steps:
        1. Identify users with > 50 messages (consolidation threshold).
        2. Recompute baselines from stored messages using batch Welford.
        3. Prune messages older than 30 days.
        4. Record to audit chain.

        Returns
        -------
        dict
            {"users_updated": N, "messages_pruned": N, "errors": []}
        """
        conn = self._engine._conn
        errors: list[str] = []
        users_updated = 0
        messages_pruned = 0

        # -------------------------------------------------------------------
        # Step 1: Find users with enough messages
        # -------------------------------------------------------------------
        cursor = conn.execute(
            """
            SELECT user_id, COUNT(*) as msg_count
            FROM messages
            GROUP BY user_id
            HAVING msg_count > ?
            """,
            (_CONSOLIDATION_THRESHOLD,),
        )
        candidate_users = cursor.fetchall()

        for user_row in candidate_users:
            user_id = user_row[0]
            try:
                self._recompute_baseline(conn, user_id)
                users_updated += 1
            except Exception as exc:
                err_msg = f"Baseline recompute failed for {user_id}: {exc}"
                logger.error(err_msg)
                errors.append(err_msg)

        # -------------------------------------------------------------------
        # Step 2: Prune old messages
        # -------------------------------------------------------------------
        # P0 fix: only prune messages for users who have enough recent messages
        # to maintain a valid baseline. Users with < _CONSOLIDATION_THRESHOLD
        # total messages keep their history intact — it's their only baseline data.
        cutoff = (
            datetime.now(tz=timezone.utc) - timedelta(days=_PRUNE_DAYS)
        ).isoformat()
        try:
            cursor = conn.execute(
                """
                DELETE FROM messages
                WHERE timestamp < ?
                  AND user_id IN (
                      SELECT user_id FROM baselines
                      WHERE message_count > ?
                  )
                """,
                (cutoff, _CONSOLIDATION_THRESHOLD),
            )
            messages_pruned = cursor.rowcount
            conn.commit()
        except Exception as exc:
            err_msg = f"Message pruning failed: {exc}"
            logger.error(err_msg)
            errors.append(err_msg)

        # -------------------------------------------------------------------
        # Step 3: Audit chain
        # -------------------------------------------------------------------
        try:
            audit = self._engine.get_audit_chain()
            audit.append(
                operation="consolidate",
                user_id="SYSTEM",
                channel_id="SYSTEM",
                payload_summary=(
                    f"Consolidation complete: users_updated={users_updated}, "
                    f"messages_pruned={messages_pruned}, errors={len(errors)}"
                ),
            )
            # audit.append() no longer auto-commits; we own the transaction here.
            conn.commit()
        except Exception as exc:
            logger.error(f"Audit chain write failed during consolidation: {exc}")

        return {
            "users_updated": users_updated,
            "messages_pruned": messages_pruned,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Private: batch Welford recompute
    # ------------------------------------------------------------------

    def _recompute_baseline(self, conn, user_id: str) -> None:
        """
        Recompute a clean baseline for a single user from all stored messages.
        Uses batch Welford algorithm for numerical stability.
        Executes atomically under BEGIN IMMEDIATE.
        """
        # Read all messages for this user
        cursor = conn.execute(
            """
            SELECT nv_ratio, cli_stress, active_signals
            FROM messages
            WHERE user_id = ?
            ORDER BY id ASC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return

        # Batch Welford — reset from scratch
        n = 0
        nv_mean = 0.0
        nv_M2 = 0.0
        cli_mean = 0.0
        signals_mean = 0.0
        signals_sum = 0   # exact integer accumulator (baseline delta path)

        for row in rows:
            nv_ratio = float(row[0])

            # Parse cli_stress stored as "numerator/denominator"
            cli_str: str = row[1]
            try:
                num_s, den_s = cli_str.split("/")
                cli_stress = float(num_s) / max(float(den_s), 1.0)
            except (ValueError, ZeroDivisionError):
                cli_stress = 0.0

            active_signals = int(row[2])
            signals_sum += active_signals

            n += 1
            # Welford for nv_ratio
            nv_delta = nv_ratio - nv_mean
            nv_mean += nv_delta / n
            nv_delta2 = nv_ratio - nv_mean
            nv_M2 += nv_delta * nv_delta2

            # Running mean for cli_stress
            cli_mean += (cli_stress - cli_mean) / n

            # Running mean for signals
            signals_mean += (active_signals - signals_mean) / n

        nv_std = math.sqrt(max(nv_M2 / n, 0.0)) if n > 0 else 0.5

        # Atomic update under BEGIN IMMEDIATE
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO baselines
                    (user_id, nv_ratio_mean, nv_ratio_std, cli_stress_mean,
                     avg_signals_per_message, signals_sum, message_count, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    nv_ratio_mean           = excluded.nv_ratio_mean,
                    nv_ratio_std            = excluded.nv_ratio_std,
                    cli_stress_mean         = excluded.cli_stress_mean,
                    avg_signals_per_message = excluded.avg_signals_per_message,
                    signals_sum             = excluded.signals_sum,
                    message_count           = excluded.message_count,
                    last_updated            = excluded.last_updated
                """,
                (user_id, nv_mean, nv_std, cli_mean, signals_mean, signals_sum, n),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
