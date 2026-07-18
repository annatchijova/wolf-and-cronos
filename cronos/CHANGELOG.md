# CRONOS — Changelog

All notable changes documented here.

---

## [0.1.0] — 2026-06-20

Initial implementation of CRONOS, built for the Slack Agent Builder Challenge.

### Architecture

- **CronosTracer** — Context-manager SDK. Records steps *while the agent runs*: objective, recalls, tool calls, hypotheses, discards, evidence, decision.
- **TraceStore** — SQLite WAL persistence. Steps + header + chain entry in a single atomic commit.
- **TraceChain** — SHA-256 tamper-evident hash chain. Each entry chains to the previous; any retroactive modification breaks downstream hashes.
- **Narrator** — Rule-based NLG. Produces short card (for inline posting), full breakdown (for `/cronos explain`), and natural language prose — no LLM.
- **Slack layer** — Bolt async app. `/cronos explain | trace | audit | status`. Block Kit formatters with `_escape()` on all user-supplied text.
- **Demo agent** — `DemoAgent` wraps a deterministic support ticket resolver using the SDK. Demonstrates the full cycle: recall → tool → hypothesis → evidence → discard → decide → post trace card.
- **Confidence** — `fractions.Fraction` throughout; zero floats in the scoring path.
- **Tests** — 104 tests across 5 files: tracer, chain, store, narrator, output.

### Design decisions

- `decide()` raises `TypeError` if passed a float — enforces Fraction discipline at the API boundary.
- `TraceChain.append()` never calls `conn.commit()` — callers own the transaction (engine.py issues the single commit that covers chain + header + steps).
- `_escape()` applied to all user-supplied text in Block Kit payloads (XSS via Slack mrkdwn).
- `CronosTracer.__exit__` stores the trace even when the agent code raises — the partial trace is forensically valuable.
- `Fraction(74, 100)` auto-reduces to `37/50`; the store round-trips `p/q` string and reconstructs the exact Fraction — equality holds.

---

## [0.1.1] — 2026-06-20 — Post-audit hardening

### Breaking change — SHA-256 chain serialization

`_compute_entry_hash` now uses `json.dumps(..., separators=(',', ':'))` (compact,
no spaces) instead of the default space-padded format.

**Impact:** Any `entry_hash` produced by `0.1.0` will fail re-verification under
`0.1.1` because the canonical JSON bytes differ.  This affects only audit chain
verification (`/cronos audit`), not trace retrieval or display.

**Migration:** If you have an existing `cronos.db` from `0.1.0`, delete it and
start fresh, or export all traces before upgrading.  The old hashes are stored in
`trace_chain.entry_hash` — a mismatch against a recomputed value indicates the
version boundary, not tampering.

### Fixes

- **`chain.py`** — compact JSON separators for deterministic cross-implementation hashes
- **`tracer.py`** — `__exit__` logs storage failures; `decide()` validates `[0,1]`; `add_evidence()` rejects `supports+refutes` simultaneously
- **`store.py`** — `ON DELETE CASCADE` on `trace_steps`; auto-migration for legacy DBs; `_str_to_fraction` hardened
- **`output.py`** — `_trunc()` helper; 50-block cap on `format_trace_explain`; `_escape` comment clarifies mrkdwn-vs-plain_text behavior
- **`config.py`** — warns when channel names (not IDs) are used in `CRONOS_WATCH_CHANNELS`
- **`main.py`** — SIGTERM/SIGINT handler for graceful async shutdown
- **`bot.py`** — event deduplication with bounded LRU; `_is_duplicate` handles absent `client_msg_id`
- **`demo/agent.py`** — trigger regex requires ticket/issue/bug context
- **`commands.py`** — `_handle_explain` wraps all store calls in try/except with user-facing error message
