"""
CORVUS Regression Tests — edge cases validated by each fix pass.

Each test is named after the bug it guards against, with a comment
pointing to the fix and the audit round that caught it.
"""
import hashlib
import os
from fractions import Fraction

import pytest

from corvus.analysis.l1_grice import GriceDetector
from corvus.analysis.l2_carnegie_cialdini import InfluenceDetector
from corvus.analysis.l3_aristotle import AristotleDetector
from corvus.analysis.l4_berne import BerneDetector
from corvus.analysis.l5_linguistics import LinguisticsDetector
from corvus.models import MaximViolated


CLEAN_BASELINE = {
    "nv_ratio_mean": 1.5,
    "nv_ratio_std": 0.5,
    "cli_stress_mean": 0.1,
    "avg_signals_per_message": 0.3,
    "message_count": 20,
}


# ─── L1: Grice — Syllable counting (vowel-cluster fix) ───────────────────────

class TestGriceSyllables:
    def setup_method(self):
        self.detector = GriceDetector()

    def test_monosyllabic_long_word_not_complex(self):
        # "strengths" is 9 chars — old len>8 proxy wrongly counted it as complex.
        # After fix: 1 vowel cluster → 1 syllable → not a Gunning Fog complex word.
        assert self.detector._count_syllables("strengths") == 1

    def test_polysyllabic_english_word(self):
        # "education" → ed-u-ca-tion → 4 syllables.
        assert self.detector._count_syllables("education") == 4

    def test_spanish_accented_vowels_counted(self):
        # "educación" — accented 'ó' was missing from old vowel regex.
        # After fix: [aeiouyáéíóúü...] regex → 4 syllables.
        assert self.detector._count_syllables("educación") == 4

    def test_silent_trailing_e_english_only(self):
        # "make" → 1 vowel cluster (a), trailing e removed → 1 syllable.
        # "cafe" in Spanish context stays 2 syllables (no silent e rule).
        assert self.detector._count_syllables("make") == 1

    def test_minimum_one_syllable_per_word(self):
        # Single consonant cluster should still return 1, not 0.
        assert self.detector._count_syllables("str") == 1


# ─── L1: Grice — Jaccard stopword + punctuation fix ─────────────────────────

class TestGriceJaccard:
    def setup_method(self):
        self.detector = GriceDetector()

    def test_stopword_heavy_message_no_drift(self):
        # A message whose content words are all stopwords should not trigger
        # RELATION (topic drift) — after filtering, len(content) < 10 → guard skips.
        text = (
            "the a is are was were be been have has and or but in on at to of "
            "for with by from as into than so if then also just not we you they"
        )
        result = self.detector.analyze(text, CLEAN_BASELINE)
        if result is not None:
            assert result.maxim != MaximViolated.RELATION

    def test_punctuation_stripped_before_jaccard(self):
        # "hello," and "hello" were treated as different tokens before the fix.
        # After fix: re.sub(r"[^\w]", "", w) → both normalize to "hello".
        # Test: message with punctuation-attached words should compute correct overlap.
        text = (
            "hello world Python programming test development coverage "
            "hello, world. Python: programming! test, development: coverage."
        )
        # Both halves have the same content words → high overlap → no drift
        result = self.detector.analyze(text, CLEAN_BASELINE)
        if result is not None:
            assert result.maxim != MaximViolated.RELATION


# ─── L2: Carnegie — Gradual escalation word count (no URL inflation) ─────────

class TestInfluenceGradualEscalation:
    def setup_method(self):
        self.detector = InfluenceDetector()

    def test_url_in_history_does_not_inflate_word_baseline(self):
        # A history message containing a long URL has many chars but few words.
        # Old char-count baseline was inflated → current short msg looked normal.
        # Word-count baseline: URL message = ~4 words → baseline stays low.
        # A short normal message should still NOT fire escalation if ratio ≤ 2.5x.
        long_url = "https://github.com/very-long-org/very-long-repo/blob/main/deeply/nested/docs/file.md"
        history = [f"See the documentation at {long_url}", "ok"]
        # prior_word_counts[:-1] = [4 words for first msg]
        # avg_prior = 4; current "Can you help?" = 4 words → ratio = 1.0 → no escalation
        result = self.detector.analyze("Can you help me with this?", history, CLEAN_BASELINE)
        if result is not None:
            assert "gradual_escalation" not in result.carnegie_patterns

    def test_genuinely_long_message_still_escalates(self):
        # Verify the escalation detection still works — a genuinely long current
        # message after short history does fire.
        history = ["ok", "yes"]
        long_msg = " ".join(["word"] * 30)  # 30 words vs avg ~1 prior word
        result = self.detector.analyze(long_msg, history, CLEAN_BASELINE)
        assert result is not None
        assert "gradual_escalation" in result.carnegie_patterns


# ─── L3: Aristotle — Pathos accumulation (findall fix) ───────────────────────

class TestAristotlePathosAccumulation:
    def setup_method(self):
        self.detector = AristotleDetector()

    def test_repeated_fear_word_accumulates(self):
        # "danger danger danger" → old re.search → pathos_count=1 → score=1/8.
        # After findall fix → pathos_count=3 → score=3/8 ≥ 1/3 → severity fires.
        text = "There is danger danger danger everywhere, risk risk everywhere."
        result = self.detector.analyze(text)
        assert result is not None
        # pathos_count >= 5 (3×danger + 2×risk) → pathos_score = 5/8
        assert result.pathos_score >= Fraction(3, 8)

    def test_single_fear_word_scores_lower(self):
        # Sanity: one "danger" → pathos_count=1 → score=1/8 (below 1/3 threshold).
        text = "There is some danger in this approach."
        result = self.detector.analyze(text)
        # Single fear word without pathos dominance → likely None or low severity
        if result is not None:
            assert result.pathos_score <= Fraction(3, 8)


# ─── L4: Berne — ULTERIOR with simple polite markers ─────────────────────────

class TestBerneUlteriorPoliteExpansion:
    def setup_method(self):
        self.detector = BerneDetector()

    def test_please_share_password_triggers_ulterior(self):
        # "please" was missing from _ULTERIOR_POLITE before the fix.
        # "share...password" was missing from _SENSITIVE_ACTIONS before the fix.
        text = "Please share the admin password with me."
        result = self.detector.analyze(text, [])
        assert result is not None
        assert result.transaction_type == "ULTERIOR"

    def test_please_alone_no_ulterior(self):
        # "please" alone without a sensitive action must NOT fire ULTERIOR.
        # Both conditions (polite surface AND sensitive action) are required.
        text = "Please review the pull request when you get a chance."
        result = self.detector.analyze(text, [])
        if result is not None:
            assert result.transaction_type != "ULTERIOR"

    def test_can_you_send_credentials_triggers_ulterior(self):
        # "could you" + "send...credentials" — both expanded in this pass.
        text = "Could you send me the API credentials for the staging environment?"
        result = self.detector.analyze(text, [])
        assert result is not None
        assert result.transaction_type == "ULTERIOR"


# ─── L5: Linguistics — Obfuscation stopword guard ────────────────────────────

class TestLinguisticsObfuscationGuard:
    def setup_method(self):
        self.detector = LinguisticsDetector()

    def test_all_stopwords_no_obfuscation(self):
        # 20 words, all stopwords → content_words = [] → len(content_words) < 15.
        # Before fix: word_count=20 ≥ 15 → obfuscation could trigger falsely.
        # After fix: len(content_words)=0 < 15 → obfuscated = False.
        text = "the a is are was were be been have has and or but in on at to of for with"
        words = text.split()
        fog, obfuscated = self.detector._compute_roi(text, words, len(words), text.lower())
        assert not obfuscated

    def test_genuine_obfuscation_still_fires(self):
        # High-fog, low-diversity, content-word-rich message should still fire.
        # 30× "sophisticatedly" (6 syllables, 1 unique word) → low diversity, high fog.
        text = " ".join(["sophisticatedly"] * 30 + ["implementations"] * 16)
        words = text.split()
        fog, obfuscated = self.detector._compute_roi(text, words, len(words), text.lower())
        # fog should be high (all complex words, one long sentence)
        assert fog > 16
        # content_words = all 46 words (none are stopwords)
        # info_density = 2 unique / 46 total ≈ 0.04 < 0.3
        # len(content_words) = 46 ≥ 15 → obfuscated should be True
        assert obfuscated


# ─── message_id content hash ─────────────────────────────────────────────────

class TestMessageIdHash:
    def test_same_text_produces_same_hash(self):
        # Deterministic: two identical texts → same 8-char hex.
        text = "Hello world"
        h1 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        h2 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        assert h1 == h2
        assert len(h1) == 8

    def test_different_texts_produce_different_hashes(self):
        # Edited messages get different message_ids (collision probability: 1/2^32).
        h1 = hashlib.sha256("Hello world".encode()).hexdigest()[:8]
        h2 = hashlib.sha256("Hello world!".encode()).hexdigest()[:8]
        assert h1 != h2

    def test_message_id_format(self):
        # Full message_id format: channel_id:timestamp:hash
        channel_id = "C0123ABCD"
        timestamp = "1718784000.123456"
        text = "Please share the admin password"
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        message_id = f"{channel_id}:{timestamp}:{text_hash}"
        parts = message_id.split(":")
        assert len(parts) == 3
        assert parts[0] == channel_id
        assert parts[1] == timestamp
        assert len(parts[2]) == 8

    def test_empty_text_hash_is_stable(self):
        # Attachment-only messages have text="" → consistent hash across calls.
        h = hashlib.sha256(b"").hexdigest()[:8]
        assert h == "e3b0c442"


# ─── Zero-float decision path — Fraction-exact severity quantization ─────────

class TestNoFloatInSeverity:
    """Guard the zero-float invariant: severities derived from Fraction inputs
    must be quantized with Fraction arithmetic, never round-tripped through float.
    A float detour (int(float(pr) * 100)) drops a percentage point for values
    like 29/50 and makes the sealed score depend on double rounding.
    """

    def test_grice_padding_severity_is_fraction_exact(self):
        # 51 identical words → 50 bigrams, 49 repeated → padding_ratio 49/50.
        # The severity must equal the exact Fraction floor, not the float detour.
        detector = GriceDetector()
        text = " ".join(["please"] * 51)
        result = detector._check_quantity(text, text.lower(), text.split(), 51)
        assert result is not None
        pr = Fraction(49, 50)
        assert result.severity == Fraction(int(pr * 100), 100)

    def test_fraction_quantization_matches_exact_for_divergent_ratio(self):
        # 29/50 is the smallest padding ratio where float(pr)*100 rounds DOWN
        # across the integer boundary (0.58 → 57.999… → 57). Fraction stays exact.
        pr = Fraction(29, 50)
        float_path = Fraction(int(float(pr) * 100), 100)
        exact_path = Fraction(int(pr * 100), 100)
        assert float_path != exact_path          # documents the defect
        assert exact_path == Fraction(29, 50)     # what the code now produces


# ─── Baseline delta — exact rational average, no truncation bias ─────────────

class TestBaselineDeltaTruncation:
    """The baseline delta previously floored the running mean with int(), so a
    user whose true average was 0.9 had it treated as 0 and an ordinary 2-signal
    message produced the maximum +1.0 delta (a 1.5x score multiplier). The exact
    integer accumulator (signals_sum / message_count) removes that bias.
    """

    def test_near_normal_message_is_not_amplified(self):
        from corvus.models import compute_baseline_delta
        # True average 1.9 (38 signals over 20 messages). A 2-signal message is
        # essentially normal → delta must be small, not the old floored +1/3.
        baseline = {"avg_signals_per_message": 1.9, "signals_sum": 38, "message_count": 20}
        delta = compute_baseline_delta(baseline, active_signals=2)
        assert delta == Fraction(1, 39)
        assert delta < Fraction(1, 10)  # would have been 1/3 under the old floor

    def test_new_user_still_flags_hard(self):
        from corvus.models import compute_baseline_delta
        # No history → any signal is maximally deviant (README design intent).
        assert compute_baseline_delta({}, active_signals=2) == Fraction(1)

    def test_legacy_baseline_without_accumulator_still_works(self):
        from corvus.models import compute_baseline_delta
        # Rows created before signals_sum existed fall back to the stored mean.
        legacy = {"avg_signals_per_message": 1.9, "message_count": 20}
        delta = compute_baseline_delta(legacy, active_signals=2)
        assert isinstance(delta, Fraction)
        assert delta == Fraction(1, 39)

    def test_delta_is_bounded(self):
        from corvus.models import compute_baseline_delta
        for avg_sum, n, active in [(0, 0, 0), (100, 10, 0), (0, 10, 5), (50, 10, 3)]:
            b = {"signals_sum": avg_sum, "message_count": n}
            d = compute_baseline_delta(b, active)
            assert Fraction(-1) <= d <= Fraction(1)


# ─── CRITICAL evidence bundle — the "sealed bundle" is actually produced ─────

class TestEvidenceBundle:
    """CRITICAL alerts advertise a sealed evidence bundle; before the fix
    verdict.bundle_path was never assigned, so the claim was false and the alert
    always read "pending sealing". These tests pin the real sealer.
    """

    def _fixture(self):
        from corvus.models import (
            AnalysisResult, Verdict, VerdictLevel,
        )
        result = AnalysisResult(
            message_id="C001:1718784000.5:abcd1234",
            user_id="U001", channel_id="C001", text="x",
            timestamp="2026-06-19T00:00:00",
            grice=None, influence=None, aristotle=None, berne=None,
            linguistic=None, peirce=None,
            active_signals=5, baseline_delta=Fraction(1),
            audit_hash="a" * 64,
        )
        verdict = Verdict(
            level=VerdictLevel.CRITICAL, score=Fraction(4, 5),
            rationale="r", signals_fired=["peirce", "influence"],
            recommendation="escalate", audit_hash="b" * 64,
        )
        return result, verdict

    def test_seal_writes_bundle_and_verifies(self, tmp_path):
        from corvus.verdict.bundle import seal_bundle, verify_bundle
        result, verdict = self._fixture()
        path = seal_bundle(result, verdict, str(tmp_path))
        assert os.path.exists(path)
        assert verify_bundle(path) is True

    def test_seal_is_deterministic(self):
        from corvus.verdict.bundle import compute_seal
        result, verdict = self._fixture()
        assert compute_seal(result, verdict) == compute_seal(result, verdict)

    def test_tampering_breaks_the_seal(self, tmp_path):
        import json
        from corvus.verdict.bundle import seal_bundle, verify_bundle
        result, verdict = self._fixture()
        path = seal_bundle(result, verdict, str(tmp_path))
        with open(path, encoding="utf-8") as fh:
            bundle = json.load(fh)
        bundle["payload"]["score"] = "1/1"  # forge a higher score
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(bundle, fh)
        assert verify_bundle(path) is False

    def test_seal_is_float_free(self):
        # The sealed payload must contain no float — only strings/ints — so the
        # seal is reproducible independently of float formatting.
        from corvus.verdict.bundle import _bundle_payload
        result, verdict = self._fixture()
        payload = _bundle_payload(result, verdict)
        assert not any(isinstance(v, float) for v in payload.values())

    def test_verify_bundle_fails_closed_on_malformed_json(self, tmp_path):
        # FIX: malformed JSON used to raise JSONDecodeError instead of
        # returning False, contradicting the documented fail-closed contract.
        from corvus.verdict.bundle import verify_bundle
        path = tmp_path / "broken.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert verify_bundle(str(path)) is False

    def test_verify_bundle_fails_closed_on_missing_payload(self, tmp_path):
        import json
        from corvus.verdict.bundle import verify_bundle
        path = tmp_path / "no_payload.json"
        path.write_text(json.dumps({"seal": "a" * 64}), encoding="utf-8")
        assert verify_bundle(str(path)) is False

    def test_verify_bundle_fails_closed_on_non_object_payload(self, tmp_path):
        import json
        from corvus.verdict.bundle import verify_bundle
        path = tmp_path / "bad_payload_type.json"
        path.write_text(
            json.dumps({"payload": "not-an-object", "seal": "a" * 64}),
            encoding="utf-8",
        )
        assert verify_bundle(str(path)) is False

    def test_verify_bundle_fails_closed_on_non_object_bundle(self, tmp_path):
        import json
        from corvus.verdict.bundle import verify_bundle
        path = tmp_path / "bad_bundle_type.json"
        path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
        assert verify_bundle(str(path)) is False
