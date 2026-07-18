"""
L3 — Aristotelian Rhetoric Detector
Theoretical framework: Aristotle's three modes of persuasion from "Rhetoric" (c. 350 BCE).
  Ethos   — credibility / authority appeals
  Pathos  — emotional appeals
  Logos   — logical / evidential appeals
The manipulation signal is an imbalance: pathos >> logos (emotion overrides reason).
"""

import re
from fractions import Fraction
from typing import Optional

from corvus.models import AristotleSignal


# ---------------------------------------------------------------------------
# [Aristotle Ethos] Credibility / credential establishment markers
# ---------------------------------------------------------------------------

_ETHOS_PATTERNS = [
    r"\bas an expert\b",
    r"\bin my experience\b",
    r"\bI have \d+ years?\b",
    r"\bmy phd\b",
    r"\bI.{0,5}ve studied\b",
    r"\bI.{0,5}ve researched\b",
    r"\bI.{0,5}m a professional\b",
    r"\bI.{0,5}m a specialist\b",
    r"\bmy background in\b",
    r"\bI.{0,5}m certified\b",
    r"\bI.{0,5}m trained\b",
    # Spanish
    r"como experto",
    r"tengo \d+ años de experiencia",
    r"con mi doctorado",
    r"mi experiencia profesional",
    r"soy especialista",
    r"estoy certificado",
    r"mi formación en",
]

# ---------------------------------------------------------------------------
# [Aristotle Pathos] Emotional manipulation markers
# ---------------------------------------------------------------------------

_PATHOS_FEAR = [
    r"\bdanger\b", r"\brisk\b", r"\bthreat\b", r"\bcatastrophe\b",
    r"\bdisaster\b", r"\bharm\b", r"\bdamage\b", r"\bcrisis\b",
    r"\bpeligro\b", r"\briesgo\b", r"\bamenaza\b", r"\bcatástrofe\b",
    r"\bdesastre\b", r"\bcrisis\b",
]

_PATHOS_GUILT = [
    r"\bdisappointed\b", r"\blet me down\b", r"\bexpected better\b",
    r"\bbetray\b", r"\bfailed me\b", r"\blet.{0,5}down\b",
    r"\bdecepcionado\b", r"\bdecepcionar\b", r"\besperaba más\b",
    r"\bme fallaste\b", r"\bme defraudaste\b",
]

_PATHOS_SYMPATHY = [
    r"\bplease\b", r"\bI beg\b", r"\bdesperate\b", r"\bdesperately\b",
    r"\bI.{0,5}m begging\b", r"\bplease help\b", r"\bI need your help\b",
    r"\bpor favor\b", r"\bnecesito tu ayuda\b", r"\bte lo ruego\b",
    r"\bdesesperado\b", r"\bte suplico\b",
]

# ---------------------------------------------------------------------------
# [Aristotle Logos] Logical / evidential markers (mitigating)
# ---------------------------------------------------------------------------

_LOGOS_PATTERNS = [
    r"\bbecause\b", r"\btherefore\b", r"\bthus\b", r"\bhence\b",
    r"\bevidence shows\b", r"\bdata indicates\b", r"\bdata shows\b",
    r"\baccording to\b", r"\bstatistics\b", r"\bstudy shows\b",
    r"\bproof\b", r"\bdemonstrates\b", r"\bconsequently\b",
    r"\bit follows that\b", r"\bwhich means\b",
    # Spanish
    r"\bporque\b", r"\bpor lo tanto\b", r"\bpor ende\b",
    r"los datos muestran", r"la evidencia indica", r"según los datos",
    r"\bdemuestran\b", r"\bconcluyendo\b", r"\bpor consiguiente\b",
]


class AristotleDetector:
    """
    [Aristotle] Detects rhetorical imbalance (pathos >> logos) as a manipulation signal.
    Pure emotional appeals with no logical backing indicate manipulative intent.
    """

    def analyze(self, text: str) -> Optional[AristotleSignal]:
        """
        Analyze text for Aristotelian rhetorical imbalance.

        Parameters
        ----------
        text : str
            The raw message text.

        Returns
        -------
        Optional[AristotleSignal]
            Detected rhetorical signal, or None if severity is zero.
        """
        text_lower = text.lower()

        evidence: list[str] = []

        # -------------------------------------------------------------------
        # [Aristotle Ethos] Count credibility claims
        # -------------------------------------------------------------------
        ethos_count = 0
        for pat in _ETHOS_PATTERNS:
            m = re.search(pat, text_lower, re.IGNORECASE)
            if m:
                ethos_count += 1
                evidence.append(f"[Ethos] '{m.group()}'")

        ethos_score = min(Fraction(ethos_count, 10), Fraction(1, 1))

        # -------------------------------------------------------------------
        # [Aristotle Pathos] Count emotional appeals
        # findall accumulates ALL matches per pattern, so "danger danger danger" = 3.
        # -------------------------------------------------------------------
        pathos_count = 0
        for pat in _PATHOS_FEAR:
            hits = re.findall(pat, text_lower, re.IGNORECASE)
            if hits:
                pathos_count += len(hits)
                evidence.append(f"[Pathos:Fear] '{hits[0]}' ×{len(hits)}")

        for pat in _PATHOS_GUILT:
            hits = re.findall(pat, text_lower, re.IGNORECASE)
            if hits:
                pathos_count += len(hits)
                evidence.append(f"[Pathos:Guilt] '{hits[0]}' ×{len(hits)}")

        for pat in _PATHOS_SYMPATHY:
            hits = re.findall(pat, text_lower, re.IGNORECASE)
            if hits:
                pathos_count += len(hits)
                evidence.append(f"[Pathos:Sympathy] '{hits[0]}' ×{len(hits)}")

        pathos_score = min(Fraction(pathos_count, 8), Fraction(1, 1))

        # -------------------------------------------------------------------
        # [Aristotle Logos] Count logical arguments (reduces suspicion)
        # -------------------------------------------------------------------
        logos_count = 0
        for pat in _LOGOS_PATTERNS:
            m = re.search(pat, text_lower, re.IGNORECASE)
            if m:
                logos_count += 1
                # Logos is legitimate — note but don't add to evidence list

        logos_score = min(Fraction(logos_count, 10), Fraction(1, 1))

        # -------------------------------------------------------------------
        # [Aristotle Imbalance] Manipulation signal
        # pathos >> logos = imbalance
        # -------------------------------------------------------------------
        if pathos_score > logos_score:
            imbalance_score = pathos_score - logos_score
        else:
            imbalance_score = Fraction(0, 1)

        # Pure emotional manipulation: pathos >> ethos + logos combined
        combined_rational = ethos_score + logos_score
        if pathos_score > combined_rational:
            evidence.append(
                f"[Imbalance] Pure emotional manipulation: pathos={float(pathos_score):.2f} "
                f"> ethos+logos={float(combined_rational):.2f}"
            )

        # Severity is the imbalance, but only if pathos exceeds threshold
        if pathos_score > Fraction(1, 3):
            severity = imbalance_score
        else:
            severity = Fraction(0, 1)

        # [Aristotle Hollow Ethos] Credential claims with zero logical backing
        # "As an expert..." without any because/therefore/data → credential fraud signal
        if ethos_score > Fraction(0) and logos_score == Fraction(0) and pathos_score == Fraction(0):
            hollow_sev = min(ethos_score, Fraction(2, 5))
            severity = max(severity, hollow_sev)
            evidence.append(
                f"[Hollow Ethos] Credential claims (ethos={float(ethos_score):.2f}) "
                "with no logical backing — unsupported authority assertion."
            )

        if severity == Fraction(0, 1):
            return None

        return AristotleSignal(
            ethos_score=ethos_score,
            pathos_score=pathos_score,
            logos_score=logos_score,
            imbalance_score=imbalance_score,
            evidence=evidence,
        )
