"""
CRONOS — Demo Seeder
====================
Populates the CRONOS database with a curated set of traces that
exercise EVERY capability of the system, so the Slack demo (and the
hackathon video) can show rich, realistic data on demand.

Scenarios seeded
----------------
  1. support-resolver  auth ticket        FULL quality, RTS-sourced recall
  2. support-resolver  cache ticket       FULL quality
  3. support-resolver  IAM escalation     FULL quality, highest confidence
  4. deploy-guard      overconfident      MINIMAL quality → ceiling clamps 95%→60%
  5. deploy-guard      no-recall deploy   PARTIAL quality → ceiling clamps 90%→85%
  6. incident-triage   contradictions     Type A + Type B detected and reported
  7. claude-code       MCP-recorded       trace recorded by an external MCP agent
  8. deploy-guard      falsely modest     floor raises 2% → 10% (evidence exists)

Usage
-----
  python demo_seed.py                 # seed all scenarios into cronos.db
  python demo_seed.py --reset         # delete DB first, then seed fresh
  python demo_seed.py --verify        # verify the SHA-256 chain and exit
  python demo_seed.py --tamper        # simulate an attacker editing a trace
  python demo_seed.py --db path.db    # use a specific database file

Demo flow for the video
-----------------------
  python demo_seed.py --reset        → seed
  /cronos audit  (in Slack)          → chain VERIFIED
  python demo_seed.py --tamper       → attacker modifies a decision
  /cronos audit  (in Slack)          → chain BROKEN, exact entry identified
  python demo_seed.py --reset        → clean slate for the next take
"""

import argparse
import os
import sqlite3
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cronos import CronosTracer, TraceStore

F = Fraction


# ── Scenario builders ─────────────────────────────────────────────────────────

def seed_auth_full(store: TraceStore) -> None:
    """FULL quality: recall + tools + reasoning. RTS-sourced memories."""
    with CronosTracer(store, agent_id="support-resolver",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Resolve ticket #842 — users report login timeouts") as t:
        t.call_tool("workspace_recall",
                    "assistant.search.context → source=rts, 2 memories retrieved")
        t.record_recall("RTS-1",
                        "Auth timeout in service A — 2024-03 incident, fixed by "
                        "token rotation [slack permalink]", score=F(5, 5))
        t.record_recall("RTS-2",
                        "Failed login cascade — expired JWT secret, rotated "
                        "2024-11 [slack permalink]", score=F(4, 5))
        t.call_tool("jira", "ticket #842 → Open / Auth / High")
        t.call_tool("github", "3 commits in auth-service match pattern (last: 2025-11-14)")
        t.add_hypothesis("auth_bug", "Authentication token expired or rotated unexpectedly")
        t.add_hypothesis("cache_bug", "Auth response incorrectly cached with wrong TTL")
        t.add_evidence("Jira categorized as Auth with High priority", supports="auth_bug")
        t.add_evidence("RTS-1 matches: prior incident resolved by token rotation",
                       supports="auth_bug")
        t.add_evidence("No cache errors in Jira log", refutes="cache_bug")
        t.discard_hypothesis("cache_bug", "No cache indicators in Jira or GitHub")
        t.decide("Rotate auth token and restart auth-service", F(74, 100))


def seed_cache_full(store: TraceStore) -> None:
    with CronosTracer(store, agent_id="support-resolver",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Resolve ticket #1187 — dashboard shows stale data") as t:
        t.record_recall("M-110",
                        "Cache invalidation bug — 2025-02, fixed by flushing Redis TTL",
                        score=F(88, 100))
        t.call_tool("jira", "ticket #1187 → Open / Cache / Medium")
        t.call_tool("github", "1 commit in cache-layer: 'fix TTL invalidation' (2025-02-08)")
        t.add_hypothesis("cache_bug", "Cache invalidation failure causing stale data")
        t.add_hypothesis("auth_bug", "Session incorrectly cached — appears as cache issue")
        t.add_evidence("Redis TTL config unchanged for 9 months", supports="cache_bug")
        t.add_evidence("No auth errors reported in the same window", refutes="auth_bug")
        t.discard_hypothesis("auth_bug", "No auth error correlation found")
        t.decide("Flush Redis cache and reset TTL configuration", F(81, 100))


def seed_security_full(store: TraceStore) -> None:
    with CronosTracer(store, agent_id="support-resolver",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Resolve ticket #666 — user accessed admin-only report") as t:
        t.record_recall("M-147",
                        "Permission escalation via misconfigured IAM role — 2025-05, "
                        "fixed by role audit", score=F(83, 100))
        t.call_tool("jira", "ticket #666 → Open / Security / Critical")
        t.call_tool("github", "IAM policy updated in infra-config (2025-05-22)")
        t.add_hypothesis("perm_bug", "IAM role misconfiguration allowing escalation")
        t.add_hypothesis("auth_bug", "Auth bypass via misconfigured policy")
        t.add_evidence("Role diff shows wildcard grant added last sprint", supports="perm_bug")
        t.add_evidence("Auth logs show valid token — no bypass", refutes="auth_bug")
        t.discard_hypothesis("auth_bug", "Token validation confirmed correct")
        t.decide("Audit IAM roles and revoke excess permissions", F(87, 100))


def seed_overconfident_minimal(store: TraceStore) -> None:
    """
    MONEY SHOT #1 — the confidence ceiling.
    The agent claims 95% confidence but only reasoned (no recall, no
    tools). Diversity = 1/3 → ceiling 60%. CRONOS stores 60% and the
    warning explains exactly why. The black box does not let an agent
    claim certainty its evidence base cannot support.
    """
    with CronosTracer(store, agent_id="deploy-guard",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Approve production deploy of release v3.2.0") as t:
        t.add_hypothesis("safe_deploy", "Release is safe — tests passed on my machine")
        t.add_evidence("CI pipeline green on the release branch", supports="safe_deploy")
        t.decide("Approve deploy to production", F(95, 100))


def seed_partial_no_recall(store: TraceStore) -> None:
    """PARTIAL quality: tools + reasoning, no recall → ceiling 85%."""
    with CronosTracer(store, agent_id="deploy-guard",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Approve hotfix deploy for payment-service") as t:
        t.call_tool("ci", "pipeline #4471 → all 312 tests green")
        t.call_tool("github", "diff: 14 lines, isolated to retry logic")
        t.add_hypothesis("safe_hotfix", "Small isolated change, low blast radius")
        t.add_evidence("Diff touches only retry backoff constants", supports="safe_hotfix")
        t.decide("Approve hotfix deploy", F(90, 100))


def seed_contradiction(store: TraceStore) -> None:
    """
    MONEY SHOT #2 — contradiction detection.
    Type A: 'network_issue' has evidence both supporting AND refuting it.
    Type B: 'dns_failure' had supporting evidence but was discarded anyway.
    CRONOS records the decision AND flags both inconsistencies.
    """
    with CronosTracer(store, agent_id="incident-triage",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Triage incident INC-2077 — intermittent 502 errors") as t:
        t.record_recall("M-3021", "Similar 502 burst during 2025-09 CDN migration",
                        score=F(66, 100))
        t.call_tool("grafana", "error rate 2.3% — spikes correlate with deploy windows")
        t.add_hypothesis("network_issue", "Upstream network packet loss")
        t.add_hypothesis("dns_failure", "DNS resolution intermittently failing")
        t.add_evidence("Packet loss 4% on upstream link", supports="network_issue")
        t.add_evidence("Loss disappears outside deploy windows — not network",
                       refutes="network_issue")
        t.add_evidence("Resolver logs show 3 SERVFAIL bursts", supports="dns_failure")
        t.discard_hypothesis("dns_failure", "Assumed unrelated — closed without check")
        t.decide("Restart upstream load balancer", F(70, 100))


def seed_mcp_claude_code(store: TraceStore) -> None:
    """
    A trace recorded by an EXTERNAL agent through the CRONOS MCP server.
    Demonstrates that the black box is infrastructure for any MCP-capable
    agent, not a feature of the demo bot.
    """
    with CronosTracer(store, agent_id="claude-code",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Fix failing test test_store.py::test_chain_atomicity") as t:
        t.call_tool("pytest", "1 failed, 41 passed — FK constraint error on cascade")
        t.record_recall("RTS-1",
                        "Thread from 2026-05: cascade migration discussed in #eng "
                        "[slack permalink]", score=F(5, 5))
        t.call_tool("grep", "ON DELETE CASCADE present in schema, absent in legacy table")
        t.add_hypothesis("stale_schema", "Test DB created before cascade migration")
        t.add_hypothesis("code_bug", "save_trace violates FK ordering")
        t.add_evidence("Fresh DB passes the same test", supports="stale_schema")
        t.add_evidence("Insert order verified correct in save_trace", refutes="code_bug")
        t.discard_hypothesis("code_bug", "Insert ordering verified — not a code defect")
        t.decide("Recreate test fixture DB with current schema", F(82, 100))


def seed_floor_case(store: TraceStore) -> None:
    """
    The confidence FLOOR: an agent with real supporting evidence cannot
    report near-zero confidence. Claimed 2% → raised to 10% with warning.
    """
    with CronosTracer(store, agent_id="deploy-guard",
                      channel_id="C_DEMO", user_id="U_DEMO",
                      objective="Assess rollback need after error spike") as t:
        t.record_recall("M-88", "Previous spike self-resolved after cache warmup",
                        score=F(71, 100))
        t.call_tool("grafana", "error rate declining 40% over last 10 minutes")
        t.add_hypothesis("transient", "Spike is transient cache-warmup noise")
        t.add_evidence("Error rate declining without intervention", supports="transient")
        t.decide("No rollback needed — monitor for 30 minutes", F(2, 100))


_SCENARIOS = [
    ("FULL / RTS recall / ticket auth",       seed_auth_full),
    ("FULL / ticket cache",                   seed_cache_full),
    ("FULL / ticket seguridad",               seed_security_full),
    ("MINIMAL / techo 95%→60%",               seed_overconfident_minimal),
    ("PARTIAL / techo 90%→85%",               seed_partial_no_recall),
    ("Contradicciones tipo A y B",            seed_contradiction),
    ("Agente externo vía MCP (claude-code)",  seed_mcp_claude_code),
    ("Piso de confianza 2%→10%",              seed_floor_case),
]


# ── Tamper simulation ─────────────────────────────────────────────────────────

def tamper(db_path: str) -> None:
    """
    Simulate an attacker retroactively editing a recorded decision,
    bypassing the API and writing SQL directly. The next /cronos audit
    must detect the exact entry whose hash no longer matches.
    """
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT trace_id, decision FROM trace_chain ORDER BY id LIMIT 1 OFFSET 2"
    ).fetchone()
    if not row:
        print("Nothing to tamper — seed the database first.")
        return
    trace_id, original = row
    forged = "Deploy was approved by a human reviewer"
    conn.execute("UPDATE trace_chain SET decision = ? WHERE trace_id = ?",
                 (forged, trace_id))
    conn.execute("UPDATE traces SET decision = ? WHERE trace_id = ?",
                 (forged, trace_id))
    conn.commit()
    conn.close()
    print(f"TAMPERED trace {trace_id[:8]}…")
    print(f"  original : {original!r}")
    print(f"  forged   : {forged!r}")
    print("Run '/cronos audit' in Slack (or --verify here) to see the chain break.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Seed CRONOS demo scenarios")
    p.add_argument("--db", default=os.environ.get("CRONOS_DB_PATH", "cronos.db"))
    p.add_argument("--reset",  action="store_true", help="delete DB before seeding")
    p.add_argument("--verify", action="store_true", help="verify chain and exit")
    p.add_argument("--tamper", action="store_true", help="simulate attacker edit and exit")
    args = p.parse_args()

    if args.tamper:
        tamper(args.db)
        return

    if args.verify:
        store = TraceStore(args.db)
        ok, errors = store.chain.verify()
        n = store.count_traces()
        print(f"Chain entries : {n}")
        print(f"Chain intact  : {'YES' if ok else 'NO'}")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(0 if ok else 1)

    if args.reset and os.path.exists(args.db):
        for suffix in ("", "-wal", "-shm"):
            path = args.db + suffix
            if os.path.exists(path):
                os.remove(path)
        print(f"Removed {args.db}")

    store = TraceStore(args.db)

    print(f"Seeding {len(_SCENARIOS)} scenarios into {args.db}\n")
    for name, builder in _SCENARIOS:
        builder(store)
        trace = store.get_latest_trace()
        conf = trace.confidence
        conf_s = f"{conf.numerator}/{conf.denominator}" if conf else "-"
        warn = f" · {len(trace.confidence_warnings)} warning(s)" if trace.confidence_warnings else ""
        contra = f" · {len(trace.contradictions)} contradiction(s)" if trace.contradictions else ""
        print(f"  [{trace.trace_id[:8]}] {name}")
        print(f"      agent={trace.agent_id} quality={trace.quality.value} "
              f"confidence={conf_s}{warn}{contra}")

    ok, errors = store.chain.verify()
    print(f"\nChain: {store.count_traces()} entries — "
          f"{'VERIFIED' if ok else 'BROKEN'}")
    print("\nSuggested Slack commands:")
    print("  /cronos status")
    print("  /cronos trace")
    print("  /cronos trace deploy-guard")
    print("  /cronos explain")
    print("  /cronos audit")


if __name__ == "__main__":
    main()
