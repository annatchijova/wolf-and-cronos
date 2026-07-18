"""
CRONOS — CronosTracer
Context-manager SDK for instrumenting agent decision cycles.

The tracer records steps *while* the agent runs — not as a post-hoc
rationalization. Every recall, tool call, hypothesis, discard, and piece
of evidence is timestamped as it happens. When the context exits, the
full trace is sealed with quality metrics applied, then written atomically.

VIGÍA ideas integrated here:
  - Version sentinel: cronos_version recorded in OBJECTIVE step payload
  - Negation detection: add_evidence() auto-tags negation context
  - Confidence ceiling + floor: apply_confidence_constraints() in decide()
  - Quality / diversity / contradiction: computed on __exit__ before save

Usage
-----
    from fractions import Fraction
    from cronos import CronosTracer, TraceStore

    store = TraceStore("cronos.db")

    with CronosTracer(store, agent_id="ticket-resolver",
                      channel_id="C123", user_id="U456",
                      objective="Resolve ticket #842") as t:

        t.record_recall("M-22",  "Auth timeout in service A", score=Fraction(91, 100))
        t.call_tool("jira",   "ticket #842 → Open / Auth / High")
        t.add_hypothesis("auth_bug",  "Authentication token expired")
        t.add_hypothesis("cache_bug", "Cache invalidation failure")
        t.add_evidence("Jira confirms Auth category",  supports="auth_bug")
        t.add_evidence("No cache errors in Jira log",  refutes="cache_bug")
        t.discard_hypothesis("cache_bug", "No cache errors in Jira log")
        t.decide("Apply auth token reset", confidence=Fraction(74, 100))
"""

import logging
from datetime import datetime, timezone
from fractions import Fraction
from typing import Optional
from uuid import uuid4

log = logging.getLogger("cronos.tracer")

from .models import Trace, TraceStep, StepKind
from .quality import (
    CRONOS_VERSION,
    apply_confidence_constraints,
    compute_quality,
    diversity_score,
    detect_negation,
    find_contradictions,
)
from .store import TraceStore


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class CronosTracer:
    """
    Records the decision trace of a single agent action cycle.
    Must be used as a context manager.
    On __exit__: quality metrics are computed, confidence is constrained,
    and the trace is sealed + stored atomically.
    """

    def __init__(
        self,
        store: TraceStore,
        agent_id: str,
        channel_id: str,
        user_id: str,
        objective: str,
    ) -> None:
        self._store = store
        self.trace = Trace(
            trace_id=str(uuid4()),
            agent_id=agent_id,
            channel_id=channel_id,
            user_id=user_id,
            objective=objective,
            started_at=_now(),
            cronos_version=CRONOS_VERSION,  # 8. version sentinel
        )
        # OBJECTIVE is always the first step.
        # Payload includes cronos_version for future audit reproducibility.
        self.trace.steps.append(TraceStep(
            kind=StepKind.OBJECTIVE,
            payload={
                "objective":      objective,
                "cronos_version": CRONOS_VERSION,   # 8. version sentinel
            },
            timestamp=self.trace.started_at,
        ))

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "CronosTracer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.trace.closed_at = _now()
        self.trace.closed = True

        if not self.trace.decision:
            self.trace.decision = "(no decision recorded)"
            self.trace.confidence = Fraction(0)

        # ── Compute quality metrics before saving ──────────────────────────
        steps = self.trace.steps

        # 7. Trace quality level
        self.trace.quality    = compute_quality(steps)
        # 1. Observational diversity score
        self.trace.diversity  = diversity_score(steps)
        # 5. Contradiction detection
        self.trace.contradictions = find_contradictions(steps)
        # 2 & 3. Confidence ceiling + floor
        if self.trace.confidence is not None:
            adj, warnings = apply_confidence_constraints(self.trace.confidence, steps)
            self.trace.confidence          = adj
            self.trace.confidence_warnings = warnings
            # Back-patch the DECISION step payload if confidence was adjusted
            for step in reversed(steps):
                if step.kind == StepKind.DECISION:
                    step.payload["confidence"] = (
                        f"{adj.numerator}/{adj.denominator}"
                    )
                    if warnings:
                        step.payload["confidence_warnings"] = warnings
                    break

        try:
            self._store.save_trace(self.trace)
        except Exception as store_err:  # noqa: BLE001
            # Log storage failure but never mask the agent's own exception.
            # If exc_type is set, the agent already failed — the caller will
            # see that exception, not this one.  If exc_type is None, this
            # raises from here, which is the correct behavior.
            log.error(
                "CRONOS: failed to persist trace %s — reasoning was NOT recorded: %s",
                self.trace.trace_id[:8],
                store_err,
            )
            raise
        return False  # never suppress exceptions

    # ── Recording API ─────────────────────────────────────────────────────────

    def record_recall(
        self,
        memory_id: str,
        summary: str,
        score: Optional[Fraction] = None,
    ) -> None:
        """Record a memory retrieval from the episodic/semantic store."""
        payload: dict = {"memory_id": memory_id, "summary": summary}
        if score is not None:
            payload["score"] = f"{score.numerator}/{score.denominator}"
        self.trace.steps.append(TraceStep(StepKind.RECALL, payload, _now()))

    def call_tool(self, tool_name: str, result_summary: str) -> None:
        """Record an external tool call and its result summary."""
        self.trace.steps.append(TraceStep(
            StepKind.TOOL,
            {"tool": tool_name, "result": result_summary},
            _now(),
        ))

    def add_hypothesis(self, label: str, description: str) -> None:
        """Register a hypothesis under active consideration."""
        self.trace.steps.append(TraceStep(
            StepKind.HYPOTHESIS,
            {"label": label, "description": description},
            _now(),
        ))

    def discard_hypothesis(self, label: str, reason: str) -> None:
        """Mark a hypothesis as discarded and record the reason."""
        self.trace.steps.append(TraceStep(
            StepKind.DISCARD,
            {"label": label, "reason": reason},
            _now(),
        ))

    def add_evidence(
        self,
        text: str,
        supports: Optional[str] = None,
        refutes: Optional[str] = None,
    ) -> None:
        """
        Record a piece of evidence.

        6. Negation context detection (from VIGÍA negation_handler):
           If the text contains negation words, payload["negation_detected"] = True
           is set automatically. This marks the evidence as attenuating context
           rather than positive confirmation.

        Parameters
        ----------
        text:     human-readable fact
        supports: label of the hypothesis this evidence supports (optional)
        refutes:  label of the hypothesis this evidence refutes (optional)
        """
        if supports and refutes:
            raise ValueError(
                "add_evidence: a single piece of evidence cannot both support and refute. "
                "Call add_evidence twice if the fact is ambiguous."
            )
        payload: dict = {"text": text}
        if supports:
            payload["supports"] = supports
        if refutes:
            payload["refutes"] = refutes
        # 6. Negation context auto-detection
        if detect_negation(text):
            payload["negation_detected"] = True
        self.trace.steps.append(TraceStep(StepKind.EVIDENCE, payload, _now()))

    def decide(self, decision: str, confidence: Fraction) -> None:
        """
        Record the final decision and raw confidence score.
        confidence must be a fractions.Fraction in [0, 1].

        Note: the final stored confidence may differ from the value passed here
        if the confidence ceiling (diversity-based) or floor (evidence-based)
        requires clamping. See quality.apply_confidence_constraints().
        The DECISION step payload records the adjusted value and any warnings.
        """
        if not isinstance(confidence, Fraction):
            raise TypeError(
                "confidence must be fractions.Fraction — "
                f"got {type(confidence).__name__}. CRONOS uses no floats."
            )
        if not (Fraction(0) <= confidence <= Fraction(1)):
            raise ValueError(
                f"confidence must be in [0, 1] — got {confidence}. "
                "Use Fraction(0) for no confidence, Fraction(1) for certainty."
            )
        self.trace.decision   = decision
        self.trace.confidence = confidence
        self.trace.steps.append(TraceStep(
            StepKind.DECISION,
            {
                "decision":   decision,
                "confidence": f"{confidence.numerator}/{confidence.denominator}",
                "raw":        True,  # will be updated in __exit__ if adjusted
            },
            _now(),
        ))
