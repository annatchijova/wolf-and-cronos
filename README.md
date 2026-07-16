# CORVUS + CRONOS — Multi-Agent Rhetorical Negotiation Engine

**Qwen Cloud Hackathon 2026 · Track 3: Agentic AI**

---

## What this is

A **multi-agent system** that detects manipulation and social engineering in text through six independent theoretical frameworks. The agents negotiate a verdict via a corroboration gate — no single agent can trigger an alarm alone. The negotiation is permanently auditable via CRONOS, a SHA-256 tamper-evident trace chain.

This submission combines two existing systems with **zero modification to their internals**:

- **CORVUS** (90 tests) — the multi-agent analysis engine
- **CRONOS** (161 tests) — the forensic audit trail

The integration bridge in this repo wraps CORVUS output into CRONOS traces, then calls Qwen to narrate the negotiation for human review.

---

## Architecture

```
TEXT ARTIFACT
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│                CORVUS ANALYSIS LAYER (parallel)              │
│                                                             │
│  L1 · Grice        Maxim of Manner violations               │
│  L2 · Carnegie     Influence + Cialdini principles          │
│  L3 · Aristotle    Ethos / Pathos / Logos imbalance         │
│  L4 · Berne        Transactional ego states                 │
│  L5 · Linguistics  Complexity, register, Zipf anomaly       │
│                                                  ↓          │
│  L6 · Peirce       Abductive synthesis (after L1-L5)        │
└─────────────────────┬───────────────────────────────────────┘
                      │  signals[]
                      ▼
         ┌────────────────────────┐
         │  CORROBORATION GATE    │  >= 2 active agents required
         │  (negotiation outcome) │  for any verdict above SILENT
         └────────────┬───────────┘
                      │
          ┌───────────┴──────────────┐
          │                          │
          ▼                          ▼
   [CRONOS TRACES]          [SEALED VERDICT]
   one per agent +          level + score +
   one for gate             Fraction arithmetic
   SHA-256 chain            (zero floats)
          │                          │
          └───────────┬──────────────┘
                      ▼
             [QWEN NARRATOR]
             narrates the agent
             negotiation transcript
             (read-only — cannot
              alter the verdict)
```

### Why six agents instead of one?

| Mode | Configuration | Outcome |
|------|--------------|---------|
| Single arbiter | Gate threshold = 1 (any agent fires) | 62.5% FPR — too many false alarms |
| Multi-agent consensus | Gate threshold = 2 (>= 2 must agree) | 0% FPR — zero false alarms |

The corroboration gate is not a filter added on top of agents — it IS the negotiation mechanism. Agents that fire below the threshold have their "gate_fires" hypothesis discarded by CRONOS, creating an auditable record of the overrule.

### How agents resolve disagreements

Each agent operates independently and emits a vote (SILENT / active). The gate:

1. Counts active votes (L1-L5 only; L6 is synthesis).
2. If `count >= 2`: consensus reached — emits the VerdictEngine result.
3. If `count < 2`: gate discards all hypotheses — forces SILENT.

CRONOS records every step: which agents voted, what evidence they cited, which hypotheses were discarded by the gate. The SHA-256 chain makes this trace tamper-evident — any post-hoc modification breaks the hash.

---

## Qwen Integration

Qwen (`qwen-plus` via DashScope) provides the **narrative layer only**:

- The deterministic verdict is sealed BEFORE Qwen is called.
- Qwen receives a read-only summary and produces a negotiation transcript.
- Swapping Qwen for another model changes the wording — never the verdict.

```bash
export DASHSCOPE_API_KEY="sk-..."
python3 scripts/demo.py
```

Without `DASHSCOPE_API_KEY`, the system runs fully deterministically (fallback narration).

---

## Benchmark (single-arbiter vs. multi-agent)

```
python3 benchmark/benchmark.py
```

On the 20-sample built-in corpus (12 deceptive, 8 benign):

| Mode | TP | FP | TN | FN | FPR | FNR | Accuracy |
|------|----|----|----|----|-----|-----|----------|
| Single arbiter (gate=1) | 12 | 5 | 3 | 0 | 62.5% | 0.0% | 75.0% |
| Multi-agent (gate=2) | 5 | 0 | 8 | 7 | 0.0% | 58.3% | 65.0% |

**FPR reduction: 62.5 pp (100% relative improvement).**

For a forensic system, FPR is the critical metric — false alarms destroy analyst trust and cause alert fatigue. The multi-agent gate eliminates all false positives at the cost of some recall.

---

## Quick start

```bash
# Dependencies
pip install requests   # HTTP client used for Qwen narration (see requirements.txt)
# CORVUS and CRONOS are resolved from ../corvus and ../cronos

# Demo (deterministic, no API key needed)
python3 scripts/demo.py

# Demo with Qwen narration
DASHSCOPE_API_KEY=sk-... python3 scripts/demo.py

# Benchmark
python3 benchmark/benchmark.py

# Tests
python3 -m pytest tests/ -v
```

---

## Tests

| Suite | Tests | Status |
|-------|-------|--------|
| CORVUS (L1-L6 + gate + memory + regressions) | 90 | all green |
| CRONOS (chain + tracer + quality + store) | 161 | all green |
| Bridge integration (this repo) | 16 | all green |

---

## Theoretical frameworks

| Layer | Framework | Manipulation signal |
|-------|-----------|-------------------|
| L1 | Grice (1975) — Cooperative Principle | Manner maxim violations: fog, ambiguity, register mismatch |
| L2 | Carnegie + Cialdini — Influence & Persuasion | Reciprocity, authority, scarcity, social proof patterns |
| L3 | Aristotle — Rhetoric | Pathos >> Logos imbalance (emotion overrides reason) |
| L4 | Berne — Transactional Analysis | Critical parent, ulterior transactions, crossed ego states |
| L5 | Linguistics — SDA-NR / CLI / Zipf | Cognitive load, unnaturally low error rates (scripted text) |
| L6 | Peirce — Abductive Semiotics | Firstness / Secondness / Thirdness synthesis of L1-L5 |

---

## Determinism invariants

- All scoring uses `fractions.Fraction` — zero floats in any verdict field.
- SHA-256 audit hash over the canonical JSON of all agent signals.
- CRONOS chain: each entry hashes the previous entry — any retroactive edit breaks the chain.
- Qwen narration is outside the sealed payload — swapping models cannot alter the verdict.

---

*Built on CORVUS (Apache 2.0) and CRONOS (Apache 2.0) — VIGÍA AI Collective 2026.*
