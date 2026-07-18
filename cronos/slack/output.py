"""
CRONOS — Block Kit formatters.
Produces Slack Block Kit payloads from Narrator output.

Two levels:
- format_trace_card()   → short card posted inline (after agent action)
- format_trace_explain() → full explanation card with expandable sections
- format_trace_list()   → list of recent traces for /cronos trace
- format_audit_export() → chain verification result for /cronos audit
"""

from typing import Optional

from cronos.narrator import Narrator
from cronos.models import Trace

# Slack Block Kit limits
_SLACK_MAX_BLOCKS    = 50
_SLACK_MAX_TEXT_CHARS = 3000


# ── Shared helpers ────────────────────────────────────────────────────────────

def _escape(text: str) -> str:
    """
    Escape Slack mrkdwn special characters in user-supplied text.

    Slack's mrkdwn parser requires &, <, > to be encoded as HTML entities.
    In `"type": "mrkdwn"` fields, Slack decodes &amp; → &, &lt; → <, &gt; → >
    before rendering, so end users see the original characters.

    NOTE: do NOT apply _escape to `"type": "plain_text"` fields — plain_text
    is displayed verbatim and HTML entities would appear literally (&amp;, etc.).
    Every user-supplied string in this module goes into mrkdwn fields only.
    """
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _trunc(text: str, max_len: int = _SLACK_MAX_TEXT_CHARS) -> str:
    """Hard-truncate a text field to stay within Slack's per-block character limit."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _chain_badge(chain_ok: bool, hash_short: str) -> str:
    if chain_ok:
        return f"✅ Chain verified · `{hash_short}`"
    return f"❌ Chain verification failed · `{hash_short}`"


def _quality_badge(quality: str) -> str:
    badges = {
        "FULL":    "🟢 FULL",
        "PARTIAL": "🟡 PARTIAL",
        "MINIMAL": "🟠 MINIMAL",
        "EMPTY":   "🔴 EMPTY",
    }
    return badges.get(quality, f"— {quality}")


def _confidence_bar(pct_str: str, width: int = 10) -> str:
    """Render a text progress bar for confidence. '74%' → '[███████░░░]'."""
    try:
        pct = int(pct_str.rstrip("%")) / 100
    except (ValueError, AttributeError):
        return "[----------]"
    filled = round(pct * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


# ── Trace card (posted by agent after each action) ─────────────────────────────

def format_trace_card(trace: Trace) -> list[dict]:
    """
    Short inline card appended to the agent's reply.
    Shows decision, why-bullets, confidence, chain badge.
    """
    n = Narrator(trace)
    s = n.short()

    decision_text = _escape(s["decision"])
    why_text = "\n".join(
        f"{sym} {_escape(line)}" for sym, line in s["why_lines"]
    ) or "_No reasoning steps recorded._"

    conf_pct    = s["confidence_pct"]
    conf_bar    = _confidence_bar(conf_pct)
    chain_line  = _chain_badge(s["chain_ok"], s["hash_short"])
    quality_bdg = _quality_badge(s.get("quality", ""))
    div_pct     = s.get("diversity_pct", "—")

    # Contradiction warning line (if any)
    contradictions = s.get("contradictions", [])
    contra_line = ""
    if contradictions:
        contra_line = f"\n⚠️ *{len(contradictions)} contradiction(s) detected* — run `/cronos explain` for details"

    # Confidence clamping warning
    conf_warnings = s.get("confidence_warnings", [])
    conf_warn_line = ""
    if conf_warnings:
        conf_warn_line = f"\n_ℹ️ Confidence adjusted: {'; '.join(conf_warnings[:1])}_"

    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*⬡ CRONOS TRACE* · `{s['agent_id']}`\n"
                    f"*Decision:* {decision_text}"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Why?*\n{why_text}{contra_line}{conf_warn_line}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Confidence:* {conf_bar} {conf_pct}   |   "
                        f"Quality: {quality_bdg} ({div_pct} diversity)   |   "
                        f"{chain_line}   |   "
                        f"`/cronos explain {s['trace_id'][:8]}`"
                    ),
                }
            ],
        },
    ]


# ── Explain card (/cronos explain) ─────────────────────────────────────────────

def format_trace_explain(trace: Trace) -> list[dict]:
    """
    Full explanation card with all sections.
    Used by /cronos explain.
    """
    n = Narrator(trace)
    f = n.full()

    blocks: list[dict] = []

    # Header
    decision_text = _escape(f["decision"])
    conf_pct = f["confidence_pct"]
    conf_bar = _confidence_bar(conf_pct)

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"🔭 CRONOS TRACE — {f['agent_id']}"},
    })
    blocks.append({
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*Objective*\n{_escape(f['objective'])}"},
            {"type": "mrkdwn", "text": f"*Decision*\n{decision_text}"},
        ],
    })

    # Confidence + chain
    chain_line = _chain_badge(f["chain_ok"], f["hash_short"])
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Confidence:* {conf_bar} {conf_pct}   |   {chain_line}",
        },
    })

    # Why bullets
    why_text = "\n".join(
        f"{sym} {_escape(line)}" for sym, line in f["why_lines"]
    ) or "_No reasoning steps recorded._"
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*Why?*\n{why_text}"},
    })

    blocks.append({"type": "divider"})

    # Memories
    if f["memories"]:
        mem_lines = "\n".join(
            f"• `{m['id']}` — {_escape(m['summary'][:80])}"
            + (f" (score {m['score']})" if m.get("score") else "")
            for m in f["memories"]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Memories recalled*\n{mem_lines}"},
        })

    # Tools
    if f["tools"]:
        tool_lines = "\n".join(
            f"• `{t['name']}` → {_escape(t['result'][:80])}"
            for t in f["tools"]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Tool calls*\n{tool_lines}"},
        })

    # Hypotheses
    if f["hypotheses"]:
        h_lines = []
        for h in f["hypotheses"]:
            if h["status"] == "kept":
                h_lines.append(f"✓ `{h['label']}` — {_escape(h['description'][:70])}")
            else:
                reason = _escape(h.get("discard_reason") or "")
                h_lines.append(
                    f"✗ `{h['label']}` — {_escape(h['description'][:50])} _(discarded: {reason})_"
                )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Hypotheses*\n" + "\n".join(h_lines)},
        })

    # Natural language prose
    prose = n.natural()
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": _trunc(f"*In plain language:*\n_{_escape(prose)}_"),
        },
    })

    # Devil's advocate (from VIGÍA devil_advocate_gen)
    da = f.get("devils_advocate", "")
    if da and da != "No alternative hypotheses were generated.":
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Devil's advocate:*\n_{_escape(da)}_",
            },
        })

    # Contradiction warnings (from VIGÍA self-correction loop)
    contradictions = f.get("contradictions", [])
    if contradictions:
        ct_lines = "\n".join(f"⚠️ {_escape(c)}" for c in contradictions)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Contradictions detected:*\n{ct_lines}",
            },
        })

    # Confidence warnings (ceiling/floor clamping)
    conf_warnings = f.get("confidence_warnings", [])
    if conf_warnings:
        cw_lines = "\n".join(f"ℹ️ {_escape(w)}" for w in conf_warnings)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Confidence constraints applied:*\n{cw_lines}"},
        })

    # Quality + diversity + version (from VIGÍA acquisition assurance + config_sentinel)
    quality_line = (
        f"Quality: {_quality_badge(f.get('quality',''))} · "
        f"Diversity: {f.get('diversity_pct','—')} · "
        f"CRONOS v{f.get('cronos_version','—')}"
    )
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": quality_line}],
    })

    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f"Trace `{f['trace_id'][:16]}…`   |   "
                    f"Started {(f['started_at'] or '')[:19]}Z   |   "
                    f"Closed {(f['closed_at'] or '')[:19]}Z"
                ),
            }
        ],
    })

    # Slack hard limit: 50 blocks per message.  Truncate gracefully.
    if len(blocks) > _SLACK_MAX_BLOCKS:
        blocks = blocks[: _SLACK_MAX_BLOCKS - 1]
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn",
                          "text": "_⚠️ Output truncated — trace too large for a single message. "
                                  "Use `/cronos audit` to export the full record._"}],
        })

    return blocks


# ── Trace list (/cronos trace) ─────────────────────────────────────────────────

def format_trace_list(traces: list[dict]) -> list[dict]:
    """Render a list of recent trace headers."""
    if not traces:
        return [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No traces recorded yet._"},
        }]

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔭 Recent CRONOS Traces"}},
    ]
    for t in traces:
        hash_short = (t.get("entry_hash") or "")[:7] or "—"
        chain_icon = "✅" if t.get("chain_ok") else "❌"
        closed = (t.get("closed_at") or "")[:19]
        decision = _escape((t.get("decision") or "(no decision)")[:60])
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"`{t['agent_id']}` · {closed}Z\n"
                    f"*{decision}*\n"
                    f"_{_escape(t.get('objective', '')[:60])}_   "
                    f"{chain_icon} `{hash_short}`"
                ),
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Explain →"},
                "value": t["trace_id"],
                "action_id": "cronos_explain_trace",
            },
        })

    return blocks


# ── Audit export (/cronos audit) ───────────────────────────────────────────────

def format_audit_export(
    entries: list[dict],
    chain_ok: bool,
    errors: list[str],
) -> list[dict]:
    """Render chain verification result as Block Kit blocks."""
    if chain_ok:
        status_text = f"✅ *Chain intact* — {len(entries)} entries verified"
    else:
        status_text = f"❌ *Chain integrity failure* — {len(errors)} error(s) detected"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "🔒 CRONOS Audit Chain"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": status_text}},
    ]

    if not chain_ok:
        err_text = "\n".join(f"• {e}" for e in errors[:5])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Errors:*\n{err_text}"},
        })

    if entries:
        last = entries[-1]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Latest entry*\n"
                    f"`{last['entry_hash'][:32]}…`\n"
                    f"Agent: `{last['agent_id']}` · {last['timestamp'][:19]}Z"
                ),
            },
        })

    return blocks


# ── Status (/cronos status) ────────────────────────────────────────────────────

def format_status(total: int, recent: list[dict]) -> list[dict]:
    """High-level status overview."""
    agents: dict[str, int] = {}
    for t in recent:
        agents[t["agent_id"]] = agents.get(t["agent_id"], 0) + 1

    agent_lines = "\n".join(
        f"• `{name}` — {count} recent trace{'s' if count != 1 else ''}"
        for name, count in agents.items()
    ) or "_No agents recorded._"

    return [
        {"type": "header", "text": {"type": "plain_text", "text": "🔭 CRONOS Status"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total traces*\n{total}"},
                {"type": "mrkdwn", "text": f"*Active agents*\n{len(agents)}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Agents (last 20)*\n{agent_lines}"},
        },
    ]
