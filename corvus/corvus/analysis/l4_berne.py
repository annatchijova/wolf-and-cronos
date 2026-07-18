"""
L4 — Berne Transactional Analysis Detector
Theoretical framework: Eric Berne's Transactional Analysis (1964).
  Ego states:    Parent (Critical/Nurturing), Adult, Child (Adaptive/Rebellious)
  Transactions:  Complementary, Crossed, Ulterior
Ulterior transactions are the primary manipulation signal — surface message ≠ subtext.
"""

import re
from fractions import Fraction
from typing import Optional

from corvus.models import BerneSignal


# ---------------------------------------------------------------------------
# [Berne] Ego state markers
# ---------------------------------------------------------------------------

_PARENT_CRITICAL = [
    r"\byou should\b", r"\byou must\b", r"\byou always\b", r"\byou never\b",
    r"\bhow could you\b", r"\byou have to\b", r"\byou ought to\b",
    r"\byou.{0,10}re supposed to\b", r"\bdon.{0,3}t you dare\b",
    # Spanish
    r"\bdeberías\b", r"\btenés que\b", r"\btienes que\b",
    r"\bsiempre hacés\b", r"\bnunca hacés\b", r"\bcómo pudiste\b",
    r"\bcómo podías\b", r"\bjamás deberías\b",
]

_PARENT_NURTURING = [
    r"\blet me take care of\b", r"\bpoor you\b", r"\bI.{0,5}ll handle it\b",
    r"\bdon.{0,3}t worry.{0,10}I.{0,5}ll\b", r"\bI.{0,5}m here for you\b",
    r"\blet me help you\b", r"\bI.{0,5}ll take care\b",
    r"\bpoor thing\b", r"\byou.{0,5}re not alone\b",
    # Spanish
    r"\bdejame ayudarte\b", r"\bpobrecito\b", r"\byo me encargo\b",
    r"\bno te preocupes.{0,15}yo\b", r"\bte cuido\b", r"\bme hago cargo\b",
]

_CHILD_ADAPTIVE = [
    r"\bwhatever you say\b", r"\bif you think so\b",
    r"\bI.{0,5}ll do whatever\b", r"\byou.{0,5}re probably right\b",
    r"\bas you wish\b", r"\bif that.{0,5}s what you want\b",
    r"\bof course.{0,20}whatever\b",
    # Spanish
    r"\blo que vos digas\b", r"\bsi te parece\b", r"\bcomo digas\b",
    r"\blo que quieras\b", r"\bcomo vos quieras\b",
]

_CHILD_REBELLIOUS = [
    r"\bI don.{0,3}t care\b", r"\bwhatever\b", r"\bnot my problem\b",
    r"\byou can.{0,3}t make me\b", r"\bI.{0,5}ll do what I want\b",
    r"\bback off\b", r"\bleave me alone\b",
    # Spanish
    r"\bno me importa\b", r"\bno es mi problema\b", r"\bque se yo\b",
    r"\bhacé lo que quieras\b",
]

# [Berne Ulterior] Polite surface concealing sensitive request
# Includes simple "please" / "can you" — safe because ULTERIOR only fires
# when BOTH polite surface AND sensitive action are present in the same message.
_ULTERIOR_POLITE = [
    r"\bplease\b", r"\bcan you\b", r"\bcould you\b", r"\bwould you\b",
    r"\bcould you perhaps\b", r"\bwould you mind\b", r"\bI wonder if you could\b",
    r"\bmight you be able\b", r"\bif it.{0,10}s not too much trouble\b",
    r"\bwhen you get a chance\b", r"\bif you have a moment\b",
    # Spanish
    r"\bpor favor\b", r"\bpodrías\b", r"\bpodrías quizás\b",
    r"\bte molestaría\b", r"\bsi no es mucha molestia\b",
    r"\bcuando tengas un momento\b",
]

_SENSITIVE_ACTIONS = [
    r"\bshare.{0,20}access\b", r"\bshare.{0,20}password\b",
    r"\bshare.{0,20}credentials\b", r"\bshare.{0,20}admin\b",
    r"\bsend.{0,20}password\b", r"\bsend.{0,20}credentials\b",
    r"\bsend.{0,20}token\b",
    r"\bgive.{0,20}credentials\b", r"\bgive.{0,20}password\b",
    r"\bgive.{0,20}access\b",
    r"\bprovide.{0,20}token\b", r"\bprovide.{0,20}credentials\b",
    r"\btransfer.{0,20}funds\b", r"\bsend.{0,20}money\b",
    r"\bwire.{0,20}transfer\b",
    r"\bbypass.{0,20}security\b", r"\bdisable.{0,20}two.factor\b",
    r"\bshare.{0,20}screen\b", r"\binstall.{0,20}software\b",
    r"\bclick.{0,20}link\b", r"\bopen.{0,20}attachment\b",
    # Spanish
    r"\bcompartí.{0,20}acceso\b", r"\bcompartí.{0,20}contraseña\b",
    r"\bmandame.{0,20}contraseña\b", r"\benvíame.{0,20}credenciales\b",
    r"\btransferí.{0,20}dinero\b",
]

# [Berne Crossed] Previous adult context → current critical parent or rebellious child
_ADULT_INDICATORS = [
    r"\baccording to\b", r"\bthe data\b", r"\bthe report\b",
    r"\bI checked\b", r"\banalysis shows\b", r"\bstatistics\b",
    r"\bpor los datos\b", r"\bel informe\b", r"\bverifiqué\b",
]


# ---------------------------------------------------------------------------
# Precompile all regex patterns at module load — not per-message call.
# (same optimisation applied to L2; _C suffix = compiled version)
# ---------------------------------------------------------------------------
_PARENT_CRITICAL_C   = [re.compile(rx, re.IGNORECASE) for rx in _PARENT_CRITICAL]
_PARENT_NURTURING_C  = [re.compile(rx, re.IGNORECASE) for rx in _PARENT_NURTURING]
_CHILD_ADAPTIVE_C    = [re.compile(rx, re.IGNORECASE) for rx in _CHILD_ADAPTIVE]
_CHILD_REBELLIOUS_C  = [re.compile(rx, re.IGNORECASE) for rx in _CHILD_REBELLIOUS]
_ULTERIOR_POLITE_C   = [re.compile(rx, re.IGNORECASE) for rx in _ULTERIOR_POLITE]
_SENSITIVE_ACTIONS_C = [re.compile(rx, re.IGNORECASE) for rx in _SENSITIVE_ACTIONS]
_ADULT_INDICATORS_C  = [re.compile(rx, re.IGNORECASE) for rx in _ADULT_INDICATORS]


def _detect_ego_state(text_lower: str) -> str:
    """Classify the primary ego state of this message."""
    # Check states in priority order — use precompiled patterns
    critical_hits   = sum(1 for rx in _PARENT_CRITICAL_C   if rx.search(text_lower))
    nurturing_hits  = sum(1 for rx in _PARENT_NURTURING_C  if rx.search(text_lower))
    adaptive_hits   = sum(1 for rx in _CHILD_ADAPTIVE_C    if rx.search(text_lower))
    rebellious_hits = sum(1 for rx in _CHILD_REBELLIOUS_C  if rx.search(text_lower))

    scores = {
        "PARENT_CRITICAL": critical_hits,
        "PARENT_NURTURING": nurturing_hits,
        "CHILD_ADAPTIVE": adaptive_hits,
        "CHILD_REBELLIOUS": rebellious_hits,
    }
    max_score = max(scores.values())
    if max_score == 0:
        return "ADULT"
    # Return highest-scoring state
    return max(scores, key=lambda k: scores[k])


class BerneDetector:
    """
    [Berne] Detects transactional analysis patterns.
    Primary signal: ULTERIOR transactions (surface vs. subtext mismatch).
    """

    def analyze(
        self, text: str, conversation_history: list[str]
    ) -> Optional[BerneSignal]:
        """
        Analyze text for Berne transactional patterns.

        Parameters
        ----------
        text : str
            The raw message text.
        conversation_history : list[str]
            Recent prior messages in the conversation (oldest first).

        Returns
        -------
        Optional[BerneSignal]
            Detected transactional pattern, or None if severity is zero.
        """
        text_lower = text.lower()
        evidence: list[str] = []

        ego_state = _detect_ego_state(text_lower)
        transaction_type = "COMPLEMENTARY"
        severity = Fraction(0, 1)

        # -------------------------------------------------------------------
        # [Berne ULTERIOR] Polite wording + request for sensitive action
        # Surface says "could you perhaps…" but subtext requests credentials/funds
        # -------------------------------------------------------------------
        has_polite_surface   = any(rx.search(text_lower) for rx in _ULTERIOR_POLITE_C)
        has_sensitive_action = any(rx.search(text_lower) for rx in _SENSITIVE_ACTIONS_C)

        if has_polite_surface and has_sensitive_action:
            transaction_type = "ULTERIOR"
            severity = max(severity, Fraction(3, 5))
            evidence.append(
                "[Berne:ULTERIOR] Polite surface language concealing request for sensitive action"
            )

        # [Berne ULTERIOR] PARENT_NURTURING ego state + sensitive request
        # "Let me help you… but can you share your credentials?"
        if ego_state == "PARENT_NURTURING" and has_sensitive_action:
            transaction_type = "ULTERIOR"
            severity = max(severity, Fraction(3, 10))
            evidence.append(
                "[Berne:ULTERIOR] Nurturing Parent ego state combined with sensitive request"
            )

        # -------------------------------------------------------------------
        # [Berne CROSSED] Prior message was Adult-state; this is critical/rebellious
        # Creates unexpected escalation — sign of manipulation or destabilization
        # -------------------------------------------------------------------
        if conversation_history:
            last_msg = conversation_history[-1].lower()
            prior_was_adult = any(rx.search(last_msg) for rx in _ADULT_INDICATORS_C)
            current_is_non_adult = ego_state in ("PARENT_CRITICAL", "CHILD_REBELLIOUS")

            if prior_was_adult and current_is_non_adult:
                transaction_type = "CROSSED"
                cross_severity = (
                    Fraction(2, 5) if ego_state == "PARENT_CRITICAL"
                    else Fraction(1, 5)
                )
                severity = max(severity, cross_severity)
                evidence.append(
                    f"[Berne:CROSSED] Prior Adult transaction followed by {ego_state} — "
                    "unexpected ego state switch"
                )

        # [Berne PARENT_CRITICAL escalation pattern]
        if ego_state == "PARENT_CRITICAL" and len(conversation_history) >= 2:
            # Check if previous messages were also critical parent (escalation)
            prior_critical_count = sum(
                1 for msg in conversation_history[-3:]
                if any(rx.search(msg.lower()) for rx in _PARENT_CRITICAL_C)
            )
            if prior_critical_count >= 2:
                severity = max(severity, Fraction(2, 5))
                evidence.append(
                    "[Berne:PARENT_CRITICAL] Sustained critical parent escalation across messages"
                )

        # [Berne Standalone] Emit signal for strong ego states even without history
        # PARENT_CRITICAL and CHILD_ADAPTIVE alone are weak signals (Fraction(1,5))
        # but provide context for Peirce synthesis
        if severity == Fraction(0, 1):
            if ego_state == "PARENT_CRITICAL":
                severity = Fraction(1, 5)
                evidence.append(
                    "[Berne:PARENT_CRITICAL] Critical parent language detected — "
                    "prescriptive/judgmental tone without prior context."
                )
            elif ego_state == "CHILD_ADAPTIVE":
                severity = Fraction(1, 5)
                evidence.append(
                    "[Berne:CHILD_ADAPTIVE] Excessive compliance language — "
                    "unconditional deference may signal coerced agreement."
                )

        if severity == Fraction(0, 1):
            return None

        # Add ego state to evidence
        evidence.insert(0, f"[Berne:EgoState] {ego_state}")

        return BerneSignal(
            ego_state=ego_state,
            transaction_type=transaction_type,
            severity=severity,
            evidence=evidence,
        )
