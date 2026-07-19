#!/usr/bin/env python3
"""
demo/render_cronos_report.py
============================
Render a sealed CRONOS trace into a Markdown audit trail (the canonical
CLAUDE.md format) and a visual HTML report in the Qwen palette.

Reads directly from the CRONOS store — the report is a faithful, read-only
view of what the agent actually sealed. Works for any agent's trace
(Claude, Codex, or Qwen via opencode); nothing model-specific.

Usage
-----
    # latest sealed trace in the db
    python3 demo/render_cronos_report.py \
        --db cronos_opencode.db \
        --md  results/vigia-opencode-001.md \
        --html results/vigia-opencode-001.html

    # a specific trace
    python3 demo/render_cronos_report.py --db cronos_opencode.db --trace-id <uuid> ...
"""

from __future__ import annotations

import argparse
import html
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_ROOT, "cronos"))

from cronos.store import TraceStore


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def _frac(f) -> str:
    if f is None:
        return "—"
    return f"{f.numerator}/{f.denominator}"


def load(db_path: str, trace_id: str | None):
    store = TraceStore(db_path)
    trace = store.load_trace(trace_id) if trace_id else store.get_latest_trace()
    if trace is None:
        raise SystemExit(f"No sealed trace found in {db_path!r}"
                         + (f" for id {trace_id!r}" if trace_id else ""))
    return trace


def hypotheses_summary(steps) -> list[dict]:
    """Derive the hypotheses table: label, status (active/discarded), outcome."""
    order: list[str] = []
    described: dict[str, str] = {}
    discarded: dict[str, str] = {}
    for s in steps:
        kind = s.kind.value
        p = s.payload
        if kind == "hypothesis":
            label = p.get("label", "")
            if label not in described:
                order.append(label)
            described[label] = p.get("description", "")
        elif kind == "discard":
            discarded[p.get("label", "")] = p.get("reason", "")
    rows = []
    for label in order:
        rows.append({
            "label": label,
            "status": "Discarded" if label in discarded else "Active",
            "outcome": discarded.get(label, described.get(label, "")),
        })
    return rows


# ---------------------------------------------------------------------------
# Markdown (canonical CRONOS audit-trail format)
# ---------------------------------------------------------------------------

def _step_md(i: int, s) -> str:
    kind = s.kind.value
    p = s.payload
    ts = s.timestamp
    if kind == "objective":
        return f"### {i}. Objective ({ts})\n\n{p.get('objective','')}"
    if kind == "hypothesis":
        return f"### {i}. Hypothesis registered: `{p.get('label','')}` ({ts})\n\n{p.get('description','')}"
    if kind == "evidence":
        link = ""
        if p.get("supports"): link = f" — supports `{p['supports']}`"
        if p.get("refutes"):  link = f" — refutes `{p['refutes']}`"
        neg = "  *(negation detected)*" if p.get("negation_detected") else ""
        return f"### {i}. Evidence{link} ({ts})\n\n{p.get('text','')}{neg}"
    if kind == "discard":
        return f"### {i}. Discard: `{p.get('label','')}` ({ts})\n\n**Reason:** {p.get('reason','')}"
    if kind == "tool":
        return f"### {i}. Tool — {p.get('tool','')} ({ts})\n\n{p.get('result','')}"
    if kind == "recall":
        sc = f" (score {p['score']})" if p.get("score") else ""
        return f"### {i}. Recall — {p.get('memory_id','')}{sc} ({ts})\n\n{p.get('summary','')}"
    if kind == "decision":
        return f"### {i}. Decision sealed ({ts})\n\n{p.get('decision','')}"
    return f"### {i}. {kind} ({ts})\n\n{p}"


def to_markdown(trace) -> str:
    L = []
    obj = trace.objective or ""
    topic = (obj[:60] + "…") if len(obj) > 60 else obj
    L.append(f"# Cronos Audit Trail — {topic}")
    L.append(f"<!-- trace_id: {trace.trace_id} -->\n")
    L.append("| Field | Value |")
    L.append("|-------|-------|")
    L.append(f"| Trace ID | `{trace.trace_id}` |")
    L.append(f"| Agent | `{trace.agent_id}` |")
    L.append(f"| Started | {trace.started_at} |")
    L.append(f"| Closed | {trace.closed_at} |")
    L.append(f"| Quality | {trace.quality.value if trace.quality else 'EMPTY'} |")
    L.append(f"| Confidence | {_frac(trace.confidence)} |")
    L.append(f"| Diversity | {_frac(trace.diversity)} |")
    L.append(f"| Chain hash | `{trace.entry_hash}` |")
    L.append(f"| Chain integrity | {'OK' if trace.chain_ok else 'BROKEN'} |")
    L.append(f"| Cronos version | {trace.cronos_version} |\n")
    L.append("---\n\n## Objective\n")
    L.append(obj + "\n")
    L.append("---\n\n## Step-by-step trace\n")
    for i, s in enumerate(trace.steps, 1):
        L.append(_step_md(i, s) + "\n")
    L.append("---\n\n## Hypotheses summary\n")
    L.append("| Label | Status | Outcome |")
    L.append("|-------|--------|---------|")
    for r in hypotheses_summary(trace.steps):
        L.append(f"| `{r['label']}` | {r['status']} | {r['outcome']} |")
    L.append("\n---\n\n## Decision\n")
    L.append(f"**{trace.decision or '—'}**\n")
    if trace.confidence_warnings:
        L.append("\n**Confidence warnings:**")
        for w in trace.confidence_warnings:
            L.append(f"- {w}")
    if trace.contradictions:
        L.append("\n**Contradictions flagged by Cronos:**")
        for c in trace.contradictions:
            L.append(f"- {c}")
    L.append("\n---\n\n## Chain of custody\n")
    L.append("```")
    L.append(f"entry_hash : {trace.entry_hash}")
    L.append(f"chain_ok   : {str(trace.chain_ok).lower()}")
    L.append("```")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# HTML (Qwen palette)
# ---------------------------------------------------------------------------

_KIND_META = {
    "objective":  ("OBJECTIVE",  "obj"),
    "hypothesis": ("HYPOTHESIS", "hyp"),
    "evidence":   ("EVIDENCE",   "ev"),
    "discard":    ("DISCARD",    "disc"),
    "tool":       ("TOOL",       "tool"),
    "recall":     ("RECALL",     "rec"),
    "decision":   ("DECISION",   "dec"),
}


def _e(x) -> str:
    return html.escape(str(x))


def _step_html(i: int, s) -> str:
    kind = s.kind.value
    label, cls = _KIND_META.get(kind, (kind.upper(), ""))
    p = s.payload
    if kind == "objective":
        title, body = "Objective", p.get("objective", "")
    elif kind == "hypothesis":
        title, body = f"Hypothesis · <code>{_e(p.get('label',''))}</code>", p.get("description", "")
    elif kind == "evidence":
        tag = ""
        if p.get("supports"): tag = f" <span class='lk sup'>supports {_e(p['supports'])}</span>"
        if p.get("refutes"):  tag = f" <span class='lk ref'>refutes {_e(p['refutes'])}</span>"
        if p.get("negation_detected"): tag += " <span class='lk neg'>negation</span>"
        title, body = f"Evidence{tag}", p.get("text", "")
    elif kind == "discard":
        title, body = f"Discard · <code>{_e(p.get('label',''))}</code>", p.get("reason", "")
    elif kind == "tool":
        title, body = f"Tool · <code>{_e(p.get('tool',''))}</code>", p.get("result", "")
    elif kind == "recall":
        sc = f" · score {_e(p['score'])}" if p.get("score") else ""
        title, body = f"Recall · <code>{_e(p.get('memory_id',''))}</code>{sc}", p.get("summary", "")
    elif kind == "decision":
        title, body = "Decision", p.get("decision", "")
    else:
        title, body = kind, str(p)
    return (
        f'<div class="tl {cls}">'
        f'<div class="tlhead"><span class="badge {cls}">{label}</span>'
        f'<span class="tlt">{title}</span><span class="when">{_e(s.timestamp)}</span></div>'
        f'<p>{_e(body)}</p></div>'
    )


def to_html(trace) -> str:
    obj = trace.objective or ""
    topic = _e((obj[:80] + "…") if len(obj) > 80 else obj)
    steps_html = "\n".join(_step_html(i, s) for i, s in enumerate(trace.steps, 1))
    hyps = hypotheses_summary(trace.steps)
    hyp_rows = "\n".join(
        f'<tr><td class="mono">{_e(r["label"])}</td>'
        f'<td><span class="st {"disc" if r["status"]=="Discarded" else "act"}">{_e(r["status"])}</span></td>'
        f'<td>{_e(r["outcome"])}</td></tr>'
        for r in hyps
    ) or '<tr><td colspan="3" style="color:var(--muted)">no hypotheses recorded</td></tr>'

    warnings = ""
    if trace.confidence_warnings:
        items = "".join(f"<li>{_e(w)}</li>" for w in trace.confidence_warnings)
        warnings += f'<div class="note"><b>Confidence warnings</b><ul>{items}</ul></div>'
    if trace.contradictions:
        items = "".join(f"<li>{_e(c)}</li>" for c in trace.contradictions)
        warnings += f'<div class="note warn"><b>Contradictions flagged by CRONOS</b><ul>{items}</ul></div>'

    ok = trace.chain_ok
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CRONOS Audit — {topic}</title>
<style>
  :root {{
    --bg0:#0a0618; --bg1:#140b30; --panel:rgba(32,22,66,.58);
    --line:rgba(167,139,250,.22); --line-strong:rgba(167,139,250,.45);
    --ink:#f3f0ff; --muted:#8f8ab8; --lavender:#c4b5fd;
    --indigo:#615ced; --violet:#a855f7; --fuchsia:#d946ef;
    --grad:linear-gradient(135deg,#615ced 0%,#a855f7 55%,#d946ef 100%);
    --ok:#4ade80; --watch:#fbbf24; --critical:#f43f5e; --blue:#7fb4ff;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;min-height:100vh;color:var(--ink);
    font:clamp(15px,.55vw+11px,18px)/1.6 "Segoe UI",system-ui,sans-serif;
    background:radial-gradient(ellipse 60rem 34rem at 12% -6%,rgba(97,92,237,.28),transparent),
      radial-gradient(ellipse 50rem 30rem at 100% 8%,rgba(217,70,239,.16),transparent),
      linear-gradient(180deg,var(--bg1),var(--bg0) 42%);background-attachment:fixed}}
  main{{width:min(94vw,1000px);margin:0 auto;padding:34px 22px 70px}}
  .mark{{width:52px;height:52px;border-radius:15px;background:var(--grad);
    display:grid;place-items:center;font-weight:800;color:#fff;font-size:20px}}
  header{{display:flex;gap:14px;align-items:center;margin-bottom:8px}}
  h1{{font-size:clamp(20px,1.4vw+10px,30px);margin:0;letter-spacing:.02em}}
  h1 .g{{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}}
  .sub{{color:var(--muted);font-size:14px;margin:2px 0 24px}}
  .panel{{position:relative;background:var(--panel);border:1px solid var(--line);
    border-radius:18px;padding:24px 26px;margin-bottom:22px;backdrop-filter:blur(14px);
    box-shadow:0 18px 50px rgba(6,2,24,.5)}}
  .panel::before{{content:"";position:absolute;top:0;left:18px;right:18px;height:1px;
    background:linear-gradient(90deg,transparent,rgba(168,85,247,.7),transparent)}}
  h2{{margin:0 0 14px;font-size:12px;letter-spacing:.2em;text-transform:uppercase;
    color:var(--muted);font-weight:700}}
  .meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
  .m{{border:1px solid var(--line);border-radius:12px;padding:10px 13px;background:rgba(10,6,26,.5)}}
  .m b{{display:block;font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:3px}}
  .m span{{font-size:14px;word-break:break-all}}
  .m .mono,.mono{{font-family:ui-monospace,Consolas,monospace;color:var(--lavender)}}
  .m.hl{{border-color:transparent;background:linear-gradient(rgba(20,11,48,.92),rgba(20,11,48,.92)) padding-box,var(--grad) border-box}}
  .lead{{font-size:16px;line-height:1.7;margin:0}}
  .timeline{{border-left:2px solid rgba(168,85,247,.35);margin-left:8px;padding-left:20px;
    display:flex;flex-direction:column;gap:14px}}
  .tl{{position:relative}}
  .tl::before{{content:"";position:absolute;left:-26.5px;top:5px;width:12px;height:12px;
    border-radius:50%;background:var(--bg1);border:2px solid var(--violet)}}
  .tl.hyp::before{{border-color:var(--watch)}}
  .tl.disc::before{{border-color:var(--critical)}}
  .tl.ev::before{{border-color:var(--blue)}}
  .tl.dec::before{{background:var(--grad);border-color:transparent}}
  .tlhead{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:3px}}
  .badge{{font-size:9.5px;letter-spacing:.12em;padding:3px 9px;border-radius:999px;
    border:1px solid var(--line);color:var(--muted);font-weight:700}}
  .badge.hyp{{color:var(--watch);border-color:rgba(251,191,36,.4)}}
  .badge.disc{{color:var(--critical);border-color:rgba(244,63,94,.4)}}
  .badge.ev{{color:var(--blue);border-color:rgba(127,180,255,.4)}}
  .badge.dec{{background:var(--grad);color:#fff;border-color:transparent}}
  .badge.tool,.badge.rec{{color:var(--lavender)}}
  .tlt{{font-weight:600;font-size:14.5px}} .tlt code{{color:var(--lavender)}}
  .when{{color:#5e5a86;font-size:11px;font-family:ui-monospace,Consolas,monospace;margin-left:auto}}
  .tl p{{margin:2px 0 0;color:var(--ink);font-size:14.5px;line-height:1.55}}
  .lk{{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--line)}}
  .lk.sup{{color:var(--ok);border-color:rgba(74,222,128,.4)}}
  .lk.ref{{color:var(--critical);border-color:rgba(244,63,94,.4)}}
  .lk.neg{{color:var(--muted)}}
  table{{width:100%;border-collapse:collapse;font-size:14px}}
  th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(167,139,250,.12)}}
  th{{color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase}}
  td.mono{{color:var(--lavender)}}
  .st{{font-size:10px;letter-spacing:.1em;padding:3px 10px;border-radius:999px;border:1px solid var(--line)}}
  .st.act{{color:var(--watch);border-color:rgba(251,191,36,.4)}}
  .st.disc{{color:var(--critical);border-color:rgba(244,63,94,.4)}}
  .decision{{border:1px solid transparent;border-radius:13px;padding:16px 18px;font-size:16px;line-height:1.6;
    background:linear-gradient(rgba(20,11,48,.92),rgba(20,11,48,.92)) padding-box,var(--grad) border-box}}
  .note{{margin-top:14px;padding:12px 15px;border-radius:12px;border:1px solid var(--line);
    background:rgba(10,6,26,.45);color:var(--muted);font-size:13.5px}}
  .note.warn{{border-color:rgba(244,63,94,.35)}}
  .note b{{color:var(--lavender)}} .note ul{{margin:6px 0 0;padding-left:18px}}
  .chain{{font-family:ui-monospace,Consolas,monospace;font-size:13px;color:var(--lavender);word-break:break-all}}
  .chain .ok{{color:var(--ok)}} .chain .bad{{color:var(--critical)}}
  footer{{color:var(--muted);font-size:12px;text-align:center;margin-top:26px}}
  footer b{{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}}
</style></head><body><main>
  <header><div class="mark">C</div>
    <div><h1><span class="g">CRONOS</span> Audit Trail</h1></div></header>
  <div class="sub">{topic}</div>

  <div class="panel"><h2>Trace</h2>
    <div class="meta">
      <div class="m"><b>Trace ID</b><span class="mono">{_e(trace.trace_id)[:18]}…</span></div>
      <div class="m"><b>Agent</b><span class="mono">{_e(trace.agent_id)}</span></div>
      <div class="m"><b>Quality</b><span>{_e(trace.quality.value if trace.quality else 'EMPTY')}</span></div>
      <div class="m hl"><b>Confidence</b><span>{_e(_frac(trace.confidence))}</span></div>
      <div class="m"><b>Diversity</b><span>{_e(_frac(trace.diversity))}</span></div>
      <div class="m"><b>Chain</b><span class="mono">{_e(trace.entry_hash)[:18]}… <span style="color:{'var(--ok)' if ok else 'var(--critical)'}">{'intact' if ok else 'BROKEN'}</span></span></div>
    </div>
  </div>

  <div class="panel"><h2>Objective</h2><p class="lead">{_e(obj)}</p></div>

  <div class="panel"><h2>Step-by-step trace</h2><div class="timeline">{steps_html}</div></div>

  <div class="panel"><h2>Hypotheses</h2>
    <table><thead><tr><th>Label</th><th>Status</th><th>Outcome</th></tr></thead>
    <tbody>{hyp_rows}</tbody></table></div>

  <div class="panel"><h2>Decision</h2>
    <div class="decision">{_e(trace.decision or '—')}</div>
    {warnings}
    <div class="chain" style="margin-top:16px">entry_hash : {_e(trace.entry_hash)}<br>
    chain_ok&nbsp;&nbsp; : <span class="{'ok' if ok else 'bad'}">{str(ok).lower()}</span></div>
  </div>

  <footer>Recorded by an MCP agent · rendered read-only from the sealed CRONOS chain · <b>Qwen narrates; it never judges.</b></footer>
</main></body></html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.path.join(_ROOT, "cronos_opencode.db"))
    ap.add_argument("--trace-id", default=None, help="specific trace id (default: latest)")
    ap.add_argument("--md", default=os.path.join(_ROOT, "results", "cronos-report.md"))
    ap.add_argument("--html", default=os.path.join(_ROOT, "results", "cronos-report.html"))
    args = ap.parse_args()

    trace = load(args.db, args.trace_id)

    os.makedirs(os.path.dirname(os.path.abspath(args.md)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.html)), exist_ok=True)
    with open(args.md, "w", encoding="utf-8") as f:
        f.write(to_markdown(trace))
    with open(args.html, "w", encoding="utf-8") as f:
        f.write(to_html(trace))

    print(f"Trace     : {trace.trace_id}  (agent: {trace.agent_id})")
    print(f"Decision  : {(trace.decision or '')[:80]}")
    print(f"Confidence: {_frac(trace.confidence)}  ·  quality {trace.quality.value if trace.quality else 'EMPTY'}"
          f"  ·  chain {'OK' if trace.chain_ok else 'BROKEN'}")
    print(f"Markdown  : {args.md}")
    print(f"HTML      : {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
