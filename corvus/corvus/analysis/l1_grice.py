"""
L1 — Gricean Maxim Detector
Theoretical framework: Paul Grice's Cooperative Principle (1975).
Detects violations of the four conversational maxims:
  MANNER   — be clear, avoid obscurity/ambiguity
  QUANTITY — be as informative as required (no more, no less)
  QUALITY  — be truthful, avoid what you lack evidence for
  RELATION — be relevant
"""

import re
from fractions import Fraction
from typing import Optional

from corvus.models import GriceSignal, MaximViolated


# [Grice MANNER] English ambiguity hedging markers
_AMBIGUITY_EN = [
    "perhaps", "maybe", "possibly", "sort of", "more or less",
    "allegedly", "reportedly", "supposedly", "it seems",
    "one might say", "arguably",
]

# [Grice MANNER] Spanish ambiguity hedging markers
_AMBIGUITY_ES = [
    "podría", "quizás", "tal vez", "posiblemente", "en cierto modo",
    "pareciera", "según se dice", "supuestamente",
]

_ALL_AMBIGUITY = _AMBIGUITY_EN + _AMBIGUITY_ES

# [Grice QUALITY] Certainty markers (followed by hedging = contradiction)
_CERTAINTY_MARKERS = [
    r"\bdefinitely\b", r"\bcertainly\b", r"\babsolutely\b",
    r"\bwithout doubt\b", r"\bI know for a fact\b",
    r"\bdefinitivamente\b", r"\bsin duda\b", r"\bcon toda seguridad\b",
]

# [Grice QUALITY] Immediate hedging after certainty
_HEDGING_MARKERS = [
    r"\bperhaps\b", r"\bmaybe\b", r"\bpossibly\b", r"\bI think\b",
    r"\bI believe\b", r"\bquizás\b", r"\btal vez\b", r"\bcreo que\b",
]

# [Grice RELATION] Domain keywords that suggest complex topic
_DOMAIN_KEYWORDS = [
    "password", "credentials", "admin", "root", "server", "database",
    "api", "token", "certificate", "vulnerability", "exploit", "injection",
    "contraseña", "credenciales", "servidor", "base de datos", "token",
    "certificado", "vulnerabilidad", "exploit", "inyección",
    "transfer", "wire", "payment", "account number", "routing",
    "transferencia", "pago", "número de cuenta",
]

# [Grice RELATION] Compliment phrases before requests
_COMPLIMENT_PATTERNS = [
    r"\byou.{0,20}amazing\b", r"\byou.{0,20}brilliant\b",
    r"\byou.{0,20}genius\b", r"\byou.{0,20}best\b",
    r"\bgreat work\b", r"\bexcellent job\b", r"\bwonderful\b",
    r"\bsos.{0,10}increíble\b", r"\bsos.{0,10}genial\b",
    r"\bqué bueno\b", r"\bexcelente trabajo\b",
]

# [Grice RELATION] Request indicators
_REQUEST_PATTERNS = [
    r"\bcould you\b", r"\bcan you\b", r"\bwould you\b", r"\bplease\b",
    r"\bI need\b", r"\bsend me\b", r"\bshare\b",
    r"\bpodrías\b", r"\bnecesito\b", r"\benvíame\b", r"\bcompartí\b",
]


class GriceDetector:
    """
    [Grice] Detects violations of Grice's Cooperative Principle.
    Returns the single most severe maxim violation, or None if below threshold.
    """

    def analyze(self, text: str, user_baseline: dict) -> Optional[GriceSignal]:
        """
        Analyze text for Gricean maxim violations.

        Parameters
        ----------
        text : str
            The raw message text.
        user_baseline : dict
            Per-user behavioral baseline from MemoryEngine.

        Returns
        -------
        Optional[GriceSignal]
            The most severe violation found, or None if below detection threshold.
        """
        text_lower = text.lower()
        words = text_lower.split()
        word_count = max(len(words), 1)

        signals: list[tuple[Fraction, GriceSignal]] = []

        # --- MANNER check ---
        manner_signal = self._check_manner(text, text_lower, words, word_count)
        if manner_signal is not None:
            signals.append((manner_signal.severity, manner_signal))

        # --- QUANTITY check ---
        quantity_signal = self._check_quantity(text, text_lower, words, word_count)
        if quantity_signal is not None:
            signals.append((quantity_signal.severity, quantity_signal))

        # --- QUALITY check ---
        quality_signal = self._check_quality(text, text_lower, words, word_count)
        if quality_signal is not None:
            signals.append((quality_signal.severity, quality_signal))

        # --- RELATION check ---
        relation_signal = self._check_relation(text, text_lower, words, word_count)
        if relation_signal is not None:
            signals.append((relation_signal.severity, relation_signal))

        if not signals:
            return None

        # Return the most severe violation
        signals.sort(key=lambda x: x[0], reverse=True)
        best = signals[0][1]
        # Only surface if severity is meaningful
        if best.severity == Fraction(0, 1):
            return None
        return best

    # ------------------------------------------------------------------
    # Private: MANNER
    # ------------------------------------------------------------------

    def _check_manner(
        self, text: str, text_lower: str, words: list[str], word_count: int
    ) -> Optional[GriceSignal]:
        """
        [Grice MANNER] Detect deliberate obfuscation via high Fog Index or
        ambiguity marker density.
        """
        fog = self._gunning_fog(text, words)

        # Count ambiguity markers
        amb_count = 0
        for marker in _ALL_AMBIGUITY:
            amb_count += len(re.findall(r"\b" + re.escape(marker) + r"\b", text_lower))

        amb_density = Fraction(amb_count, word_count)

        fog_excess = max(0.0, fog - 16.0)
        fog_severity = Fraction(int(fog_excess * 100), 2000)  # int numerator only
        amb_severity = Fraction(amb_count, 100)
        severity = min(fog_severity + amb_severity, Fraction(1, 1))

        triggered = fog > 16 or amb_density > Fraction(5, 100)

        if not triggered or severity == Fraction(0, 1):
            return None

        evidence_parts = []
        if fog > 16:
            evidence_parts.append(f"Gunning Fog Index {fog:.1f} (threshold 16)")
        if amb_density > Fraction(5, 100):
            evidence_parts.append(
                f"Ambiguity density {float(amb_density):.3f} ({amb_count} markers in {word_count} words)"
            )

        return GriceSignal(
            maxim=MaximViolated.MANNER,
            severity=severity,
            evidence="; ".join(evidence_parts),
            fog_index=fog,
            ambiguity_density=amb_density,
        )

    # ------------------------------------------------------------------
    # Private: QUANTITY
    # ------------------------------------------------------------------

    def _check_quantity(
        self, text: str, text_lower: str, words: list[str], word_count: int
    ) -> Optional[GriceSignal]:
        """
        [Grice QUANTITY] Detect padding (over-informing) or omission (under-informing).
        """
        evidence_parts = []
        severity = Fraction(0, 1)

        # Padding: repeated bigrams > 15% of total bigrams
        if word_count >= 4:
            bigrams: list[tuple[str, str]] = [
                (words[i], words[i + 1]) for i in range(len(words) - 1)
            ]
            unique_bigrams = set(bigrams)
            repeated = len(bigrams) - len(unique_bigrams)
            total_bigrams = max(len(bigrams), 1)
            padding_ratio = Fraction(repeated, total_bigrams)
            if padding_ratio > Fraction(15, 100):
                # padding_ratio is already an exact Fraction — quantize with
                # Fraction arithmetic. Detouring through float (int(float(pr)*100))
                # can drop a percentage point (e.g. 29/50 -> 57/100) and makes the
                # sealed score depend on double rounding, violating the zero-float
                # decision-path invariant.
                severity = max(severity, Fraction(int(padding_ratio * 100), 100))
                evidence_parts.append(
                    f"Repeated bigram ratio {float(padding_ratio):.2f} (padding)"
                )

        # Omission: < 20 words but references a complex/sensitive topic
        if word_count < 20:
            domain_hits = sum(
                1
                for kw in _DOMAIN_KEYWORDS
                if kw in text_lower
            )
            if domain_hits > 0:
                sev = Fraction(domain_hits, 5)
                sev = min(sev, Fraction(1, 1))
                severity = max(severity, sev)
                evidence_parts.append(
                    f"Only {word_count} words but references {domain_hits} domain keyword(s) (omission)"
                )

        if severity == Fraction(0, 1) or not evidence_parts:
            return None

        return GriceSignal(
            maxim=MaximViolated.QUANTITY,
            severity=severity,
            evidence="; ".join(evidence_parts),
        )

    # ------------------------------------------------------------------
    # Private: QUALITY
    # ------------------------------------------------------------------

    def _check_quality(
        self, text: str, text_lower: str, words: list[str], word_count: int
    ) -> Optional[GriceSignal]:
        """
        [Grice QUALITY] Detect internal contradictions: certainty followed by hedging,
        or negation/assertion of the same concept within 50 characters.
        """
        evidence_parts = []
        severity = Fraction(0, 1)

        # Pattern 1: negation + assertion within 50 chars
        # Detect "not X" then "X" (same root word) nearby
        negation_re = re.compile(r"\bnot\s+(\w+)", re.IGNORECASE)
        neg_matches = list(negation_re.finditer(text_lower))
        for neg_match in neg_matches:
            negated_word = neg_match.group(1)
            # Look for the same word within 50 chars after the negation
            start = neg_match.end()
            snippet = text_lower[start : start + 50]
            if re.search(r"\b" + re.escape(negated_word) + r"\b", snippet):
                severity = max(severity, Fraction(2, 5))
                evidence_parts.append(
                    f"Contradiction: 'not {negated_word}' followed by '{negated_word}' within 50 chars"
                )

        # Pattern 2: certainty marker immediately followed by hedging marker (within 60 chars)
        for cert_pat in _CERTAINTY_MARKERS:
            cert_re = re.compile(cert_pat, re.IGNORECASE)
            for cert_match in cert_re.finditer(text_lower):
                end = cert_match.end()
                window = text_lower[end : end + 60]
                for hedge_pat in _HEDGING_MARKERS:
                    if re.search(hedge_pat, window, re.IGNORECASE):
                        severity = max(severity, Fraction(3, 10))
                        evidence_parts.append(
                            f"Certainty marker '{cert_match.group()}' immediately followed by hedging"
                        )
                        break

        if severity == Fraction(0, 1) or not evidence_parts:
            return None

        return GriceSignal(
            maxim=MaximViolated.QUALITY,
            severity=severity,
            evidence="; ".join(evidence_parts),
        )

    # ------------------------------------------------------------------
    # Private: RELATION
    # ------------------------------------------------------------------

    def _check_relation(
        self, text: str, text_lower: str, words: list[str], word_count: int
    ) -> Optional[GriceSignal]:
        """
        [Grice RELATION] Detect tactical irrelevance: off-topic compliments before
        a request, or topic drift within the same message.
        """
        evidence_parts = []
        severity = Fraction(0, 1)

        # Pattern 1: off-topic compliment followed by a request in the same message
        has_compliment = any(
            re.search(pat, text_lower, re.IGNORECASE) for pat in _COMPLIMENT_PATTERNS
        )
        has_request = any(
            re.search(pat, text_lower, re.IGNORECASE) for pat in _REQUEST_PATTERNS
        )
        has_domain = any(kw in text_lower for kw in _DOMAIN_KEYWORDS)

        if has_compliment and has_request and has_domain:
            severity = max(severity, Fraction(4, 10))
            evidence_parts.append(
                "Off-topic compliment + sensitive request in same message (relationship irrelevance)"
            )
        elif has_compliment and has_request:
            severity = max(severity, Fraction(2, 10))
            evidence_parts.append("Compliment immediately preceding a request")

        # Pattern 2: topic drift — first half keywords vs second half keywords
        # P2 fix: remove stopwords before computing Jaccard to avoid
        # function words inflating apparent overlap between unrelated topics.
        _JACCARD_STOPWORDS = frozenset({
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "i", "you", "he", "she", "it", "we", "they",
            "this", "that", "these", "those", "and", "or", "but", "in",
            "on", "at", "to", "of", "for", "with", "by", "from", "as",
            "into", "than", "so", "if", "then", "also", "just", "not",
            # ES
            "el", "la", "los", "las", "un", "una", "de", "en", "y", "o",
            "es", "son", "fue", "era", "que", "se", "lo", "le", "me", "te",
            "nos", "al", "del", "por", "con", "para", "sin", "sobre",
        })
        if word_count >= 20:
            # Normalize: strip punctuation from tokens before stopword filtering
            # "hello," and "hello" are the same word — raw split leaves punctuation attached
            normalized = [re.sub(r"[^\w]", "", w.lower()) for w in words]
            content = [w for w in normalized if w and w not in _JACCARD_STOPWORDS]
            if len(content) >= 10:
                mid = len(content) // 2
                first_half = set(content[:mid])
                second_half = set(content[mid:])
                overlap = len(first_half & second_half)
                union = len(first_half | second_half)
                if union > 0:
                    jaccard = Fraction(overlap, union)
                    if jaccard < Fraction(2, 10):  # < 20% shared content vocab = drift
                        severity = max(severity, Fraction(2, 10))
                        evidence_parts.append(
                            f"Topic drift: only {float(jaccard):.0%} vocabulary overlap between halves"
                        )

        if severity == Fraction(0, 1) or not evidence_parts:
            return None

        return GriceSignal(
            maxim=MaximViolated.RELATION,
            severity=severity,
            evidence="; ".join(evidence_parts),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_syllables(word: str) -> int:
        """
        Approximate syllable count using vowel-cluster method, bilingual EN/ES.

        Each run of consecutive vowels = 1 syllable.
        EN: silent trailing 'e' is subtracted (make→1, have→1).
        ES: trailing 'e' is NOT silent (cafe→2, ante→2) — no subtraction.
        Language guessed by presence of Spanish diacritics.
        Minimum 1 syllable per non-empty word.

        Accuracy vs len>8:
          "strengths" (EN, 10 chars) → 1 syl  ✓ (was counted as complex before)
          "education" (EN, 9 chars)  → 4 syl  ✓
          "educación" (ES, 9 chars)  → 4 syl  ✓ (accented vowels now counted)
        """
        # Normalize: strip non-alpha, lowercase, preserve accented chars
        w = re.sub(r"[^a-zA-ZáéíóúüñÁÉÍÓÚÜÑàèìòùÀÈÌÒÙ]", "", word).lower()
        if not w:
            return 0

        # Detect Spanish by diacritics so we know whether 'e' is silent
        _ES_DIACRITICS = re.compile(r"[áéíóúüñàèìòùÀÈÌÒÙ]")
        is_spanish = bool(_ES_DIACRITICS.search(w))

        # Expand accented vowels so the cluster regex picks them up
        _VOWEL_RE = re.compile(r"[aeiouyáéíóúüàèìòù]+")
        count = len(_VOWEL_RE.findall(w))

        # EN only: subtract silent trailing 'e' (e.g. "make", "time", "have")
        if not is_spanish and w.endswith("e") and count > 1:
            count -= 1

        return max(count, 1)

    def _gunning_fog(self, text: str, words: list[str]) -> float:
        """
        [Grice MANNER] Gunning Fog Index.
        fog = 0.4 * (avg_sentence_length + 100 * complex_word_ratio)
        Complex words = polysyllabic words with ≥ 3 syllables (Gunning definition).
        Uses vowel-cluster syllable counting instead of raw character length.
        """
        sentences = re.split(r"[.!?]+", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = max(len(sentences), 1)
        word_count = max(len(words), 1)
        avg_sentence_length = word_count / sentence_count

        # Gunning Fog: complex = words with ≥ 3 syllables
        complex_count = sum(
            1 for w in words if self._count_syllables(w) >= 3
        )
        complex_ratio = complex_count / word_count

        fog = 0.4 * (avg_sentence_length + 100 * complex_ratio)
        return fog
