"""
CRONOS — Narrator
Synthesizes human-readable explanations from a Trace — no LLM required.

The narrator answers the question every incident responder asks:
"What did the agent know, what did it consider, and why did it decide this?"

Three output levels:
- short()   → {decision, why_lines, confidence_pct, hash_short} for Block Kit
- full()    → all sections (memories, tools, hypotheses, evidence)
- natural() → flowing prose paragraph

All synthesis is deterministic rule-based NLG from structured step data.
"""

import re
from fractions import Fraction
from typing import Optional

from .models import Trace, StepKind, TraceQuality
from .quality import devils_advocate as _devils_advocate

# A 4-digit year 2020-2039 as a whole token.  Word boundaries avoid matching a
# year embedded in a larger number (e.g. "2024" inside ticket id "12024567").
_YEAR_RE = re.compile(r"\b20[2-3]\d\b")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _confidence_pct(f: Optional[Fraction]) -> str:
    if f is None:
        return "unknown"
    # Multiply by 100 in Fraction space, then round to int — zero floats.
    return f"{round(f * 100)}%"


def _confidence_label(f: Optional[Fraction]) -> str:
    if f is None:
        return "unknown confidence"
    if f >= Fraction(85, 100):
        return "very high confidence"
    if f >= Fraction(70, 100):
        return "high confidence"
    if f >= Fraction(50, 100):
        return "moderate confidence"
    if f >= Fraction(30, 100):
        return "low confidence"
    return "very low confidence"


def _plural(n: int, singular: str, plural: str) -> str:
    return singular if n == 1 else plural


# ── Narrator class ────────────────────────────────────────────────────────────

class Narrator:
    """
    Converts a closed Trace into human-readable form.
    Construct with a Trace object; call short(), full(), or natural().
    """

    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        self._recalls    = [s for s in trace.steps if s.kind == StepKind.RECALL]
        self._tools      = [s for s in trace.steps if s.kind == StepKind.TOOL]
        self._hypotheses = [s for s in trace.steps if s.kind == StepKind.HYPOTHESIS]
        self._discards   = [s for s in trace.steps if s.kind == StepKind.DISCARD]
        self._evidence   = [s for s in trace.steps if s.kind == StepKind.EVIDENCE]
        self._discarded_labels = {d.payload["label"] for d in self._discards}

    # ── Short card (Block Kit surface) ────────────────────────────────────────

    def short(self) -> dict:
        """
        Returns a dict for Block Kit formatters.

        Keys:
            decision       str
            why_lines      list[tuple[str, str]]  — (symbol, text)
            confidence_pct str
            confidence_label str
            hash_short     str
            chain_ok       bool
            agent_id       str
            trace_id       str
            objective      str
        """
        why: list[tuple[str, str]] = []

        # Recalled memories
        n = len(self._recalls)
        if n:
            ids = [s.payload["memory_id"] for s in self._recalls[:3]]
            more = f", +" + str(n - 3) + " more" if n > 3 else ""
            why.append((
                "✓",
                f"Retrieved {n} relevant {_plural(n, 'memory', 'memories')} "
                f"({', '.join(ids)}{more})"
            ))

        # First recall that references a year — treat as "matching incident"
        for r in self._recalls:
            summary = r.payload.get("summary", "")
            if _YEAR_RE.search(summary):
                why.append(("✓", f"Found matching incident — {summary[:80]}"))
                break

        # Tool calls
        for t in self._tools:
            result = t.payload["result"]
            why.append(("✓", f"{t.payload['tool']} → {result[:80]}"))

        # Supporting evidence
        for e in self._evidence:
            if "supports" in e.payload:
                why.append(("✓", e.payload["text"][:90]))

        # Discarded hypotheses
        for d in self._discards:
            reason = d.payload["reason"]
            why.append(("✗", f"{d.payload['label']} discarded — {reason[:60]}"))

        hash_short = (self.trace.entry_hash or "")[:7] or "pending"

        # Quality level badge
        quality = self.trace.quality
        quality_label = quality.value if quality else "UNKNOWN"

        # Confidence warnings (ceiling/floor clamping)
        conf_warnings = list(self.trace.confidence_warnings or [])
        # Surface load-time corruption instead of letting it read as "unknown".
        if self.trace.confidence_corrupt:
            conf_warnings.insert(
                0, "Stored confidence was corrupt and could not be read — "
                   "displayed value is not trustworthy."
            )

        # Contradictions detected
        contradictions = self.trace.contradictions or []

        return {
            "decision":             self.trace.decision or "(no decision)",
            "why_lines":            why,
            "confidence_pct":       _confidence_pct(self.trace.confidence),
            "confidence_label":     _confidence_label(self.trace.confidence),
            "hash_short":           hash_short,
            "chain_ok":             self.trace.chain_ok,
            "agent_id":             self.trace.agent_id,
            "trace_id":             self.trace.trace_id,
            "objective":            self.trace.objective,
            "quality":              quality_label,
            "diversity_pct":        (
                f"{round(float(self.trace.diversity) * 100)}%"
                if self.trace.diversity is not None else "—"
            ),
            "confidence_warnings":  conf_warnings,
            "contradictions":       contradictions,
            "cronos_version":       self.trace.cronos_version or "—",
        }

    # ── Full breakdown ─────────────────────────────────────────────────────────

    def full(self) -> dict:
        """
        Returns all sections for the expanded view.
        Includes memories, tools, hypotheses (with status), evidence, timestamps.
        """
        short = self.short()

        memories = [
            {
                "id":      r.payload["memory_id"],
                "summary": r.payload.get("summary", ""),
                "score":   r.payload.get("score"),
            }
            for r in self._recalls
        ]

        tools = [
            {"name": t.payload["tool"], "result": t.payload["result"]}
            for t in self._tools
        ]

        active_labels = {h.payload["label"] for h in self._hypotheses}
        kept_labels   = active_labels - self._discarded_labels

        hypotheses = [
            {
                "label":          h.payload["label"],
                "description":    h.payload.get("description", ""),
                "status":         "kept" if h.payload["label"] in kept_labels else "discarded",
                "discard_reason": next(
                    (d.payload["reason"]
                     for d in self._discards
                     if d.payload["label"] == h.payload["label"]),
                    None,
                ),
            }
            for h in self._hypotheses
        ]

        evidence = [
            {
                "text":     e.payload["text"],
                "supports": e.payload.get("supports"),
                "refutes":  e.payload.get("refutes"),
            }
            for e in self._evidence
        ]

        # 4. Devil's advocate synthesis
        da = _devils_advocate(self.trace.steps, self.trace.decision or "")

        return {
            **short,
            "memories":          memories,
            "tools":             tools,
            "hypotheses":        hypotheses,
            "evidence":          evidence,
            "started_at":        self.trace.started_at,
            "closed_at":         self.trace.closed_at,
            "entry_hash":        self.trace.entry_hash,
            "devils_advocate":   da,
        }

    # ── Devil's advocate ──────────────────────────────────────────────────────

    def devils_advocate(self) -> str:
        """
        Synthesize the strongest alternative explanation (from VIGÍA devil_advocate_gen).
        Returns a prose string suitable for display alongside the main decision.
        """
        return _devils_advocate(self.trace.steps, self.trace.decision or "")

    # ── Natural language prose ─────────────────────────────────────────────────

    def natural(self) -> str:
        """
        Produces a single flowing prose paragraph explaining the decision.

        Example:
          "Because I retrieved 2 memories (M-22, M-81); Jira returned ticket #842
          Open / Auth / High; evidence supported auth_bug: Jira confirms Auth
          category; I discarded cache_bug because no cache errors in log —
          I decided to apply auth token reset (high confidence, 74%)."
        """
        parts: list[str] = []

        if self._recalls:
            ids  = [s.payload["memory_id"] for s in self._recalls]
            n    = len(ids)
            parts.append(
                f"I retrieved {n} {_plural(n, 'memory', 'memories')} "
                f"({', '.join(ids)})"
            )

        for t in self._tools:
            parts.append(f"{t.payload['tool']} returned: {t.payload['result']}")

        for e in self._evidence:
            if "supports" in e.payload:
                parts.append(
                    f"evidence supported {e.payload['supports']}: {e.payload['text']}"
                )
            elif "refutes" in e.payload:
                parts.append(
                    f"evidence against {e.payload['refutes']}: {e.payload['text']}"
                )

        for d in self._discards:
            parts.append(
                f"I discarded {d.payload['label']} because {d.payload['reason']}"
            )

        decision = self.trace.decision or "(no decision)"
        conf_pct   = _confidence_pct(self.trace.confidence)
        conf_label = _confidence_label(self.trace.confidence)

        if not parts:
            return f"Decision: {decision}. Confidence: {conf_pct}."

        body = "; ".join(parts)
        prose = (
            f"Because {body} — "
            f"I decided to {decision} "
            f"({conf_label}, {conf_pct})."
        )
        # Hard cap to stay within Slack's 3000-char per-block limit with headroom.
        _MAX = 2800
        if len(prose) > _MAX:
            prose = prose[: _MAX - 1] + "…"
        return prose
