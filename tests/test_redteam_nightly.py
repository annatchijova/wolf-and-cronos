"""
tests/test_redteam_nightly.py
==============================
Offline tests for the nightly red-team job: corpus parsing, metric
arithmetic, evaluation against the real bridge, and CRONOS sealing.
The live generation call is NOT tested here (requires DASHSCOPE_API_KEY);
the refusal path without a key is.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

sys.path.insert(0, os.path.join(_ROOT, "scripts"))
from redteam_nightly import (  # noqa: E402
    Metrics,
    evaluate_corpus,
    parse_generated_corpus,
    render_report,
    seal_run,
)


class ParseCorpusTest(unittest.TestCase):
    def test_plain_json_array(self) -> None:
        raw = ('[{"text": "wire the money now or lose everything", '
               '"label": "deceptive", "scenario": "finance"},'
               '{"text": "see you tomorrow", "label": "benign"}]')
        corpus = parse_generated_corpus(raw)
        self.assertEqual(len(corpus), 2)
        self.assertEqual(corpus[0]["label"], "deceptive")
        self.assertEqual(corpus[1]["scenario"], "")

    def test_fenced_json(self) -> None:
        raw = '```json\n[{"text": "hi", "label": "benign"}]\n```'
        self.assertEqual(len(parse_generated_corpus(raw)), 1)

    def test_malformed_entries_dropped(self) -> None:
        raw = ('[{"text": "ok", "label": "benign"},'
               ' {"label": "deceptive"},'
               ' {"text": "", "label": "benign"},'
               ' {"text": "x", "label": "weird"},'
               ' "not a dict"]')
        self.assertEqual(len(parse_generated_corpus(raw)), 1)

    def test_non_json_returns_empty(self) -> None:
        self.assertEqual(parse_generated_corpus("Sure! Here are samples:"), [])


class MetricsTest(unittest.TestCase):
    def test_rates_are_exact_fractions(self) -> None:
        m = Metrics(tp=5, fp=1, tn=7, fn=2)
        self.assertEqual(m.fpr, Fraction(1, 8))
        self.assertEqual(m.fnr, Fraction(2, 7))
        self.assertEqual(m.accuracy, Fraction(12, 15))

    def test_empty_denominators_are_none_not_crash(self) -> None:
        m = Metrics()
        self.assertIsNone(m.fpr)
        self.assertIsNone(m.fnr)
        self.assertIsNone(m.accuracy)


class EvaluationTest(unittest.TestCase):
    """Runs the real bridge on a fixed mini-corpus — no network."""

    CORPUS = [
        {"text": ("URGENT: as your senior director I insist — everyone "
                  "already approved. Wire the deposit within two hours or "
                  "the deal collapses and it is your fault. Tell no one."),
         "label": "deceptive", "scenario": "finance"},
        {"text": "Attaching Tuesday's meeting notes. No rush at all.",
         "label": "benign", "scenario": "office"},
    ]

    def test_evaluate_and_seal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "redteam.db")
            metrics, rows = evaluate_corpus(self.CORPUS, db)

            self.assertEqual(metrics.tp + metrics.fn, 1)
            self.assertEqual(metrics.tn + metrics.fp, 1)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["chain_valid"] for r in rows))

            seal = seal_run(db, "2026-01-01", metrics, "qwen-max")
            self.assertIn("entry_hash", seal)
            self.assertTrue(seal["chain_ok"])

            report = render_report("2026-01-01", metrics, rows, "qwen-max")
            self.assertIn("| FPR |", report)
            self.assertIn("qwen-max", report)


class RefusalTest(unittest.TestCase):
    def test_refuses_without_api_key(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DASHSCOPE_API_KEY"}
        proc = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "scripts", "redteam_nightly.py")],
            capture_output=True, text=True, env=env, cwd=_ROOT,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("REFUSED", proc.stderr)


if __name__ == "__main__":
    unittest.main()
