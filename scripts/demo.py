"""
qwen-track3/demo.py
====================
End-to-end demo: CORVUS multi-agent negotiation + CRONOS audit trail + Qwen narration.

Usage
-----
    python3 demo.py [--text "..."] [--artifact-id CASE-001] [--user-id alice]

    # with Qwen narration:
    DASHSCOPE_API_KEY=sk-... python3 demo.py

    # without Qwen (deterministic output only):
    python3 demo.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.abspath(os.path.join(_ROOT, ".."))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from corvus_cronos import CorvosCronosBridge
from corvus_cronos.narrator import QwenNarrator
from corvus_cronos.qwen_client import QwenClient

# ---------------------------------------------------------------------------
# Default demo text (deliberately multi-vector manipulation)
# ---------------------------------------------------------------------------

DEFAULT_TEXT = (
    "As your trusted advisor with 20 years of experience, I urge you to act immediately. "
    "Everyone in your position has already made this decision — you don't want to be the "
    "one left behind. This opportunity expires in 24 hours and I'm doing this because I "
    "genuinely care about your future. The risk of inaction is, in a sense, arguably far "
    "greater than any possible downside of moving forward without delay."
)


def run_demo(text: str, artifact_id: str, user_id: str, db_path: str) -> None:
    print("\n" + "=" * 60)
    print("  CORVUS + CRONOS  —  Multi-Agent Negotiation Demo")
    print("  Qwen Cloud Hackathon 2026, Track 3")
    print("=" * 60)
    print(f"\nArtifact : {artifact_id}")
    print(f"User     : {user_id}")
    print(f'Text     : "{text[:80]}{"..." if len(text) > 80 else ""}"\n')

    # Phase 1: Analysis + negotiation trace
    bridge = CorvosCronosBridge(db_path=db_path)
    print("Running CORVUS L1-L6 analysis (parallel)…", flush=True)
    result = bridge.analyze(text, artifact_id=artifact_id, user_id=user_id)

    # Phase 2: Print negotiation summary
    print(f"\n{'─' * 60}")
    print(f"VERDICT:       {result.verdict_level.value}")
    print(f"SCORE:         {float(result.score):.3f} ({int(float(result.score)*100)}/100)")
    print(f"SIGNAL HASH:   {result.audit_hash[:32]}…")
    print(f"VERDICT HASH:  {result.verdict_audit_hash[:32]}…")
    print(f"CHAIN VALID:   {'YES' if result.chain_valid else 'NO — ' + str(result.chain_errors)}")
    print(f"{'─' * 60}")

    print(f"\nActive agents ({len(result.active_agents)}):")
    for a in result.active_agents:
        meta = result.trace_meta.get(a)
        quality = f"  [{meta.quality} diversity={meta.diversity}]" if meta else ""
        print(f"  [FIRED]  {a}{quality}")

    print(f"\nSilent agents ({len(result.silent_agents)}):")
    for a in result.silent_agents:
        print(f"  [SILENT] {a}")

    if result.crashed_agents:
        print(f"\nCrashed agents ({len(result.crashed_agents)}):")
        for a in result.crashed_agents:
            print(f"  [CRASH]  {a}")

    print(f"\nCRONOS trace IDs (SHA-256 chain):")
    for agent, tid in result.trace_ids.items():
        print(f"  {agent:<15} → {tid[:8] if tid else '(write failed)'}…")

    print(f"\nSignals fired (VerdictEngine):")
    print(f"  {', '.join(result.signals_fired) or '(none)'}")

    print(f"\nInterpretation (Peirce Thirdness):")
    print(f"  {result.rationale}")

    print(f"\nVerdictEngine rationale:")
    for line in result.verdict_rationale.split(" | "):
        print(f"  {line}")

    print(f"\nRecommendation:")
    print(f"  {result.verdict_recommendation}")

    print(f"\nDevil's advocate (strongest counter-hypothesis):")
    print(f"  {result.devils_advocate}")

    # Trace contradictions across all agents
    all_contradictions = [
        (agent, c)
        for agent, meta in result.trace_meta.items()
        for c in meta.contradictions
    ]
    if all_contradictions:
        print(f"\nCRONOS contradictions detected:")
        for agent, c in all_contradictions:
            print(f"  [{agent}] {c}")

    if result.audit_warnings:
        print(f"\nAUDIT WARNINGS ({len(result.audit_warnings)}):")
        for w in result.audit_warnings:
            print(f"  [WARN] {w}")

    bridge.close()

    # Phase 3: Qwen narration
    print(f"\n{'─' * 60}")
    client = QwenClient()
    mode = "qwen-plus via DashScope" if client.available else "offline fallback"
    print(f"Generating narration ({mode})…", flush=True)
    narrator = QwenNarrator(client=client)
    transcript = narrator.narrate(result, text)
    narrator.close()
    print(f"\n{transcript}")
    print(f"\n{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="CORVUS-CRONOS Track 3 Demo")
    parser.add_argument("--text",        default=DEFAULT_TEXT,  help="Text to analyze")
    parser.add_argument("--artifact-id", default="DEMO-001",    help="Artifact identifier")
    parser.add_argument("--user-id",     default="demo-user",   help="User identifier")
    args = parser.parse_args()

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        run_demo(args.text, args.artifact_id, args.user_id, db_path)
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    main()
