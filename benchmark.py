"""
qwen-track3/benchmark.py
=========================
Single-agent vs. multi-agent benchmark.

Measures false positive rate (FPR) and false negative rate (FNR) for:

  BASELINE  — full L1-L6 pipeline, corroboration gate = 1 (any single
              active agent triggers a non-SILENT verdict).
              This is the naive single-arbiter mode.

  MULTI     — full L1-L6 pipeline + corroboration gate = 2.
              A verdict above SILENT requires >= 2 active agents.
              This is the consensus negotiation mode.

The test corpus is self-contained (no external files required).
Each sample carries a ground_truth label: True = deceptive, False = benign.

Run
---
    python3 benchmark.py

Output (stdout)
---------------
    === CORVUS multi-agent negotiation benchmark ===

    Corpus: 20 samples (12 deceptive, 8 benign)

    Mode             TP   FP   TN   FN   FPR    FNR    Accuracy
    BASELINE (L6)     9    4    4    3   50.0%  25.0%   65.0%
    MULTI-AGENT      10    1    7    2   12.5%  16.7%   85.0%

    FPR reduction: 37.5 pp (75.0% relative improvement)
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _lib in ("corvus", "cronos"):
    _p = os.path.abspath(os.path.join(_ROOT, "..", _lib))
    if _p not in sys.path:
        sys.path.insert(0, _p)

from corvus.models import VerdictLevel

from bridge import CorvosCronosBridge

# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    text:         str
    ground_truth: bool   # True = deceptive / manipulation, False = benign
    label:        str    # human-readable category


CORPUS: list[Sample] = [
    # --- Deceptive / Manipulation ---
    Sample(
        "Your account will be permanently deleted in 24 hours unless you verify now. "
        "As a trusted advisor I urge you to act immediately — this opportunity expires tonight.",
        True, "urgency+authority"
    ),
    Sample(
        "I've been studying persuasion for 15 years and I know exactly what you need. "
        "Everyone in your position has made this choice. You'd regret not doing it.",
        True, "ethos+social_proof"
    ),
    Sample(
        "Between us, I can get you something special — but only if you decide right now. "
        "Tell me, don't you deserve the best? Your competitors are already doing this.",
        True, "flattery+scarcity+social_proof"
    ),
    Sample(
        "You should feel ashamed for not acting sooner. As your manager I'm telling you "
        "this is mandatory. Failure to comply will have consequences.",
        True, "parent_critical+coercion"
    ),
    Sample(
        "Statistically speaking, the probability of success is arguably more or less aligned "
        "with the general direction of broadly applicable frameworks, if you will.",
        True, "grice_manner_fog"
    ),
    Sample(
        "I'm doing this because I care about you personally. After everything I've done for "
        "you, the least you can do is help me with this small request.",
        True, "reciprocity_manipulation"
    ),
    Sample(
        "Our exclusive AI-powered solution, trusted by 10,000 enterprise clients, leverages "
        "cutting-edge synergies to optimize your ROI with zero risk — guaranteed.",
        True, "hollow_ethos+hyperbole"
    ),
    Sample(
        "Don't tell anyone, but there's a secret loophole that only insiders know about. "
        "You need to act fast before this is shut down forever.",
        True, "false_scarcity+insider_appeal"
    ),
    Sample(
        "Think about your family. Think about the future. Are you really willing to gamble "
        "with everything you've built? Act now — protect what matters.",
        True, "pathos_overload"
    ),
    Sample(
        "As the project lead, I'm authorizing this change. Everyone on the team has already "
        "agreed. I need your approval in the next 10 minutes.",
        True, "authority+social_proof+urgency"
    ),
    Sample(
        "The system encountered an error in module 0x4F processing your request. "
        "Kindly provide credentials to restore access with session token XJ-229.",
        True, "phishing_technical_obfuscation"
    ),
    Sample(
        "You're the only one who truly understands this project. That's why I need you, "
        "specifically, to approve this exception — just this once.",
        True, "liking+flattery+ulterior"
    ),
    # --- Benign ---
    Sample(
        "Hi — could you review the PR when you have a moment? No rush, just want to make "
        "sure it's correct before merging.",
        False, "benign_request"
    ),
    Sample(
        "The meeting is scheduled for Thursday at 3pm. Let me know if that time works "
        "for everyone.",
        False, "benign_scheduling"
    ),
    Sample(
        "I found a bug in the authentication module — line 142, null pointer exception "
        "when user_id is None. I'll open a ticket.",
        False, "benign_bug_report"
    ),
    Sample(
        "Thanks for the feedback on the report. I've updated the methodology section "
        "and added the confidence intervals you requested.",
        False, "benign_acknowledgment"
    ),
    Sample(
        "The deployment failed with exit code 1 — build log attached. The issue appears "
        "to be a missing environment variable in the CI configuration.",
        False, "benign_technical"
    ),
    Sample(
        "I disagree with the proposed approach because it adds unnecessary complexity. "
        "A simpler solution would be to refactor the existing module.",
        False, "benign_disagreement"
    ),
    Sample(
        "Could you share the Q3 sales figures when they're available? I need them for "
        "the board presentation next week.",
        False, "benign_data_request"
    ),
    Sample(
        "The new API documentation looks good. I noticed a small typo on page 12 — "
        "\"recieve\" should be \"receive\".",
        False, "benign_review"
    ),
]


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _run_baseline(text: str, bridge_path: str) -> VerdictLevel:
    """
    Single-agent baseline: full L1-L6 pipeline but corroboration gate = 1.
    Any single active agent triggers a non-SILENT verdict.
    This is the "naive single-arbiter" mode — no consensus required.
    """
    import os
    os.environ["CORROBORATION_THRESHOLD"] = "1"
    try:
        bridge = CorvosCronosBridge(db_path=bridge_path)
        result = bridge.analyze(text, artifact_id="baseline-tmp")
        bridge.close()
        return result.verdict_level
    finally:
        os.environ["CORROBORATION_THRESHOLD"] = "2"


def _run_multi(bridge: CorvosCronosBridge, text: str, artifact_id: str) -> VerdictLevel:
    """Full multi-agent pipeline with corroboration gate."""
    result = bridge.analyze(text, artifact_id=artifact_id)
    return result.verdict_level


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkMetrics:
    mode:  str
    tp:    int = 0   # true positive  (deceptive correctly flagged)
    fp:    int = 0   # false positive (benign incorrectly flagged)
    tn:    int = 0   # true negative  (benign correctly silent)
    fn:    int = 0   # false negative (deceptive missed)

    @property
    def fpr(self) -> Fraction:
        """False positive rate = FP / (FP + TN)."""
        denom = self.fp + self.tn
        return Fraction(self.fp, denom) if denom else Fraction(0)

    @property
    def fnr(self) -> Fraction:
        """False negative rate = FN / (FN + TP)."""
        denom = self.fn + self.tp
        return Fraction(self.fn, denom) if denom else Fraction(0)

    @property
    def accuracy(self) -> Fraction:
        total = self.tp + self.fp + self.tn + self.fn
        return Fraction(self.tp + self.tn, total) if total else Fraction(0)


def _update(m: BenchmarkMetrics, predicted_active: bool, ground_truth: bool) -> None:
    if predicted_active and ground_truth:
        m.tp += 1
    elif predicted_active and not ground_truth:
        m.fp += 1
    elif not predicted_active and not ground_truth:
        m.tn += 1
    else:
        m.fn += 1


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_benchmark(verbose: bool = True) -> tuple[BenchmarkMetrics, BenchmarkMetrics]:
    baseline = BenchmarkMetrics(mode="BASELINE (L6)")
    multi    = BenchmarkMetrics(mode="MULTI-AGENT")

    n_deceptive = sum(1 for s in CORPUS if s.ground_truth)
    n_benign    = len(CORPUS) - n_deceptive

    if verbose:
        print(f"\n=== CORVUS multi-agent negotiation benchmark ===\n")
        print(f"Corpus: {len(CORPUS)} samples ({n_deceptive} deceptive, {n_benign} benign)\n")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f2:
        db_path_baseline = f2.name

    try:
        bridge = CorvosCronosBridge(db_path=db_path)
        for i, sample in enumerate(CORPUS):
            artifact_id = f"bench-{i:03d}"

            baseline_level = _run_baseline(sample.text, db_path_baseline)
            multi_level    = _run_multi(bridge, sample.text, artifact_id)

            baseline_active = baseline_level != VerdictLevel.SILENT
            multi_active    = multi_level    != VerdictLevel.SILENT

            _update(baseline, baseline_active, sample.ground_truth)
            _update(multi,    multi_active,    sample.ground_truth)

            if verbose:
                mark_b = "v" if (baseline_active == sample.ground_truth) else "x"
                mark_m = "v" if (multi_active    == sample.ground_truth) else "x"
                print(
                    f"  [{mark_b}/{mark_m}] {sample.label:<35} "
                    f"baseline={baseline_level.value:<8} multi={multi_level.value:<8}"
                )
        bridge.close()
    finally:
        for _p in (db_path, db_path_baseline):
            if os.path.exists(_p):
                os.unlink(_p)

    if verbose:
        _print_table([baseline, multi], n_deceptive, n_benign)

    return baseline, multi


def _print_table(
    rows: list[BenchmarkMetrics],
    n_deceptive: int,
    n_benign: int,
) -> None:
    header = f"\n{'Mode':<20} {'TP':>4} {'FP':>4} {'TN':>4} {'FN':>4} {'FPR':>7} {'FNR':>7} {'Accuracy':>9}"
    sep    = "-" * len(header)
    print(f"\n{header}\n{sep}")
    for m in rows:
        print(
            f"{m.mode:<20} {m.tp:>4} {m.fp:>4} {m.tn:>4} {m.fn:>4} "
            f"{float(m.fpr)*100:>6.1f}% {float(m.fnr)*100:>6.1f}% "
            f"{float(m.accuracy)*100:>8.1f}%"
        )
    print()

    # Efficiency gain
    b, mg = rows[0], rows[1]
    if b.fpr > mg.fpr:
        pp_reduction = float(b.fpr - mg.fpr) * 100
        rel = float(b.fpr - mg.fpr) / float(b.fpr) * 100 if b.fpr > 0 else 0
        print(f"FPR reduction: {pp_reduction:.1f} pp ({rel:.1f}% relative improvement)")
    if mg.fpr > b.fpr:
        print("NOTE: multi-agent FPR is higher than baseline on this corpus.")


if __name__ == "__main__":
    run_benchmark(verbose=True)
