"""
CRONOS — Demo Agent: Slack Support Ticket Resolver
Demonstrates the CronosTracer SDK in a realistic scenario.

When triggered by a message containing "ticket #<N>" (or "fix" / "resolve"),
the agent:
  1. Opens a CRONOS trace
  2. Recalls relevant memories — via the Slack Real-time Search API
     (assistant.search.context) when available, with a deterministic
     local fallback. The recall SOURCE is recorded in the trace.
  3. Calls two mock tools (Jira, GitHub)
  4. Generates two hypotheses
  5. Evaluates evidence
  6. Discards the weaker hypothesis
  7. Makes a decision with a confidence score
  8. Posts the agent reply + CRONOS trace card in the same thread

The Jira/GitHub tools remain deterministic mocks so the demo is
reproducible without external backends. The RECALL step is real:
it searches the workspace's own conversational history through the
RTS API, permission-scoped to what the triggering user can see.
"""

import logging
import re
from fractions import Fraction

from cronos import CronosTracer, TraceStore
from slack.output import format_trace_card
from demo.recall import WorkspaceRecall

log = logging.getLogger("cronos.demo")

# ── Deterministic local memory (fallback when RTS is unavailable) ─────────────

_MEMORIES = [
    {
        "id": "M-22",
        "summary": "Auth timeout in service A — 2024-03 incident, fixed by token rotation",
        "keywords": ["auth", "token", "login", "session", "timeout"],
        "confidence": Fraction(91, 100),
    },
    {
        "id": "M-81",
        "summary": "Failed login cascade — 2024-11 incident, root cause: expired JWT secret",
        "keywords": ["login", "jwt", "auth", "credential", "failed"],
        "confidence": Fraction(74, 100),
    },
    {
        "id": "M-110",
        "summary": "Cache invalidation bug — 2025-02 incident, fixed by flushing Redis TTL",
        "keywords": ["cache", "redis", "stale", "invalidation", "ttl"],
        "confidence": Fraction(88, 100),
    },
    {
        "id": "M-147",
        "summary": "Permission escalation via misconfigured IAM role — 2025-05, fixed by role audit",
        "keywords": ["permission", "iam", "role", "access", "escalation"],
        "confidence": Fraction(83, 100),
    },
    {
        "id": "M-203",
        "summary": "Database connection pool exhausted — 2025-08 incident, fixed by pool sizing",
        "keywords": ["database", "db", "connection", "pool", "timeout"],
        "confidence": Fraction(79, 100),
    },
]


def _recall_memories(text: str) -> list[dict]:
    """Return top-2 local memories by keyword overlap. RTS fallback path."""
    t = text.lower()
    scored = []
    for mem in _MEMORIES:
        hits = sum(1 for kw in mem["keywords"] if kw in t)
        if hits > 0:
            scored.append((hits, mem))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [dict(m) for _, m in scored[:2]]


# ── Mock tool responses ────────────────────────────────────────────────────────

def _mock_jira(ticket_num: int, text: str) -> tuple[str, str, str]:
    """
    Return (category, priority, status) based on keywords.
    Deterministic: same ticket + keywords always return the same result.
    """
    t = text.lower()
    if any(w in t for w in ["auth", "login", "token", "session", "jwt"]):
        return ("Auth", "High", "Open")
    if any(w in t for w in ["cache", "redis", "stale"]):
        return ("Cache", "Medium", "Open")
    if any(w in t for w in ["permission", "access", "iam"]):
        return ("Security", "Critical", "Open")
    if any(w in t for w in ["db", "database", "connection"]):
        return ("Infrastructure", "High", "Open")
    # Default
    return ("General", "Medium", "Open")


def _mock_github(ticket_num: int, category: str) -> str:
    """Return a plausible mock GitHub search result."""
    if category == "Auth":
        return "3 commits in auth-service match pattern (last: 2025-11-14)"
    if category == "Cache":
        return "1 commit in cache-layer: 'fix TTL invalidation' (2025-02-08)"
    if category == "Security":
        return "IAM policy updated in infra-config (2025-05-22)"
    if category == "Infrastructure":
        return "Pool size config adjusted in db-service (2025-08-30)"
    return "No recent matching commits"


# ── Hypothesis map ─────────────────────────────────────────────────────────────

_HYPOTHESES = {
    "Auth": [
        ("auth_bug",   "Authentication token expired or rotated unexpectedly"),
        ("cache_bug",  "Auth response incorrectly cached with wrong TTL"),
    ],
    "Cache": [
        ("cache_bug",  "Cache invalidation failure causing stale data"),
        ("auth_bug",   "Auth session incorrectly cached — appears as cache issue"),
    ],
    "Security": [
        ("perm_bug",   "IAM role misconfiguration allowing unintended escalation"),
        ("auth_bug",   "Auth bypass via misconfigured policy"),
    ],
    "Infrastructure": [
        ("pool_bug",   "Connection pool exhaustion under load"),
        ("auth_bug",   "Auth service unable to reach DB — appears as auth failure"),
    ],
    "General": [
        ("config_bug", "Misconfiguration in service startup"),
        ("dep_bug",    "Dependency version mismatch after last deploy"),
    ],
}

_DECISIONS = {
    "Auth":           ("Rotate auth token and restart auth-service",       Fraction(74, 100)),
    "Cache":          ("Flush Redis cache and reset TTL configuration",    Fraction(81, 100)),
    "Security":       ("Audit IAM roles and revoke excess permissions",    Fraction(87, 100)),
    "Infrastructure": ("Increase DB connection pool size and add monitoring", Fraction(78, 100)),
    "General":        ("Review recent deploys and roll back if needed",    Fraction(55, 100)),
}


# ── Demo Agent ────────────────────────────────────────────────────────────────

class DemoAgent:
    """
    A minimal Slack agent that resolves support tickets using the CRONOS SDK.
    Each handle_message() call generates one complete, traceable decision cycle.
    """

    # Trigger patterns — require specific ticket/issue context to avoid
    # false positives on everyday words like "fix my lunch".
    _TRIGGER = re.compile(
        r"\bticket\s*#?\d+\b"                                          # "ticket #42"
        r"|\b(fix|resolve|investigate|debug)\s+"
        r"(ticket|issue|bug|error|incident|problem|outage|alert)\b",   # "fix issue"
        re.IGNORECASE,
    )

    def __init__(self, store: TraceStore) -> None:
        self._store = store
        self._recall = WorkspaceRecall(local_fallback=_recall_memories)

    async def handle_message(
        self,
        text: str,
        channel_id: str,
        user_id: str,
        thread_ts: str,
        say,
        client,
        action_token: str = "",
    ) -> None:
        if not self._TRIGGER.search(text):
            return  # not for us

        # Extract ticket number or use a default
        m = re.search(r"ticket\s*#?(\d+)", text, re.IGNORECASE)
        ticket_num = int(m.group(1)) if m else 0

        log.info("DemoAgent triggered: channel=%s ticket=%s", channel_id, ticket_num)

        # ── Open a CRONOS trace ───────────────────────────────────────────────
        objective = (
            f"Resolve ticket #{ticket_num}" if ticket_num
            else f"Resolve reported issue: {text[:60]}"
        )

        with CronosTracer(
            store=self._store,
            agent_id="support-resolver",
            channel_id=channel_id,
            user_id=user_id,
            objective=objective,
        ) as t:

            # Step 1 — Recall memories via RTS API (fallback: local store).
            # The recall source is recorded as a TOOL step so the trace
            # documents the PROVENANCE of every memory it used.
            memories, recall_source = await self._recall.recall(
                client=client,
                text=text,
                channel_id=channel_id,
                action_token=action_token,
            )
            t.call_tool(
                "workspace_recall",
                f"assistant.search.context → source={recall_source}, "
                f"{len(memories)} memories retrieved",
            )
            for mem in memories:
                t.record_recall(
                    mem["id"], mem["summary"], score=mem.get("confidence"),
                )

            # Step 2 — Call Jira
            category, priority, status = _mock_jira(ticket_num, text)
            t.call_tool(
                "jira",
                f"ticket #{ticket_num} → {status} / {category} / {priority}",
            )

            # Step 3 — Call GitHub
            github_result = _mock_github(ticket_num, category)
            t.call_tool("github", github_result)

            # Step 4 — Generate hypotheses
            hyps = _HYPOTHESES.get(category, _HYPOTHESES["General"])
            primary, secondary = hyps[0], hyps[1]
            t.add_hypothesis(primary[0],   primary[1])
            t.add_hypothesis(secondary[0], secondary[1])

            # Step 5 — Evidence
            t.add_evidence(
                f"Jira categorized as {category} with {priority} priority",
                supports=primary[0],
            )
            if memories:
                t.add_evidence(
                    f"Memory {memories[0]['id']} matches: {memories[0]['summary'][:60]}",
                    supports=primary[0],
                )
            t.add_evidence(
                f"No {secondary[0].replace('_',' ')} indicators found in Jira log",
                refutes=secondary[0],
            )

            # Step 6 — Discard secondary hypothesis
            t.discard_hypothesis(
                secondary[0],
                f"No {secondary[0].replace('_',' ')} indicators in Jira or GitHub",
            )

            # Step 7 — Decide
            decision_text, confidence = _DECISIONS.get(category, _DECISIONS["General"])
            t.decide(decision_text, confidence)

            # The trace is sealed and stored when the `with` block exits.
            # Capture the trace object reference for the Slack reply.
            trace = t.trace

        # ── Post the agent reply + CRONOS card ────────────────────────────────
        conf_pct = round(float(trace.confidence) * 100)
        reply_text = (
            f"*{decision_text}*\n"
            f"Confidence: {conf_pct}% · Chain: verified"
        )

        trace_blocks = format_trace_card(trace)

        await say(
            text=reply_text,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":white_check_mark: *{decision_text}*",
                    },
                },
                *trace_blocks,
            ],
            thread_ts=thread_ts,
        )

        log.info("DemoAgent replied. trace_id=%s hash=%s",
                 trace.trace_id[:8], (trace.entry_hash or "")[:8])
