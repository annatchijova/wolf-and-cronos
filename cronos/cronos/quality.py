"""
CRONOS — Quality & Epistemics Module
Eight ideas ported from VIGÍA:

1. Observational diversity score   — how many distinct evidence kinds were used
2. Confidence ceiling from diversity — low diversity → lower ceiling (trust_fusion)
3. Confidence floor                — minimum epistemic floor when evidence exists
4. Devil's advocate synthesis      — strongest alternative explanation (devil_advocate_gen)
5. Contradiction detection         — evidence both supporting AND refuting same hypothesis
6. Negation context detection      — auto-detect negation polarity in evidence text
7. Trace quality level             — FULL / PARTIAL / MINIMAL / EMPTY (acquisition assurance)
8. Version sentinel                — record tracer version in each trace for future audits
"""

import re
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import TraceStep

# TraceQuality is defined in models.py to avoid circular imports.
# Re-exported here for convenience.
from .models import TraceQuality  # noqa: E402

# ── 8. Version sentinel ────────────────────────────────────────────────────────

CRONOS_VERSION = "0.1.0"


# ── 7. Trace quality level ────────────────────────────────────────────────────

# ── 1. Observational diversity score ──────────────────────────────────────────

def _observation_groups(steps: list) -> int:
    """
    Count how many of the three observation groups are represented:
      Group A — RECALL  (what the agent remembered)
      Group B — TOOL    (what the agent looked up)
      Group C — HYPOTHESIS, DISCARD, or EVIDENCE (what the agent reasoned about)

    Returns an integer 0–3. Higher = more diverse observations.
    """
    from .models import StepKind
    kinds = {s.kind for s in steps}
    groups = 0
    if StepKind.RECALL in kinds:
        groups += 1
    if StepKind.TOOL in kinds:
        groups += 1
    if kinds & {StepKind.HYPOTHESIS, StepKind.DISCARD, StepKind.EVIDENCE}:
        groups += 1
    return groups


def diversity_score(steps: list) -> Fraction:
    """
    Fraction(groups, 3) where groups ∈ {0, 1, 2, 3}.
    Fraction(3, 3) = fully diverse; Fraction(0, 3) = no observations.
    """
    return Fraction(_observation_groups(steps), 3)


# ── 7. Trace quality level ─────────────────────────────────────────────────────

def compute_quality(steps: list) -> "TraceQuality":
    """
    Classify the trace quality from its step diversity.
    FULL    → groups == 3
    PARTIAL → groups == 2
    MINIMAL → groups == 1
    EMPTY   → groups == 0
    """
    g = _observation_groups(steps)
    if g == 3:
        return TraceQuality.FULL
    if g == 2:
        return TraceQuality.PARTIAL
    if g == 1:
        return TraceQuality.MINIMAL
    return TraceQuality.EMPTY


# ── 2 & 3. Confidence ceiling + floor ─────────────────────────────────────────

# Ceiling: maximum allowed confidence given diversity level.
# Inspired by VIGÍA's trust_fusion: even a perfect chain of custody cannot
# eliminate all uncertainty — the ceiling encodes that epistemic limit.
_DIVERSITY_CEILING: dict[int, Fraction] = {
    3: Fraction(1),        # fully diverse → no ceiling
    2: Fraction(17, 20),   # 0.85 — two groups → moderate ceiling
    1: Fraction(3, 5),     # 0.60 — one group → significant ceiling
    0: Fraction(1, 5),     # 0.20 — no observations → very low ceiling
}

# Floor: minimum confidence when at least one supporting piece of evidence exists.
# An agent that has any supporting evidence cannot have zero confidence.
_EVIDENCE_FLOOR = Fraction(1, 10)


def apply_confidence_constraints(
    confidence: Fraction,
    steps: list,
) -> tuple[Fraction, list[str]]:
    """
    Apply diversity ceiling and evidence floor to the raw confidence value.

    Returns
    -------
    (adjusted_confidence, list_of_warnings)
        warnings explain any clamping that occurred.
    """
    from .models import StepKind
    warnings: list[str] = []
    g = _observation_groups(steps)
    ceiling = _DIVERSITY_CEILING[g]

    has_supporting_evidence = any(
        s.kind == StepKind.EVIDENCE and s.payload.get("supports")
        for s in steps
    )
    floor = _EVIDENCE_FLOOR if has_supporting_evidence else Fraction(0)

    adj = confidence
    if adj > ceiling:
        warnings.append(
            f"Confidence {confidence} capped at {ceiling} "
            f"(diversity ceiling: {g}/3 observation groups)"
        )
        adj = ceiling
    if adj < floor:
        warnings.append(
            f"Confidence {confidence} raised to floor {floor} "
            f"(supporting evidence present — cannot be zero)"
        )
        adj = floor

    return adj, warnings


# ── 5. Contradiction detector ─────────────────────────────────────────────────

def find_contradictions(steps: list) -> list[str]:
    """
    Detect logical inconsistencies in the trace:

    Type A — a hypothesis has evidence both supporting AND refuting it.
    Type B — a hypothesis has supporting evidence but was also discarded
             (the discard may have been premature or the evidence stale).

    Adapted from VIGÍA's contradiction threshold in the self-correction loop.
    """
    from .models import StepKind

    supports:  set[str] = set()
    refutes:   set[str] = set()
    discarded: set[str] = set()

    for s in steps:
        if s.kind == StepKind.EVIDENCE:
            if s.payload.get("supports"):
                supports.add(s.payload["supports"])
            if s.payload.get("refutes"):
                refutes.add(s.payload["refutes"])
        elif s.kind == StepKind.DISCARD:
            discarded.add(s.payload["label"])

    contradictions: list[str] = []

    for h in supports & refutes:
        contradictions.append(
            f"Type A: '{h}' has evidence both supporting and refuting it"
        )
    for h in supports & discarded:
        contradictions.append(
            f"Type B: '{h}' has supporting evidence but was discarded — "
            f"discard may be premature or evidence stale"
        )

    return contradictions


# ── 4. Devil's advocate synthesis ─────────────────────────────────────────────

def devils_advocate(steps: list, decision: str) -> str:
    """
    Synthesize the strongest alternative explanation from discarded hypotheses.

    Adapted from VIGÍA's devil_advocate_gen — every verdict must articulate
    the strongest counter-hypothesis it rejected (Daubert/falsifiability).

    Returns a prose string suitable for display alongside the main decision.
    """
    from .models import StepKind

    discards = [s for s in steps if s.kind == StepKind.DISCARD]
    if not discards:
        return "No alternative hypotheses were generated."

    # Find the discard that had supporting evidence — that's the strongest alternative.
    supported_labels = {
        s.payload["supports"]
        for s in steps
        if s.kind == StepKind.EVIDENCE and s.payload.get("supports")
    }
    primary = next(
        (d for d in discards if d.payload["label"] in supported_labels),
        discards[0],  # fallback: first discarded hypothesis
    )

    label  = primary.payload["label"]
    reason = primary.payload["reason"]

    # Collect any supporting evidence for the discarded hypothesis
    alt_evidence = [
        s.payload["text"]
        for s in steps
        if s.kind == StepKind.EVIDENCE and s.payload.get("supports") == label
    ]

    parts = [
        f"The strongest alternative explanation is '{label}', "
        f"rejected because: {reason}."
    ]
    if alt_evidence:
        evidence_str = "; ".join(alt_evidence[:2])
        parts.append(
            f"However, it had supporting evidence: {evidence_str}."
        )
    parts.append(
        "This alternative cannot be fully excluded without additional observation."
    )

    return " ".join(parts)


# ── 6. Negation context detection ─────────────────────────────────────────────

_NEGATION_RE = re.compile(
    r"\b(no|not|never|none|nothing|without|absence|absent|lack|lacking|missing|"
    r"failed\s+to|unable\s+to|did\s+not|does\s+not|cannot|can\'t|isn\'t|aren\'t|"
    r"wasn\'t|weren\'t|hadn\'t|haven\'t|don\'t|doesn\'t|didn\'t|no\s+evidence\s+of)\b",
    re.IGNORECASE,
)


def detect_negation(text: str) -> bool:
    """
    Return True if the evidence text contains a negation pattern within the first 200 chars.
    Adapted from VIGÍA's negation_handler (±200 char window, bidirectional search).

    Evidence like "No cache errors in Jira" should be treated as attenuating context,
    not as positive confirmation of anything.
    """
    return bool(_NEGATION_RE.search(text[:200]))
