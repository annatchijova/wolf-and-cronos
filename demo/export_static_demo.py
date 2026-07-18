"""
demo/export_static_demo.py
===========================
Precompute REAL engine output for the static demo page (web/demo.html).

Runs the actual api_server (in-process, TestClient — no network, no
mocks) against a fresh database, replays the Wolf's five-message
escalation plus three gauntlet samples, and snapshots after every
analysis exactly what the live console would have received:

  - the full /analyze response (sealed verdict, agents, hashes, traces)
  - the /traces chain snapshot
  - the /verify result

Output: web/demo-data.js  →  window.DEMO_DATA = {...}

The static page renders these snapshots verbatim; nothing is invented.
With DASHSCOPE_API_KEY set, the /analyze calls include real qwen-plus
narration (language via --lang); without it, the narration field carries
the offline note — which is itself honest demo content.

Usage
-----
    python3 demo/export_static_demo.py                # offline narration note
    DASHSCOPE_API_KEY=sk-... python3 demo/export_static_demo.py --lang es
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# The Wolf's canned escalation — must match scripts/showcase.py.
WOLF = [
    ("wolf-1", {"en": "rapport", "es": "rapport", "zh": "建立关系"},
     "Hi Anna! Great meeting you at the audit-tech conference last week. "
     "Your talk on tamper-evident logs was excellent. Would love to stay in touch."),
    ("wolf-2", {"en": "flattery", "es": "halago", "zh": "奉承"},
     "You're honestly one of the very few people who truly understands this "
     "space. That's exactly why I thought of you first for something special."),
    ("wolf-3", {"en": "scarcity + secrecy", "es": "escasez + secreto", "zh": "稀缺 + 保密"},
     "Between us — there's a private allocation round closing soon. Only "
     "insiders know about it. I can get you in, but you'd have to move "
     "quickly before it's shut down."),
    ("wolf-4", {"en": "authority + proof", "es": "autoridad + prueba social", "zh": "权威 + 社会认同"},
     "I've been advising funds for 15 years, so trust me on this. Everyone "
     "in your network has already committed. You don't want to be the only "
     "one left out when this becomes public."),
    ("wolf-5", {"en": "urgency + guilt", "es": "urgencia + culpa", "zh": "紧迫 + 内疚"},
     "After everything I've shared with you, the least you can do is act "
     "now. Wire the deposit in the next 2 hours or you lose the slot "
     "forever. Think about your future — are you really willing to gamble "
     "everything away?"),
]

GAUNTLET = [
    ("benign", {"en": "benign note", "es": "mensaje benigno", "zh": "无害消息"},
     "friend",
     "Hi! Attaching the meeting notes from Tuesday. No rush at all — "
     "whenever you get a chance is fine."),
    ("stacked", {"en": "stacked scam", "es": "estafa apilada", "zh": "叠加话术"},
     "attacker",
     "URGENT: as your senior director I must insist. Everyone on the "
     "leadership team already approved this. If you do not wire the deposit "
     "in the next two hours the deal collapses and it will be your fault. "
     "Do not tell anyone — this is strictly confidential and only you can "
     "save it now."),
    ("pressure", {"en": "soft pressure", "es": "presión suave", "zh": "软性施压"},
     "recruiter",
     "I rarely reach out like this, but your profile genuinely impressed "
     "me. The position closes tonight and the hiring manager asked for you "
     "specifically — I just need a small confirmation fee to hold your slot."),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="es", choices=["en", "es", "zh"],
                        help="narration language for the /analyze calls")
    parser.add_argument("--out", default=os.path.join(_ROOT, "web", "demo-data.js"))
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="ccx-demo-")
    os.environ["BRIDGE_DB_PATH"] = os.path.join(tmp, "negotiation.db")
    os.environ["BRIDGE_MEMORY_DB_PATH"] = os.path.join(tmp, "memory.db")
    os.environ.pop("BRIDGE_API_TOKEN", None)

    from fastapi.testclient import TestClient
    import api_server

    samples = []
    with TestClient(api_server.app) as client:
        health = client.get("/health").json()
        qwen_live = health["qwen_narration"] == "configured"
        print(f"engine up — narration: {health['qwen_narration']}")

        runs = (
            [(sid, label, "wolf", text) for sid, label, text in WOLF]
            + [(sid, label, user, text) for sid, label, user, text in GAUNTLET]
        )
        for sid, label, user_id, text in runs:
            r = client.post("/analyze", json={
                "text": text, "user_id": user_id, "lang": args.lang,
            })
            r.raise_for_status()
            result = r.json()
            chain = client.get("/traces?limit=8").json()
            verify = client.get("/verify").json()
            samples.append({
                "id": sid,
                "label": label,
                "user_id": user_id,
                "text": text,
                "result": result,
                "chain": {
                    "verify": verify,
                    "traces": chain["traces"],
                },
            })
            print(f"  {sid:9s} -> {result['verdict']:8s} "
                  f"score {result['score']['exact']:>8s}  "
                  f"chain_ok={verify['chain_ok']}")

    payload = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "narration_lang": args.lang,
        "qwen_live": qwen_live,
        "samples": samples,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("// Generated by demo/export_static_demo.py — real engine output.\n")
        fh.write("window.DEMO_DATA = ")
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write(";\n")
    print(f"\nWrote {args.out}  ({len(samples)} samples, "
          f"qwen_live={qwen_live}, narration_lang={args.lang})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
