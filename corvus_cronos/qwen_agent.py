"""
corvus_cronos/qwen_agent.py
============================
Qwen-native agent driver for CRONOS.

CRONOS speaks MCP, which Claude and Codex consume directly. Qwen models
speak OpenAI-compatible function calling through DashScope. This module
closes that gap: it exposes the exact same CRONOS tool surface as the MCP
server (open trace, hypotheses, evidence, discards, tool calls, recalls,
close, explain, list, verify) to qwen-max as `tools` in the DashScope
chat/completions API, and runs the agent loop server-side.

The result: a Qwen model performs a real reasoning task while every
hypothesis, piece of evidence, and discard is sealed into the CRONOS
SHA-256 tamper-evident chain — the same chain, the same quality scoring,
the same confidence ceilings that Claude-driven traces get.

Architectural invariant (unchanged): the model records its reasoning; it
cannot rewrite the chain. Confidence ceilings, quality tiers, and
contradiction detection are computed by CRONOS at seal time, not by the
model.

Usage
-----
    from corvus_cronos.qwen_agent import QwenCronosAgent

    agent = QwenCronosAgent(db_path="cronos_qwen.db")
    outcome = agent.run(
        task="Diagnose why the nightly export job produced 0 rows.",
        agent_id="qwen-investigator",
    )
    print(outcome.answer)
    print(outcome.sealed_trace_ids, outcome.chain_ok)

Without DASHSCOPE_API_KEY the driver raises immediately with a clear
error: this module's entire purpose is the live model. Tests inject a
fake `transport` instead.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable, Optional

log = logging.getLogger("qwen_track3.qwen_agent")

# Resolve the vendored cronos package (same bootstrap as bridge.py).
_ROOT = os.path.dirname(os.path.abspath(__file__))
for _lib in ("corvus", "cronos"):
    _p = os.path.abspath(os.path.join(_ROOT, "..", _lib))
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cronos.store import TraceStore
from cronos.tracer import CronosTracer

from corvus_cronos.qwen_client import QWEN_BASE_URL

QWEN_AGENT_MODEL = "qwen-max"

_MAX_TEXT = 4_000
_MAX_ID = 128
_MAX_OPEN_TRACES = 50
_MAX_TURNS = 24          # hard bound on model<->tool round trips
_MAX_TOOL_CALLS_PER_TURN = 8


def _trunc(text: Any, limit: int = _MAX_TEXT) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fraction(num: Any, den: Any, field_name: str) -> Fraction:
    """Build a Fraction in [0, 1] from an integer pair. No floats, ever."""
    if isinstance(num, bool) or isinstance(den, bool):
        raise ValueError(f"{field_name}: numerator and denominator must be integers.")
    if not isinstance(num, int) or not isinstance(den, int):
        raise ValueError(f"{field_name}: numerator and denominator must be integers.")
    if den <= 0:
        raise ValueError(f"{field_name}: denominator must be a positive integer.")
    f = Fraction(num, den)
    if not (Fraction(0) <= f <= Fraction(1)):
        raise ValueError(f"{field_name}: must be in [0, 1] — got {num}/{den}.")
    return f


# ---------------------------------------------------------------------------
# Tool schemas — mirror of cronos/mcp_server.py, OpenAI function-call format
# ---------------------------------------------------------------------------

def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


CRONOS_TOOLS: list[dict] = [
    _tool(
        "cronos_open_trace",
        "Open a new reasoning trace. Returns the trace_id to use in all "
        "subsequent recording calls. Every decision cycle maps to exactly "
        "one trace: open, record steps, close.",
        {
            "agent_id": {"type": "string", "description": "Stable identifier of the calling agent."},
            "objective": {"type": "string", "description": "What the agent was asked to accomplish, verbatim."},
        },
        ["agent_id", "objective"],
    ),
    _tool(
        "cronos_add_hypothesis",
        "Register a hypothesis under active consideration. Record ALL candidate "
        "explanations, not just the winner — that is what makes the trace "
        "forensically useful. label is a short stable key (e.g. 'auth_bug').",
        {
            "trace_id": {"type": "string"},
            "label": {"type": "string"},
            "description": {"type": "string"},
        },
        ["trace_id", "label", "description"],
    ),
    _tool(
        "cronos_add_evidence",
        "Record a fact observed during reasoning. Optionally link it to a "
        "hypothesis label it supports OR refutes (never both — call twice if "
        "ambiguous).",
        {
            "trace_id": {"type": "string"},
            "text": {"type": "string"},
            "supports": {"type": "string", "description": "Hypothesis label this fact supports (optional)."},
            "refutes": {"type": "string", "description": "Hypothesis label this fact refutes (optional)."},
        },
        ["trace_id", "text"],
    ),
    _tool(
        "cronos_discard_hypothesis",
        "Mark a hypothesis as discarded, with the reason. Discards show what "
        "the agent considered and rejected, not just what it concluded.",
        {
            "trace_id": {"type": "string"},
            "label": {"type": "string"},
            "reason": {"type": "string"},
        },
        ["trace_id", "label", "reason"],
    ),
    _tool(
        "cronos_record_tool_call",
        "Record an external tool call the agent made (DB query, web search, "
        "file read...) and a short summary of what it returned.",
        {
            "trace_id": {"type": "string"},
            "tool_name": {"type": "string"},
            "result_summary": {"type": "string"},
        },
        ["trace_id", "tool_name", "result_summary"],
    ),
    _tool(
        "cronos_record_recall",
        "Record a memory retrieval (episodic/semantic store, RAG hit, past "
        "incident). score is an integer fraction in [0,1], e.g. 91/100. "
        "Pass score_num=0, score_den=1 if no relevance score is available.",
        {
            "trace_id": {"type": "string"},
            "memory_id": {"type": "string"},
            "summary": {"type": "string"},
            "score_num": {"type": "integer"},
            "score_den": {"type": "integer"},
        },
        ["trace_id", "memory_id", "summary"],
    ),
    _tool(
        "cronos_close_trace",
        "Record the final decision and seal the trace into the SHA-256 "
        "tamper-evident chain. CRONOS computes quality, observational "
        "diversity, and may LOWER the stored confidence if the evidence base "
        "does not support the submitted value. confidence is an integer "
        "fraction, e.g. 74/100. Call exactly once, as your final tool call.",
        {
            "trace_id": {"type": "string"},
            "decision": {"type": "string"},
            "confidence_num": {"type": "integer"},
            "confidence_den": {"type": "integer"},
        },
        ["trace_id", "decision", "confidence_num"],
    ),
    _tool(
        "cronos_explain_trace",
        "Return a full sealed trace: objective, every recorded step in order, "
        "decision, constrained confidence, quality metrics, and chain hash. "
        "Empty trace_id returns the most recently sealed trace.",
        {"trace_id": {"type": "string"}},
        [],
    ),
    _tool(
        "cronos_list_traces",
        "List recent sealed traces (headers only). Filter by agent_id or pass "
        "empty string for all agents. limit is capped at 50.",
        {
            "agent_id": {"type": "string"},
            "limit": {"type": "integer"},
        },
        [],
    ),
    _tool(
        "cronos_verify_chain",
        "Recompute every hash in the trace chain and verify linkage. Any "
        "retroactive modification of any trace breaks every subsequent hash.",
        {},
        [],
    ),
]


# ---------------------------------------------------------------------------
# Tool executor — real CRONOS, same semantics as the MCP server
# ---------------------------------------------------------------------------

class CronosToolExecutor:
    """
    Executes CRONOS tool calls against a real TraceStore.

    Mirrors cronos/mcp_server.py semantics (open-trace registry, integer
    fractions, input truncation) without the MCP/stdio transport, so a
    Qwen-driven trace and a Claude-driven trace are indistinguishable in
    the database.
    """

    def __init__(self, db_path: str = "cronos_qwen.db") -> None:
        self._store = TraceStore(db_path)
        self._open: dict[str, CronosTracer] = {}

    # -- lifecycle ------------------------------------------------------

    @property
    def open_trace_ids(self) -> list[str]:
        return list(self._open)

    def close(self) -> None:
        self._store._conn.close()

    # -- dispatch -------------------------------------------------------

    def execute(self, name: str, args: dict) -> dict:
        """Run one tool call; always returns a JSON-safe dict (errors included)."""
        handler = getattr(self, f"_do_{name}", None)
        if handler is None:
            return {"error": f"Unknown tool {name!r}."}
        try:
            return handler(**args)
        except TypeError as exc:
            return {"error": f"{name}: bad arguments — {exc}"}
        except ValueError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — surfaced to the model, never fatal
            log.error("Tool %s failed: %s", name, exc)
            return {"error": f"{name} failed: {type(exc).__name__}: {exc}"}

    def _get_open(self, trace_id: str) -> CronosTracer:
        tracer = self._open.get(trace_id)
        if tracer is None:
            raise ValueError(
                f"No open trace with id {trace_id!r}. "
                "Call cronos_open_trace first, or the trace was already closed."
            )
        return tracer

    # -- tools ----------------------------------------------------------

    def _do_cronos_open_trace(self, agent_id: str, objective: str) -> dict:
        if len(self._open) >= _MAX_OPEN_TRACES:
            raise ValueError(
                f"Too many open traces ({_MAX_OPEN_TRACES}). Close existing "
                "traces before opening new ones."
            )
        tracer = CronosTracer(
            store=self._store,
            agent_id=_trunc(agent_id, _MAX_ID),
            channel_id="",
            user_id="",
            objective=_trunc(objective),
        )
        self._open[tracer.trace.trace_id] = tracer
        return {
            "trace_id": tracer.trace.trace_id,
            "started_at": tracer.trace.started_at,
            "open_traces": len(self._open),
        }

    def _do_cronos_add_hypothesis(self, trace_id: str, label: str, description: str) -> dict:
        tracer = self._get_open(trace_id)
        tracer.add_hypothesis(_trunc(label, _MAX_ID), _trunc(description))
        return {"trace_id": trace_id, "steps": len(tracer.trace.steps)}

    def _do_cronos_add_evidence(
        self, trace_id: str, text: str, supports: str = "", refutes: str = "",
    ) -> dict:
        tracer = self._get_open(trace_id)
        tracer.add_evidence(
            _trunc(text),
            supports=_trunc(supports, _MAX_ID) or None,
            refutes=_trunc(refutes, _MAX_ID) or None,
        )
        return {"trace_id": trace_id, "steps": len(tracer.trace.steps)}

    def _do_cronos_discard_hypothesis(self, trace_id: str, label: str, reason: str) -> dict:
        tracer = self._get_open(trace_id)
        tracer.discard_hypothesis(_trunc(label, _MAX_ID), _trunc(reason))
        return {"trace_id": trace_id, "steps": len(tracer.trace.steps)}

    def _do_cronos_record_tool_call(
        self, trace_id: str, tool_name: str, result_summary: str,
    ) -> dict:
        tracer = self._get_open(trace_id)
        tracer.call_tool(_trunc(tool_name, _MAX_ID), _trunc(result_summary))
        return {"trace_id": trace_id, "steps": len(tracer.trace.steps)}

    def _do_cronos_record_recall(
        self, trace_id: str, memory_id: str, summary: str,
        score_num: int = 0, score_den: int = 1,
    ) -> dict:
        tracer = self._get_open(trace_id)
        score = _fraction(score_num, score_den, "score") if score_num else None
        tracer.record_recall(_trunc(memory_id, _MAX_ID), _trunc(summary), score=score)
        return {"trace_id": trace_id, "steps": len(tracer.trace.steps)}

    def _do_cronos_close_trace(
        self, trace_id: str, decision: str,
        confidence_num: int, confidence_den: int = 100,
    ) -> dict:
        tracer = self._get_open(trace_id)
        confidence = _fraction(confidence_num, confidence_den, "confidence")
        tracer.decide(_trunc(decision), confidence)
        tracer.__exit__(None, None, None)
        self._open.pop(trace_id, None)

        trace = tracer.trace
        adj = trace.confidence
        return {
            "trace_id": trace.trace_id,
            "decision": trace.decision,
            "confidence_submitted": f"{confidence.numerator}/{confidence.denominator}",
            "confidence_stored": f"{adj.numerator}/{adj.denominator}" if adj else "0/1",
            "confidence_warnings": trace.confidence_warnings,
            "quality": trace.quality.value if trace.quality else None,
            "diversity": (f"{trace.diversity.numerator}/{trace.diversity.denominator}"
                          if trace.diversity is not None else None),
            "contradictions": trace.contradictions,
            "entry_hash": trace.entry_hash,
            "chain_ok": trace.chain_ok,
        }

    def _do_cronos_explain_trace(self, trace_id: str = "") -> dict:
        trace = (self._store.load_trace(trace_id) if trace_id
                 else self._store.get_latest_trace())
        if trace is None:
            return {"error": f"No trace found for id {trace_id!r}."}
        return {
            "trace_id": trace.trace_id,
            "agent_id": trace.agent_id,
            "objective": trace.objective,
            "steps": [
                {"kind": s.kind.value, "payload": s.payload, "timestamp": s.timestamp}
                for s in trace.steps
            ],
            "decision": trace.decision,
            # `is not None`, not truthiness: Fraction(0) is falsy but is a
            # real, stored confidence — an auto-closed trace reports 0/1.
            "confidence": (f"{trace.confidence.numerator}/{trace.confidence.denominator}"
                           if trace.confidence is not None else None),
            "quality": trace.quality.value if trace.quality else None,
            "entry_hash": trace.entry_hash,
            "chain_ok": trace.chain_ok,
        }

    def _do_cronos_list_traces(self, agent_id: str = "", limit: int = 10) -> dict:
        limit = max(1, min(int(limit), 50))
        traces = self._store.get_recent_traces(agent_id=agent_id or None, limit=limit)
        return {"count": len(traces), "traces": traces}

    def _do_cronos_verify_chain(self) -> dict:
        ok, errors = self._store.chain.verify()
        return {
            "chain_ok": ok,
            "entries": self._store.count_traces(),
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a forensic reasoning agent equipped with CRONOS, a tamper-evident
black-box recorder. You MUST document your reasoning as you work:

1. FIRST call cronos_open_trace with your agent_id and the task as objective.
2. Register EVERY candidate explanation with cronos_add_hypothesis before
   committing to any of them.
3. Record each fact you establish with cronos_add_evidence, linking it to
   the hypothesis it supports or refutes.
4. When you rule a hypothesis out, call cronos_discard_hypothesis with the
   reason. Discards are as valuable as conclusions.
5. Record external lookups with cronos_record_tool_call.
6. FINALLY call cronos_close_trace exactly once, with your decision and an
   integer confidence fraction (e.g. 70/100). CRONOS may lower your stored
   confidence if your evidence base does not support it — that is correct
   behavior, not an error.

After closing the trace, give the user your final answer in plain text.
Be rigorous: hypotheses before conclusions, evidence before confidence."""


@dataclass
class AgentOutcome:
    """Result of one QwenCronosAgent.run() call."""
    answer: str
    sealed_trace_ids: list[str]
    unsealed_trace_ids: list[str]     # auto-closed by the driver, not the model
    chain_ok: bool
    turns: int
    tool_calls: int
    transcript: list[dict] = field(repr=False, default_factory=list)


class QwenCronosAgent:
    """
    Runs qwen-max as a CRONOS-disciplined agent via DashScope function
    calling. The `transport` parameter accepts any callable
    (payload: dict) -> dict mimicking the chat/completions response shape,
    which is how tests drive the loop without the network.
    """

    def __init__(
        self,
        db_path: str = "cronos_qwen.db",
        api_key: Optional[str] = None,
        model: str = QWEN_AGENT_MODEL,
        base_url: str = QWEN_BASE_URL,
        timeout: int = 60,
        transport: Optional[Callable[[dict], dict]] = None,
    ) -> None:
        self.executor = CronosToolExecutor(db_path)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self._transport = transport or self._http_transport
        if transport is None and not self.api_key:
            raise RuntimeError(
                "QwenCronosAgent requires DASHSCOPE_API_KEY (or an injected "
                "transport for testing). This driver exists to run the live "
                "Qwen model — there is no offline simulation mode."
            )

    # -- transport ------------------------------------------------------

    def _http_transport(self, payload: dict) -> dict:
        import requests

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # -- loop -----------------------------------------------------------

    def run(self, task: str, agent_id: str = "qwen-cronos-agent") -> AgentOutcome:
        """
        Execute one task with full CRONOS discipline. Returns the final
        answer plus the sealed trace ids and post-run chain verification.
        """
        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"agent_id: {agent_id}\n\nTask: {task}"},
        ]
        sealed: list[str] = []
        total_tool_calls = 0
        answer = ""

        for turn in range(1, _MAX_TURNS + 1):
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": CRONOS_TOOLS,
                "temperature": 0.2,
            }
            response = self._transport(payload)
            choice = response["choices"][0]
            msg = choice["message"]
            messages.append(msg)

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                answer = msg.get("content") or ""
                break

            for call in tool_calls[:_MAX_TOOL_CALLS_PER_TURN]:
                fn = call["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except ValueError as exc:
                    result: dict = {"error": f"Malformed tool arguments: {exc}"}
                else:
                    result = self.executor.execute(name, args)

                total_tool_calls += 1
                if name == "cronos_close_trace" and "entry_hash" in result:
                    sealed.append(result["trace_id"])

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        else:
            turn = _MAX_TURNS  # loop exhausted without a text answer

        # Honest degradation: traces the model never sealed are closed by
        # the driver with zero confidence and an explicit marker — an
        # unsealed trace must never look like a completed one.
        unsealed = []
        for tid in self.executor.open_trace_ids:
            res = self.executor.execute("cronos_close_trace", {
                "trace_id": tid,
                "decision": "UNSEALED-BY-MODEL: driver auto-close (agent loop "
                            "ended without cronos_close_trace)",
                "confidence_num": 0,
                "confidence_den": 100,
            })
            if "entry_hash" in res:
                unsealed.append(tid)

        verify = self.executor.execute("cronos_verify_chain", {})

        return AgentOutcome(
            answer=answer,
            sealed_trace_ids=sealed,
            unsealed_trace_ids=unsealed,
            chain_ok=bool(verify.get("chain_ok")),
            turns=turn,
            tool_calls=total_tool_calls,
            transcript=messages,
        )

    def close(self) -> None:
        self.executor.close()

    def __enter__(self) -> "QwenCronosAgent":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
