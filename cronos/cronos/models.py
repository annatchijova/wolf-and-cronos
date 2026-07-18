"""
CRONOS — shared data models.
All confidence values use fractions.Fraction — zero floats in the scoring path.
"""
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Optional


# TraceQuality is defined here (not in quality.py) to avoid circular imports.
class TraceQuality(str, Enum):
    """
    Observational completeness of a trace.
    Adapted from VIGÍA's acquisition assurance gating.
    FULL    — RECALL + TOOL + (HYPOTHESIS or EVIDENCE) present
    PARTIAL — two of the three observation groups present
    MINIMAL — only one observation group
    EMPTY   — no observations (only OBJECTIVE and/or DECISION)
    """
    FULL    = "FULL"
    PARTIAL = "PARTIAL"
    MINIMAL = "MINIMAL"
    EMPTY   = "EMPTY"


class StepKind(str, Enum):
    OBJECTIVE  = "objective"   # what the agent was asked to do
    RECALL     = "recall"      # memory retrieved from episodic store
    TOOL       = "tool"        # external tool called (Jira, GitHub, DB…)
    HYPOTHESIS = "hypothesis"  # candidate explanation generated
    DISCARD    = "discard"     # hypothesis rejected with reason
    EVIDENCE   = "evidence"    # fact that supports or refutes a hypothesis
    DECISION   = "decision"    # final action chosen


@dataclass
class TraceStep:
    kind: StepKind
    payload: dict   # step-specific structured data (varies by kind)
    timestamp: str  # UTC ISO-8601


@dataclass
class Trace:
    trace_id: str             # UUID4
    agent_id: str             # e.g. "ticket-resolver", "onboarding-bot"
    channel_id: str           # Slack channel where the agent was triggered
    user_id: str              # Slack user who triggered the action
    objective: str            # what the agent was asked to accomplish
    steps: list[TraceStep] = field(default_factory=list)
    decision: Optional[str] = None           # final decision text
    confidence: Optional[Fraction] = None    # 0–1, no floats
    confidence_corrupt: bool = False         # stored confidence failed to parse on load
    started_at: Optional[str] = None         # UTC ISO-8601
    closed_at: Optional[str] = None          # UTC ISO-8601
    entry_hash: Optional[str] = None         # SHA-256 from the chain
    chain_ok: bool = False                   # chain integrity at close time
    closed: bool = False
    # ── Quality / epistemics (ideas from VIGÍA) ──────────────────────────────
    quality: Optional[TraceQuality] = None           # observational completeness
    diversity: Optional[Fraction] = None             # Fraction(groups, 3) — 0/3 to 3/3
    contradictions: list[str] = field(default_factory=list)  # detected contradictions
    confidence_warnings: list[str] = field(default_factory=list)  # ceiling/floor clamping
    cronos_version: str = "0.1.0"                    # version sentinel (config_sentinel)
