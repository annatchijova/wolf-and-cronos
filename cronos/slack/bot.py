"""
CRONOS — Bolt async app factory.
Wires together: slash commands, demo agent message handler,
action handler for "Explain →" buttons.
"""

import logging
from collections import OrderedDict

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from config import Config
from cronos.store import TraceStore
from slack.commands import register_commands
from demo.agent import DemoAgent

log = logging.getLogger("cronos.bot")

# ── Event deduplication ───────────────────────────────────────────────────────
# Slack retries failed events with identical ts+client_msg_id.  A simple
# bounded LRU set prevents double-processing without any external state.

_SEEN_EVENTS: OrderedDict[str, None] = OrderedDict()
_MAX_SEEN_EVENTS = 500


def _is_duplicate(event: dict) -> bool:
    """Return True and skip if this event was already processed."""
    # client_msg_id is absent on some Slack event subtypes (e.g. bot messages,
    # file shares).  Fall back to ts alone — it is unique per channel per message.
    # Use a sentinel prefix so "None-ts" and "-ts" cannot collide.
    msg_id = event.get("client_msg_id") or ""
    ts     = event.get("ts") or ""
    if not ts:
        return False  # no timestamp — cannot deduplicate safely, let it through
    key = f"mid:{msg_id}|ts:{ts}"
    if key in _SEEN_EVENTS:
        log.debug("Duplicate event skipped: %s", key)
        return True
    _SEEN_EVENTS[key] = None
    if len(_SEEN_EVENTS) > _MAX_SEEN_EVENTS:
        _SEEN_EVENTS.popitem(last=False)
    return False


def create_app(config: Config, store: TraceStore) -> tuple[AsyncApp, AsyncSocketModeHandler]:
    """
    Build and wire the Bolt app.
    Returns (app, handler) — caller must await handler.start().
    """
    app = AsyncApp(
        token=config.SLACK_BOT_TOKEN,
        signing_secret=config.SLACK_SIGNING_SECRET,
    )

    # Slash commands
    register_commands(app, store)

    # Demo agent — reacts to @mentions or keywords in watched channels
    demo = DemoAgent(store)

    @app.event("app_mention")
    async def handle_mention(event, say, client):
        channel = event.get("channel", "")
        user    = event.get("user", "")
        text    = event.get("text", "")
        ts      = event.get("ts", "")
        await demo.handle_message(
            text=text,
            channel_id=channel,
            user_id=user,
            thread_ts=ts,
            say=say,
            client=client,
        )

    @app.event("message")
    async def handle_message(event, say, client):
        # Only handle messages in watched channels (if configured)
        channel = event.get("channel", "")
        if config.WATCH_CHANNELS and channel not in config.WATCH_CHANNELS:
            return
        # Skip bot messages, edits, and Slack retries
        if event.get("bot_id") or event.get("subtype") in ("bot_message", "message_changed"):
            return
        if _is_duplicate(event):
            return
        user = event.get("user", "")
        text = event.get("text", "")
        ts   = event.get("ts", "")
        if not text or not user:
            return
        await demo.handle_message(
            text=text,
            channel_id=channel,
            user_id=user,
            thread_ts=ts,
            say=say,
            client=client,
        )

    # "Explain →" button in trace list
    @app.action("cronos_explain_trace")
    async def handle_explain_button(ack, body, respond):
        await ack()
        trace_id = body["actions"][0]["value"]
        trace = store.load_trace(trace_id)
        if not trace:
            await respond(text=f"Trace `{trace_id[:8]}` not found.")
            return
        from slack.output import format_trace_explain
        await respond(
            blocks=format_trace_explain(trace),
            text="CRONOS trace explanation",
            replace_original=False,
        )

    handler = AsyncSocketModeHandler(app, config.SLACK_APP_TOKEN)
    return app, handler
