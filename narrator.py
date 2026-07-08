"""
qwen-track3/narrator.py
========================
Qwen-powered negotiation narrator.

Calls Qwen Cloud via qwen_client.QwenClient (requests, no openai SDK).
The narrator is OUTSIDE the decision path — the CORVUS verdict is sealed
before Qwen is called, and Qwen cannot alter it.

This follows the same architectural invariant as raven-memory and VIGÍA:
  LLM out of the decision path.
"""

from __future__ import annotations

from dataclasses import dataclass

from bridge import NegotiationResult
from qwen_client import QwenClient


# ---------------------------------------------------------------------------
# Narration input (read-only summary derived from NegotiationResult)
# ---------------------------------------------------------------------------

@dataclass
class NarrationInput:
    verdict_level: str
    score_pct:     int
    active_agents: list[str]
    silent_agents: list[str]
    rationale:     str
    audit_hash:    str       # first 16 chars for readability

    @classmethod
    def from_result(cls, result: NegotiationResult) -> "NarrationInput":
        return cls(
            verdict_level = result.verdict_level.value,
            score_pct     = int(round(float(result.score) * 100)),
            active_agents = result.active_agents,
            silent_agents = result.silent_agents,
            rationale     = result.rationale,
            audit_hash    = result.audit_hash[:16],
        )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_AGENT_LABEL = {
    "L1_GRICE":      "Grice Maxim Analyst    (clarity, quantity, quality, relevance)",
    "L2_CARNEGIE":   "Influence Analyst      (Carnegie persuasion + Cialdini principles)",
    "L3_ARISTOTLE":  "Rhetoric Analyst       (ethos / pathos / logos balance)",
    "L4_BERNE":      "Transaction Analyst    (ego states, ulterior agendas)",
    "L5_LINGUISTIC": "Linguistic Analyst     (complexity, cognitive load, register)",
    "L6_PEIRCE":     "Synthesis Agent        (Peirce abductive reasoning)",
    "GATE":          "Corroboration Gate     (consensus: >= 2 agents required)",
}


_PROMPT_SENTINELS = (
    "=== SEALED VERDICT",
    "=== END SEALED VERDICT",
    "=== NEGOTIATION OUTCOME",
    "=== END NEGOTIATION OUTCOME",
)


def _sanitize_text(raw: str, max_chars: int = 300) -> str:
    """
    RT-02: Strip prompt-injection markers from user-supplied text before
    embedding it in the Qwen prompt.  Removes any line that starts with
    a known sentinel prefix (case-insensitive after strip).  The result
    is truncated to `max_chars` and the original content is never altered.
    """
    lines = raw.splitlines()
    clean = []
    for line in lines:
        stripped = line.strip().upper()
        if any(stripped.startswith(s.upper()) for s in _PROMPT_SENTINELS):
            clean.append("[REDACTED]")
        else:
            clean.append(line)
    joined = "\n".join(clean)
    return joined[:max_chars]


def _build_prompt(ni: NarrationInput, text: str) -> str:
    active_block = "\n".join(
        f"  FIRED  — {_AGENT_LABEL.get(a, a)}"
        for a in ni.active_agents
    ) or "  (none)"

    silent_block = "\n".join(
        f"  SILENT — {_AGENT_LABEL.get(a, a)}"
        for a in ni.silent_agents
    ) or "  (none)"

    gate_outcome = (
        "threshold met — verdict emitted"
        if ni.verdict_level != "SILENT"
        else "threshold not met — SILENT enforced"
    )

    safe_text = _sanitize_text(text, max_chars=300)
    truncated = len(text) > 300 or safe_text != text[:300]

    return f"""=== SEALED VERDICT (DO NOT ALTER) ===
Verdict : {ni.verdict_level}
Score   : {ni.score_pct}/100
Hash    : {ni.audit_hash}...
=== END SEALED VERDICT ===

Text analyzed (first 300 chars):
  "{safe_text}{"..." if truncated else ""}"

=== NEGOTIATION OUTCOME ===
Agents that voted non-SILENT (filed an anomaly hypothesis):
{active_block}

Agents that voted SILENT (no anomaly detected):
{silent_block}

Corroboration gate ({len(ni.active_agents)} active / 5 required >= 2): {gate_outcome}

Peirce synthesis (Thirdness — inferred pattern):
  {ni.rationale}
=== END NEGOTIATION OUTCOME ===

Write a negotiation transcript with:
1. For each FIRED agent (2-3 sentences): what it detected and why.
2. For SILENT agents (1 sentence): why they found nothing.
3. Gate paragraph: how consensus was reached (or blocked).
4. Final sentence: restate the sealed verdict verbatim.

Be precise. Do not invent evidence. Do not suggest an alternative verdict."""


# ---------------------------------------------------------------------------
# Narrator
# ---------------------------------------------------------------------------

class QwenNarrator:
    """
    Narrates a CORVUS-CRONOS negotiation result using Qwen Cloud.

    Uses QwenClient (requests, DashScope international endpoint).
    Falls back to structured plain-text when DASHSCOPE_API_KEY is absent.
    """

    def __init__(self, client: QwenClient | None = None) -> None:
        self._client = client or QwenClient()

    def narrate(self, result: NegotiationResult, text: str) -> str:
        """Return a human-readable negotiation transcript."""
        ni = NarrationInput.from_result(result)
        if not self._client.available:
            return self._fallback(ni)
        prompt = _build_prompt(ni, text)
        return self._client.complete(prompt)

    @staticmethod
    def _fallback(ni: NarrationInput) -> str:
        lines = [
            "=== NEGOTIATION TRANSCRIPT (offline mode) ===",
            "",
            f"Verdict: {ni.verdict_level} ({ni.score_pct}/100)  "
            f"Audit: {ni.audit_hash}...",
            "",
            "Agents that detected anomalies:",
        ]
        for a in ni.active_agents:
            lines.append(f"  {_AGENT_LABEL.get(a, a)}: filed non-SILENT hypothesis in CRONOS")
        if not ni.active_agents:
            lines.append("  (none)")

        lines += ["", "Agents that found nothing:"]
        for a in ni.silent_agents:
            lines.append(f"  {_AGENT_LABEL.get(a, a)}: all thresholds within normal range")
        if not ni.silent_agents:
            lines.append("  (none)")

        gate_msg = (
            "threshold met — verdict emitted"
            if ni.verdict_level != "SILENT"
            else "threshold NOT met — SILENT enforced by gate"
        )
        lines += [
            "",
            f"Gate ({len(ni.active_agents)} active agent(s)): {gate_msg}.",
            "",
            f"Interpretation: {ni.rationale}",
            "",
            "Set DASHSCOPE_API_KEY for Qwen-powered narration.",
            "=== END TRANSCRIPT ===",
        ]
        return "\n".join(lines)

    def close(self) -> None:
        self._client.close()
