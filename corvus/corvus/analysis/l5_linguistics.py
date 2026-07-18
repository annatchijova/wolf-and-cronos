"""
L5 — Linguistic Analysis Detector
Theoretical frameworks:
  SDA-NR  — Syntactic-Discursive Analysis via Nominalization/Register
  CLI     — Cognitive Load Indicators
  ROI     — Readability/Obfuscation Index (Gunning Fog)
  GCI-Zipf — Galton-Cattell Index for calculated (non-random) error patterns

Key insight: high nominalization (noun/verb ratio) signals register shifts
that may indicate scripted, non-authentic communication.
"""

import re
import math
from fractions import Fraction
from typing import Optional

from corvus.models import LinguisticSignal


# ---------------------------------------------------------------------------
# [SDA-NR] Nominalization proxies (noun suffixes)
# ---------------------------------------------------------------------------

_NOUN_SUFFIXES_EN = (
    "tion", "sion", "ment", "ness", "ity", "ance", "ence",
    "ism", "ist", "ship", "hood",
)
_NOUN_SUFFIXES_ES = (
    "ción", "sión", "miento", "idad", "dad", "anza", "encia",
    "ismo", "ista",
)

# [SDA-NR] Verb proxies (common verbs + morphological markers)
_COMMON_VERBS_EN = {
    "is", "are", "was", "were", "will", "have", "has", "do", "does",
    "did", "get", "make", "take", "go", "come", "see", "know", "need",
    "want", "say", "tell", "give", "use", "find", "think", "feel",
    "look", "let", "put", "keep", "hold", "bring", "help", "ask",
    "seem", "show", "try", "call", "work", "move", "live", "run",
    "believe", "consider", "provide", "require", "ensure", "allow",
}
_COMMON_VERBS_ES = {
    "es", "son", "fue", "era", "será", "tiene", "hace", "va", "viene",
    "puede", "debe", "quiere", "sabe", "dice", "da", "toma", "pone",
    "ser", "estar", "tener", "hacer", "poder", "querer", "saber",
    "dar", "ver", "ir", "venir", "llevar", "dejar", "seguir",
    "encontrar", "llamar", "creer", "pensar", "parece",
}

# ---------------------------------------------------------------------------
# [CLI] Cognitive Load Indicator markers
# ---------------------------------------------------------------------------

_EXCLUSION_MARKERS = [
    r"\bnot\b", r"\bnever\b", r"\bnobody\b", r"\bnothing\b",
    r"\bno one\b", r"\bnone\b", r"\bwithout\b", r"\babsence\b",
    # Spanish
    r"\bnadie\b", r"\bnunca\b", r"\bnada\b", r"\bsin\b", r"\bjamás\b",
]

_CERTAINTY_MARKERS = [
    r"\bdefinitely\b", r"\bcertainly\b", r"\babsolutely\b",
    r"\bwithout doubt\b", r"\bI know\b", r"\bbeyond question\b",
    r"\bno question\b", r"\bfor sure\b", r"\bundoubtedly\b",
    # Spanish
    r"\bdefinitivamente\b", r"\bsin duda\b", r"\babsolutamente\b",
    r"\bcon certeza\b", r"\bseguramente\b",
]

_DISTANCING_MARKERS = [
    r"\bthey say\b", r"\breportedly\b", r"\ballegedly\b",
    r"\bit is said\b", r"\bapparently\b", r"\bsupposedly\b",
    r"\bI.{0,5}ve heard\b",
    # Spanish
    r"\bse dice\b", r"\bsegún dicen\b", r"\bsupuestamente\b",
    r"\bapparentemente\b", r"\bdicen que\b", r"\bse rumorea\b",
]

# ---------------------------------------------------------------------------
# [GCI-Zipf] Basic common word list for "error" detection
# ---------------------------------------------------------------------------

_COMMON_EN_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "as", "is", "was", "are",
    "were", "be", "been", "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "that", "this", "these", "those", "it", "its", "he", "she", "they",
    "we", "you", "i", "me", "him", "her", "us", "them", "my", "your",
    "his", "their", "our", "what", "which", "who", "how", "when",
    "where", "why", "not", "no", "yes", "so", "if", "then", "there",
    "here", "all", "any", "some", "more", "most", "other", "than",
    "just", "also", "about", "up", "out", "into", "over", "after",
    "time", "way", "work", "life", "world", "new", "good", "first",
    "last", "long", "great", "little", "own", "right", "old", "big",
    "high", "different", "small", "large", "next", "early", "young",
    "important", "few", "public", "bad", "same", "able", "need",
    "because", "come", "could", "people", "take", "make", "know",
    "get", "like", "think", "see", "look", "want", "use", "find",
    "give", "tell", "keep", "let", "seem", "feel", "try", "leave",
    "call", "say", "go", "back", "help", "through", "between", "same",
}


class LinguisticsDetector:
    """
    [Linguistics] Multi-framework linguistic analysis detector.
    Combines SDA-NR, CLI, ROI, and GCI-Zipf signals.
    """

    def analyze(self, text: str, user_baseline: dict) -> Optional[LinguisticSignal]:
        """
        Analyze text for linguistic manipulation indicators.

        Parameters
        ----------
        text : str
            The raw message text.
        user_baseline : dict
            Per-user behavioral baseline including nv_ratio_mean, nv_ratio_std.

        Returns
        -------
        Optional[LinguisticSignal]
            Detected linguistic signal, or None if severity is zero.
        """
        text_lower = text.lower()
        words = text_lower.split()
        word_count = max(len(words), 1)
        evidence: list[str] = []

        # -------------------------------------------------------------------
        # [SDA-NR] Noun/Verb ratio and baseline deviation
        # -------------------------------------------------------------------
        noun_count, verb_count, nv_ratio, nv_z_score = self._compute_nv_ratio(
            words, word_count, user_baseline
        )

        # -------------------------------------------------------------------
        # [CLI] Cognitive Load Index
        # -------------------------------------------------------------------
        cli_stress = self._compute_cli(text_lower, word_count)

        # -------------------------------------------------------------------
        # [ROI] Readability / Obfuscation Index
        # -------------------------------------------------------------------
        fog_index, obfuscated = self._compute_roi(text, words, word_count, text_lower)

        # -------------------------------------------------------------------
        # [GCI-Zipf] Calculated error detection
        # -------------------------------------------------------------------
        zipf_r2, is_calculated = self._compute_zipf(words)

        # -------------------------------------------------------------------
        # Severity aggregation
        # -------------------------------------------------------------------
        severity = Fraction(0, 1)

        # [SDA-NR] Minimum word threshold: short messages lack enough tokens
        # for reliable N/V ratio estimation — skip to avoid false positives
        if abs(nv_z_score) > 2.0 and word_count >= 10:
            sev = Fraction(3, 10)
            severity = max(severity, sev)
            direction = "high" if nv_z_score > 0 else "low"
            evidence.append(
                f"[SDA-NR] NV ratio {nv_ratio:.2f} is {abs(nv_z_score):.1f} std deviations "
                f"{direction} from user baseline "
                f"(mean={user_baseline.get('nv_ratio_mean', 1.0):.2f})"
            )

        if cli_stress > Fraction(1, 3):
            sev = cli_stress * Fraction(1, 2)
            sev = min(sev, Fraction(1, 1))
            severity = max(severity, sev)
            evidence.append(
                f"[CLI] Cognitive load stress {float(cli_stress):.3f} exceeds threshold 0.333"
            )

        if obfuscated:
            sev = Fraction(4, 10)
            severity = max(severity, sev)
            unique_count = len(set(words))
            info_density = unique_count / word_count
            evidence.append(
                f"[ROI] Obfuscation detected: Fog={fog_index:.1f} > 16, "
                f"info density={info_density:.2f} < 0.3"
            )

        if is_calculated:
            sev = Fraction(2, 10)
            severity = max(severity, sev)
            evidence.append(
                f"[GCI-Zipf] Calculated error pattern detected: R²={zipf_r2:.3f} < 0.75"
            )

        if severity == Fraction(0, 1):
            return None

        return LinguisticSignal(
            nv_ratio=nv_ratio,
            nv_z_score=nv_z_score,
            cli_stress=cli_stress,
            fog_index=fog_index,
            zipf_r2=zipf_r2,
            severity=severity,
            evidence=evidence,
        )

    # ------------------------------------------------------------------
    # Private: SDA-NR
    # ------------------------------------------------------------------

    def _compute_nv_ratio(
        self, words: list[str], word_count: int, user_baseline: dict
    ) -> tuple[int, int, float, float]:
        """
        [SDA-NR] Compute noun/verb ratio and z-score vs. user baseline.
        Returns (noun_count, verb_count, nv_ratio, z_score).
        """
        noun_count = 0
        verb_count = 0

        for w in words:
            clean = re.sub(r"[^a-záéíóúüñ]", "", w)
            if not clean:
                continue

            # Verb detection: common verbs or morphological markers
            if clean in _COMMON_VERBS_EN or clean in _COMMON_VERBS_ES:
                verb_count += 1
                continue

            # Verb morphological markers (-ing, -ed proxy for English)
            if clean.endswith("ing") and len(clean) > 5:
                verb_count += 1
                continue
            if clean.endswith("ed") and len(clean) > 4:
                verb_count += 1
                continue

            # Noun suffix detection
            is_noun = any(clean.endswith(suf) for suf in _NOUN_SUFFIXES_EN + _NOUN_SUFFIXES_ES)
            if is_noun:
                noun_count += 1

        nv_ratio = noun_count / max(verb_count, 1)

        # P1 fix: warm-up period. Users with < 10 messages have an unreliable
        # baseline. Suppress SDA-NR z-score flagging during warm-up by returning
        # a z-score of 0 (no deviation). The nv_ratio is still returned for
        # accurate baseline accumulation.
        message_count = user_baseline.get("message_count", 0)
        if message_count < 10:
            return noun_count, verb_count, nv_ratio, 0.0

        baseline_mean = user_baseline.get("nv_ratio_mean", 1.0)
        baseline_std = user_baseline.get("nv_ratio_std", 0.5)
        std = max(baseline_std, 0.1)
        z_score = (nv_ratio - baseline_mean) / std

        return noun_count, verb_count, nv_ratio, z_score

    # ------------------------------------------------------------------
    # Private: CLI
    # ------------------------------------------------------------------

    def _compute_cli(self, text_lower: str, word_count: int) -> Fraction:
        """
        [CLI] Compute Cognitive Load Index from exclusion, certainty, and
        distancing markers.
        cli_stress = (excl + cert + dist) / word_count * 3, capped at 1.
        """
        exclusion_count = sum(
            len(re.findall(pat, text_lower, re.IGNORECASE))
            for pat in _EXCLUSION_MARKERS
        )
        certainty_count = sum(
            len(re.findall(pat, text_lower, re.IGNORECASE))
            for pat in _CERTAINTY_MARKERS
        )
        distancing_count = sum(
            len(re.findall(pat, text_lower, re.IGNORECASE))
            for pat in _DISTANCING_MARKERS
        )

        total_markers = exclusion_count + certainty_count + distancing_count
        # Fraction arithmetic only — no float division
        cli_raw = (
            Fraction(exclusion_count, word_count)
            + Fraction(certainty_count, word_count)
            + Fraction(distancing_count, word_count)
        ) * 3
        cli_stress = min(cli_raw, Fraction(1, 1))
        return cli_stress

    # ------------------------------------------------------------------
    # Private: ROI
    # ------------------------------------------------------------------

    def _compute_roi(
        self, text: str, words: list[str], word_count: int, text_lower: str
    ) -> tuple[float, bool]:
        """
        [ROI] Gunning Fog + information density check.
        Returns (fog_index, is_obfuscated).
        """
        sentences = re.split(r"[.!?]+", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        sentence_count = max(len(sentences), 1)
        avg_sentence_length = word_count / sentence_count

        complex_count = sum(
            1 for w in words if len(re.sub(r"[^a-zA-Z]", "", w)) > 8
        )
        complex_ratio = complex_count / word_count
        fog = 0.4 * (avg_sentence_length + 100 * complex_ratio)

        # P0 fix: use CONTENT word uniqueness, not all tokens.
        # Stopwords inflate apparent uniqueness in short repetitive messages.
        # "a a a a a" → 5 words, 1 unique → density=0.2, but it's not obfuscation.
        # Require fog > 16 AND low content-word diversity AND minimum length.
        _STOPWORDS = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "shall", "can",
            "i", "you", "he", "she", "it", "we", "they", "this", "that",
            "and", "or", "but", "in", "on", "at", "to", "of", "for",
            "with", "by", "from", "up", "about", "as", "into", "than",
            "el", "la", "los", "las", "un", "una", "de", "en", "y", "o",
        }
        content_words = [w for w in words if w.lower() not in _STOPWORDS]
        if not content_words:
            return fog, False
        unique_content = len(set(w.lower() for w in content_words))
        info_density = unique_content / len(content_words)

        # Obfuscation requires: high fog, low content diversity, AND enough words
        obfuscated = fog > 16 and info_density < 0.3 and len(content_words) >= 15
        return fog, obfuscated

    # ------------------------------------------------------------------
    # Private: GCI-Zipf
    # ------------------------------------------------------------------

    def _compute_zipf(self, words: list[str]) -> tuple[float, bool]:
        """
        [GCI-Zipf] Detect calculated (non-random) error patterns.
        Uses variance of inter-error distances as a proxy for R².
        Low variance = errors are uniformly spaced = calculated.
        Returns (zipf_r2_proxy, is_calculated).
        """
        # P0 fix: Zipf error detection was marking technical terms, proper nouns,
        # and Spanish words as "calculated errors". Restrict to clear typo patterns:
        # repeated characters, transposed common pairs, or mixed digit/letter tokens.
        # No longer penalizes unknown-but-valid words.
        error_positions: list[int] = []
        _TYPO_PATTERNS = [
            re.compile(r"(.)\1{2,}"),          # "helllo", "noooo" — repeated chars
            re.compile(r"\d+[a-z]+\d+"),       # "3rd1" style mixed tokens (not "3rd")
            re.compile(r"[a-z]{1,2}[0-9][a-z]{1,2}"),  # "a1b" style
        ]
        for i, w in enumerate(words):
            clean = re.sub(r"[^a-z0-9]", "", w.lower())
            if not clean or len(clean) < 2:
                continue
            if any(pat.search(clean) for pat in _TYPO_PATTERNS):
                error_positions.append(i)

        error_count = len(error_positions)

        if error_count <= 3:
            # Too few errors to analyze pattern
            return 1.0, False

        # Compute inter-error distances
        distances = [
            error_positions[i + 1] - error_positions[i]
            for i in range(len(error_positions) - 1)
        ]

        if not distances:
            return 1.0, False

        # Variance of distances — low variance = uniform = calculated
        mean_dist = sum(distances) / len(distances)
        variance = sum((d - mean_dist) ** 2 for d in distances) / len(distances)

        # Map variance to a pseudo-R² proxy
        # High variance → R² near 1 (random), low variance → R² near 0 (calculated)
        # We scale: variance > 4 → R²=1.0 (random), variance < 1 → R²=0.0 (uniform)
        variance_clamped = max(0.0, min(variance, 4.0))
        zipf_r2 = variance_clamped / 4.0

        is_calculated = error_count > 3 and variance < 2.0

        return zipf_r2, is_calculated
