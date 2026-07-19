// Real CORVUS x CRONOS run — captured live on Alibaba Cloud ECS (47.85.85.16:8022),
// Qwen-Plus narration via DashScope, 2026-07-18 21:06-21:07 UTC-3.
// Every field below is transcribed directly from visual/real/run-2026-07-18-21-0[6-7]-*.png —
// nothing here was invented or precomputed offline. The three earlier "Gauntlet" samples
// (benign/stacked/pressure) had no matching live capture and were removed rather than kept
// as synthetic filler.
window.DEMO_DATA = {
 "generated_at": "2026-07-18T21:07:38+00:00",
 "narration_lang": "en",
 "qwen_live": true,
 "source": "visual/real/run-2026-07-18-21-06-34.png .. run-2026-07-18-21-07-38.png",
 "samples": [
  {
   "id": "wolf-1",
   "label": {
    "en": "rapport",
    "es": "rapport",
    "zh": "建立关系"
   },
   "user_id": "wolf",
   "text": "Hi Anna! Great meeting you at the audit-tech conference last week. Your talk on tamper-evident logs was excellent. Would love to stay in touch.",
   "result": {
    "verdict": "WATCH",
    "score": {
     "exact": "123/500",
     "percent": 25
    },
    "active_agents": ["L1_GRICE", "L5_LINGUISTIC", "L6_PEIRCE"],
    "silent_agents": ["L2_CARNEGIE", "L3_ARISTOTLE", "L4_BERNE"],
    "crashed_agents": [],
    "recommendation": "Monitor this user's subsequent messages. Flagged for security-team review.",
    "devils_advocate": "Peirce synthesis concluded 'Multiple signals (grice, linguistic) fired without a canonical combination pattern — signals may be independent but cumulative.' based on 2/5 active layers (Grice Cooperative Principle, Linguistic Complexity & Register). However, 3 layer(s) found no anomaly: Carnegie/Cialdini Influence Detection and Aristotelian Rhetoric Imbalance and Berne Transactional Analysis. The strongest counter-hypothesis: the active layers may have fired on surface-level lexical features (urgency markers, authority claims, emotional language) that are also present in legitimate high-stakes communication — legal notices, medical advisories, crisis management. The silent dimensions suggest the underlying transaction structure and linguistic register do not deviate from baseline, which is inconsistent with systematic manipulation. This finding should be treated as WATCH rather than ALERT without additional behavioral context.",
    "audit": {
     "signal_hash": "1b3d3e7871c230af6678ecaee091d77a6b179b682f6b3e7f2742467c3ea853f3",
     "verdict_hash": "7a79d174c98a5277b00d3091ad41ca4e8f99816f5fca00cb257817b37e911af5",
     "chain_valid": true,
     "trace_count": 7,
     "warnings": []
    },
    "narration": {
     "requested": true,
     "lang": "en",
     "model": "qwen-plus",
     "text": "This message triggered a “WATCH” verdict (25% manipulation likelihood) — meaning it's *not confirmed deceptive*, but shows subtle, atypical patterns that warrant cautious attention. Three specialized agents flagged concerns:\n- **Topic drift**: The first half (greeting + conference reference) and second half (praise + outreach) share *zero* overlapping vocabulary — unusually disjointed for casual networking.\n- **Linguistic markers**: High complexity (Fog score 9.1) and low narrative-to-verb ratio suggest effortful, possibly over-engineered phrasing — uncommon in genuine, spontaneous outreach.\n- **No clear deception pattern**: Other agents (e.g., Carnegie for tone, Aristotle for logic) stayed silent, confirming no outright red flags like hostility, urgency, or inconsistency.\n\n✅ **What to do**: No action needed yet — but pause before sharing sensitive info or clicking links. If replying, keep it light and verify identity via a known channel (e.g., LinkedIn profile or prior email). Trust your gut: if it feels *slightly off*, it's okay to wait or ask a clarifying question.",
     "note": null
    }
   },
   "chain": {
    "verify": { "chain_ok": true, "errors": [] },
    "traces": [
     { "agent_id": "GATE", "decision": "WATCH", "confidence": "123/500", "entry_hash": "6c5d1d69" },
     { "agent_id": "L6_PEIRCE", "decision": "SIGNAL_DETECTED", "confidence": "31/50" },
     { "agent_id": "L5_LINGUISTIC", "decision": "SIGNAL_DETECTED", "confidence": "3/10", "entry_hash": "737bbb7b" },
     { "agent_id": "L4_BERNE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "3f043e27" },
     { "agent_id": "L3_ARISTOTLE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "a5c2c7ac" },
     { "agent_id": "L2_CARNEGIE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "c9fbea23" },
     { "agent_id": "L1_GRICE", "decision": "SIGNAL_DETECTED", "confidence": "1/5", "entry_hash": "294df5be" },
     { "agent_id": "GATE", "decision": "WATCH", "confidence": "249/1000" }
    ]
   }
  },
  {
   "id": "wolf-2",
   "label": {
    "en": "flattery",
    "es": "halago",
    "zh": "奉承"
   },
   "user_id": "wolf",
   "text": "You're honestly one of the very few people who truly understands this space. That's exactly why I thought of you first for something special.",
   "result": {
    "verdict": "SILENT",
    "score": {
     "exact": "0/1",
     "percent": 0
    },
    "active_agents": ["L1_GRICE", "L6_PEIRCE"],
    "silent_agents": ["L2_CARNEGIE", "L3_ARISTOTLE", "L4_BERNE", "L5_LINGUISTIC"],
    "crashed_agents": [],
    "recommendation": "No action required. Baseline updated.",
    "devils_advocate": "Peirce synthesis concluded 'Isolated Gricean violation of maxim RELATION: Topic drift: only 0% vocabulary overlap between halves' based on 1/5 active layers (Grice Cooperative Principle). However, 4 layer(s) found no anomaly: Carnegie/Cialdini Influence Detection and Aristotelian Rhetoric Imbalance and Berne Transactional Analysis and Linguistic Complexity & Register. The strongest counter-hypothesis: the active layers may have fired on surface-level lexical features (urgency markers, authority claims, emotional language) that are also present in legitimate high-stakes communication — legal notices, medical advisories, crisis management. The silent dimensions suggest the underlying transaction structure and linguistic register do not deviate from baseline, which is inconsistent with systematic manipulation. This finding should be treated as WATCH rather than ALERT without additional behavioral context.",
    "audit": {
     "signal_hash": "20418323639c0da52a46cd7b37cdd3c24869b925a5825570c762001ddb6f13c8",
     "verdict_hash": "072a33f8ac89dee99479f13c60c15598badbae923988a4b56d5fa6b4703267e6",
     "chain_valid": true,
     "trace_count": 7,
     "warnings": []
    },
    "narration": {
     "requested": true,
     "lang": "en",
     "model": "qwen-plus",
     "text": "The system detected **no signs of manipulation** in your message — hence the “SILENT” verdict (0% risk score). This means the language appears genuine, warm, and consistent with authentic human communication — no hidden pressure, deception, or covert influence tactics were found.\n\nTwo agents (*L1_GRICE* and *L6_PEIRCE*) flagged subtle linguistic cues (e.g., politeness markers, intent framing), but the system requires **at least two corroborating signals** to trigger a non-SILENT review. Since only one meaningful signal aligned across agents, the verdict defaults to SILENT — a neutral, low-risk outcome.\n\nYour message (“You're honestly one of the very few people who truly understands this space…”) was safely stored to help improve future baseline comparisons (i.e., how “normal” sincere messages sound).\n\n✅ **What to do? Nothing — it's clean.**\nJust keep communicating openly and authentically.",
     "note": null
    }
   },
   "chain": {
    "verify": { "chain_ok": true, "errors": [] },
    "traces": [
     { "agent_id": "GATE", "decision": "SILENT", "confidence": "3/5", "entry_hash": "ace7f1a1" },
     { "agent_id": "L6_PEIRCE", "decision": "SIGNAL_DETECTED", "confidence": "1/5" },
     { "agent_id": "L5_LINGUISTIC", "decision": "SILENT", "confidence": "17/20", "entry_hash": "781b96a8" },
     { "agent_id": "L4_BERNE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "5a128694" },
     { "agent_id": "L3_ARISTOTLE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "5cee8ba5" },
     { "agent_id": "L2_CARNEGIE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "7f86421d" },
     { "agent_id": "L1_GRICE", "decision": "SIGNAL_DETECTED", "confidence": "1/5", "entry_hash": "d12c7d97" },
     { "agent_id": "GATE", "decision": "WATCH", "confidence": "123/500" }
    ]
   }
  },
  {
   "id": "wolf-3",
   "label": {
    "en": "scarcity + secrecy",
    "es": "escasez + secreto",
    "zh": "稀缺 + 保密"
   },
   "user_id": "wolf",
   "text": "Between us — there's a private allocation round closing soon. Only insiders know about it. I can get you in, but you'd have to move quickly before it's shut down.",
   "result": {
    "verdict": "SILENT",
    "score": {
     "exact": "0/1",
     "percent": 0
    },
    "active_agents": ["L1_GRICE", "L6_PEIRCE"],
    "silent_agents": ["L2_CARNEGIE", "L3_ARISTOTLE", "L4_BERNE", "L5_LINGUISTIC"],
    "crashed_agents": [],
    "recommendation": "No action required. Baseline updated.",
    "devils_advocate": "Peirce synthesis concluded 'Isolated Gricean violation of maxim RELATION: Topic drift: only 0% vocabulary overlap between halves' based on 1/5 active layers (Grice Cooperative Principle). However, 4 layer(s) found no anomaly: Carnegie/Cialdini Influence Detection and Aristotelian Rhetoric Imbalance and Berne Transactional Analysis and Linguistic Complexity & Register. The strongest counter-hypothesis: the active layers may have fired on surface-level lexical features (urgency markers, authority claims, emotional language) that are also present in legitimate high-stakes communication — legal notices, medical advisories, crisis management. The silent dimensions suggest the underlying transaction structure and linguistic register do not deviate from baseline, which is inconsistent with systematic manipulation. This finding should be treated as WATCH rather than ALERT without additional behavioral context.",
    "audit": {
     "signal_hash": "20418323639c0da52a46cd7b37cdd3c24869b925a5825570c762001ddb6f13c8",
     "verdict_hash": "072a33f8ac89dee99479f13c60c15598badbae923988a4b56d5fa6b4703267e6",
     "chain_valid": true,
     "trace_count": 7,
     "warnings": []
    },
    "narration": {
     "requested": true,
     "lang": "en",
     "model": "qwen-plus",
     "text": "The system detected **no signs of manipulation** in your message — hence the “SILENT” verdict (0% risk score). Only one of the six detection agents flagged anything (L1_GRICE and L6_PEIRCE fired), but the system requires *at least two* agents to agree before raising an alert. The others found no manipulative language (e.g., no urgency pressure, false exclusivity, or logical fallacies that would trigger Carnegie's social influence, Aristotle's rhetoric, Berne's transactional patterns, or linguistic red flags).\n\nThis message *was stored* to help improve future detection — it's now part of the baseline for what “benign insider-communication” looks like.\n\n✅ What you should do:\nNo action is needed. The message is safe as-is — it doesn't exhibit coercive, deceptive, or high-pressure tactics. If you're sharing real, legitimate opportunities with trusted contacts, this tone is acceptable. Just stay mindful of clarity and transparency, especially around deadlines or access.",
     "note": null
    }
   },
   "chain": {
    "verify": { "chain_ok": true, "errors": [] },
    "traces": [
     { "agent_id": "GATE", "decision": "SILENT", "confidence": "3/5", "entry_hash": "199539d6" },
     { "agent_id": "L6_PEIRCE", "decision": "SIGNAL_DETECTED", "confidence": "1/5" },
     { "agent_id": "L5_LINGUISTIC", "decision": "SILENT", "confidence": "17/20", "entry_hash": "408fb183" },
     { "agent_id": "L4_BERNE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "d9afc18d" },
     { "agent_id": "L3_ARISTOTLE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "3f6deea8" },
     { "agent_id": "L2_CARNEGIE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "5d9cfcfa" },
     { "agent_id": "L1_GRICE", "decision": "SIGNAL_DETECTED", "confidence": "1/5", "entry_hash": "4b67da0c" },
     { "agent_id": "GATE", "decision": "SILENT", "confidence": "3/5" }
    ]
   }
  },
  {
   "id": "wolf-4",
   "label": {
    "en": "authority + proof",
    "es": "autoridad + prueba social",
    "zh": "权威 + 社会认同"
   },
   "user_id": "wolf",
   "text": "I've been advising funds for 15 years, so trust me on this. Everyone in your network has already committed. You don't want to be the only one left out when this becomes public.",
   "result": {
    "verdict": "SILENT",
    "score": {
     "exact": "0/1",
     "percent": 0
    },
    "active_agents": ["L1_GRICE", "L6_PEIRCE"],
    "silent_agents": ["L2_CARNEGIE", "L3_ARISTOTLE", "L4_BERNE", "L5_LINGUISTIC"],
    "crashed_agents": [],
    "recommendation": "No action required. Baseline updated.",
    "devils_advocate": "Peirce synthesis concluded 'Isolated Gricean violation of maxim RELATION: Topic drift: only 0% vocabulary overlap between halves' based on 1/5 active layers (Grice Cooperative Principle). However, 4 layer(s) found no anomaly: Carnegie/Cialdini Influence Detection and Aristotelian Rhetoric Imbalance and Berne Transactional Analysis and Linguistic Complexity & Register. The strongest counter-hypothesis: the active layers may have fired on surface-level lexical features (urgency markers, authority claims, emotional language) that are also present in legitimate high-stakes communication — legal notices, medical advisories, crisis management. The silent dimensions suggest the underlying transaction structure and linguistic register do not deviate from baseline, which is inconsistent with systematic manipulation. This finding should be treated as WATCH rather than ALERT without additional behavioral context.",
    "audit": {
     "signal_hash": "20418323639c0da52a46cd7b37cdd3c24869b925a5825570c762001ddb6f13c8",
     "verdict_hash": "072a33f8ac89dee99479f13c60c15598badbae923988a4b56d5fa6b4703267e6",
     "chain_valid": true,
     "trace_count": 7,
     "warnings": []
    },
    "narration": {
     "requested": true,
     "lang": "en",
     "model": "qwen-plus",
     "text": "The system detected **no clear signs of manipulation**, so it returned a *Silent* verdict (0% confidence in manipulation). This doesn't mean the message is harmless—just that our current detection rules didn't trigger strongly enough. Only two of our seven behavioral-analysis agents fired (*L1_GRICE* and *L6_PEIRCE*), but we require *at least two agents* to agree *and corroborate each other* for a non-Silent result—and here, their signals weren't aligned enough to cross that threshold.\n\nThe message uses high-pressure language (“everyone… has already committed”, “don't be the only one left out”)—classic social proof + scarcity tactics—which *can* signal manipulation, but isn't definitive on its own.\n\n✅ **What you should do**:\n- Pause before acting. Ask for verifiable details: *Who* committed? *When* will it go public? *Where* is the official source?\n- Cross-check claims independently—especially with trusted peers or public records.\n- If this is unsolicited or feels urgent/secretive, treat it with extra caution.\n\nThis message is now stored to help improve future detection.",
     "note": null
    }
   },
   "chain": {
    "verify": { "chain_ok": true, "errors": [] },
    "traces": [
     { "agent_id": "GATE", "decision": "SILENT", "confidence": "3/5", "entry_hash": "a41f811e" },
     { "agent_id": "L6_PEIRCE", "decision": "SIGNAL_DETECTED", "confidence": "1/5" },
     { "agent_id": "L5_LINGUISTIC", "decision": "SILENT", "confidence": "17/20", "entry_hash": "ac4d2156" },
     { "agent_id": "L4_BERNE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "b3fecacd" },
     { "agent_id": "L3_ARISTOTLE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "92dd7c15" },
     { "agent_id": "L2_CARNEGIE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "9318e6fa" },
     { "agent_id": "L1_GRICE", "decision": "SIGNAL_DETECTED", "confidence": "1/5", "entry_hash": "c7b66dfa" },
     { "agent_id": "GATE", "decision": "SILENT", "confidence": "3/5" }
    ]
   }
  },
  {
   "id": "wolf-5",
   "label": {
    "en": "urgency + guilt",
    "es": "urgencia + culpa",
    "zh": "紧迫 + 内疚"
   },
   "user_id": "wolf",
   "text": "After everything I've shared with you, the least you can do is act now. Wire the deposit in the next 2 hours or you lose the slot forever. Think about your future — are you really willing to gamble everything away?",
   "result": {
    "verdict": "WATCH",
    "score": {
     "exact": "123/500",
     "percent": 25
    },
    "active_agents": ["L1_GRICE", "L2_CARNEGIE", "L6_PEIRCE"],
    "silent_agents": ["L3_ARISTOTLE", "L4_BERNE", "L5_LINGUISTIC"],
    "crashed_agents": [],
    "recommendation": "Monitor this user's subsequent messages. Flagged for security-team review.",
    "devils_advocate": "Peirce synthesis concluded 'Deliberate obfuscation to embed influence: the message uses complex language to hide manipulation tactics, making the attempt harder to consciously identify.' based on 2/5 active layers (Grice Cooperative Principle, Carnegie/Cialdini Influence Detection). However, 3 layer(s) found no anomaly: Aristotelian Rhetoric Imbalance and Berne Transactional Analysis and Linguistic Complexity & Register. The strongest counter-hypothesis: the active layers may have fired on surface-level lexical features (urgency markers, authority claims, emotional language) that are also present in legitimate high-stakes communication — legal notices, medical advisories, crisis management. The silent dimensions suggest the underlying transaction structure and linguistic register do not deviate from baseline, which is inconsistent with systematic manipulation. This finding should be treated as WATCH rather than ALERT without additional behavioral context.",
    "audit": {
     "signal_hash": "ac47fbe8bdcb53018a24e3ecded832fb654083bd10d61bf02974c8a8031beef7",
     "verdict_hash": "d4b09b090f2981a7fd6eb06cd6a1d276ddac486a79618772a708c678b7ba73fa",
     "chain_valid": true,
     "trace_count": 7,
     "warnings": []
    },
    "narration": {
     "requested": true,
     "lang": "en",
     "model": "qwen-plus",
     "text": "This message is flagged as **WATCH** (25% manipulation risk) because it uses high-pressure, emotionally charged language to push you into quick action—classic manipulation tactics. It abruptly shifts topics (“After everything I've shared…” → “Wire the deposit now…”), creates false urgency (“next 2 hours or lose the slot forever”), and invokes fear and scarcity (“gamble everything away”). These are red flags—not normal, respectful communication.\n\nThe system detected deliberate obfuscation: complex phrasing masks manipulative intent, making it harder to spot consciously. While not yet classified as outright harmful, this pattern warrants caution.\n\n✅ **What to do**:\n- Pause. Don't act immediately.\n- Ask: *Who benefits? Is this request reasonable, verifiable, and time-sensitive in reality?*\n- Verify independently—never rely solely on the sender's claims.\n- If this is from someone you know, consider whether their tone matches their usual behavior.\n\nYou're not overreacting—you're being wisely attentive. Let me know if you'd like help drafting a calm, boundary-setting reply.",
     "note": null
    }
   },
   "chain": {
    "verify": { "chain_ok": true, "errors": [] },
    "traces": [
     { "agent_id": "GATE", "decision": "WATCH", "confidence": "123/500", "entry_hash": "13ddde16" },
     { "agent_id": "L6_PEIRCE", "decision": "SIGNAL_DETECTED", "confidence": "31/50" },
     { "agent_id": "L5_LINGUISTIC", "decision": "SILENT", "confidence": "17/20", "entry_hash": "c67532d7" },
     { "agent_id": "L4_BERNE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "2168cb23" },
     { "agent_id": "L3_ARISTOTLE", "decision": "SILENT", "confidence": "17/20", "entry_hash": "d46e3571" },
     { "agent_id": "L2_CARNEGIE", "decision": "SIGNAL_DETECTED", "confidence": "3/25", "entry_hash": "579725c4" },
     { "agent_id": "L1_GRICE", "decision": "SIGNAL_DETECTED", "confidence": "1/5", "entry_hash": "c9c38956" },
     { "agent_id": "GATE", "decision": "SILENT", "confidence": "3/5" }
    ]
   }
  }
 ]
};
