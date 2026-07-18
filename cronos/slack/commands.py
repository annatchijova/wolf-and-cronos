"""
CRONOS — /cronos slash command handlers.

Subcommands:
  /cronos explain [trace_id]   Full explanation of last (or specific) trace
  /cronos trace [agent_id]     List recent traces, optionally filtered by agent
  /cronos audit                Export and verify the SHA-256 chain
  /cronos status               Overview of all registered agents
  /cronos help                 Command reference
"""

import logging

from slack_bolt.async_app import AsyncApp

from cronos.store import TraceStore
from slack.output import (
    format_trace_explain,
    format_trace_list,
    format_audit_export,
    format_status,
)

log = logging.getLogger("cronos.commands")

HELP_TEXT = """\
*CRONOS* — Black Box Recorder for AI Agents

```
/cronos explain [trace_id]   Explain last (or specific) trace in plain language
/cronos trace [agent_id]     List recent traces (optionally filter by agent)
/cronos audit                Verify and export the SHA-256 audit chain
/cronos status               Overview of all agents and trace counts
/cronos help                 Show this message
```
"""


def register_commands(app: AsyncApp, store: TraceStore) -> None:
    """Register all /cronos subcommand handlers on the Bolt app."""

    @app.command("/cronos")
    async def handle_cronos(ack, respond, command):
        await ack()
        raw = (command.get("text") or "").strip()
        parts = raw.split(None, 1)
        sub = parts[0].lower() if parts else "help"
        arg = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("explain", "ex"):
            await _handle_explain(respond, store, arg)
        elif sub in ("trace", "traces", "tr"):
            await _handle_trace(respond, store, arg)
        elif sub in ("audit", "a"):
            await _handle_audit(respond, store)
        elif sub in ("status", "s"):
            await _handle_status(respond, store)
        else:
            await respond(text=HELP_TEXT)


# ── /cronos explain ───────────────────────────────────────────────────────────

async def _handle_explain(respond, store: TraceStore, arg: str) -> None:
    """Explain a specific trace (by prefix) or the most recent one."""
    try:
        trace = None

        if arg:
            # Prefix match — find the first trace whose ID starts with arg
            recent = store.get_recent_traces(limit=100)
            match = next(
                (r for r in recent if r["trace_id"].startswith(arg)),
                None,
            )
            if match:
                trace = store.load_trace(match["trace_id"])
            if not trace:
                await respond(text=f"No trace found matching prefix `{arg}`.")
                return
        else:
            trace = store.get_latest_trace()

        if not trace:
            await respond(text="_No traces recorded yet. Run an agent to generate one._")
            return

        await respond(blocks=format_trace_explain(trace), text="CRONOS trace explanation")

    except Exception as exc:  # noqa: BLE001
        log.exception("Error in /cronos explain: %s", exc)
        await respond(
            text=f"⚠️ Failed to load trace: `{exc}`. Check logs for details."
        )


# ── /cronos trace ─────────────────────────────────────────────────────────────

async def _handle_trace(respond, store: TraceStore, arg: str) -> None:
    """List recent traces, optionally filtered by agent_id."""
    agent_id = arg or None
    recent = store.get_recent_traces(agent_id=agent_id, limit=10)
    await respond(
        blocks=format_trace_list(recent),
        text="CRONOS recent traces",
    )


# ── /cronos audit ─────────────────────────────────────────────────────────────

async def _handle_audit(respond, store: TraceStore) -> None:
    """Verify and export the SHA-256 audit chain."""
    chain_ok, errors = store.chain.verify()
    entries = store.chain.export()
    await respond(
        blocks=format_audit_export(entries, chain_ok, errors),
        text="CRONOS audit chain",
    )


# ── /cronos status ────────────────────────────────────────────────────────────

async def _handle_status(respond, store: TraceStore) -> None:
    """High-level status: total traces, active agents."""
    total = store.count_traces()
    recent = store.get_recent_traces(limit=20)
    await respond(
        blocks=format_status(total, recent),
        text="CRONOS status",
    )
