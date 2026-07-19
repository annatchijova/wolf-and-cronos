# Using CRONOS with Claude

CRONOS is a plain MCP server — any MCP-capable agent can drive it. The live
runs on the [CRONOS page](https://wolf-and-cronos.vercel.app/cronos.html) were
driven by **Qwen Plus** via [opencode](https://opencode.ai) (setup shown there).
This document is the equivalent setup for **Claude Code** and **Claude Desktop**,
so a Claude agent records its reasoning into the exact same tamper-evident chain.

Nothing about CRONOS is model-specific: a trace sealed by Claude and a trace
sealed by Qwen are indistinguishable in the store — same ten tools, same quality
tiers, same diversity-capped confidence.

## Prerequisites

```bash
pip install "mcp>=1.0.0"
# CRONOS ships inside this repo at cronos/mcp_server.py
```

## Claude Code (CLI)

```bash
claude mcp add cronos \
  --env CRONOS_DB_PATH=/path/to/cronos.db \
  -- python3 /path/to/wolf-and-cronos/cronos/mcp_server.py
```

Verify it connected:

```bash
claude mcp list        # cronos should show as connected
```

## Claude Desktop

Add the server to `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "cronos": {
      "command": "python3",
      "args": ["/path/to/wolf-and-cronos/cronos/mcp_server.py"],
      "env": { "CRONOS_DB_PATH": "/path/to/cronos.db" }
    }
  }
}
```

Restart Claude Desktop; the `cronos_*` tools appear in the tool list.

## The ten tools

`cronos_open_trace`, `cronos_add_hypothesis`, `cronos_add_evidence`,
`cronos_discard_hypothesis`, `cronos_record_tool_call`, `cronos_record_recall`,
`cronos_close_trace`, `cronos_explain_trace`, `cronos_list_traces`,
`cronos_verify_chain`.

## Prompt pattern

Tell the agent to record as it reasons:

> Analyze this, and record your entire reasoning in CRONOS with the `cronos_*`
> tools: open a trace, register **every** hypothesis you consider, attach each
> fact to the hypothesis it supports or refutes, discard the ones that don't
> survive with a reason, then close the trace with your decision and an integer
> confidence, and verify the chain.

## Render a sealed trace to a report

Turn any sealed trace (from Claude or Qwen) into a Markdown + HTML report:

```bash
python3 demo/render_cronos_report.py \
  --db cronos.db \
  --md  results/report.md \
  --html results/report.html
```

See [`REAL-Cronos-Qwen/`](../REAL-Cronos-Qwen) for three example runs driven by Qwen.
