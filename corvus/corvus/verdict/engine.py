"""
CORVUS Verdict Engine
Converts a multi-layer AnalysisResult into a final Verdict with level,
weighted score, rationale, and audit hash.

Scoring architecture:
  1. Corroboration gate   — minimum signal count required for non-SILENT verdict
  2. Weighted aggregation — each layer has a fixed weight
  3. Baseline delta boost — deviation from user's own baseline amplifies score
  4. Threshold mapping    — score → VerdictLevel
  5. Audit hash           — SHA-256(score + level + result.audit_hash)
"""

import hashlib
from fractions import Fraction
from typing import Optional

from corvus.models import AnalysisResult, Verdict, VerdictLevel


# Layer weights — sum to 1.15, intentionally > 1.0.
# Rationale: not all 6 layers fire on any single message. When only 2-3 fire,
# their combined score rarely exceeds 0.75 (CRITICAL). When 5-6 fire simultaneously,
# the cap at Fraction(1,1) prevents overflow. This design gives each layer
# proportional influence without requiring weights to sum exactly to 1.0.
_WEIGHT_PEIRCE    = Fraction(3, 10)    # 0.30 — meta-signal, highest weight
_WEIGHT_INFLUENCE = Fraction(25, 100)  # 0.25
_WEIGHT_BERNE     = Fraction(2, 10)    # 0.20
_WEIGHT_ARISTOTLE = Fraction(15, 100)  # 0.15
_WEIGHT_GRICE     = Fraction(15, 100)  # 0.15
_WEIGHT_LINGUISTIC= Fraction(1, 10)    # 0.10

# Baseline delta multiplier factor
_DELTA_FACTOR = Fraction(1, 2)


class VerdictEngine:
    """
    Converts AnalysisResult into a Verdict with a Fraction score and VerdictLevel.
    All arithmetic uses fractions.Fraction — no floats in the scoring path.
    """

    def __init__(self, config) -> None:
        """
        Parameters
        ----------
        config : corvus.config.Config
        """
        self.corroboration_threshold = config.CORROBORATION_THRESHOLD
        self.watch_threshold = config.WATCH_THRESHOLD
        self.alert_threshold = config.ALERT_THRESHOLD
        self.critical_threshold = config.CRITICAL_THRESHOLD

    def compute(self, result: AnalysisResult) -> Verdict:
        """
        Compute the verdict for an AnalysisResult.

        Parameters
        ----------
        result : AnalysisResult

        Returns
        -------
        Verdict
        """
        signals_fired: list[str] = []

        # -------------------------------------------------------------------
        # Step 1: Corroboration gate
        # If fewer than CORROBORATION_THRESHOLD signals fired, force SILENT.
        # -------------------------------------------------------------------
        if result.active_signals < self.corroboration_threshold:
            return self._silent_verdict(result)

        # -------------------------------------------------------------------
        # Step 2: Weighted signal scoring (Fraction arithmetic only)
        # -------------------------------------------------------------------
        raw_score = Fraction(0, 1)

        if result.peirce is not None:
            raw_score += result.peirce.severity * _WEIGHT_PEIRCE
            signals_fired.append("peirce")

        if result.influence is not None:
            raw_score += result.influence.severity * _WEIGHT_INFLUENCE
            signals_fired.append("influence")

        if result.berne is not None:
            raw_score += result.berne.severity * _WEIGHT_BERNE
            signals_fired.append("berne")

        if result.aristotle is not None:
            raw_score += result.aristotle.imbalance_score * _WEIGHT_ARISTOTLE
            signals_fired.append("aristotle")

        if result.grice is not None:
            raw_score += result.grice.severity * _WEIGHT_GRICE
            signals_fired.append("grice")

        if result.linguistic is not None:
            raw_score += result.linguistic.severity * _WEIGHT_LINGUISTIC
            signals_fired.append("linguistic")

        # -------------------------------------------------------------------
        # Step 3: Baseline delta multiplier
        # score_final = score * (1 + baseline_delta * 0.5)
        # Only boost if the delta is positive (more signals than typical)
        # -------------------------------------------------------------------
        if result.baseline_delta > Fraction(0, 1):
            multiplier = Fraction(1, 1) + result.baseline_delta * _DELTA_FACTOR
            score = raw_score * multiplier
        else:
            score = raw_score

        # -------------------------------------------------------------------
        # Step 4: Cap at 1
        # -------------------------------------------------------------------
        score = min(score, Fraction(1, 1))

        # -------------------------------------------------------------------
        # Step 5: Apply thresholds → VerdictLevel
        # -------------------------------------------------------------------
        if score >= self.critical_threshold:
            level = VerdictLevel.CRITICAL
        elif score >= self.alert_threshold:
            level = VerdictLevel.ALERT
        elif score >= self.watch_threshold:
            level = VerdictLevel.WATCH
        else:
            level = VerdictLevel.SILENT

        # -------------------------------------------------------------------
        # Step 6: Generate human-readable rationale
        # -------------------------------------------------------------------
        rationale = self._build_rationale(result, score, level, signals_fired)
        recommendation = self._build_recommendation(level, signals_fired, result)

        # -------------------------------------------------------------------
        # Step 7: Audit hash
        # SHA-256(score_str + level_value + result.audit_hash)
        # -------------------------------------------------------------------
        score_str = f"{score.numerator}/{score.denominator}"
        audit_payload = f"{score_str}|{level.value}|{result.audit_hash}"
        audit_hash = hashlib.sha256(audit_payload.encode("utf-8")).hexdigest()

        return Verdict(
            level=level,
            score=score,
            rationale=rationale,
            signals_fired=signals_fired,
            recommendation=recommendation,
            audit_hash=audit_hash,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _silent_verdict(self, result: AnalysisResult) -> Verdict:
        """Return a SILENT verdict when corroboration threshold is not met."""
        audit_payload = f"0/1|SILENT|{result.audit_hash}"
        audit_hash = hashlib.sha256(audit_payload.encode("utf-8")).hexdigest()
        return Verdict(
            level=VerdictLevel.SILENT,
            score=Fraction(0, 1),
            rationale=(
                f"Corroboration gate: only {result.active_signals} signal(s) fired "
                f"(minimum {self.corroboration_threshold} required for non-SILENT verdict). "
                "Message stored for baseline update."
            ),
            signals_fired=[],
            recommendation="No action required. Baseline updated.",
            audit_hash=audit_hash,
        )

    def _build_rationale(
        self,
        result: AnalysisResult,
        score: Fraction,
        level: VerdictLevel,
        signals_fired: list[str],
    ) -> str:
        """Generate a plain-language rationale for the verdict."""
        score_pct = f"{float(score) * 100:.1f}%"
        delta_str = (
            f"{float(result.baseline_delta) * 100:+.1f}% vs. baseline"
            if result.baseline_delta != Fraction(0, 1)
            else "at baseline"
        )

        parts = [
            f"CORVUS scored this message at {score_pct} ({delta_str}). "
            f"Verdict: {level.value}.",
        ]

        if result.peirce is not None:
            parts.append(
                f"[Peirce] Abductive hypothesis: {result.peirce.hypothesis}"
            )
            if result.peirce.oscillation:
                parts.append(
                    "[Peirce] Contradictory signals detected — oscillation flag set."
                )

        if result.grice is not None:
            parts.append(
                f"[Grice/{result.grice.maxim.value}] {result.grice.evidence}"
            )

        if result.influence is not None:
            carnegie = ", ".join(result.influence.carnegie_patterns) or "none"
            cialdini = ", ".join(result.influence.cialdini_triggers) or "none"
            parts.append(
                f"[Carnegie] {carnegie} | [Cialdini] {cialdini}"
            )

        if result.aristotle is not None:
            parts.append(
                f"[Aristotle] Pathos={float(result.aristotle.pathos_score):.2f}, "
                f"Logos={float(result.aristotle.logos_score):.2f}, "
                f"Ethos={float(result.aristotle.ethos_score):.2f} "
                f"(imbalance={float(result.aristotle.imbalance_score):.2f})"
            )

        if result.berne is not None:
            parts.append(
                f"[Berne] {result.berne.ego_state} / {result.berne.transaction_type}"
            )

        if result.linguistic is not None:
            parts.append(
                f"[Linguistic] NV-ratio z={result.linguistic.nv_z_score:.2f}, "
                f"Fog={result.linguistic.fog_index:.1f}, "
                f"CLI={float(result.linguistic.cli_stress):.3f}"
            )

        return " | ".join(parts)

    def _build_recommendation(
        self,
        level: VerdictLevel,
        signals_fired: list[str],
        result: AnalysisResult,
    ) -> str:
        """Generate an actionable recommendation based on verdict level."""
        if level == VerdictLevel.SILENT:
            return "No action required. Baseline updated."

        if level == VerdictLevel.WATCH:
            return (
                "Monitor this user's subsequent messages. "
                "Flagged for security-team review."
            )

        if level == VerdictLevel.ALERT:
            base = (
                "Security team alerted. Treat any requests from this user with caution. "
                "Do not share credentials, transfer funds, or install software. "
            )
            if result.berne is not None and result.berne.transaction_type == "ULTERIOR":
                base += "Note: Ulterior transaction detected — stated intent may differ from actual intent."
            return base

        if level == VerdictLevel.CRITICAL:
            return (
                "CRITICAL THREAT. Immediately escalate to security team. "
                "Do NOT comply with any requests in this message. "
                "Message pinned and evidence bundle sealed. "
                "Initiate incident response protocol."
            )

        return "Review manually."
