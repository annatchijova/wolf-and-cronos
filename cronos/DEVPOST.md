# CRONOS — Devpost Submission Text

## Tagline (short description field, under 200 characters)

The black box recorder for AI agents. CRONOS records an agent's reasoning while it happens — every memory, hypothesis, and discard — seals it in a SHA-256 chain, and explains it in Slack.

---

## Inspiration

When a plane goes down, investigators don't ask witnesses what they think happened — they open the black box. AI agents are now making real decisions in production: approving deploys, triaging incidents, resolving tickets. When one of those decisions goes wrong, the question is never *what* the agent did — that's visible in the channel. The question is *why*. What did it consider? What did it discard? How certain was it, really?

Today that answer doesn't exist. Agent reasoning evaporates the moment the response is posted. Post-hoc explanations are rationalizations, not records. CRONOS was born from a simple conviction: if agents are going to act, they should be recorded like flight systems — while flying, not after the crash.

The project builds on ideas from VIGÍA, our open-source forensic intentionality analysis engine: observational diversity, contradiction detection, and epistemic constraints on confidence, adapted from analyzing human intent to recording machine reasoning.

## What it does

CRONOS is a black box recorder for AI agents, living natively in Slack.

While an agent works, CRONOS records every step of its decision cycle in real time: what it recalled, which tools it called, every hypothesis it considered, the evidence for and against each one, what it discarded and why, and the final decision with a confidence score. The trace is sealed the moment the cycle ends.

Then CRONOS does something unusual: it doesn't just record confidence — it constrains it. If an agent claims 95% certainty but only reasoned from a single type of observation, CRONOS caps the stored confidence at 60% and records exactly why. An agent cannot claim a certainty its evidence base doesn't support. It also detects contradictions (evidence both supporting and refuting the same hypothesis, or a supported hypothesis discarded without justification) and classifies every trace by quality: FULL, PARTIAL, MINIMAL, or EMPTY.

Every sealed trace is appended to a tamper-evident SHA-256 hash chain. If anyone retroactively edits a recorded decision — even directly in the database, bypassing the API — the next audit identifies the exact entry that was manipulated.

In Slack, humans get the whole story through Block Kit: trace cards posted in-thread when a decision is made, and slash commands (`/cronos explain`, `/cronos trace`, `/cronos audit`, `/cronos status`) to inspect any trace in plain language, list activity by agent, and verify the integrity of the entire chain.

## How we built it

CRONOS uses two of the hackathon's required technologies:

**MCP server integration.** CRONOS exposes its recorder as a custom MCP server (`mcp_server.py`, built on FastMCP over stdio). Any MCP-capable agent — Claude Code, Claude Desktop, custom agents — can record its own black box through nine tools: `cronos_open_trace`, `cronos_record_recall`, `cronos_record_tool_call`, `cronos_add_hypothesis`, `cronos_add_evidence`, `cronos_discard_hypothesis`, `cronos_close_trace`, `cronos_explain_trace`, and `cronos_verify_chain`. When an external agent closes a trace, the quality metrics and confidence ceiling are applied, the trace is sealed into the hash chain, and the trace card is posted to the originating Slack channel automatically. This turns CRONOS from a bot feature into observability infrastructure for the whole agent ecosystem.

**Real-Time Search API.** The RECALL step of the agent is real, not mocked. When the demo agent investigates a ticket, it searches the workspace's own conversational history through `assistant.search.context`, phrasing queries as natural-language questions to leverage semantic retrieval where available. Past incidents discussed in channels become the agent's episodic memory, permission-scoped to what the triggering user can see, with permalinks recorded in the trace. If the RTS call fails for any reason, the agent falls back to a local memory store — and the trace records `source=local_fallback` with the exact reason. A black box that hides how it obtained its memories is not a black box: the trace documents its own degradation.

The rest of the stack: Python with Bolt for Slack (async, Socket Mode), SQLite in WAL mode shared between the bot and the MCP server, and a design constraint we're proud of — zero floats in the entire scoring path. Every confidence value, relevance score, and quality metric is an exact `fractions.Fraction`, so audits are reproducible bit-for-bit and no rounding artifact can ever change a recorded verdict.

## Challenges we ran into

The hardest problem was epistemic, not technical: how do you keep an agent honest about its own certainty? Our answer was the diversity-based confidence ceiling — confidence is capped by how many independent kinds of observation (recall, tools, reasoning) actually informed the decision. Getting the thresholds to feel right took several iterations.

On the technical side, the Real-Time Search API is brand new (February 2026), and integrating it meant working through fresh documentation: bot-token calls require an `action_token` from a user interaction, the app must have AI capabilities enabled, and result payloads needed defensive parsing. We designed the recall module to degrade gracefully and record its provenance precisely because new APIs deserve honest error handling.

Finally, making tampering *visible* required care: the hash chain uses canonical JSON serialization (sorted keys, no whitespace) so an independent verifier can recompute every hash byte-for-byte, in any language, without our code.

## Accomplishments that we're proud of

The tamper demo. We edit a recorded decision directly in SQLite, bypassing the entire API — and `/cronos audit` identifies the exact forged entry, showing the stored hash against the recomputed one. That single moment communicates the whole thesis of the project.

We're also proud that the confidence ceiling works against any agent, including ones we didn't write: when Claude Code records a trace through MCP and claims more certainty than its steps support, CRONOS stores the constrained value and the warning. And we're proud of the honesty of the design — the Jira and GitHub tools in the demo agent are deterministic mocks (clearly labeled), while the memory layer is real workspace data via RTS. The trace always tells you which is which.

## What we learned

That accountability is a systems property, not a logging feature. Recording steps is easy; making the record trustworthy required exact arithmetic, atomic writes, canonical hashing, and constraints that push back against the agent itself. We also learned that Slack's new agent platform genuinely changes what's possible: MCP gives every agent a common doorway into the recorder, and RTS turns the workspace itself into agent memory without copying data anywhere.

## What's next for CRONOS

Assistant threads for conversational trace exploration ("why did the agent discard the cache hypothesis?"), an App Home dashboard with per-agent reliability metrics over time, chain anchoring to an external timestamping service for stronger non-repudiation, and SDK packages so any Python or TypeScript agent can instrument itself in three lines. Longer term: cross-agent forensics — correlating traces from multiple agents involved in the same incident, in the spirit of VIGÍA's cross-artifact analysis.

## How to test it

Join the sandbox workspace (invites sent to slackhack@salesforce.com and testing@devpost.com). Run `/cronos help` to see the commands. Mention the bot with `@cronos fix ticket #842 login timeout auth` in #incidents to watch a live trace with RTS-sourced recall, then `/cronos explain` to read the reasoning and `/cronos audit` to verify the chain. Full test matrix and the tamper demonstration script are in DEMO.md in the repository.
