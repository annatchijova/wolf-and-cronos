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
    AnalysisResult, PeirceSignal, VerdictLevel,
)
from corvus.verdict.engine import VerdictEngine

from cronos import CronosTracer, TraceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_fraction(value) -> Fraction:
    """Safely coerce a Fraction, float, or int severity to Fraction."""
    if isinstance(value, Fraction):
        return value
    try:
        return Fraction(str(round(float(value), 9)))
    except Exception:
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

        self._l1 = GriceDetector()
        self._l2 = InfluenceDetector()
        self._l3 = AristotleDetector()
        self._l4 = BerneDetector()
        self._l5 = LinguisticsDetector()
        self._l6 = PeirceDetector()

        # Concurrency guard — CRONOS+MemoryEngine writes are not re-entrant.
        # A single bridge instance shared across threads must serialize Phases
        # 7-9 (trace writes, chain verify, memory store).  Analysis Phases 1-6
        # (read-only CORVUS detectors) run without the lock so parallel calls
        # still benefit from their internal thread pool.
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

        ts = datetime.now(tz=timezone.utc).isoformat()
        history = conversation_history or []

        # Phase 0: resolve behavioral baseline
        # Explicit override > MemoryEngine > empty dict
        if user_baseline is not None:
            baseline = dict(user_baseline)
        elif self._memory is not None:
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
        baseline_delta = Fraction(0)
        avg_raw = baseline.get("avg_signals_per_message") \
               or baseline.get("avg_active_signals")
        if avg_raw is not None:
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

        # Classify agents
        crashed_set   = set(crashed)
        active_agents = [
            k for k, v in signals.items() if k != "L6_PEIRCE" and v is not None
        ]
        silent_agents = [
            k for k, v in signals.items()
            if k != "L6_PEIRCE" and v is None and k not in crashed_set
        ]
        if peirce_signal is not None:
            active_agents.append("L6_PEIRCE")
        else:
            silent_agents.append("L6_PEIRCE")

        # Peirce thirdness as primary rationale; fall back to gate summary
        rationale = (
            peirce_signal.thirdness
            if peirce_signal is not None
            else f"Gate: {active_count}/5 agents active — verdict {verdict.level.value}"
        )

        # Devil's advocate from L6 trace (CRONOS quality module)
        devil = trace_meta.get("L6_PEIRCE", AgentTraceMeta(
            quality="EMPTY", diversity="0/3", contradictions=[], confidence_warnings=[],
        ))
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
        active_names = [
            k for k, v in signals.items()
            if k != "L6_PEIRCE" and v is not None
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
