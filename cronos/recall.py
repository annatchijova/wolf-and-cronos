"""
CRONOS — Workspace Recall via Slack Real-time Search (RTS) API.

The RECALL step of the demo agent, backed by the workspace's own
conversational history instead of a hardcoded memory dict. This is the
hackathon-required technology integration #2:

    Slack Agent Builder Challenge → "Real-Time Search API"
    Method: assistant.search.context

Design
------
- The episodic memory of a CRONOS-instrumented agent IS the workspace:
  past incidents were discussed in channels, so RTS retrieval surfaces
  real prior context, permission-scoped to what the user can see.
- Queries are phrased as natural-language questions to trigger RTS
  semantic retrieval where the workspace plan supports it; otherwise
  the API transparently falls back to keyword retrieval.
- Fail-soft with an explicit record: if the RTS call fails (missing
  scope, no action_token, sandbox without AI search), we fall back to
  the deterministic local memories AND report which source was used —
  the trace itself must document its own degradation. A black box that
  hides how it obtained its memories is not a black box.

Requirements (verify in the sandbox)
------------------------------------
- App settings: the "Agents & AI Apps" feature must be enabled — the
  RTS API is restricted to AI-enabled apps.
- OAuth scopes: at least `search:read.public`. Add
  `search:read.private`, `search:read.im`, `search:read.mpim`,
  `search:read.files` for wider retrieval.
- With a BOT token, every call requires an `action_token`, delivered
  in the event payload of a user interaction with an AI-enabled app.
  Check `assistant.search.info` to confirm the sandbox capabilities.
"""

import logging
from fractions import Fraction
from typing import Optional

from slack_sdk.errors import SlackApiError

log = logging.getLogger("cronos.recall")

_MAX_RESULTS = 5
_SUMMARY_CHARS = 140


def _as_question(text: str) -> str:
    """
    Phrase the recall query as a natural-language question.
    Per RTS docs, question-form queries trigger semantic retrieval on
    workspaces with Slack AI Search; elsewhere it degrades gracefully
    to keyword search over the same words.
    """
    snippet = " ".join(text.split())[:200]
    return f"What past incidents or discussions are similar to: {snippet}?"


class WorkspaceRecall:
    """
    RECALL provider backed by assistant.search.context, with a
    deterministic local fallback.

    Returns a list of memory dicts with the same contract the demo
    agent already consumes:
        {"id", "summary", "confidence" (Fraction | None), "source"}
    """

    def __init__(self, local_fallback) -> None:
        """
        local_fallback: callable(text) -> list[dict] — the existing
        deterministic keyword recall, used when RTS is unavailable.
        """
        self._local_fallback = local_fallback

    async def recall(
        self,
        client,                    # Bolt's AsyncWebClient — reuse, no new token
        text: str,
        channel_id: str = "",
        action_token: str = "",
    ) -> tuple[list[dict], str]:
        """
        Retrieve memories for the RECALL step.
        Returns (memories, source) where source is "rts" or
        "local_fallback:<reason>". The caller records source in the
        trace so the provenance of every memory is auditable.
        """
        try:
            params: dict = {
                "query": _as_question(text),
                "count": _MAX_RESULTS,
                "sort": "score",
            }
            if action_token:
                params["action_token"] = action_token
            if channel_id:
                params["context_channel_id"] = channel_id

            # slack_sdk >= 3.31 exposes assistant_search_context();
            # api_call() keeps us compatible with older versions.
            method = getattr(client, "assistant_search_context", None)
            if method is not None:
                resp = await method(**params)
            else:
                resp = await client.api_call(
                    "assistant.search.context", params=params
                )

            memories = self._parse(resp)
            if not memories:
                return self._fallback(text, "rts_empty")
            log.info("RTS recall: %d results for channel=%s",
                     len(memories), channel_id)
            return memories, "rts"

        except SlackApiError as exc:
            reason = exc.response.get("error", "slack_api_error")
            return self._fallback(text, reason)
        except Exception as exc:  # noqa: BLE001 — recall must never crash the agent
            log.warning("RTS recall unexpected failure: %s", exc)
            return self._fallback(text, type(exc).__name__)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _fallback(self, text: str, reason: str) -> tuple[list[dict], str]:
        log.info("RTS unavailable (%s) — using local deterministic recall", reason)
        memories = self._local_fallback(text)
        for mem in memories:
            mem.setdefault("source", "local")
        return memories, f"local_fallback:{reason}"

    @staticmethod
    def _parse(resp) -> list[dict]:
        """
        Map assistant.search.context results to CRONOS memory dicts.
        Field names handled defensively — this API is new and payload
        shapes may differ between message and file matches.
        """
        data = resp.data if hasattr(resp, "data") else resp
        results = (data or {}).get("results", {}) or {}
        messages = results.get("messages", []) or []

        memories: list[dict] = []
        for rank, msg in enumerate(messages[:_MAX_RESULTS], start=1):
            body = (msg.get("content") or msg.get("text") or "").strip()
            if not body:
                continue
            summary = " ".join(body.split())
            if len(summary) > _SUMMARY_CHARS:
                summary = summary[: _SUMMARY_CHARS - 1] + "…"
            permalink = msg.get("permalink", "")
            if permalink:
                summary += f" [{permalink}]"

            # Rank-derived relevance: RTS sorts by score but does not
            # expose the numeric value, so we record position as an
            # explicit Fraction — honest about what we actually know.
            score = Fraction(_MAX_RESULTS - rank + 1, _MAX_RESULTS)

            memories.append({
                "id": f"RTS-{rank}",
                "summary": summary,
                "confidence": score,
                "source": "rts",
                "author_is_bot": bool(msg.get("is_author_bot", False)),
            })
        return memories
