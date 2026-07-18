"""
L6 — Peirce Abductive Reasoning Engine
Theoretical framework: Charles Sanders Peirce's semiotics and abductive reasoning.
  Firstness  — the pure quality/feeling of the signal (what is observed)
  Secondness — the actual deviation/fact (comparison to baseline)
  Thirdness  — the law/interpretation (inferred pattern, hypothesis)
Performs bounded abductive reasoning (Miller limit: 7 iterations max) to synthesize
the outputs of L1-L5 into a unified manipulation hypothesis.
"""

from fractions import Fraction
from typing import Optional

from corvus.models import (
    PeirceSignal,
    GriceSignal, InfluenceSignal, AristotleSignal, BerneSignal, LinguisticSignal,
    compute_baseline_delta,
)

# ---------------------------------------------------------------------------
# [Peirce Thirdness] Hypothesis table
# Signal combination → interpretation string
# ---------------------------------------------------------------------------

_HYPOTHESIS_TABLE: list[tuple[set[str], str]] = [
    # All signals present
    (
        {"grice", "influence", "aristotle", "berne", "linguistic"},
        "Coordinated multi-vector manipulation: all analysis layers triggered simultaneously, "
        "indicating a highly sophisticated deception attempt combining obfuscation, influence, "
        "emotional manipulation, transactional deception, and linguistic anomalies.",
    ),
    # Influence + Grice MANNER
    (
        {"influence", "grice"},
        "Deliberate obfuscation to embed influence: the message uses complex language to hide "
        "manipulation tactics, making the attempt harder to consciously identify.",
    ),
    # Aristotle PATHOS + Berne ULTERIOR
    (
        {"aristotle", "berne"},
        "Emotional manipulation with hidden agenda: heavy emotional appeals are paired with "
        "an ulterior transactional structure, suggesting the emotion is being weaponized "
        "to bypass rational evaluation.",
    ),
    # Linguistic CLI + Influence SCARCITY
    (
        {"linguistic", "influence"},
        "Artificial urgency with cognitive pressure: high cognitive load indicators combined "
        "with scarcity/urgency tactics are designed to prevent careful reasoning.",
    ),
    # Aristotle ETHOS (hollow) + Influence AUTHORITY
    (
        {"aristotle", "influence"},
        "Credential fraud pattern: hollow authority claims in rhetoric are amplified by "
        "explicit authority-principle triggers, indicating fabricated or exaggerated credentials.",
    ),
    # Berne PARENT_CRITICAL + history escalation
    (
        {"berne", "linguistic"},
        "Coercive escalation pattern: critical parent ego state combined with linguistic "
        "anomalies suggests a scripted escalation strategy designed to pressure compliance.",
    ),
    # Grice + Berne
    (
        {"grice", "berne"},
        "Obfuscated ulterior transaction: deliberately unclear language conceals a transactional "
        "hidden agenda, making the manipulation harder to identify.",
    ),
    # Aristotle + Linguistic
    (
        {"aristotle", "linguistic"},
        "Rehearsed emotional appeal: linguistic register anomalies alongside emotional rhetoric "
        "suggest the message was crafted rather than spontaneous.",
    ),
]

# Sort descending by required-set size so more specific hypotheses (larger sets)
# are always evaluated before generic ones. A 5-signal entry must win over a
# 2-signal entry when both would match — this sort makes that invariant
# independent of the order the table entries are written in.
#
# TIE-BREAKING (equal set sizes): Python's sort is stable — entries with the
# same number of required signals keep their ORIGINAL insertion order above.
# Maintainer rule: when adding two entries of the same specificity, place the
# more restrictive one HIGHER in the list so it wins the tie. Do NOT rely on
# alphabetical or any other implicit ordering.
_HYPOTHESIS_TABLE.sort(key=lambda entry: len(entry[0]), reverse=True)

# Oscillation: contradictory signal pairs
_OSCILLATION_PAIRS: list[tuple[str, str, str]] = [
    # (signal_a, signal_b, description)
    ("authority_claim", "adaptive_compliance", "AUTHORITY claim co-occurring with CHILD_ADAPTIVE ego state"),
    ("influence_authority", "berne_child", "Cialdini AUTHORITY trigger co-occurring with Child ego state"),
    ("influence_scarcity", "logos_heavy", "Urgency/scarcity combined with logos-heavy rational argument"),
    ("ethos_high", "pathos_high", "High credibility claims AND high emotional appeals simultaneously"),
]


def _active_signal_names(
    grice: Optional[GriceSignal],
    influence: Optional[InfluenceSignal],
    aristotle: Optional[AristotleSignal],
    berne: Optional[BerneSignal],
    linguistic: Optional[LinguisticSignal],
) -> list[str]:
    """Return list of fired detector names."""
    fired: list[str] = []
    if grice is not None:
        fired.append("grice")
    if influence is not None:
        fired.append("influence")
    if aristotle is not None:
        fired.append("aristotle")
    if berne is not None:
        fired.append("berne")
    if linguistic is not None:
        fired.append("linguistic")
    return fired


class PeirceDetector:
    """
    [Peirce] Meta-analytical layer using bounded abductive reasoning.
    Synthesizes L1-L5 signals into a unified hypothesis about manipulation intent.
    Miller limit: maximum 7 hypothesis iterations.
    """

    MILLER_LIMIT = 7

    def analyze(
        self,
        text: str,
        signals: list,
        user_baseline: dict,
    ) -> Optional[PeirceSignal]:
        """
        Perform Peirce abductive analysis on the collected signals.

        Parameters
        ----------
        text : str
            The raw message text.
        signals : list
            List of [grice, influence, aristotle, berne, linguistic] — any may be None.
        user_baseline : dict
            Per-user behavioral baseline.

        Returns
        -------
        Optional[PeirceSignal]
            Abductive hypothesis result, or None if no signals fired.
        """
        # Unpack signals by type — order in list does not matter
        grice: Optional[GriceSignal] = next((s for s in signals if isinstance(s, GriceSignal)), None)
        influence: Optional[InfluenceSignal] = next((s for s in signals if isinstance(s, InfluenceSignal)), None)
        aristotle: Optional[AristotleSignal] = next((s for s in signals if isinstance(s, AristotleSignal)), None)
        berne: Optional[BerneSignal] = next((s for s in signals if isinstance(s, BerneSignal)), None)
        linguistic: Optional[LinguisticSignal] = next((s for s in signals if isinstance(s, LinguisticSignal)), None)

        fired_names = _active_signal_names(grice, influence, aristotle, berne, linguistic)
        active_signals = len(fired_names)

        if active_signals == 0:
            return None

        # ---------------------------------------------------------------
        # [Peirce Firstness] Raw observation
        # ---------------------------------------------------------------
        firstness = f"Message contains: [{', '.join(fired_names)}]"

        # ---------------------------------------------------------------
        # [Peirce Secondness] Deviation from baseline
        # ---------------------------------------------------------------
        baseline_avg = user_baseline.get("avg_signals_per_message", 0)  # display only
        # Exact rational deviation — shared with the analyzer so the two never
        # diverge. See models.compute_baseline_delta.
        baseline_delta = compute_baseline_delta(user_baseline, active_signals)
        if baseline_delta > Fraction(0, 1):
            secondness = (
                f"Deviation: {active_signals} signals fired vs. baseline avg of "
                f"{baseline_avg:.1f} (delta={float(baseline_delta):.3f})"
            )
        elif baseline_delta < Fraction(0, 1):
            secondness = (
                f"Below-baseline signal density: {active_signals} signals vs. avg of "
                f"{baseline_avg:.1f} — message may be unusually terse."
            )
        else:
            secondness = (
                f"Signal count {active_signals} matches user baseline avg of {baseline_avg:.1f}."
            )

        # ---------------------------------------------------------------
        # [Peirce Thirdness] Abductive hypothesis (Miller limit = 7 iterations)
        # ---------------------------------------------------------------
        fired_set = set(fired_names)
        winning_hypothesis = ""
        iterations = 0

        for required_signals, hypothesis_text in _HYPOTHESIS_TABLE:
            if iterations >= self.MILLER_LIMIT:
                break
            iterations += 1
            if required_signals.issubset(fired_set):
                winning_hypothesis = hypothesis_text
                break

        if not winning_hypothesis:
            # Single signal or no combination match — use signal's own interpretation
            if active_signals == 1:
                winning_hypothesis = self._single_signal_hypothesis(
                    grice, influence, aristotle, berne, linguistic
                )
            else:
                winning_hypothesis = (
                    f"Multiple signals ({', '.join(fired_names)}) fired without a "
                    "canonical combination pattern — signals may be independent but cumulative."
                )

        thirdness = winning_hypothesis

        # ---------------------------------------------------------------
        # [Peirce Oscillation] Contradictory evidence detection
        # ---------------------------------------------------------------
        oscillation = self._detect_oscillation(influence, aristotle, berne)

        # ---------------------------------------------------------------
        # Confidence and severity
        # ---------------------------------------------------------------
        # baseline_delta is an exact Fraction; quantize with Fraction arithmetic.
        # int(float(baseline_delta) * 100) reintroduced a float into the value that
        # becomes confidence -> severity -> sealed score, violating the zero-float
        # decision-path invariant.
        delta_contribution = int(baseline_delta * 100) if baseline_delta > 0 else 0
        confidence = min(100, active_signals * 20 + delta_contribution)
        severity = Fraction(confidence, 100)

        return PeirceSignal(
            firstness=firstness,
            secondness=secondness,
            thirdness=thirdness,
            hypothesis=winning_hypothesis,
            oscillation=oscillation,
            confidence=confidence,
            severity=severity,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _single_signal_hypothesis(
        self,
        grice: Optional[GriceSignal],
        influence: Optional[InfluenceSignal],
        aristotle: Optional[AristotleSignal],
        berne: Optional[BerneSignal],
        linguistic: Optional[LinguisticSignal],
    ) -> str:
        """Generate a hypothesis for a single-signal scenario."""
        if grice is not None:
            return (
                f"Isolated Gricean violation of maxim {grice.maxim.value}: "
                f"{grice.evidence}"
            )
        if influence is not None:
            patterns = ", ".join(influence.carnegie_patterns + influence.cialdini_triggers)
            return (
                f"Isolated influence pattern ({patterns}): may indicate "
                "single-vector persuasion attempt rather than coordinated manipulation."
            )
        if aristotle is not None:
            return (
                f"Isolated rhetorical imbalance: pathos={float(aristotle.pathos_score):.2f} "
                f"vs logos={float(aristotle.logos_score):.2f} — emotional appeal without "
                "logical backing, possibly manipulative."
            )
        if berne is not None:
            return (
                f"Isolated transactional anomaly: {berne.transaction_type} transaction "
                f"from {berne.ego_state} ego state."
            )
        if linguistic is not None:
            return (
                f"Isolated linguistic anomaly: NV ratio z-score={linguistic.nv_z_score:.2f}, "
                "possible register shift or scripted communication."
            )
        return "No interpretable signal."

    def _detect_oscillation(
        self,
        influence: Optional[InfluenceSignal],
        aristotle: Optional[AristotleSignal],
        berne: Optional[BerneSignal],
    ) -> bool:
        """
        [Peirce Oscillation] Detect contradictory evidence.
        Contradiction = signals that pull in opposite directions simultaneously.
        """
        # AUTHORITY influence trigger + CHILD_ADAPTIVE or CHILD_REBELLIOUS berne state
        if influence is not None and berne is not None:
            has_authority = "AUTHORITY" in influence.cialdini_triggers
            is_child_state = berne.ego_state in ("CHILD_ADAPTIVE", "CHILD_REBELLIOUS")
            if has_authority and is_child_state:
                return True

        # High ethos claims AND high pathos (credential fraud + emotional manipulation
        # are contradictory strategies)
        if aristotle is not None:
            if (
                aristotle.ethos_score > Fraction(1, 2)
                and aristotle.pathos_score > Fraction(1, 2)
            ):
                return True

        # Scarcity (urgency/pressure) combined with logos-heavy rational argument
        if influence is not None and aristotle is not None:
            has_scarcity = "SCARCITY" in influence.cialdini_triggers
            logos_heavy = aristotle.logos_score > Fraction(6, 10)
            if has_scarcity and logos_heavy:
                return True

        return False
