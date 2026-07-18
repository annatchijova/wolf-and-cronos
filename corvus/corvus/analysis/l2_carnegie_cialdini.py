"""
L2 — Carnegie/Cialdini Influence Detector
Theoretical frameworks:
  - Dale Carnegie: "How to Win Friends and Influence People" (1936)
  - Robert Cialdini: "Influence: The Psychology of Persuasion" (1984)
Detects social influence tactics used to manipulate behavior.
"""

import re
from fractions import Fraction
from typing import Optional

from corvus.models import InfluenceSignal


# ---------------------------------------------------------------------------
# [Carnegie] Pattern definitions
# ---------------------------------------------------------------------------

_CARNEGIE_PATTERNS: dict[str, list[str]] = {
    "flattery": [
        r"\bonly you\b",
        r"\byour expertise\b",
        r"\bnobody else\b",
        r"\byou.{0,10}best\b",
        r"\byou.{0,10}re the best\b",
        r"un modelo de tu calibre",
        r"sos el único",
        r"solo vos podés",
        r"nadie más que vos",
        r"tu nivel",
    ],
    "emotional_urgency": [
        r"\burgent\b",
        r"\blife depends\b",
        r"\bno one else can help\b",
        r"\bI.{0,5}m desperate\b",
        r"es urgente",
        r"\bdesesperado\b",
        r"\bnecesito que\b",
        r"\bcritical.{0,20}now\b",
        r"\bimmediately\b",
        r"\bright now\b",
    ],
    "lesser_evil": [
        r"\bjust theory\b",
        r"\bhypothetically\b",
        r"\bwithout the details\b",
        r"\bjust the concept\b",
        r"\bin theory\b",
        r"en teoría",
        r"sin los detalles peligrosos",
        r"solo el concepto",
        r"hipotéticamente",
        r"teóricamente",
    ],
    "false_familiarity": None,  # Handled separately due to compound logic
    "gradual_escalation": None,  # Handled separately via conversation history
}

# [Carnegie] Intimacy address markers (false familiarity component)
_INTIMACY_MARKERS = [
    r"\bbuddy\b", r"\bfriend\b", r"\bmate\b", r"\bamigo\b",
    r"\bche\b", r"\bviejo\b", r"\bpal\b", r"\bbrother\b",
    r"\bbro\b", r"\bhermano\b", r"\bcompa\b",
]

# [Carnegie] Sensitive topic references (false familiarity component)
_SENSITIVE_REFS = [
    r"\bpassword\b", r"\bcredentials\b", r"\badmin\b", r"\broot\b",
    r"\btransfer\b", r"\bcontraseña\b", r"\baccess\b", r"\btoken\b",
    r"\bssh\b", r"\bapi key\b", r"\bsecret\b", r"\bclave\b",
    r"\bcredenciales\b", r"\bacceso\b", r"\btoken\b",
]


# ---------------------------------------------------------------------------
# [Cialdini] Principle definitions
# ---------------------------------------------------------------------------

_CIALDINI_PATTERNS: dict[str, list[str]] = {
    "RECIPROCITY": [
        r"\bI helped you\b",
        r"\bI did.{0,10}for you\b",
        r"\bafter everything I.{0,5}ve done\b",
        r"te ayudé",
        r"hice.{0,10}por vos",
        r"hice.{0,10}por ti",
        r"\bI.{0,5}ve done so much\b",
        r"\bremember when I\b",
    ],
    "COMMITMENT": [
        r"\byou agreed\b",
        r"\byou said you would\b",
        r"\bas we discussed\b",
        r"\byou promised\b",
        r"como acordamos",
        r"dijiste que",
        r"prometiste que",
        r"\byou committed\b",
        r"\bwe agreed\b",
    ],
    "SOCIAL_PROOF": [
        r"\beveryone is doing\b",
        r"\bthe whole team\b",
        r"\bothers have already\b",
        r"\beverybody\b.{0,20}\bdoes\b",
        r"todos están haciendo",
        r"el equipo ya",
        r"todo el mundo",
        r"\bmost people\b",
        r"\bcommon practice\b",
        r"\bstandard procedure\b",
    ],
    "AUTHORITY": [
        r"\bas the .{0,20}manager\b",
        r"\bper.{0,15}policy\b",
        r"\bregulations require\b",
        r"\bmanagement requires\b",
        r"\bper.{0,10}protocol\b",
        r"\bper.{0,10}procedure\b",
        r"\byou are required\b",
        r"\byou must comply\b",
        r"\bpolicy requires\b",
        r"\bpolicy states\b",
        r"como gerente",
        r"la política dice",
        r"el reglamento",
        r"\bIT department\b",
        r"\bsecurity team\b",
        r"\bHR requires\b",
        r"\bcompliancy\b",
        r"\bcompliance requires\b",
    ],
    "LIKING": None,  # Handled via conversation history (rapport-building then ask)
    "SCARCITY": [
        r"\bexpires today\b",
        r"\blast chance\b",
        r"\blimited time\b",
        r"\bnow or never\b",
        r"\bact now\b",
        r"\bdon.{0,3}t miss\b",
        r"vence hoy",
        r"última oportunidad",
        r"ahora o nunca",
        r"\bdeadline.{0,10}today\b",
        r"\bdeadline.{0,10}tomorrow\b",
        r"\btime.sensitive\b",
        r"\btime sensitive\b",
    ],
}

# Score weights
_CARNEGIE_WEIGHT = Fraction(15, 100)   # per pattern
_CIALDINI_WEIGHT = Fraction(12, 100)   # per principle

# ---------------------------------------------------------------------------
# Precompile all regex patterns at module load time — not per-message call.
# Each message was previously triggering re.compile() for ~40 patterns.
# ---------------------------------------------------------------------------
_CARNEGIE_COMPILED: dict[str, list] = {
    name: [re.compile(rx, re.IGNORECASE) for rx in patterns]
    for name, patterns in _CARNEGIE_PATTERNS.items()
    if patterns is not None
}

_CIALDINI_COMPILED: dict[str, list] = {
    name: [re.compile(rx, re.IGNORECASE) for rx in patterns]
    for name, patterns in _CIALDINI_PATTERNS.items()
    if patterns is not None
}

_INTIMACY_COMPILED = [re.compile(rx, re.IGNORECASE) for rx in _INTIMACY_MARKERS]
_SENSITIVE_COMPILED = [re.compile(rx, re.IGNORECASE) for rx in _SENSITIVE_REFS]


class InfluenceDetector:
    """
    [Carnegie/Cialdini] Detects social influence and manipulation tactics.
    Scans for Carnegie persuasion patterns and Cialdini's six principles.
    """

    def analyze(
        self,
        text: str,
        conversation_history: list[str],
        user_baseline: dict,
    ) -> Optional[InfluenceSignal]:
        """
        Analyze text for influence and manipulation patterns.

        Parameters
        ----------
        text : str
            The raw message text.
        conversation_history : list[str]
            Recent prior messages in the conversation (oldest first).
        user_baseline : dict
            Per-user behavioral baseline.

        Returns
        -------
        Optional[InfluenceSignal]
            Detected influence patterns, or None if score is zero.
        """
        text_lower = text.lower()

        carnegie_found: list[str] = []
        cialdini_found: list[str] = []
        evidence: list[str] = []

        # -------------------------------------------------------------------
        # [Carnegie] Check pattern-matched tactics
        # -------------------------------------------------------------------
        for pattern_name, regexes in _CARNEGIE_COMPILED.items():
            for rx in regexes:
                m = rx.search(text_lower)
                if m:
                    if pattern_name not in carnegie_found:
                        carnegie_found.append(pattern_name)
                    evidence.append(f"[Carnegie:{pattern_name}] matched '{m.group()}'")
                    break

        # [Carnegie] False familiarity: intimacy address + sensitive topic in same message
        has_intimacy = any(rx.search(text_lower) for rx in _INTIMACY_COMPILED)
        has_sensitive = any(rx.search(text_lower) for rx in _SENSITIVE_COMPILED)
        if has_intimacy and has_sensitive:
            carnegie_found.append("false_familiarity")
            evidence.append("[Carnegie:false_familiarity] intimate address combined with sensitive topic")

        # [Carnegie] Gradual escalation via conversation history
        # P1 fix: measure word count, not character count, to avoid URL inflation.
        # A short message + long URL would falsely trigger on char length.
        if len(conversation_history) >= 2:
            prior_word_counts = [
                len(m.split()) for m in conversation_history[:-1] if m.split()
            ]
            if prior_word_counts:
                avg_prior_words = sum(prior_word_counts) / len(prior_word_counts)
                current_words = len(text.split())
                if avg_prior_words > 0 and (current_words / avg_prior_words) > 2.5:
                    carnegie_found.append("gradual_escalation")
                    evidence.append(
                        f"[Carnegie:gradual_escalation] message {current_words} words is "
                        f"{current_words / avg_prior_words:.1f}x avg of "
                        f"{avg_prior_words:.0f} prior words"
                    )

        # -------------------------------------------------------------------
        # [Cialdini] Check six principles
        # -------------------------------------------------------------------
        for principle, regexes in _CIALDINI_COMPILED.items():
            for rx in regexes:
                m = rx.search(text_lower)
                if m:
                    if principle not in cialdini_found:
                        cialdini_found.append(principle)
                    evidence.append(f"[Cialdini:{principle}] matched '{m.group()}'")
                    break

        # [Cialdini] LIKING: sustained rapport-building (no ask) then a request.
        # P1 fix: history is channel-level, not per-user. We cannot reliably
        # attribute rapport to the current sender. Only fire LIKING when the
        # current message itself contains both rapport markers AND a request —
        # i.e., "Hey, you're great! Could you share your password?" in one message.
        _RAPPORT_MARKERS = re.compile(
            r"\byou.{0,20}great\b|\byou.{0,20}amazing\b|\byou.{0,20}the best\b"
            r"|\bI.{0,10}appreciate\b|\bI.{0,10}admire\b"
            r"|\bvos.{0,20}genial\b|\bsos.{0,20}increíble\b",
            re.IGNORECASE,
        )
        _REQUEST_MARKERS = re.compile(
            r"\bcould you\b|\bcan you\b|\bwould you\b|\bsend me\b"
            r"|\bnecesito\b|\bpodrías\b|\bme mandás\b",
            re.IGNORECASE,
        )
        if _RAPPORT_MARKERS.search(text_lower) and _REQUEST_MARKERS.search(text_lower):
            cialdini_found.append("LIKING")
            evidence.append(
                "[Cialdini:LIKING] rapport markers co-occurring with explicit request "
                "within same message — intra-message liking strategy"
            )

        # -------------------------------------------------------------------
        # Score computation
        # -------------------------------------------------------------------
        score = (
            _CARNEGIE_WEIGHT * len(carnegie_found)
            + _CIALDINI_WEIGHT * len(cialdini_found)
        )
        score = min(score, Fraction(1, 1))

        if score == Fraction(0, 1):
            return None

        return InfluenceSignal(
            carnegie_patterns=carnegie_found,
            cialdini_triggers=cialdini_found,
            severity=score,
            evidence=evidence,
        )
