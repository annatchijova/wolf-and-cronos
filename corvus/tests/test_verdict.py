"""
CORVUS Verdict Engine Tests
Tests scoring, corroboration gate, baseline delta multiplier, and verdict levels.
"""
import pytest
from fractions import Fraction

from corvus.verdict.engine import VerdictEngine
from corvus.models import (
    AnalysisResult, GriceSignal, InfluenceSignal, AristotleSignal,
    BerneSignal, LinguisticSignal, PeirceSignal,
    VerdictLevel, MaximViolated,
)
from corvus.config import Config


def make_result(
    active_signals=0,
    baseline_delta=Fraction(0),
    grice=None,
    influence=None,
    aristotle=None,
    berne=None,
    linguistic=None,
    peirce=None,
):
    return AnalysisResult(
        message_id="test",
        user_id="U001",
        channel_id="C001",
        text="test",
        timestamp="2026-06-19T00:00:00",
        grice=grice,
        influence=influence,
        aristotle=aristotle,
        berne=berne,
        linguistic=linguistic,
        peirce=peirce,
        active_signals=active_signals,
        baseline_delta=baseline_delta,
        audit_hash="a" * 64,
    )


class TestVerdictEngine:
    def setup_method(self):
        self.engine = VerdictEngine(Config())

    def test_zero_signals_is_silent(self):
        result = make_result(active_signals=0)
        verdict = self.engine.compute(result)
        assert verdict.level == VerdictLevel.SILENT
        assert verdict.score == Fraction(0)

    def test_single_signal_below_corroboration_is_silent(self):
        """Single signal cannot reach WATCH regardless of severity (corroboration gate)."""
        result = make_result(
            active_signals=1,
            influence=InfluenceSignal(
                carnegie_patterns=["flattery"],
                cialdini_triggers=["AUTHORITY", "SCARCITY"],
                severity=Fraction(9, 10),
                evidence=["only you"],
            )
        )
        verdict = self.engine.compute(result)
        assert verdict.level == VerdictLevel.SILENT

    def test_two_signals_can_reach_watch(self):
        # Severities calibrated so weighted sum >= WATCH threshold (0.20):
        # influence: 0.6 * 0.25 = 0.15 | grice: 0.6 * 0.15 = 0.09 → total 0.24
        result = make_result(
            active_signals=2,
            influence=InfluenceSignal(
                carnegie_patterns=["flattery"],
                cialdini_triggers=["AUTHORITY"],
                severity=Fraction(3, 5),
                evidence=["x"],
            ),
            grice=GriceSignal(
                maxim=MaximViolated.MANNER,
                severity=Fraction(3, 5),
                evidence="fog",
            ),
        )
        verdict = self.engine.compute(result)
        assert verdict.level in (VerdictLevel.WATCH, VerdictLevel.ALERT, VerdictLevel.CRITICAL)

    def test_high_baseline_delta_amplifies_score(self):
        """Same signals with high baseline delta should score higher."""
        signals_low = make_result(
            active_signals=2,
            baseline_delta=Fraction(0),
            influence=InfluenceSignal(
                carnegie_patterns=["urgency"],
                cialdini_triggers=["SCARCITY"],
                severity=Fraction(1, 2),
                evidence=["urgent"],
            ),
            grice=GriceSignal(maxim=MaximViolated.MANNER, severity=Fraction(1, 4), evidence="fog"),
        )
        signals_high = make_result(
            active_signals=2,
            baseline_delta=Fraction(1),  # maximum deviation
            influence=InfluenceSignal(
                carnegie_patterns=["urgency"],
                cialdini_triggers=["SCARCITY"],
                severity=Fraction(1, 2),
                evidence=["urgent"],
            ),
            grice=GriceSignal(maxim=MaximViolated.MANNER, severity=Fraction(1, 4), evidence="fog"),
        )
        low_verdict = self.engine.compute(signals_low)
        high_verdict = self.engine.compute(signals_high)
        assert high_verdict.score >= low_verdict.score

    def test_full_attack_is_critical(self, tmp_path):
        # Isolated bundle_dir: this verdict is CRITICAL, and CRITICAL verdicts
        # now really seal a bundle (see TestCriticalBundleSealing) — without
        # this override it would write to the real default ~/.corvus/bundles.
        config = Config()
        config.CORVUS_BUNDLE_DIR = str(tmp_path)
        engine = VerdictEngine(config)

        result = make_result(
            active_signals=5,
            baseline_delta=Fraction(1),
            grice=GriceSignal(maxim=MaximViolated.MANNER, severity=Fraction(4, 5), evidence="fog"),
            influence=InfluenceSignal(
                carnegie_patterns=["flattery", "urgency", "lesser_evil"],
                cialdini_triggers=["AUTHORITY", "SCARCITY", "SOCIAL_PROOF"],
                severity=Fraction(9, 10),
                evidence=["only you", "urgent", "everyone"],
            ),
            aristotle=AristotleSignal(
                ethos_score=Fraction(1, 2),
                pathos_score=Fraction(4, 5),
                logos_score=Fraction(1, 10),
                imbalance_score=Fraction(7, 10),
                evidence=["danger", "please"],
            ),
            berne=BerneSignal(
                ego_state="PARENT_CRITICAL",
                transaction_type="ULTERIOR",
                severity=Fraction(3, 5),
                evidence=["you must", "credentials"],
            ),
            peirce=PeirceSignal(
                firstness="5 manipulation layers detected",
                secondness="100% deviation from baseline",
                thirdness="coordinated multi-vector manipulation",
                hypothesis="Coordinated multi-vector manipulation attempt",
                oscillation=False,
                confidence=95,
                severity=Fraction(19, 20),
            ),
        )
        verdict = engine.compute(result)
        assert verdict.level == VerdictLevel.CRITICAL
        assert verdict.score >= Fraction(3, 4)

    def test_score_never_exceeds_one(self):
        result = make_result(
            active_signals=6,
            baseline_delta=Fraction(1),
            grice=GriceSignal(maxim=MaximViolated.MANNER, severity=Fraction(1), evidence="max"),
            influence=InfluenceSignal(
                carnegie_patterns=["x"], cialdini_triggers=["x"],
                severity=Fraction(1), evidence=["x"]
            ),
            aristotle=AristotleSignal(
                ethos_score=Fraction(1), pathos_score=Fraction(1),
                logos_score=Fraction(0), imbalance_score=Fraction(1), evidence=[]
            ),
            berne=BerneSignal(
                ego_state="PARENT_CRITICAL", transaction_type="ULTERIOR",
                severity=Fraction(1), evidence=[]
            ),
            linguistic=LinguisticSignal(
                nv_ratio=5.0, nv_z_score=4.0, cli_stress=Fraction(1),
                fog_index=25.0, zipf_r2=0.5, severity=Fraction(1), evidence=[]
            ),
            peirce=PeirceSignal(
                firstness="x", secondness="x", thirdness="x",
                hypothesis="x", oscillation=False, confidence=100,
                severity=Fraction(1),
            ),
        )
        verdict = self.engine.compute(result)
        assert verdict.score <= Fraction(1)

    def test_score_is_fraction(self):
        result = make_result(
            active_signals=2,
            influence=InfluenceSignal(
                carnegie_patterns=["flattery"],
                cialdini_triggers=["AUTHORITY"],
                severity=Fraction(1, 2),
                evidence=["x"],
            ),
            grice=GriceSignal(maxim=MaximViolated.MANNER, severity=Fraction(1, 3), evidence="fog"),
        )
        verdict = self.engine.compute(result)
        assert isinstance(verdict.score, Fraction)

    def test_signals_fired_populated(self):
        result = make_result(
            active_signals=2,
            influence=InfluenceSignal(
                carnegie_patterns=["urgency"],
                cialdini_triggers=["SCARCITY"],
                severity=Fraction(2, 5),
                evidence=["urgent"],
            ),
            aristotle=AristotleSignal(
                ethos_score=Fraction(0), pathos_score=Fraction(1, 2),
                logos_score=Fraction(0), imbalance_score=Fraction(1, 2),
                evidence=["please"],
            ),
        )
        verdict = self.engine.compute(result)
        assert isinstance(verdict.signals_fired, list)

    def test_rationale_is_string(self):
        result = make_result(active_signals=0)
        verdict = self.engine.compute(result)
        assert isinstance(verdict.rationale, str)
        assert len(verdict.rationale) > 0

    def test_audit_hash_64_chars(self):
        result = make_result(active_signals=0)
        verdict = self.engine.compute(result)
        assert len(verdict.audit_hash) == 64


def _critical_result(message_id="critical-bundle-test"):
    """An AnalysisResult that reliably scores CRITICAL (>= 0.75)."""
    return AnalysisResult(
        message_id=message_id, user_id="U001", channel_id="C001", text="test",
        timestamp="2026-06-19T00:00:00",
        active_signals=5, baseline_delta=Fraction(1),
        audit_hash="a" * 64,
        grice=GriceSignal(maxim=MaximViolated.MANNER, severity=Fraction(4, 5), evidence="fog"),
        influence=InfluenceSignal(
            carnegie_patterns=["flattery", "urgency", "lesser_evil"],
            cialdini_triggers=["AUTHORITY", "SCARCITY", "SOCIAL_PROOF"],
            severity=Fraction(9, 10),
            evidence=["only you", "urgent", "everyone"],
        ),
        aristotle=AristotleSignal(
            ethos_score=Fraction(1, 2), pathos_score=Fraction(4, 5),
            logos_score=Fraction(1, 10), imbalance_score=Fraction(7, 10),
            evidence=["danger", "please"],
        ),
        berne=BerneSignal(
            ego_state="PARENT_CRITICAL", transaction_type="ULTERIOR",
            severity=Fraction(3, 5), evidence=["you must", "credentials"],
        ),
        peirce=PeirceSignal(
            firstness="5 manipulation layers detected",
            secondness="100% deviation from baseline",
            thirdness="coordinated multi-vector manipulation",
            hypothesis="Coordinated multi-vector manipulation attempt",
            oscillation=False, confidence=95, severity=Fraction(19, 20),
        ),
        linguistic=None,
    )


class TestCriticalBundleSealing:
    """
    FIX: CRITICAL verdicts have always claimed "evidence bundle sealed" in
    their recommendation text, and Verdict.bundle_path exists to record
    where — but nothing in production ever called
    corvus.verdict.bundle.seal_bundle, so bundle_path stayed None forever.
    These tests pin the real wiring, isolated to a tmp_path bundle_dir so
    they never touch the real default (~/.corvus/bundles).
    """

    def _engine(self, bundle_dir):
        config = Config()
        config.CORVUS_BUNDLE_DIR = str(bundle_dir)
        return VerdictEngine(config)

    def test_critical_verdict_writes_a_real_bundle(self, tmp_path):
        from corvus.verdict.bundle import verify_bundle

        engine = self._engine(tmp_path)
        result = _critical_result()
        verdict = engine.compute(result)

        assert verdict.level == VerdictLevel.CRITICAL
        assert verdict.bundle_path is not None
        assert verify_bundle(verdict.bundle_path) is True
        assert "FAILED" not in verdict.recommendation

    def test_non_critical_verdict_does_not_seal(self, tmp_path):
        engine = self._engine(tmp_path)
        result = make_result(active_signals=0)
        verdict = engine.compute(result)
        assert verdict.bundle_path is None

    def test_sealing_failure_is_visible_not_silent(self, tmp_path, monkeypatch):
        # Point bundle_dir at a file (not a directory) so os.makedirs raises
        # FileExistsError (an OSError subclass) — simulating a real sealing
        # failure without mocking internals.
        blocked = tmp_path / "not_a_directory"
        blocked.write_text("x")
        engine = self._engine(blocked)
        result = _critical_result(message_id="critical-bundle-failure-test")

        verdict = engine.compute(result)

        assert verdict.level == VerdictLevel.CRITICAL
        assert verdict.bundle_path is None
        assert "FAILED" in verdict.recommendation
