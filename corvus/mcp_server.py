"""
CORVUS MCP Server
=================
Exposes the CORVUS manipulation-detection engine as an MCP server so that
external agents (Claude, Qwen-based assistants, CI pipelines) can query
verdicts, behavioral baselines, and the tamper-evident audit chain over
the Model Context Protocol.

Design notes
------------
- Persists to a SQLite database (CORVUS_DB_PATH), so baselines built from
  analyzed traffic are queryable by any MCP client.
- No external service credentials required — fully local analysis.
- Read-mostly by design: `analyze_message` defaults to persist=False so
  external probes never pollute per-user baselines or the audit chain
  unless the caller explicitly opts in.
- Input sanitization pattern adapted from VIGÍA (vigia_sift_bridge):
  hard caps on text size and list length to prevent OOM/ReDoS via MCP.

Run
---
    pip install "mcp>=1.0.0"
    python -m corvus.mcp.server            # stdio transport (default)

Claude Desktop / Claude Code config:
    {
      "mcpServers": {
        "corvus": {
          "command": "python",
          "args": ["-m", "corvus.mcp.server"],
          "env": { "CORVUS_DB_PATH": "/path/to/memory.db" }
        }
      }
    }
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from fractions import Fraction
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from corvus.config import Config
from corvus.memory.engine import MemoryEngine
from corvus.analysis import Analyzer
from corvus.verdict.engine import VerdictEngine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input limits — VIGÍA-style hard caps. MCP clients are untrusted callers.
# ---------------------------------------------------------------------------
MAX_TEXT_LENGTH = 50_000     # 50 KB per message
MAX_HISTORY_ITEMS = 20       # conversation history entries per call
MAX_EXPORT_ENTRIES = 200     # audit chain entries per export call
MAX_USER_ID_LENGTH = 64


def _sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Cast and truncate input to prevent ReDoS / OOM through MCP calls."""
    if not isinstance(text, str):
        text = str(text)
    encoded = text.encode("utf-8")[:max_length]
    return encoded.decode("utf-8", errors="ignore")


def _sanitize_history(history: Optional[list]) -> list[str]:
    """Validate and cap the conversation history list."""
    if not history:
        return []
    if not isinstance(history, list):
        raise ValueError("conversation_history must be a list of strings.")
    return [_sanitize_text(h) for h in history[:MAX_HISTORY_ITEMS]]


def _sanitize_id(value: str, name: str) -> str:
    """Validate a user/channel identifier."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    value = value.strip().lstrip("@#")
    if len(value) > MAX_USER_ID_LENGTH:
        raise ValueError(f"{name} too long (max {MAX_USER_ID_LENGTH} chars).")
    return value


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Serialization — Fraction-typed scores travel as float + exact string.
# The exact fraction is CORVUS's differentiator (deterministic, bit-for-bit
# reproducible arithmetic); we preserve it instead of flattening to float.
# ---------------------------------------------------------------------------
def _jsonify(obj: Any) -> Any:
    """Recursively convert CORVUS dataclasses/Fractions/Enums to JSON-safe."""
    if isinstance(obj, Fraction):
        return {"value": round(float(obj), 6), "exact": f"{obj.numerator}/{obj.denominator}"}
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj):
        return {k: _jsonify(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Engine bootstrap — persistent store at CORVUS_DB_PATH
# ---------------------------------------------------------------------------
_config = Config()
_memory = MemoryEngine(_config.CORVUS_DB_PATH)
_memory.initialize()
_analyzer = Analyzer()
_verdict_engine = VerdictEngine(_config)

mcp = FastMCP("corvus")


# ---------------------------------------------------------------------------
# TOOLS
# ---------------------------------------------------------------------------

@mcp.tool()
def analyze_message(
    text: str,
    user_id: str = "mcp_external",
    conversation_history: Optional[list] = None,
    persist: bool = False,
) -> dict:
    """
    Run the full CORVUS pipeline (L1–L6) on a message and return a verdict.

    Layers: L1 Grice maxims, L2 Carnegie+Cialdini influence, L3 Aristotle
    rhetorical imbalance, L4 Berne transactional analysis, L5 forensic
    linguistics, L6 Peirce abductive synthesis. Deterministic — same input
    always yields the same Fraction-exact score.

    Args:
        text: The message to analyze (max 50 KB).
        user_id: Identity to evaluate against. If this user has a behavioral
            baseline in CORVUS memory (built from previously analyzed traffic), the
            analysis measures deviation from THEIR normal, not just absolute
            thresholds. Unknown users get the default baseline.
        conversation_history: Optional prior messages, oldest first (max 20).
        persist: If True, store the result and update the user's baseline
            and the audit chain. Default False — external probes must not
            pollute behavioral memory.

    Returns:
        Verdict (SILENT/WATCH/ALERT/CRITICAL), exact Fraction score,
        rationale, per-layer signals, and audit hash.
    """
    try:
        text = _sanitize_text(text)
        user_id = _sanitize_id(user_id, "user_id")
        history = _sanitize_history(conversation_history)
    except ValueError as exc:
        return {"error": str(exc)}

    if not text.strip():
        return {"error": "text must be a non-empty string."}

    baseline = _memory.get_user_baseline(user_id)
    message_id = f"mcp-{uuid.uuid4().hex[:12]}"
    timestamp = _utcnow()

    result = _analyzer.analyze(
        message_id=message_id,
        user_id=user_id,
        channel_id="mcp",
        text=text,
        timestamp=timestamp,
        conversation_history=history,
        user_baseline=baseline,
    )
    verdict = _verdict_engine.compute(result)

    if persist:
        _memory.store_message(result, verdict)
        logger.info(f"[CORVUS-MCP] Persisted analysis {message_id} for {user_id}")

    layers = {
        "l1_grice": _jsonify(result.grice),
        "l2_influence": _jsonify(result.influence),
        "l3_aristotle": _jsonify(result.aristotle),
        "l4_berne": _jsonify(result.berne),
        "l5_linguistics": _jsonify(result.linguistic),
        "l6_peirce": _jsonify(result.peirce),
    }

    return {
        "message_id": message_id,
        "user_id": user_id,
        "timestamp": timestamp,
        "verdict": verdict.level.value,
        "score": _jsonify(verdict.score),
        "rationale": verdict.rationale,
        "signals_fired": verdict.signals_fired,
        "active_signals": result.active_signals,
        "baseline_delta": _jsonify(result.baseline_delta),
        "recommendation": verdict.recommendation,
        "layers": layers,
        # FIX: a crashed detector must be visible to callers, not folded into
        # an apparently-clean result — see corvus.analysis.Analyzer.analyze.
        "crashed_agents": result.crashed_agents,
        "audit_hash": verdict.audit_hash,
        "persisted": persist,
        "corvus_verdict": (
            f"[CORVUS]: {verdict.level.value}. "
            f"{result.active_signals} layer(s) fired "
            f"({', '.join(verdict.signals_fired) or 'none'}). "
            f"{verdict.rationale}"
            + (
                f" ⚠ {len(result.crashed_agents)} detector(s) crashed: "
                f"{', '.join(result.crashed_agents)} — treated as silent, not clean."
                if result.crashed_agents else ""
            )
        ),
    }


@mcp.tool()
def get_user_baseline(user_id: str) -> dict:
    """
    Return the adaptive behavioral baseline CORVUS holds for a user.

    Baselines are built online (Welford's algorithm) from analyzed
    traffic. They describe the user's OWN normal:
    noun/verb ratio, cognitive-load stress, average signals per message.
    Deviation from this baseline amplifies verdict scores.
    """
    try:
        user_id = _sanitize_id(user_id, "user_id")
    except ValueError as exc:
        return {"error": str(exc)}

    baseline = _memory.get_user_baseline(user_id)
    return {
        "user_id": user_id,
        "baseline": _jsonify(baseline),
        "timestamp": _utcnow(),
    }


@mcp.tool()
def get_user_history(user_id: str, limit: int = 20) -> dict:
    """
    Return the recent analysis history for a user: verdicts, signal counts,
    and audit hashes for their last N analyzed messages. Message text is
    never stored — only SHA-256 hashes and derived metrics (privacy by design).
    """
    try:
        user_id = _sanitize_id(user_id, "user_id")
    except ValueError as exc:
        return {"error": str(exc)}

    limit = max(1, min(int(limit), 100))
    history = _memory.get_user_history(user_id, limit=limit)
    return {
        "user_id": user_id,
        "entries": _jsonify(history),
        "count": len(history),
        "timestamp": _utcnow(),
    }


@mcp.tool()
def get_channel_stats(channel_id: str) -> dict:
    """
    Return aggregate analysis statistics for a channel: message
    volume, verdict distribution, and highest-risk users.
    """
    try:
        channel_id = _sanitize_id(channel_id, "channel_id")
    except ValueError as exc:
        return {"error": str(exc)}

    stats = _memory.get_channel_stats(channel_id)
    return {
        "channel_id": channel_id,
        "stats": _jsonify(stats),
        "timestamp": _utcnow(),
    }


@mcp.tool()
def verify_audit_chain() -> dict:
    """
    Verify the integrity of the SHA-256 tamper-evident audit chain.

    Every CORVUS analysis appends a hash-linked entry. If any entry was
    modified or deleted after the fact, the chain breaks and this tool
    reports exactly where. Returns {intact: bool, violations: [...]}.
    """
    chain = _memory.get_audit_chain()
    intact, violations = chain.verify()
    return {
        "intact": intact,
        "violations": violations,
        "timestamp": _utcnow(),
        "corvus_verdict": (
            "[CORVUS]: AUDIT CHAIN INTACT. Every entry hash-links to its predecessor."
            if intact else
            f"[CORVUS]: AUDIT CHAIN BROKEN — {len(violations)} violation(s). "
            "Stored history was tampered with after the fact."
        ),
    }


@mcp.tool()
def export_audit_chain(limit: int = 50) -> dict:
    """
    Export the most recent entries of the audit chain for external review
    or evidence preservation. Entries include operation, user, channel,
    payload summary, and the linked hashes.
    """
    limit = max(1, min(int(limit), MAX_EXPORT_ENTRIES))
    chain = _memory.get_audit_chain()
    entries = chain.export()
    recent = entries[-limit:]
    return {
        "entries": _jsonify(recent),
        "returned": len(recent),
        "total_in_chain": len(entries),
        "timestamp": _utcnow(),
    }


@mcp.tool()
def corvus_info() -> dict:
    """
    Describe CORVUS's analysis layers, verdict thresholds, and guarantees.
    Call this first to understand how to interpret verdicts and scores.
    """
    return {
        "name": "CORVUS",
        "description": (
            "Real-time communication intent analysis. Detects manipulation, "
            "social engineering, and deceptive patterns using six parallel "
            "theoretical frameworks and per-user adaptive baselines."
        ),
        "layers": {
            "L1": "Grice — Cooperative Principle maxim violations (QUANTITY/QUALITY/RELATION/MANNER)",
            "L2": "Carnegie + Cialdini — influence tactics (flattery, urgency, AUTHORITY, SCARCITY, ...)",
            "L3": "Aristotle — rhetorical imbalance (pathos >> logos = manipulation signal)",
            "L4": "Berne — transactional analysis (ego states, crossed/ulterior transactions)",
            "L5": "Forensic linguistics — noun/verb ratio z-score, cognitive load, Zipf deviation",
            "L6": "Peirce — bounded abductive synthesis of L1–L5 (Miller limit 7)",
        },
        "verdict_thresholds": {
            "SILENT": "score < 0.20 — memory update only",
            "WATCH": "0.20 <= score < 0.45 — DM security channel",
            "ALERT": "0.45 <= score < 0.75 — thread reply",
            "CRITICAL": "score >= 0.75 — pinned alert + sealed audit bundle",
        },
        "guarantees": [
            "Deterministic: fractions.Fraction arithmetic — same input, same exact score",
            "Corroboration gate: >= 2 independent layers required for a non-SILENT verdict",
            "Adaptive: deviation measured against each user's own baseline, not absolute thresholds",
            "Tamper-evident: every analysis appended to a SHA-256 hash chain",
            "Privacy by design: message text never stored, only hashes and derived metrics",
        ],
        "timestamp": _utcnow(),
    }


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=_config.LOG_LEVEL,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(
        f"CORVUS MCP server starting — db={_config.CORVUS_DB_PATH}, "
        "transport=stdio"
    )
    mcp.run()


if __name__ == "__main__":
    main()
