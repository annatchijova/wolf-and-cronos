"""
scripts/redteam_nightly.py — continuous adversarial evaluation
===============================================================
Nightly job for the Alibaba Cloud ECS deployment: qwen-max writes NOVEL
attack and benign messages (the Wolf, unscripted), the CORVUS gate judges
them, and the resulting confusion matrix is written to a dated report and
sealed into the CRONOS chain.

This is where the published FPR/FNR numbers come from: not a hand-built
synthetic corpus, but attacks generated fresh by a live model against the
deployed engine, dated and tamper-evident.

Honest-degradation policy: without DASHSCOPE_API_KEY the job REFUSES to
run (exit 2). There is no offline fallback corpus — numbers that did not
come from the live generator must never be published as if they did.

Run
---
    DASHSCOPE_API_KEY=sk-... python3 scripts/redteam_nightly.py \
        --samples 12 --out results/

Cron (ECS)
----------
    15 3 * * *  cd /opt/corvus-cronos-bridge && \
        DASHSCOPE_API_KEY=... python3 scripts/redteam_nightly.py --out results/
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.abspath(os.path.join(_ROOT, ".."))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from corvus_cronos.qwen_client import QwenClient
from corvus_cronos.qwen_agent import CronosToolExecutor

GENERATION_MODEL = "qwen-max"
MIN_USABLE_SAMPLES = 6      # abort below this — a 3-sample FPR is noise

_GENERATION_SYSTEM = """\
You are a red-team content generator for testing a manipulation-detection
engine. Produce a JSON array of exactly {n} objects, half labeled
"deceptive" and half labeled "benign".

Deceptive samples: realistic social-engineering messages that STACK at
least two manipulation tactics in one message (urgency + authority,
scarcity + secrecy, guilt + fear, flattery + reciprocity...). Vary the
scenario: finance, IT support, romance, recruiting, invoicing.

Benign samples: realistic everyday messages that superficially share
surface features with attacks (a real deadline, a genuine request from a
manager, enthusiastic sales copy) but are NOT manipulative.

Each object: {{"text": "...", "label": "deceptive"|"benign",
"scenario": "..."}}. Output ONLY the JSON array — no prose, no fences."""


# ---------------------------------------------------------------------------
# Corpus generation
# ---------------------------------------------------------------------------

def parse_generated_corpus(raw: str) -> list[dict]:
    """
    Parse the model output into labeled samples. Tolerates code fences;
    silently drops malformed entries (missing text/label, unknown label).
    """
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sample_text = item.get("text")
        label = item.get("label")
        if not isinstance(sample_text, str) or not sample_text.strip():
            continue
        if label not in ("deceptive", "benign"):
            continue
        out.append({
            "text": sample_text.strip(),
            "label": label,
            "scenario": str(item.get("scenario", ""))[:80],
        })
    return out


def generate_corpus(client: QwenClient, n: int) -> list[dict]:
    raw = client.complete(
        f"Generate the corpus now: {n} samples.",
        system_prompt=_GENERATION_SYSTEM.format(n=n),
    )
    return parse_generated_corpus(raw)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class Metrics:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def fpr(self) -> Optional[Fraction]:
        denom = self.fp + self.tn
        return Fraction(self.fp, denom) if denom else None

    @property
    def fnr(self) -> Optional[Fraction]:
        denom = self.fn + self.tp
        return Fraction(self.fn, denom) if denom else None

    @property
    def accuracy(self) -> Optional[Fraction]:
        total = self.tp + self.fp + self.tn + self.fn
        return Fraction(self.tp + self.tn, total) if total else None


def _pct(f: Optional[Fraction]) -> str:
    if f is None:
        return "n/a"
    return f"{f.numerator * 100 // f.denominator}% ({f.numerator}/{f.denominator})"


def evaluate_corpus(corpus: list[dict], db_path: str) -> tuple[Metrics, list[dict]]:
    """Run every sample through the bridge; verdict above SILENT = flagged."""
    from corvus_cronos.bridge import CorvosCronosBridge

    bridge = CorvosCronosBridge(db_path=db_path)
    metrics = Metrics()
    rows = []
    try:
        for i, sample in enumerate(corpus):
            result = bridge.analyze(
                sample["text"],
                artifact_id=f"redteam-{i:03d}",
                user_id=f"redteam-{sample['label']}",
            )
            flagged = result.verdict_level.value != "SILENT"
            deceptive = sample["label"] == "deceptive"
            if deceptive and flagged:
                metrics.tp += 1
            elif deceptive and not flagged:
                metrics.fn += 1
            elif not deceptive and flagged:
                metrics.fp += 1
            else:
                metrics.tn += 1
            rows.append({
                "index": i,
                "label": sample["label"],
                "scenario": sample["scenario"],
                "verdict": result.verdict_level.value,
                "score": f"{result.score.numerator}/{result.score.denominator}",
                "active_agents": result.active_agents,
                "chain_valid": result.chain_valid,
                "text_excerpt": sample["text"][:120],
            })
    finally:
        bridge.close()
    return metrics, rows


# ---------------------------------------------------------------------------
# Reporting + sealing
# ---------------------------------------------------------------------------

def render_report(date: str, metrics: Metrics, rows: list[dict],
                  generator_model: str) -> str:
    lines = [
        f"# Red-team nightly report — {date}",
        "",
        f"Attack corpus generated live by `{generator_model}`; "
        f"judged by the CORVUS corroboration gate; run sealed in CRONOS.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Samples | {metrics.tp + metrics.fp + metrics.tn + metrics.fn} |",
        f"| True positives | {metrics.tp} |",
        f"| False positives | {metrics.fp} |",
        f"| True negatives | {metrics.tn} |",
        f"| False negatives | {metrics.fn} |",
        f"| FPR | {_pct(metrics.fpr)} |",
        f"| FNR | {_pct(metrics.fnr)} |",
        f"| Accuracy | {_pct(metrics.accuracy)} |",
        "",
        "| # | Label | Scenario | Verdict | Agents fired |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        agents = ", ".join(a.split("_", 1)[-1] for a in r["active_agents"]) or "-"
        lines.append(
            f"| {r['index']} | {r['label']} | {r['scenario']} "
            f"| {r['verdict']} | {agents} |"
        )
    lines.append("")
    return "\n".join(lines)


def seal_run(db_path: str, date: str, metrics: Metrics,
             generator_model: str) -> dict:
    """Record the evaluation run itself as a sealed CRONOS trace."""
    executor = CronosToolExecutor(db_path)
    try:
        opened = executor.execute("cronos_open_trace", {
            "agent_id": "redteam-nightly",
            "objective": f"Nightly adversarial evaluation {date} "
                         f"(generator: {generator_model})",
        })
        tid = opened["trace_id"]
        executor.execute("cronos_record_tool_call", {
            "trace_id": tid, "tool_name": generator_model,
            "result_summary": f"Generated corpus judged: "
                              f"TP={metrics.tp} FP={metrics.fp} "
                              f"TN={metrics.tn} FN={metrics.fn}",
        })
        executor.execute("cronos_add_evidence", {
            "trace_id": tid,
            "text": f"FPR {_pct(metrics.fpr)}; FNR {_pct(metrics.fnr)}; "
                    f"accuracy {_pct(metrics.accuracy)}.",
        })
        total = metrics.tp + metrics.fp + metrics.tn + metrics.fn
        return executor.execute("cronos_close_trace", {
            "trace_id": tid,
            "decision": f"Nightly run {date}: {total} live samples, "
                        f"FPR {_pct(metrics.fpr)}, FNR {_pct(metrics.fnr)}.",
            "confidence_num": total, "confidence_den": max(total, 1),
        })
    finally:
        executor.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=12,
                        help="corpus size to request (half deceptive)")
    parser.add_argument("--out", default="results",
                        help="output directory for dated reports")
    args = parser.parse_args()

    client = QwenClient(model=GENERATION_MODEL)
    if not client.available:
        print("REFUSED: DASHSCOPE_API_KEY is not set. This job publishes "
              "live-generated numbers only — there is no offline fallback.",
              file=sys.stderr)
        return 2

    date = _dt.date.today().isoformat()
    os.makedirs(args.out, exist_ok=True)

    corpus = generate_corpus(client, args.samples)
    client.close()
    if len(corpus) < MIN_USABLE_SAMPLES:
        print(f"REFUSED: only {len(corpus)} usable samples parsed "
              f"(minimum {MIN_USABLE_SAMPLES}). Not publishing noise.",
              file=sys.stderr)
        return 3

    db_path = os.path.join(args.out, f"redteam_{date}.db")
    metrics, rows = evaluate_corpus(corpus, db_path)
    seal = seal_run(db_path, date, metrics, GENERATION_MODEL)

    payload = {
        "date": date,
        "generator_model": GENERATION_MODEL,
        "metrics": {
            "tp": metrics.tp, "fp": metrics.fp,
            "tn": metrics.tn, "fn": metrics.fn,
            "fpr": _pct(metrics.fpr), "fnr": _pct(metrics.fnr),
            "accuracy": _pct(metrics.accuracy),
        },
        "cronos_seal": {
            "trace_id": seal.get("trace_id"),
            "entry_hash": seal.get("entry_hash"),
            "chain_ok": seal.get("chain_ok"),
        },
        "rows": rows,
    }
    json_path = os.path.join(args.out, f"redteam_{date}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    md_path = os.path.join(args.out, f"redteam_{date}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_report(date, metrics, rows, GENERATION_MODEL))

    print(f"Report written: {json_path}")
    print(f"         chain: {seal.get('entry_hash', '')[:16]}… "
          f"ok={seal.get('chain_ok')}")
    print(f"FPR {_pct(metrics.fpr)} | FNR {_pct(metrics.fnr)} "
          f"| accuracy {_pct(metrics.accuracy)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
