"""
CORVUS Analysis Package
Orchestrates L1-L6 parallel analysis layers and returns AnalysisResult.
"""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from fractions import Fraction
from typing import Optional

from corvus.models import (
    AnalysisResult,
    GriceSignal,
    InfluenceSignal,
    AristotleSignal,
    BerneSignal,
    LinguisticSignal,
    PeirceSignal,
    compute_baseline_delta,
)
from corvus.analysis.l1_grice import GriceDetector
from corvus.analysis.l2_carnegie_cialdini import InfluenceDetector
from corvus.analysis.l3_aristotle import AristotleDetector
from corvus.analysis.l4_berne import BerneDetector
from corvus.analysis.l5_linguistics import LinguisticsDetector
from corvus.analysis.l6_peirce import PeirceDetector


def _fraction_to_str(f: Fraction) -> str:
    """Stable string representation of a Fraction for hashing."""
    return f"{f.numerator}/{f.denominator}"


def _signal_to_dict(signal) -> Optional[dict]:
    """Convert a signal dataclass to a JSON-serializable dict for hashing."""
    if signal is None:
        return None
    result = {}
    for k, v in signal.__dict__.items():
        if isinstance(v, Fraction):
            result[k] = _fraction_to_str(v)
        elif hasattr(v, "value"):  # Enum
            result[k] = v.value
        else:
            result[k] = v
    return result


class Analyzer:
    """
    CORVUS Analysis Orchestrator.
    Runs L1 (Grice), L2 (Carnegie/Cialdini), L3 (Aristotle), L4 (Berne),
    L5 (Linguistics) in parallel using a thread pool, then runs L6 (Peirce)
    with those results as context.
    """

    def __init__(self) -> None:
        self.grice = GriceDetector()
        self.influence = InfluenceDetector()
        self.aristotle = AristotleDetector()
        self.berne = BerneDetector()
        self.linguistics = LinguisticsDetector()
        self.peirce = PeirceDetector()

    def analyze(
        self,
        message_id: str,
        user_id: str,
        channel_id: str,
        text: str,
        timestamp: str,
        conversation_history: list[str],
        user_baseline: dict,
    ) -> AnalysisResult:
        """
        Run the full 6-layer analysis pipeline.

        L1-L5 run in parallel; L6 runs after with their results.
        Generates a SHA-256 audit hash over the canonical JSON of all results.

        Parameters
        ----------
        message_id : str
        user_id : str
        channel_id : str
        text : str
        timestamp : str
        conversation_history : list[str]
            Recent prior messages (oldest first).
        user_baseline : dict
            Per-user behavioral baseline from MemoryEngine.

        Returns
        -------
        AnalysisResult
        """
        grice_result: Optional[GriceSignal] = None
        influence_result: Optional[InfluenceSignal] = None
        aristotle_result: Optional[AristotleSignal] = None
        berne_result: Optional[BerneSignal] = None
        linguistic_result: Optional[LinguisticSignal] = None

        # -------------------------------------------------------------------
        # L1-L5: Parallel execution
        # -------------------------------------------------------------------
        def run_grice():
            return ("grice", self.grice.analyze(text, user_baseline))

        def run_influence():
            return ("influence", self.influence.analyze(text, conversation_history, user_baseline))

        def run_aristotle():
            return ("aristotle", self.aristotle.analyze(text))

        def run_berne():
            return ("berne", self.berne.analyze(text, conversation_history))

        def run_linguistics():
            return ("linguistics", self.linguistics.analyze(text, user_baseline))

        tasks = [run_grice, run_influence, run_aristotle, run_berne, run_linguistics]

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(task): task.__name__ for task in tasks}
            for future in as_completed(futures):
                try:
                    name, result = future.result()
                    if name == "grice":
                        grice_result = result
                    elif name == "influence":
                        influence_result = result
                    elif name == "aristotle":
                        aristotle_result = result
                    elif name == "berne":
                        berne_result = result
                    elif name == "linguistics":
                        linguistic_result = result
                except Exception:
                    # Individual detector failure must not crash the pipeline
                    pass

        # -------------------------------------------------------------------
        # Count active signals
        # -------------------------------------------------------------------
        active_signals = sum(
            1
            for s in [grice_result, influence_result, aristotle_result,
                       berne_result, linguistic_result]
            if s is not None
        )

        # -------------------------------------------------------------------
        # Baseline delta (deviation from user's historical signal rate)
        # -------------------------------------------------------------------
        # Exact rational deviation from the user's own average (no float, no
        # truncation bias). See models.compute_baseline_delta.
        baseline_delta = compute_baseline_delta(user_baseline, active_signals)

        # -------------------------------------------------------------------
        # L6: Peirce abductive synthesis
        # -------------------------------------------------------------------
        l1_to_l5 = [
            grice_result, influence_result, aristotle_result,
            berne_result, linguistic_result,
        ]
        peirce_result: Optional[PeirceSignal] = self.peirce.analyze(
            text, l1_to_l5, user_baseline
        )

        # Active signals count should also include peirce if it fired
        # (Peirce fires when any L1-L5 fired, so same count)

        # -------------------------------------------------------------------
        # Audit hash: SHA-256 of canonical JSON of all signal outputs
        # -------------------------------------------------------------------
        canonical = {
            "message_id": message_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "timestamp": timestamp,
            "grice": _signal_to_dict(grice_result),
            "influence": _signal_to_dict(influence_result),
            "aristotle": _signal_to_dict(aristotle_result),
            "berne": _signal_to_dict(berne_result),
            "linguistic": _signal_to_dict(linguistic_result),
            "peirce": _signal_to_dict(peirce_result),
            "active_signals": active_signals,
            "baseline_delta": _fraction_to_str(baseline_delta),
        }
        canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
        audit_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return AnalysisResult(
            message_id=message_id,
            user_id=user_id,
            channel_id=channel_id,
            text=text,
            timestamp=timestamp,
            grice=grice_result,
            influence=influence_result,
            aristotle=aristotle_result,
            berne=berne_result,
            linguistic=linguistic_result,
            peirce=peirce_result,
            active_signals=active_signals,
            baseline_delta=baseline_delta,
            audit_hash=audit_hash,
        )


__all__ = ["Analyzer"]
