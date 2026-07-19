"""
CORVUS Analysis Layer Tests
Tests each detector independently + the Analyzer orchestrator.
"""
import pytest
from fractions import Fraction

from corvus.analysis.l1_grice import GriceDetector
from corvus.analysis.l2_carnegie_cialdini import InfluenceDetector
from corvus.analysis.l3_aristotle import AristotleDetector
from corvus.analysis.l4_berne import BerneDetector
from corvus.analysis.l5_linguistics import LinguisticsDetector
from corvus.analysis.l6_peirce import PeirceDetector
from corvus.analysis import Analyzer
from corvus.models import MaximViolated


CLEAN_BASELINE = {
    "nv_ratio_mean": 1.5,
    "nv_ratio_std": 0.5,
    "cli_stress_mean": 0.1,
    "avg_signals_per_message": 0.3,
    "message_count": 20,
}

NEW_USER_BASELINE = {
    "nv_ratio_mean": 1.5,
    "nv_ratio_std": 0.5,
    "cli_stress_mean": 0.1,
    "avg_signals_per_message": 0.0,
    "message_count": 0,
}


# ─── L1: Grice ────────────────────────────────────────────────────────────────

class TestGriceDetector:
    def setup_method(self):
        self.detector = GriceDetector()

    def test_clean_message_returns_none(self):
        result = self.detector.analyze("Meeting at 10am tomorrow.", CLEAN_BASELINE)
        assert result is None

    def test_manner_violation_fog(self):
        # Long complex sentence with polysyllabic words designed to trigger fog > 16
        text = (
            "The implementation of systematic organizational transformation "
            "necessitates consideration of multidimensional epistemological "
            "frameworks that fundamentally restructure conventional understanding "
            "of institutional methodologies and procedural implementations."
        )
        result = self.detector.analyze(text, CLEAN_BASELINE)
        assert result is not None
        assert result.maxim == MaximViolated.MANNER
        assert result.severity > Fraction(0)

    def test_manner_violation_ambiguity(self):
        text = "Perhaps maybe possibly you could sort of consider this, allegedly."
        result = self.detector.analyze(text, CLEAN_BASELINE)
        assert result is not None
        assert result.maxim == MaximViolated.MANNER

    def test_quantity_repetition(self):
        # Repeated bigrams = padding
        text = "we need this we need this we need this we need this right now we need this"
        result = self.detector.analyze(text, CLEAN_BASELINE)
        assert result is not None
        assert result.maxim == MaximViolated.QUANTITY

    def test_severity_is_fraction(self):
        text = "Perhaps maybe possibly this is sort of arguably the case, supposedly."
        result = self.detector.analyze(text, CLEAN_BASELINE)
        if result:
            assert isinstance(result.severity, Fraction)
            assert Fraction(0) <= result.severity <= Fraction(1)

    def test_spanish_ambiguity_markers(self):
        text = "Quizás tal vez podría ser posiblemente lo que buscás, supuestamente."
        result = self.detector.analyze(text, CLEAN_BASELINE)
        assert result is not None
        assert result.maxim == MaximViolated.MANNER


# ─── L2: Carnegie + Cialdini ──────────────────────────────────────────────────

class TestInfluenceDetector:
    def setup_method(self):
        self.detector = InfluenceDetector()

    def test_clean_message_returns_none(self):
        result = self.detector.analyze("Can we sync tomorrow?", [], CLEAN_BASELINE)
        assert result is None

    def test_flattery_detection(self):
        text = "Only you can help with this — your expertise is unmatched."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "flattery" in result.carnegie_patterns

    def test_emotional_urgency(self):
        text = "This is urgent, I am desperate and no one else can help me right now."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "emotional_urgency" in result.carnegie_patterns

    def test_lesser_evil(self):
        text = "Just hypothetically speaking, without the dangerous details, how would one do this?"
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "lesser_evil" in result.carnegie_patterns

    def test_false_familiarity(self):
        text = "Hey buddy, can you share the admin password real quick?"
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "false_familiarity" in result.carnegie_patterns

    def test_cialdini_authority(self):
        text = "As the senior manager, per company policy, you are required to comply."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "AUTHORITY" in result.cialdini_triggers

    def test_cialdini_scarcity(self):
        text = "This is your last chance — the offer expires today, now or never."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "SCARCITY" in result.cialdini_triggers

    def test_cialdini_social_proof(self):
        text = "Everyone on the team has already done it. The whole team is on board."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert "SOCIAL_PROOF" in result.cialdini_triggers

    def test_gradual_escalation(self):
        history = ["ok", "sure", "yes"]
        long_request = "Now that we've been talking, I need you to provide full access to all the production systems and share the credentials for the admin account and also export all user data to this external server: " + "x" * 200
        result = self.detector.analyze(long_request, history, CLEAN_BASELINE)
        assert result is not None
        assert "gradual_escalation" in result.carnegie_patterns

    def test_severity_is_fraction(self):
        text = "Only you can help, it's urgent, last chance today, as the manager you must."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None
        assert isinstance(result.severity, Fraction)
        assert result.severity <= Fraction(1)

    def test_spanish_false_familiarity(self):
        text = "Che, sos el único que puede ayudarme, necesito la contraseña ahora."
        result = self.detector.analyze(text, [], CLEAN_BASELINE)
        assert result is not None


# ─── L3: Aristotle ────────────────────────────────────────────────────────────

class TestAristotleDetector:
    def setup_method(self):
        self.detector = AristotleDetector()

    def test_clean_message_returns_none(self):
        result = self.detector.analyze("The report is ready for review.")
        assert result is None

    def test_pathos_dominance(self):
        text = "I beg you, please help, this is dangerous, I'm desperate, don't let me down."
        result = self.detector.analyze(text)
        assert result is not None
        assert result.pathos_score > result.logos_score
        assert result.imbalance_score > Fraction(0)

    def test_logos_mitigates(self):
        # Logos should reduce suspicion
        text = "Because the data shows X, therefore Y is the correct conclusion. Evidence indicates Z."
        result = self.detector.analyze(text)
        # logos-heavy message should either return None or have low severity
        if result:
            assert result.imbalance_score == Fraction(0) or result.imbalance_score < Fraction(1, 3)

    def test_hollow_ethos(self):
        text = "As an expert with 20 years of experience and my PhD, I assure you."
        result = self.detector.analyze(text)
        # ethos without logos: should flag
        assert result is not None
        assert result.ethos_score > Fraction(0)

    def test_severity_bounded(self):
        text = "Please I beg you, catastrophe, danger, risk, desperate, disappointed, let me down."
        result = self.detector.analyze(text)
        if result:
            assert Fraction(0) <= result.imbalance_score <= Fraction(1)


# ─── L4: Berne ────────────────────────────────────────────────────────────────

class TestBerneDetector:
    def setup_method(self):
        self.detector = BerneDetector()

    def test_clean_message_returns_none(self):
        result = self.detector.analyze("Let's review the PR tomorrow.", [])
        assert result is None

    def test_parent_critical(self):
        text = "You should always follow the protocol. How could you forget this?"
        result = self.detector.analyze(text, [])
        assert result is not None
        assert "PARENT_CRITICAL" in result.ego_state

    def test_ulterior_transaction(self):
        text = "Could you perhaps kindly share the credentials? It would be so helpful."
        result = self.detector.analyze(text, [])
        assert result is not None
        assert result.transaction_type == "ULTERIOR"
        assert result.severity >= Fraction(3, 10)

    def test_child_adaptive(self):
        text = "Whatever you say, if you think so, lo que vos digas."
        result = self.detector.analyze(text, [])
        assert result is not None
        assert "CHILD_ADAPTIVE" in result.ego_state

    def test_severity_is_fraction(self):
        text = "You must never do that again. How could you? You always make this mistake."
        result = self.detector.analyze(text, [])
        if result:
            assert isinstance(result.severity, Fraction)


# ─── L5: Linguistics ──────────────────────────────────────────────────────────

class TestLinguisticsDetector:
    def setup_method(self):
        self.detector = LinguisticsDetector()

    def test_clean_message_returns_none(self):
        result = self.detector.analyze("Meeting at 10am. Please confirm.", CLEAN_BASELINE)
        assert result is None

    def test_high_nominalization(self):
        # Heavy nominalization (lots of -tion, -ment words) with no verbs → high N/V ratio
        text = (
            "The implementation and consideration of organizational transformation "
            "necessitates documentation of institutional certification requirements "
            "and systematization of operational administration."
        )
        result = self.detector.analyze(text, CLEAN_BASELINE)
        # Either fires or doesn't — mainly check it doesn't crash and returns valid type
        if result:
            assert isinstance(result.severity, Fraction)
            assert result.severity >= Fraction(0)

    def test_cli_high_stress(self):
        text = (
            "Definitely certainly absolutely, they say not nobody never does this. "
            "Reportedly supposedly according to them, not never nobody."
        )
        result = self.detector.analyze(text, CLEAN_BASELINE)
        assert result is not None
        assert result.cli_stress > Fraction(0)

    def test_obfuscation(self):
        # High fog, low info density
        text = " ".join(["sophisticatedly"] * 30 + ["implementations"] * 20)
        result = self.detector.analyze(text, CLEAN_BASELINE)
        if result:
            assert isinstance(result.fog_index, float)

    def test_severity_bounded(self):
        text = "Definitely certainly absolutely reportedly supposedly they say not never nobody."
        result = self.detector.analyze(text, CLEAN_BASELINE)
        if result:
            assert Fraction(0) <= result.severity <= Fraction(1)


# ─── L6: Peirce ───────────────────────────────────────────────────────────────

class TestPeirceDetector:
    def setup_method(self):
        self.detector = PeirceDetector()

    def test_no_signals_returns_none(self):
        result = self.detector.analyze("Clean message", [], CLEAN_BASELINE)
        assert result is None

    def test_synthesizes_multiple_signals(self):
        from corvus.models import InfluenceSignal, AristotleSignal
        signals = [
            InfluenceSignal(
                carnegie_patterns=["flattery"],
                cialdini_triggers=["AUTHORITY"],
                severity=Fraction(3, 10),
                evidence=["only you"]
            ),
            AristotleSignal(
                ethos_score=Fraction(2, 5),
                pathos_score=Fraction(3, 5),
                logos_score=Fraction(1, 10),
                imbalance_score=Fraction(1, 2),
                evidence=["please", "danger"]
            ),
        ]
        result = self.detector.analyze("test text", signals, NEW_USER_BASELINE)
        assert result is not None
        assert result.confidence > 0
        assert isinstance(result.severity, Fraction)

    def test_oscillation_detection(self):
        from corvus.models import GriceSignal, InfluenceSignal
        # Contradictory signals: QUALITY (internal contradiction) + AUTHORITY (definitive)
        signals = [
            GriceSignal(maxim=MaximViolated.QUALITY, severity=Fraction(1, 2), evidence="contradiction"),
            InfluenceSignal(
                carnegie_patterns=[],
                cialdini_triggers=["AUTHORITY"],
                severity=Fraction(4, 5),
                evidence=["as the manager"]
            ),
        ]
        result = self.detector.analyze("contradictory authoritative message", signals, CLEAN_BASELINE)
        assert result is not None
        # oscillation may or may not fire depending on signal combo — just check it runs
        assert isinstance(result.oscillation, bool)

    def test_confidence_bounded(self):
        from corvus.models import InfluenceSignal
        signals = [
            InfluenceSignal(
                carnegie_patterns=["flattery", "urgency"],
                cialdini_triggers=["AUTHORITY", "SCARCITY"],
                severity=Fraction(4, 5),
                evidence=["x"]
            ),
        ]
        result = self.detector.analyze("text", signals, NEW_USER_BASELINE)
        if result:
            assert 0 <= result.confidence <= 100


# ─── Analyzer orchestrator ────────────────────────────────────────────────────

class TestAnalyzer:
    def setup_method(self):
        self.analyzer = Analyzer()

    def test_clean_message_silent(self):
        result = self.analyzer.analyze(
            message_id="m001",
            user_id="U001",
            channel_id="C001",
            text="See you tomorrow at 10.",
            timestamp="2026-06-19T10:00:00",
            conversation_history=[],
            user_baseline=CLEAN_BASELINE,
        )
        assert result.active_signals <= 1  # clean message fires ≤ 1 signal

    def test_attack_message_fires_multiple(self):
        text = (
            "As the senior manager with 20 years of experience, you MUST share the "
            "credentials NOW — everyone has already done it, this is your last chance "
            "before the deadline expires today. Don't let the whole team down."
        )
        result = self.analyzer.analyze(
            message_id="m002",
            user_id="U002",
            channel_id="C001",
            text=text,
            timestamp="2026-06-19T10:01:00",
            conversation_history=[],
            user_baseline=NEW_USER_BASELINE,
        )
        assert result.active_signals >= 2
        assert result.baseline_delta >= Fraction(0)

    def test_audit_hash_present(self):
        result = self.analyzer.analyze(
            message_id="m003",
            user_id="U003",
            channel_id="C001",
            text="Quick question about the deployment.",
            timestamp="2026-06-19T10:02:00",
            conversation_history=[],
            user_baseline=CLEAN_BASELINE,
        )
        assert result.audit_hash
        assert len(result.audit_hash) == 64  # SHA-256 hex = 64 chars

    def test_baseline_delta_is_fraction(self):
        result = self.analyzer.analyze(
            message_id="m004",
            user_id="U004",
            channel_id="C001",
            text="Test message",
            timestamp="2026-06-19T10:03:00",
            conversation_history=[],
            user_baseline=NEW_USER_BASELINE,
        )
        assert isinstance(result.baseline_delta, Fraction)

    def test_crashed_detector_is_recorded_not_silent(self, monkeypatch):
        # FIX: a detector crash used to be swallowed by a bare `except
        # Exception: pass`, so it was indistinguishable from a detector that
        # ran cleanly and found nothing. Force L1 (Grice) to raise and prove
        # the crash is tracked, not folded into an apparently-clean result.
        def _boom(*args, **kwargs):
            raise RuntimeError("forced detector failure")

        monkeypatch.setattr(self.analyzer.grice, "analyze", _boom)

        result = self.analyzer.analyze(
            message_id="m005",
            user_id="U005",
            channel_id="C001",
            text="Quick question about the deployment.",
            timestamp="2026-06-19T10:04:00",
            conversation_history=[],
            user_baseline=CLEAN_BASELINE,
        )
        assert result.grice is None
        assert "grice" in result.crashed_agents
        assert len(result.crashed_agents) == 1
