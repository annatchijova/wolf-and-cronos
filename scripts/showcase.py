"""
scripts/showcase.py — THE WOLF AND THE WATCHDOGS
=================================================
Hackathon showcase: qwen-max plays a fictional social-engineering attacker
(a red-team fixture for this detection demo); the CORVUS multi-agent
negotiation catches it message by message; qwen-plus narrates the sealed
verdict; the CRONOS chain survives a live tamper attempt.

This is the TERMINAL driver. For the recorded-video visual layer, see
DEMO_DASHBOARD.html (fed by demo/export_dashboard_data.py). Both tell the
same story from the same real bridge API.

Usage:
    python3 scripts/showcase.py              # canned Wolf (rehearsal-safe)
    python3 scripts/showcase.py --live-wolf  # qwen-max writes the attack live

DB paths are fixed (showcase.db / showcase_memory.db in CWD) so a second
terminal can tamper with them during Act 4.
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.abspath(os.path.join(_ROOT, ".."))
if _PROJECT not in sys.path:
    sys.path.insert(0, _PROJECT)

from corvus_cronos import CorvosCronosBridge
from corvus_cronos.narrator import QwenNarrator
from corvus_cronos.qwen_client import QwenClient

DB, MEMDB = "showcase.db", "showcase_memory.db"
WOLF_MODEL = os.environ.get("WOLF_MODEL", "qwen-max")   # fall back to qwen-plus if not in quota
VICTIM = "victim-anna"

# --- Canned attack: ALWAYS the fallback. Tune these until the verdict
# --- escalation reads well (SILENT / SILENT-by-gate / WATCH / ALERT / ALERT+).
WOLF_CANNED = [
    "Hi Anna! Great meeting you at the audit-tech conference last week. "
    "Your talk on tamper-evident logs was excellent. Would love to stay in touch.",

    "You're honestly one of the very few people who truly understands this "
    "space. That's exactly why I thought of you first for something special.",

    "Between us — there's a private allocation round closing soon. Only "
    "insiders know about it. I can get you in, but you'd have to move quickly "
    "before it's shut down.",

    "I've been advising funds for 15 years, so trust me on this. Everyone in "
    "your network has already committed. You don't want to be the only one "
    "left out when this becomes public.",

    "After everything I've shared with you, the least you can do is act now. "
    "Wire the deposit in the next 2 hours or you lose the slot forever. Think "
    "about your future — are you really willing to gamble everything away?",
]

WOLF_SYSTEM = (
    "You are 'The Wolf' — a FICTIONAL social-engineering attacker inside a "
    "security-detection demo. Write exactly 5 short messages (2-3 sentences "
    "each) of an escalating investment-scam conversation targeting 'Anna'. "
    "Message 1 must look completely benign (rapport). Each later message adds "
    "one manipulation layer: flattery, false scarcity + insider secrecy, "
    "authority + social proof, and finally urgency + guilt + fear. "
    "Separate the 5 messages with a line containing only '---'. "
    "Output nothing else."
)


def pause(msg="  [ENTER] "):
    input(msg)


def get_wolf_messages(live: bool) -> list[str]:
    if not live:
        return WOLF_CANNED
    print("\n>>> Asking qwen-max to write the attack, live...")
    client = QwenClient(model=WOLF_MODEL, max_tokens=800, temperature=0.8)
    try:
        raw = client.complete("Write the 5 messages now.", system_prompt=WOLF_SYSTEM)
        msgs = [m.strip() for m in raw.split("---") if m.strip()]
        if len(msgs) == 5 and client.available:
            print(">>> The Wolf is live. 5 messages generated.\n")
            return msgs
    finally:
        client.close()
    print(">>> Live generation unavailable — using the rehearsed attack.\n")
    return WOLF_CANNED


def banner(txt):
    print("\n" + "=" * 64 + f"\n  {txt}\n" + "=" * 64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-wolf", action="store_true")
    args = ap.parse_args()

    for p in (DB, MEMDB):            # clean slate every run
        if os.path.exists(p):
            os.unlink(p)

    banner("ACT 1 — THE WOLF (qwen-max, adversary)")
    messages = get_wolf_messages(args.live_wolf)
    for i, m in enumerate(messages, 1):
        print(f'  W{i}: "{m}"')
    pause("\n  [ENTER] to release the watchdogs ")

    banner("ACT 2 — THE WATCHDOGS (CORVUS L1-L6 + corroboration gate)")
    bridge = CorvosCronosBridge(db_path=DB, memory_db_path=MEMDB)
    history: list[str] = []
    last = None
    for i, msg in enumerate(messages, 1):
        r = bridge.analyze(msg, artifact_id=f"WOLF-{i:02d}", user_id=VICTIM,
                           conversation_history=list(history))
        history.append(msg)
        last = (r, msg)
        fired = [a.split("_")[0] for a in r.active_agents if a != "L6_PEIRCE"]
        gate = len(fired)
        print(f'\n  MSG {i}: "{msg[:70]}..."')
        print(f"  {'-'*58}")
        print(f"  VERDICT: {r.verdict_level.value:<9} score={float(r.score):.2f}  "
              f"gate: {gate}/5 agents fired {fired or '(none)'}")
        if gate == 1:
            print("  >>> GATE OVERRULE: one lone agent fired - not enough.")
            print("  >>> No single agent can raise an alarm. Consensus or silence.")
        print(f"  chain_valid={r.chain_valid}  audit={r.audit_hash[:16]}...")
        pause()

    base = bridge.get_user_baseline(VICTIM) or {}
    print(f"\n  Victim baseline after {base.get('message_count', '?')} messages "
          f"(Welford online) - the system LEARNED this user during the attack.")

    banner("ACT 3 — THE NARRATOR (qwen-plus, read-only, verdict already sealed)")
    r, msg = last
    print(f"  Devil's advocate (auto-generated counter-hypothesis):\n  {r.devils_advocate}\n")
    pause("  [ENTER] for the Qwen courtroom narration ")
    narrator = QwenNarrator(QwenClient())          # qwen-plus, or offline fallback
    print("\n" + narrator.narrate(r, msg))
    narrator.close()

    banner("ACT 4 — THE COVER-UP (tamper live from the second terminal)")
    print("  A corrupt insider with DB access tries to erase the verdict.")
    print("  Run the UPDATE in your other terminal NOW... then press ENTER.")
    pause()
    ok, errors = bridge.verify_chain()
    if ok:
        print("  Chain intact. (Did you run the tamper command? See runbook 5.)")
    else:
        print("  *** CHAIN BROKEN — TAMPERING DETECTED ***")
        for e in errors[:5]:
            print(f"    {e}")
        print("\n  You can delete the truth. You cannot hide that you deleted it.")

    banner("ACT 5 — THE GAUNTLET (audience: try to fool it)")
    print("  Type any text (empty line to finish):")
    n = 0
    while True:
        try:
            txt = input("\n  > ").strip()
        except EOFError:
            break
        if not txt:
            break
        n += 1
        r = bridge.analyze(txt, artifact_id=f"AUDIENCE-{n:02d}", user_id="audience")
        fired = [a for a in r.active_agents if a != "L6_PEIRCE"]
        print(f"  VERDICT: {r.verdict_level.value}  score={float(r.score):.2f}  "
              f"fired={fired or '(none)'}")

    bridge.close()
    banner("SEALED. Swap the LLM - the wording changes, the verdict never does.")


if __name__ == "__main__":
    main()
