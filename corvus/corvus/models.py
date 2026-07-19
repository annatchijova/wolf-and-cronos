from dataclasses import dataclass, field
from fractions import Fraction
from enum import Enum
from typing import Optional


class VerdictLevel(Enum):
    SILENT = "SILENT"      # score < 0.2 — memory update only
    WATCH = "WATCH"        # 0.2 <= score < 0.45 — DM security channel
    ALERT = "ALERT"        # 0.45 <= score < 0.75 — reply in thread
    CRITICAL = "CRITICAL"  # score >= 0.75 — pin + sealed bundle


class MaximViolated(Enum):
    QUANTITY = "QUANTITY"
    QUALITY = "QUALITY"
    RELATION = "RELATION"
    MANNER = "MANNER"


@dataclass
class GriceSignal:
    maxim: MaximViolated
    severity: Fraction       # 0–1
    evidence: str            # human-readable why
    fog_index: Optional[float] = None
    ambiguity_density: Optional[Fraction] = None


# [Cialdini] Influence principles — canonical string values used in InfluenceSignal.
# These are the valid values for InfluenceSignal.cialdini_triggers elements.
# P2 fix: was previously a dead Enum never referenced in l2_carnegie_cialdini.py.
# Now used as the authoritative source of valid Cialdini trigger names.
CIALDINI_PRINCIPLES = frozenset({
    "RECIPROCITY", "COMMITMENT", "SOCIAL_PROOF",
    "AUTHORITY", "LIKING", "SCARCITY",
})


@dataclass
class InfluenceSignal:
    carnegie_patterns: list[str]   # e.g. ["flattery", "urgency", "false_familiarity"]
    cialdini_triggers: list[str]   # values must be in CIALDINI_PRINCIPLES
    severity: Fraction
    evidence: list[str]            # matched phrases


@dataclass
class AristotleSignal:
    ethos_score: Fraction      # credibility claims
    pathos_score: Fraction     # emotional appeals
    logos_score: Fraction      # logical arguments
    imbalance_score: Fraction  # pathos >> logos = manipulation signal
    evidence: list[str]


@dataclass
class BerneSignal:
    ego_state: str       # "PARENT_CRITICAL" | "PARENT_NURTURING" | "ADULT" | "CHILD_ADAPTIVE" | "CHILD_REBELLIOUS"
    transaction_type: str  # "COMPLEMENTARY" | "CROSSED" | "ULTERIOR"
    severity: Fraction
    evidence: list[str]


@dataclass
class LinguisticSignal:
    nv_ratio: float        # noun/verb ratio
    nv_z_score: float      # deviation from user baseline
    cli_stress: Fraction   # cognitive load index
    fog_index: float
    zipf_r2: float         # < 0.75 = calculated errors
    severity: Fraction
    evidence: list[str]


@dataclass
class PeirceSignal:
    firstness: str     # raw observation
    secondness: str    # deviation description
    thirdness: str     # inferred pattern
    hypothesis: str    # winning abductive hypothesis
    oscillation: bool  # contradictory evidence detected
    confidence: int    # 0–100 integer
    severity: Fraction


@dataclass
class AnalysisResult:
    message_id: str
    user_id: str
    channel_id: str
    text: str
    timestamp: str
    grice: Optional[GriceSignal]
    influence: Optional[InfluenceSignal]
    aristotle: Optional[AristotleSignal]
    berne: Optional[BerneSignal]
    linguistic: Optional[LinguisticSignal]
    peirce: Optional[PeirceSignal]
    active_signals: int       # how many layers fired
    baseline_delta: Fraction  # deviation from user's own baseline
    audit_hash: str
    # FIX: a detector that raised an exception used to be indistinguishable
    # from one that genuinely found nothing (both surfaced as None/silent).
    # Names of L1-L5 detectors that crashed during analyze(), so a caller can
    # tell "nothing suspicious" apart from "we don't actually know."
    crashed_agents: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    level: VerdictLevel
    score: Fraction
    rationale: str            # human-readable explanation
    signals_fired: list[str]  # which layers triggered
    recommendation: str       # what action to take
    audit_hash: str
    bundle_path: Optional[str] = None  # path to sealed bundle if CRITICAL


def compute_baseline_delta(user_baseline: dict, active_signals: int) -> Fraction:
    """
    Deviation of this message's signal count from the user's own average,
    returned as an exact Fraction in [-1, 1]:

        delta = (active_signals - avg) / (active_signals + avg)

    The average is taken from the exact integer accumulator
    ``signals_sum / message_count`` so the value that feeds the sealed score
    carries no float — satisfying the zero-float decision-path invariant.

    Previously the average was floored with ``int(avg_signals_per_message)``,
    which truncated (not rounded) the running mean. A user whose true average
    was 0.9 had it floored to 0, so an ordinary 2-signal message produced the
    maximum +1.0 delta and a 1.5x score multiplier — systematic false-positive
    pressure. Using the exact rational average removes that bias.

    Legacy baselines that predate the ``signals_sum`` accumulator fall back to
    the stored float mean, converted exactly (dyadic) and bounded, so existing
    databases keep working.
    """
    msg_count = int(user_baseline.get("message_count", 0) or 0)
    signals_sum = user_baseline.get("signals_sum")

    if signals_sum is not None and msg_count > 0:
        avg = Fraction(int(signals_sum), msg_count)
    elif msg_count > 0:
        # Legacy row without the accumulator: derive from the stored mean.
        avg = Fraction(
            user_baseline.get("avg_signals_per_message", 0)
        ).limit_denominator(10 ** 6)
    else:
        avg = Fraction(0)

    denom = active_signals + avg
    if denom == 0:
        return Fraction(0)
    return (Fraction(active_signals) - avg) / denom
