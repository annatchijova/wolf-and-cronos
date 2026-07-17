"""
qwen-track3/bridge.py
======================
CORVUS-CRONOS Integration Bridge.

Maps the CORVUS multi-agent analysis pipeline onto CRONOS hypothesis
traces so that each agent's "vote" in the negotiation is permanently
auditable. The bridge does NOT alter CORVUS or CRONOS internals — it is
a read-only adapter that translates signal outputs into CRONOS events.

Architecture
------------
For a single text artifact, the bridge:

  1. Resolves the per-user behavioral baseline from CORVUS MemoryEngine
     (Welford online algorithm; falls back to empty dict if memory is
     disabled or the user has no history).
  2. Runs CORVUS L1-L5 in parallel (deterministic detectors).
  3. Runs CORVUS L6 (Peirce abductive synthesis over L1-L5 signals).
  4. Applies the CORVUS corroboration gate (>= 2 active signals for
     any verdict above SILENT).
  5. Runs VerdictEngine — produces rationale, recommendation,
     signals_fired, and a per-verdict audit hash.
  6. For each L1-L6 agent, opens one CRONOS trace that records:
       - call_tool() with the detector output summary (L1-L5)
       - record_recall() for each L1-L5 result (L6 synthesis)
       - Hypotheses, evidence, and the agent's own vote
     CRONOS computes TraceQuality/diversity/contradictions on __exit__.
  7. Opens a GATE trace that records the consensus decision.
  8. Verifies the full CRONOS chain integrity after all writes.
  9. Persists the message + baseline update to CORVUS MemoryEngine
     (if memory_db_path is configured).

No floats enter the CRONOS confidence fields — all values are Fraction.

Usage
-----
    from bridge import CorvosCronosBridge

    # With persistent per-user baseline:
    bridge = CorvosCronosBridge(
        db_path="negotiation.db",
        memory_db_path="corvus_memory.db",
    )
    result = bridge.analyze(
        "Free trial ending — act now!",
        artifact_id="CASE-001",
        user_id="alice",
    )
    print(result.verdict_level, result.chain_valid)
    print(result.verdict_rationale)
    bridge.close()

    # Without memory (stateless):
    bridge = CorvosCronosBridge(db_path="negotiation.db")
    result = bridge.analyze("Hi, can you review the PR?")
    bridge.close()
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from typing import Optional

log = logging.getLogger("qwen_track3.bridge")

# RT-08: cap the analyzed text itself, not just artifact_id/user_id (RT-04).
# `text` is the highest-attacker-control input and the one actually run
# through all six detector algorithms in parallel; unlike artifact_id it
# had no bound at all. 50k chars is generous for the single-message /
# short-conversation use case this system targets while bounding worst-case
# detector CPU/memory and the JSON payload hashed in Phase 5.
MAX_TEXT_CHARS = 50_000

# RT-10: cross-message accumulation window.
#
# Confirmed by induction (red-team audit, corroboration-gate probe): a
# "drip-feed" attacker who spreads one manipulation tactic per message —
# instead of stacking them in a single message, the way the canned Wolf
# demo does from message 3 onward — never fires >= CORROBORATION_THRESHOLD
# agents on any single message. A 10-message escalating conversation ran
# through this exact bridge stayed SILENT on all 10 messages; the system's
# own baseline_delta multiplier cannot rescue it, because VerdictEngine's
# gate (corvus/verdict/engine.py Step 1) forces SILENT before baseline_delta
# is ever consulted. That gate is CORVUS's own code and is intentionally
# left unmodified (see module docstring: "zero modification to internals").
#
# This window is the bridge-owned fix: instead of requiring >= 2 independent
# frameworks to fire on ONE message, it also accepts >= 2 independent
# frameworks firing across the last DRIP_WINDOW_SIZE messages from the same
# user_id. Same corroboration philosophy (no single framework, ever, acting
# alone), just widened from one message to a short recent window — so a
# patient attacker gains nothing by pacing tactics one per message.
DRIP_WINDOW_SIZE = 6

# ---------------------------------------------------------------------------
# Resolve CORVUS and CRONOS on sys.path (no install required for the demo)
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.abspath(__file__))
# corvus/ and cronos/ live two levels up: project_root/../corvus etc.
for _lib in ("corvus", "cronos"):
    _p = os.path.abspath(os.path.join(_ROOT, "..", "..", _lib))
    if _p not in sys.path:
        sys.path.insert(0, _p)

from corvus.analysis.l1_grice import GriceDetector
from corvus.analysis.l2_carnegie_cialdini import InfluenceDetector
from corvus.analysis.l3_aristotle import AristotleDetector
from corvus.analysis.l4_berne import BerneDetector
from corvus.analysis.l5_linguistics import LinguisticsDetector
from corvus.analysis.l6_peirce import PeirceDetector
from corvus.config import Config
from corvus.memory.engine import MemoryEngine
from corvus.models import (
    AnalysisResult, PeirceSignal, Verdict, VerdictLevel,
)
from corvus.verdict.engine import VerdictEngine

from cronos import CronosTracer, TraceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_fraction(value) -> Fraction:
    """Safely coerce a Fraction, float, or int severity to Fraction.

    Falls back to Fraction(0) on anything malformed (NaN, Infinity,
    non-numeric strings, None) — logged at WARNING, not silent, since a
    swallowed-to-zero severity is indistinguishable from a genuine zero
    reading (the same class of defect fixed as RT-01 for detector crashes).
    """
    if isinstance(value, Fraction):
        return value
    try:
        return Fraction(str(round(float(value), 9)))
    except Exception as exc:
        log.warning(
            "_to_fraction: could not coerce %r to Fraction (%s) — defaulting to 0",
            value, exc,
        )
        return Fraction(0)


def _extract_evidence(signal) -> list[str]:
    """Extract the evidence list from any CORVUS signal (safe, capped at 5)."""
    if signal is None:
        return []
    ev = getattr(signal, "evidence", None)
    if isinstance(ev, list):
        return [str(x) for x in ev[:5]]
    return []


def _sig_to_dict(signal) -> Optional[dict]:
    """Serialize a CORVUS signal dataclass to a JSON-safe dict (for audit hash)."""
    if signal is None:
        return None
    out = {}
    for k, v in signal.__dict__.items():
        if isinstance(v, Fraction):
            out[k] = f"{v.numerator}/{v.denominator}"
        elif hasattr(v, "value"):     # Enum
            out[k] = v.value
        elif isinstance(v, list):
            out[k] = [str(x) for x in v]
        else:
            out[k] = v
    return out


def _sig_summary(agent_id: str, signal) -> str:
    """
    One-line summary of a CORVUS signal for CRONOS call_tool() recording.
    Keeps the tool result brief; full detail lives in the evidence steps.
    """
    if signal is None:
        return f"{agent_id}: no signal detected"
    severity = getattr(signal, "severity", None)
    sev_str = f"severity={float(severity):.3f}" if severity is not None else ""
    ev = _extract_evidence(signal)
    ev_str = f" | evidence[0]: {ev[0][:80]}" if ev else ""
    return f"{agent_id}: signal detected {sev_str}{ev_str}"


def _trace_meta_from(tracer: CronosTracer) -> dict:
    """
    Extract post-close quality metadata from a CronosTracer whose __exit__
    has already run.  The Trace object is still in memory after context exit.
    """
    t = tracer.trace
    return {
        "quality":              t.quality.value if t.quality else "EMPTY",
        "diversity":            (
            f"{t.diversity.numerator}/{t.diversity.denominator}"
            if t.diversity is not None else "0/3"
        ),
        "contradictions":       list(t.contradictions or []),
        "confidence_warnings":  list(t.confidence_warnings or []),
    }


# ---------------------------------------------------------------------------
# TraceMetadata per agent
# ---------------------------------------------------------------------------

@dataclass
class AgentTraceMeta:
    """Quality metadata for one agent's CRONOS trace."""
    quality:             str        # TraceQuality.value: FULL/PARTIAL/MINIMAL/EMPTY
    diversity:           str        # "n/3"
    contradictions:      list[str]  # Type A/B contradiction descriptions
    confidence_warnings: list[str]  # ceiling/floor clamping messages


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class NegotiationResult:
    """Full output of one bridge analysis run."""
    # ── Core verdict ────────────────────────────────────────────────────
    verdict_level:          VerdictLevel
    score:                  Fraction
    # ── Agent classification ─────────────────────────────────────────────
    active_agents:          list[str]           # agents that fired (signal not None)
    silent_agents:          list[str]           # agents that found nothing
    crashed_agents:         list[str]           # agents that raised an exception (RT-01)
    # ── Audit hashes ─────────────────────────────────────────────────────
    audit_hash:             str                 # SHA-256 over all agent signals
    verdict_audit_hash:     str                 # SHA-256 from VerdictEngine
    # ── CRONOS traceability ──────────────────────────────────────────────
    trace_ids:              dict[str, str]       # agent_id → CRONOS trace_id
    trace_meta:             dict[str, AgentTraceMeta]  # agent_id → quality metadata
    chain_valid:            bool                 # CRONOS chain integrity after all writes
    chain_errors:           list[str]            # chain verification errors (empty = clean)
    # ── Narrative / reasoning ────────────────────────────────────────────
    rationale:              str                  # Peirce thirdness or gate summary
    verdict_rationale:      str                  # VerdictEngine detailed rationale
    verdict_recommendation: str                  # actionable recommendation
    signals_fired:          list[str]            # layer names that contributed to score
    devils_advocate:        str                  # strongest counter-hypothesis (L6 trace)
    # ── Diagnostics ──────────────────────────────────────────────────────
    audit_warnings:         list[str]            # non-fatal CRONOS write failures
    # ── Raw output ───────────────────────────────────────────────────────
    analysis_result:        AnalysisResult = field(repr=False, default=None)


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

class CorvosCronosBridge:
    """
    Runs CORVUS L1-L6 analysis and records each agent's vote as a
    CRONOS trace, making the multi-agent negotiation auditable and
    tamper-evident via the CRONOS SHA-256 hash chain.

    Parameters
    ----------
    db_path : str
        Path to the CRONOS SQLite database (trace chain).
    memory_db_path : str | None
        Path to the CORVUS MemoryEngine SQLite database (per-user baselines).
        Pass None (default) to run stateless — no baseline persistence.
    """

    def __init__(
        self,
        db_path: str = "negotiation.db",
        memory_db_path: Optional[str] = None,
    ) -> None:
        self._store  = TraceStore(db_path)
        self._config = Config()
        self._engine = VerdictEngine(self._config)

        # RT-10: bridge-owned table for the drip-feed accumulation window.
        # Lives in the same SQLite file as the CRONOS chain but is a table
        # the bridge creates and owns — CRONOS's own schema/code is untouched.
        self._store._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bridge_drip_window (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL,
                artifact_id TEXT    NOT NULL,
                frameworks  TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            )
            """
        )
        self._store._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bridge_drip_window_user "
            "ON bridge_drip_window (user_id, id)"
        )
        self._store._conn.commit()

        self._l1 = GriceDetector()
        self._l2 = InfluenceDetector()
        self._l3 = AristotleDetector()
        self._l4 = BerneDetector()
        self._l5 = LinguisticsDetector()
        self._l6 = PeirceDetector()

        # Concurrency guard — CRONOS+MemoryEngine access is not re-entrant.
        # A single bridge instance shared across threads must serialize any
        # touch of those two stores: Phase 0 (MemoryEngine baseline read) and
        # Phases 7-9 (CRONOS trace writes, chain verify, MemoryEngine store).
        # Phases 1-6 (the CORVUS detectors themselves, pure computation over
        # the already-resolved baseline) run without the lock so parallel
        # calls still benefit from their internal thread pool.
        self._write_lock = threading.Lock()

        # CORVUS MemoryEngine — optional, disabled when memory_db_path is None
        self._memory: Optional[MemoryEngine] = None
        if memory_db_path is not None:
            # MemoryEngine.initialize() calls os.makedirs(dirname(path)); ensure
            # an absolute path so dirname is never the empty string.
            abs_mem = os.path.abspath(memory_db_path)
            # If the parent directory does not exist yet, create it now so that
            # initialize() does not fail on an empty dirname.
            mem_dir = os.path.dirname(abs_mem)
            if mem_dir:
                os.makedirs(mem_dir, exist_ok=True)
            self._memory = MemoryEngine(abs_mem)
            try:
                self._memory.initialize()
                log.info("CORVUS MemoryEngine initialized: %s", abs_mem)
            except Exception as exc:
                log.error(
                    "MemoryEngine init failed (%s) — running stateless: %s",
                    abs_mem, exc,
                )
                self._memory = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        text: str,
        artifact_id: str = "artifact",
        user_id: str = "anonymous",
        user_baseline: Optional[dict] = None,
        conversation_history: Optional[list[str]] = None,
    ) -> NegotiationResult:
        """
        Run the full negotiation: CORVUS analysis → CRONOS trace per agent.

        Parameters
        ----------
        text                 : raw text to analyze
        artifact_id          : identifier for the audit trail
        user_id              : identifier for per-user baseline tracking
        user_baseline        : explicit baseline override (takes priority over
                               MemoryEngine; pass None to use stored baseline)
        conversation_history : prior messages for L2/L4 context (empty = standalone)
        """
        # RT-04: cap artifact_id to prevent unbounded CRONOS objective strings
        artifact_id = str(artifact_id)[:256]
        user_id     = str(user_id)[:128]
        # RT-08: cap text itself — see MAX_TEXT_CHARS for rationale.
        text        = str(text)[:MAX_TEXT_CHARS]

        ts = datetime.now(tz=timezone.utc).isoformat()
        history = conversation_history or []

        # Phase 0: resolve behavioral baseline
        # Explicit override > MemoryEngine > empty dict
        if user_baseline is not None:
            baseline = dict(user_baseline)
        elif self._memory is not None:
            # Shares the write lock with Phases 7-9: this is a MemoryEngine
            # read, not a CORVUS detector, and MemoryEngine is not guaranteed
            # safe against a concurrent store_message() from another thread.
            with self._write_lock:
                baseline = self._memory.get_user_baseline(user_id)
        else:
            baseline = {}

        # Phase 1: L1-L5 in parallel
        signals, crashed = self._run_parallel(text, baseline, history)

        # Phase 2: L6 Peirce synthesis over L1-L5 results
        peirce_signal: Optional[PeirceSignal] = self._l6.analyze(
            text          = text,
            signals       = [s for s in signals.values() if s is not None],
            user_baseline = baseline,
        )
        signals["L6_PEIRCE"] = peirce_signal

        # Phase 3: corroboration count (L1-L5 only; L6 is synthesis)
        active_count = sum(
            1 for k, v in signals.items()
            if k != "L6_PEIRCE" and v is not None
        )

        # Phase 4: baseline delta — normalised deviation from user history
        # MemoryEngine stores avg_signals_per_message; explicit baselines may
        # use avg_active_signals (legacy key).  Accept either.
        # A stored average of exactly 0 (all-silent history) is a legitimate
        # baseline, distinct from "no baseline" — so test for key presence with
        # `is None`, never truthiness (an `or` chain would coerce 0 to missing,
        # the RT-07 defect class).  message_count == 0 means no real history:
        # keep delta at 0 rather than treating the storage default as a baseline.
        baseline_delta = Fraction(0)
        avg_raw = baseline.get("avg_signals_per_message")
        if avg_raw is None:
            avg_raw = baseline.get("avg_active_signals")
        if avg_raw is not None and baseline.get("message_count", 1) > 0:
            avg = _to_fraction(avg_raw)
            baseline_delta = Fraction(active_count, 5) - avg

        # Phase 5: SHA-256 audit hash over all agent signals
        audit_hash = hashlib.sha256(
            json.dumps(
                {k: _sig_to_dict(v) for k, v in signals.items()},
                sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            ).encode()
        ).hexdigest()

        # Phase 6: build AnalysisResult and run VerdictEngine
        analysis_result = AnalysisResult(
            message_id     = artifact_id,
            user_id        = user_id,
            channel_id     = artifact_id,
            text           = text,
            timestamp      = ts,
            grice          = signals.get("L1_GRICE"),
            influence      = signals.get("L2_CARNEGIE"),
            aristotle      = signals.get("L3_ARISTOTLE"),
            berne          = signals.get("L4_BERNE"),
            linguistic     = signals.get("L5_LINGUISTIC"),
            peirce         = peirce_signal,
            active_signals = active_count,
            baseline_delta = baseline_delta,
            audit_hash     = audit_hash,
        )
        verdict = self._engine.compute(analysis_result)

        # RT-10: drip-feed accumulation check. Only relevant when CORVUS's own
        # gate forced SILENT on this message but the message was not fully
        # blank (active_count > 0) — a real, if lone, signal fired.
        accumulation_trace_id: Optional[str] = None
        accumulation_meta: Optional[AgentTraceMeta] = None
        if verdict.level == VerdictLevel.SILENT and 0 < active_count < self._config.CORROBORATION_THRESHOLD:
            with self._write_lock:
                escalated, accumulation_trace_id, accumulation_meta = (
                    self._check_drip_accumulation(
                        user_id, artifact_id, signals, active_count,
                    )
                )
            if escalated is not None:
                verdict = escalated

        # Phases 7-9: serialized write block.
        # CRONOS TraceStore and MemoryEngine are not safe for concurrent writes
        # from multiple threads sharing the same bridge instance.  The lock
        # serializes all writes while still allowing Phases 1-6 (read-only CORVUS
        # detectors and VerdictEngine) to run concurrently across callers.
        with self._write_lock:
            # Phase 7: CRONOS tracing
            # Rec-3: CRONOS write failures are non-fatal — surfaced in audit_warnings.
            trace_ids, trace_meta, audit_warnings = self._trace_agents(
                signals, artifact_id, user_id,
            )
            gate_tid, gate_meta, gate_warn = self._trace_gate(
                active_count, signals, artifact_id, verdict,
            )
            trace_ids["GATE"]   = gate_tid
            trace_meta["GATE"]  = gate_meta
            audit_warnings.extend(gate_warn)

            if accumulation_trace_id:
                trace_ids["ACCUMULATION"]  = accumulation_trace_id
                trace_meta["ACCUMULATION"] = accumulation_meta

            # Phase 8: verify CRONOS chain integrity
            chain_valid, chain_errors = self._store.chain.verify()
            if not chain_valid:
                log.warning(
                    "CRONOS chain integrity check failed after analysis %s: %s",
                    artifact_id, chain_errors,
                )

            # Phase 9: persist to CORVUS MemoryEngine (non-fatal if unavailable)
            if self._memory is not None:
                try:
                    self._memory.store_message(analysis_result, verdict)
                except Exception as exc:
                    msg = f"MEMORY_STORE_FAILED:{type(exc).__name__}:{exc}"
                    audit_warnings.append(msg)
                    log.error("MemoryEngine store failed: %s", exc)

        # Classify agents.  Iterate in the fixed L1→L5 framework order, not
        # signals.items() — that dict is filled in thread-completion order, so
        # the lists (and every prompt/trace string built from them) would vary
        # run-to-run for identical input.
        crashed_set   = set(crashed)
        l1_l5_order   = [k for k in self._AGENT_FRAMEWORK if k != "L6_PEIRCE"]
        active_agents = [
            k for k in l1_l5_order if signals.get(k) is not None
        ]
        silent_agents = [
            k for k in l1_l5_order
            if signals.get(k) is None and k not in crashed_set
        ]
        if peirce_signal is not None:
            active_agents.append("L6_PEIRCE")
        else:
            silent_agents.append("L6_PEIRCE")

        # Peirce thirdness as primary rationale; fall back to gate summary.
        # RT-10: an accumulation escalation overrides both — this message
        # alone did not trigger Peirce synthesis or the single-message gate.
        if accumulation_trace_id:
            rationale = verdict.rationale
        else:
            rationale = (
                peirce_signal.thirdness
                if peirce_signal is not None
                else f"Gate: {active_count}/5 agents active — verdict {verdict.level.value}"
            )

        # Build the devil's advocate prose from the L6 Peirce signal and the
        # per-agent signal map.  See _build_devils_advocate() for the design note.
        devil_prose = self._build_devils_advocate(peirce_signal, signals)

        return NegotiationResult(
            verdict_level          = verdict.level,
            score                  = verdict.score,
            active_agents          = active_agents,
            silent_agents          = silent_agents,
            crashed_agents         = crashed,
            audit_hash             = audit_hash,
            verdict_audit_hash     = verdict.audit_hash,
            trace_ids              = trace_ids,
            trace_meta             = trace_meta,
            chain_valid            = chain_valid,
            chain_errors           = chain_errors,
            rationale              = rationale,
            verdict_rationale      = verdict.rationale,
            verdict_recommendation = verdict.recommendation,
            signals_fired          = verdict.signals_fired,
            devils_advocate        = devil_prose,
            audit_warnings         = audit_warnings,
            analysis_result        = analysis_result,
        )

    def verify_chain(self) -> tuple[bool, list[str]]:
        """
        Verify the CRONOS hash chain integrity on demand.
        Returns (True, []) if intact; (False, [error, ...]) otherwise.
        """
        return self._store.chain.verify()

    def export_chain(self) -> list[dict]:
        """Export all CRONOS chain entries in chronological order."""
        return self._store.chain.export()

    def get_user_baseline(self, user_id: str) -> Optional[dict]:
        """
        Return the stored behavioral baseline for a user.
        Returns None if MemoryEngine is not configured.
        """
        if self._memory is None:
            return None
        return self._memory.get_user_baseline(user_id)

    def get_user_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """
        Return the last N stored messages for a user.
        Returns [] if MemoryEngine is not configured.
        """
        if self._memory is None:
            return []
        return self._memory.get_user_history(user_id, limit=limit)

    def get_recent_traces(
        self,
        agent_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return lightweight CRONOS trace headers (no steps) for listing."""
        return self._store.get_recent_traces(agent_id=agent_id, limit=limit)

    def close(self) -> None:
        """Close all database connections."""
        self._store._conn.close()
        if self._memory is not None:
            self._memory.close()

    # ------------------------------------------------------------------
    # Internal: parallel L1-L5 execution
    # ------------------------------------------------------------------

    def _run_parallel(
        self, text: str, baseline: dict, history: list[str]
    ) -> tuple[dict[str, object], list[str]]:
        """
        Run L1-L5 detectors in parallel.

        Returns (signals, crashed) where:
          signals  : {agent_id: signal | None}
          crashed  : list of agent_ids that raised an exception

        RT-01 fix: exceptions are logged and tracked separately from genuine
        SILENT results so a crash cannot silently suppress a detection.
        """
        results: dict[str, object] = {}
        crashed: list[str] = []

        def _safe(name, fn):
            try:
                return name, fn(), None
            except Exception as exc:
                log.warning(
                    "RT-01: detector %s raised %s: %s — treating as SILENT but marking crashed",
                    name, type(exc).__name__, exc,
                )
                return name, None, exc

        tasks = {
            "L1_GRICE":      lambda: self._l1.analyze(text, baseline),
            "L2_CARNEGIE":   lambda: self._l2.analyze(text, history, baseline),
            "L3_ARISTOTLE":  lambda: self._l3.analyze(text),
            "L4_BERNE":      lambda: self._l4.analyze(text, history),
            "L5_LINGUISTIC": lambda: self._l5.analyze(text, baseline),
        }
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {pool.submit(_safe, k, v): k for k, v in tasks.items()}
            for fut in as_completed(futs):
                name, sig, exc = fut.result()
                results[name] = sig
                if exc is not None:
                    crashed.append(name)

        return results, crashed

    # ------------------------------------------------------------------
    # Internal: CRONOS tracing
    # ------------------------------------------------------------------

    _AGENT_FRAMEWORK: dict[str, str] = {
        "L1_GRICE":      "Grice Cooperative Principle",
        "L2_CARNEGIE":   "Carnegie/Cialdini Influence Detection",
        "L3_ARISTOTLE":  "Aristotelian Rhetoric Imbalance",
        "L4_BERNE":      "Berne Transactional Analysis",
        "L5_LINGUISTIC": "Linguistic Complexity & Register",
        "L6_PEIRCE":     "Peirce Abductive Synthesis",
    }

    def _trace_agents(
        self,
        signals: dict[str, object],
        artifact_id: str,
        user_id: str,
    ) -> tuple[dict[str, str], dict[str, AgentTraceMeta], list[str]]:
        """
        Open one CRONOS trace per agent (L1-L6).

        L1-L5: records call_tool() with detector output → PARTIAL quality (B+C groups).
        L6:    records record_recall() for each L1-L5 result → PARTIAL quality (A+C groups).

        Returns (trace_ids, trace_meta, warnings).
        """
        trace_ids:  dict[str, str]           = {}
        trace_meta: dict[str, AgentTraceMeta] = {}
        warnings:   list[str] = []

        l1_to_l5 = [k for k in self._AGENT_FRAMEWORK if k != "L6_PEIRCE"]

        for agent_id in l1_to_l5:
            framework = self._AGENT_FRAMEWORK[agent_id]
            signal    = signals.get(agent_id)
            evidence  = _extract_evidence(signal)
            severity  = _to_fraction(getattr(signal, "severity", Fraction(0)))

            try:
                tracer = CronosTracer(
                    self._store,
                    agent_id   = agent_id,
                    channel_id = artifact_id,
                    user_id    = user_id,
                    objective  = f"[{framework}] Analyze: {artifact_id}",
                )
                with tracer as t:
                    tid = t.trace.trace_id   # UUID4 set in __init__, stable
                    if signal is not None:
                        t.add_hypothesis(
                            "anomaly_detected",
                            f"{agent_id} detected manipulation/anomaly signal",
                        )
                        # call_tool: record the detector output as a tool result.
                        # This adds a TOOL step → raises observational diversity
                        # from MINIMAL (C only) to PARTIAL (B+C).
                        t.call_tool(
                            tool_name      = agent_id,
                            result_summary = _sig_summary(agent_id, signal),
                        )
                        for ev in evidence:
                            t.add_evidence(ev, supports="anomaly_detected")
                        # RT-03: agent records own vote, not the gate verdict.
                        t.decide("SIGNAL_DETECTED", confidence=severity or Fraction(1, 2))
                    else:
                        t.add_hypothesis(
                            "no_signal",
                            f"{agent_id} found no anomaly in this artifact",
                        )
                        t.call_tool(
                            tool_name      = agent_id,
                            result_summary = _sig_summary(agent_id, None),
                        )
                        t.add_evidence(
                            "All pattern thresholds within normal range",
                            supports="no_signal",
                        )
                        t.decide("SILENT", confidence=Fraction(1))

                trace_ids[agent_id]  = tid
                trace_meta[agent_id] = AgentTraceMeta(**_trace_meta_from(tracer))

            except Exception as exc:
                # Rec-3: non-fatal — verdict is already sealed.
                msg = f"CRONOS_WRITE_FAILED:{agent_id}:{type(exc).__name__}:{exc}"
                warnings.append(msg)
                log.error("Rec-3: %s", msg)

        # L6 Peirce — uses record_recall() for each L1-L5 result
        peirce_signal = signals.get("L6_PEIRCE")
        peirce_sev    = _to_fraction(getattr(peirce_signal, "severity", Fraction(0)))
        peirce_ev     = _extract_evidence(peirce_signal)

        try:
            tracer = CronosTracer(
                self._store,
                agent_id   = "L6_PEIRCE",
                channel_id = artifact_id,
                user_id    = user_id,
                objective  = f"[{self._AGENT_FRAMEWORK['L6_PEIRCE']}] Synthesize: {artifact_id}",
            )
            with tracer as t:
                tid = t.trace.trace_id
                # record_recall() for each L1-L5 result: adds RECALL steps →
                # observational group A, raising diversity from MINIMAL to PARTIAL.
                for l_id in l1_to_l5:
                    sig = signals.get(l_id)
                    t.record_recall(
                        memory_id = l_id,
                        summary   = _sig_summary(l_id, sig),
                        score     = (
                            _to_fraction(getattr(sig, "severity", Fraction(0)))
                            if sig is not None else Fraction(0)
                        ),
                    )
                if peirce_signal is not None:
                    t.add_hypothesis(
                        "cross_layer_manipulation",
                        "Peirce abductive synthesis: converging signals indicate "
                        "a deliberate manipulation pattern",
                    )
                    for ev in peirce_ev:
                        t.add_evidence(ev, supports="cross_layer_manipulation")
                    t.decide("SIGNAL_DETECTED", confidence=peirce_sev or Fraction(1, 2))
                else:
                    t.add_hypothesis(
                        "no_convergence",
                        "No cross-layer pattern sufficient for abductive conclusion",
                    )
                    t.add_evidence(
                        "L1-L5 signals do not converge on a common manipulation pattern",
                        supports="no_convergence",
                    )
                    t.decide("SILENT", confidence=Fraction(1))

            trace_ids["L6_PEIRCE"]  = tid
            trace_meta["L6_PEIRCE"] = AgentTraceMeta(**_trace_meta_from(tracer))

        except Exception as exc:
            msg = f"CRONOS_WRITE_FAILED:L6_PEIRCE:{type(exc).__name__}:{exc}"
            warnings.append(msg)
            log.error("Rec-3: %s", msg)

        return trace_ids, trace_meta, warnings

    def _trace_gate(
        self,
        active_count: int,
        signals: dict[str, object],
        artifact_id: str,
        verdict,
    ) -> tuple[str, AgentTraceMeta, list[str]]:
        """
        Open a CRONOS trace for the corroboration gate decision.

        Returns (trace_id, meta, warnings).
        On write failure trace_id is "" and meta is EMPTY.
        """
        threshold    = self._config.CORROBORATION_THRESHOLD
        # Fixed L1→L5 order (not signals.items()) so the evidence string
        # recorded in the CRONOS chain is identical across runs.
        active_names = [
            k for k in self._AGENT_FRAMEWORK
            if k != "L6_PEIRCE" and signals.get(k) is not None
        ]
        _empty_meta = AgentTraceMeta(
            quality="EMPTY", diversity="0/3", contradictions=[], confidence_warnings=[],
        )
        try:
            tracer = CronosTracer(
                self._store,
                agent_id   = "GATE",
                channel_id = artifact_id,
                user_id    = "corvus-gate",
                objective  = (
                    f"Corroboration gate: require >= {threshold} active agents "
                    f"for any verdict above SILENT"
                ),
            )
            with tracer as t:
                tid = t.trace.trace_id
                t.add_hypothesis(
                    "threshold_met",
                    f">= {threshold} agents must be active to emit non-SILENT verdict",
                )
                if active_count >= threshold:
                    t.add_evidence(
                        f"{active_count} agents active ({', '.join(active_names)}) "
                        f"— threshold {threshold} met",
                        supports="threshold_met",
                    )
                    t.decide(verdict.level.value, confidence=verdict.score)
                else:
                    t.add_evidence(
                        f"Only {active_count} agent(s) active "
                        f"({', '.join(active_names) or 'none'}) — "
                        f"below threshold {threshold}",
                        refutes="threshold_met",
                    )
                    t.discard_hypothesis(
                        "threshold_met",
                        f"Corroboration gate: {active_count} < {threshold} — forcing SILENT",
                    )
                    t.decide("SILENT", confidence=Fraction(1))

            return tid, AgentTraceMeta(**_trace_meta_from(tracer)), []

        except Exception as exc:
            msg = f"CRONOS_WRITE_FAILED:GATE:{type(exc).__name__}:{exc}"
            log.error("Rec-3: %s", msg)
            return "", _empty_meta, [msg]

    # ------------------------------------------------------------------
    # Internal: RT-10 drip-feed accumulation
    # ------------------------------------------------------------------

    def _check_drip_accumulation(
        self,
        user_id: str,
        artifact_id: str,
        signals: dict[str, object],
        active_count: int,
    ) -> tuple[Optional[Verdict], Optional[str], Optional[AgentTraceMeta]]:
        """
        Record this near-miss message's fired L1-L5 frameworks into the
        user's drip window (bounded to DRIP_WINDOW_SIZE messages), then
        check whether the UNION of frameworks fired across that window
        reaches the corroboration threshold — even though no single
        message in the window did on its own.

        Caller holds self._write_lock. Returns (verdict, trace_id, meta),
        all None if no escalation occurred.
        """
        fired = sorted(
            k for k in self._AGENT_FRAMEWORK
            if k != "L6_PEIRCE" and signals.get(k) is not None
        )
        conn = self._store._conn
        conn.execute(
            "INSERT INTO bridge_drip_window (user_id, artifact_id, frameworks, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, artifact_id, ",".join(fired),
             datetime.now(tz=timezone.utc).isoformat()),
        )
        # Prune to the last DRIP_WINDOW_SIZE rows for this user.
        conn.execute(
            """
            DELETE FROM bridge_drip_window
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM bridge_drip_window WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
            )
            """,
            (user_id, user_id, DRIP_WINDOW_SIZE),
        )
        conn.commit()

        rows = conn.execute(
            "SELECT artifact_id, frameworks FROM bridge_drip_window "
            "WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()

        union: set[str] = set()
        contributing: list[tuple[str, list[str]]] = []
        for aid, fw_str in rows:
            fws = [f for f in fw_str.split(",") if f]
            if fws:
                union.update(fws)
                contributing.append((aid, fws))

        threshold = self._config.CORROBORATION_THRESHOLD
        if len(union) < threshold:
            return None, None, None

        # Escalate. Clear the window so the next escalation needs fresh
        # evidence — prevents one crossing from re-triggering on every
        # subsequent silent message (RT-10 unbounded-repeat guard).
        conn.execute("DELETE FROM bridge_drip_window WHERE user_id = ?", (user_id,))
        conn.commit()

        frameworks_str = ", ".join(sorted(union))
        messages_str = ", ".join(aid for aid, _ in contributing)
        rationale = (
            f"RT-10 cross-message accumulation: no single message fired "
            f">= {threshold} frameworks, but {len(union)} independent "
            f"frameworks ({frameworks_str}) fired across {len(contributing)} "
            f"recent messages from this user ({messages_str}), within a "
            f"{DRIP_WINDOW_SIZE}-message window."
        )
        audit_payload = f"ACCUMULATION|{user_id}|{frameworks_str}|{messages_str}"
        audit_hash = hashlib.sha256(audit_payload.encode()).hexdigest()

        verdict = Verdict(
            level=VerdictLevel.WATCH,
            score=self._config.WATCH_THRESHOLD,
            rationale=rationale,
            signals_fired=sorted(union),
            recommendation=(
                "Monitor this user's subsequent messages. Escalated via "
                "cross-message accumulation (RT-10), not a single-message trigger — "
                "no individual message crossed the corroboration threshold alone."
            ),
            audit_hash=audit_hash,
        )

        trace_id, trace_meta = self._trace_accumulation(
            user_id, artifact_id, union, contributing, threshold,
        )
        return verdict, trace_id, trace_meta

    def _trace_accumulation(
        self,
        user_id: str,
        artifact_id: str,
        union: set[str],
        contributing: list[tuple[str, list[str]]],
        threshold: int,
    ) -> tuple[str, AgentTraceMeta]:
        """Open a CRONOS trace recording the accumulation escalation itself,
        so the exception path is exactly as auditable as the normal gate."""
        _empty_meta = AgentTraceMeta(
            quality="EMPTY", diversity="0/3", contradictions=[], confidence_warnings=[],
        )
        try:
            tracer = CronosTracer(
                self._store,
                agent_id   = "ACCUMULATION",
                channel_id = artifact_id,
                user_id    = user_id,
                objective  = (
                    f"Cross-message accumulation: require >= {threshold} independent "
                    f"frameworks across the last {DRIP_WINDOW_SIZE} messages from "
                    f"this user when no single message met the gate alone"
                ),
            )
            with tracer as t:
                tid = t.trace.trace_id
                t.add_hypothesis(
                    "drip_feed_pattern",
                    f"{len(union)} independent frameworks fired across "
                    f"{len(contributing)} recent messages from {user_id}",
                )
                for aid, fws in contributing:
                    t.add_evidence(
                        f"{aid}: {', '.join(fws)}",
                        supports="drip_feed_pattern",
                    )
                t.decide("WATCH", confidence=Fraction(1, 2))
            return tid, AgentTraceMeta(**_trace_meta_from(tracer))
        except Exception as exc:
            log.error("Rec-3: CRONOS_WRITE_FAILED:ACCUMULATION:%s:%s", type(exc).__name__, exc)
            return "", _empty_meta

    # ------------------------------------------------------------------
    # Internal: devil's advocate prose
    # ------------------------------------------------------------------

    @staticmethod
    def _build_devils_advocate(
        peirce_signal,
        signals: dict[str, object],
    ) -> str:
        """
        Synthesize the strongest counter-hypothesis to the current verdict.

        Builds the argument directly from CORVUS signal data.
        `_cronos_devils_advocate()` is not used here because it expects
        real DISCARD/EVIDENCE steps whose labels share a namespace —
        synthetic steps built ad-hoc from signal names would produce
        vacuous output (the label "L4_BERNE_no_signal" never appears
        in the EVIDENCE supports set "cross_layer_manipulation", so the
        function always falls back to discards[0] with no explanatory prose).
        """
        _FRAMEWORK = {
            "L1_GRICE":      "Grice Cooperative Principle",
            "L2_CARNEGIE":   "Carnegie/Cialdini Influence Detection",
            "L3_ARISTOTLE":  "Aristotelian Rhetoric Imbalance",
            "L4_BERNE":      "Berne Transactional Analysis",
            "L5_LINGUISTIC": "Linguistic Complexity & Register",
        }

        active_l1_l5   = [
            k for k in _FRAMEWORK if signals.get(k) is not None
        ]
        silent_l1_l5   = [
            k for k in _FRAMEWORK if signals.get(k) is None
        ]
        active_count   = len(active_l1_l5)

        # No Peirce synthesis → no cross-layer convergence
        if peirce_signal is None:
            if not active_l1_l5:
                return (
                    "No layer detected any signal. "
                    "The strongest benign explanation: text is fully cooperative, "
                    "expressive, and contextually normal across all five rhetorical "
                    "dimensions examined."
                )
            silent_frameworks = [_FRAMEWORK[k] for k in silent_l1_l5]
            active_frameworks = [_FRAMEWORK[k] for k in active_l1_l5]
            silent_str = ", ".join(silent_frameworks) if silent_frameworks else "none"
            return (
                f"Only {active_count}/5 layer(s) detected anomalies "
                f"({', '.join(active_frameworks)}). "
                f"The corroboration gate requires >= 2 independent signals; "
                f"{len(silent_l1_l5)} layer(s) found nothing ({silent_str}). "
                "Strongest benign alternative: the text uses emphatic or persuasive "
                "language that superficially resembles manipulation but is "
                "contextually legitimate — expressive register, not deliberate "
                "exploitation. Without cross-layer convergence the manipulation "
                "hypothesis is not confirmed."
            )

        # Peirce fired — build the strongest case AGAINST its conclusion
        # using the silent layers as the counter-evidence base.
        hypothesis = getattr(peirce_signal, "hypothesis", "a manipulation pattern")

        if not silent_l1_l5:
            # All five layers fired — this is the hardest case to refute
            return (
                f"All five analytical layers corroborate '{hypothesis}'. "
                "The strongest counter-argument available: simultaneous activation "
                "of all layers is possible in highly charged but legitimate contexts "
                "(negotiation, advocacy, sales, political speech) where intensity "
                "is intentional rather than deceptive. "
                "The system cannot distinguish intent from effect — "
                "a persuasive text and a manipulative one can produce identical "
                "signal profiles. This verdict requires human review before acting on it."
            )

        silent_frameworks = [_FRAMEWORK[k] for k in silent_l1_l5]
        active_frameworks = [_FRAMEWORK[k] for k in active_l1_l5]

        # The silent layers are the most honest counter-evidence.
        # Build the argument: "these dimensions found nothing, which means..."
        silent_str = " and ".join(silent_frameworks)
        active_str = ", ".join(active_frameworks)

        return (
            f"Peirce synthesis concluded '{hypothesis}' based on {active_count}/5 "
            f"active layers ({active_str}). "
            f"However, {len(silent_l1_l5)} layer(s) found no anomaly: {silent_str}. "
            "The strongest counter-hypothesis: the active layers may have fired on "
            "surface-level lexical features (urgency markers, authority claims, "
            "emotional language) that are also present in legitimate high-stakes "
            "communication — legal notices, medical advisories, crisis management. "
            "The silent dimensions suggest the underlying transaction structure "
            "and linguistic register do not deviate from baseline, which is "
            "inconsistent with systematic manipulation. "
            "This finding should be treated as WATCH rather than ALERT without "
            "additional behavioral context."
        )
