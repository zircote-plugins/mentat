# mentat

> Forensic diagnosis and repair contract for flaky Claude Code artifacts.

mentat takes a misbehaving Claude Code session — a `/command`, skill, sub-agent,
or plugin that loops, errors, freezes, or burns tokens — comprehends what it was
trying to do, diagnoses the erroneous behaviour from the session's JSONL
transcript, and proposes (or, under contract, applies) fixes. It stays aligned
to the **installed** Claude Code version by syncing version-matched docs.

## Why it is grounded, not plausible

The illustrative seed referenced transcript fields (`chain_id`, a single `error`
block) that **do not exist** in real Claude Code transcripts. mentat is built on
the verified schema (profiled from real 10k-line sessions): threading is
`uuid`/`parentUuid`, subagents are flagged `isSidechain`, and errors surface
three ways — `tool_result.is_error`, `toolUseResult.code`, `isApiErrorMessage`.
See `skills/session-forensics/references/seed-mapping.md`.

## Components

| Type | Name | Purpose |
| --- | --- | --- |
| Command | `/mentat-diagnose` | diagnose a session/artifact across dimensions, report, propose fixes |
| Command | `/mentat-watch` | live monitor + agent-to-agent feedback (reliability + security) |
| Command | `/mentat-corpus` | cross-session corpus: `scan` \| `trends` \| `suggest` |
| Command | `/mentat-refresh-docs` | re-sync version-matched docs |
| Agent | `log-forensics` | forensic diagnosis of a session/artifact |
| Agent | `transcript-monitor` | mid-run monitoring, feedback to a supervising agent |
| Agent | `artifact-repair` | negotiated repair via a two-round contract with the top-level session |
| Skill | `session-forensics` | parse + triage + remediation playbook |
| Skill | `artifact-diagnosis` | fix flaky command/skill/agent/plugin structure |

## Analysis dimensions

Every analyzer emits the same normalized `Finding` record, so findings render,
gate, and dedup uniformly. Select with `--dimension reliability|security|efficiency|all`:

| Dimension | Catches | Matrix |
| --- | --- | --- |
| `reliability` | loops, tool/runtime + API failures, sequence anti-patterns, context pressure, corrupt transcripts | `references/triage-matrix.md` |
| `security` | secrets in tool I/O (redacted), dangerous commands, prompt injection in tool output, exfiltration | `references/security-matrix.md` |
| `efficiency` | real token spend, expensive uncached turns, redundant re-reads, repeated successful commands, oversized results | `references/efficiency-matrix.md` |

Findings carry a stable `fingerprint` (`hash(dimension + category + normalized_evidence)`)
that **deduplicates across sessions** — the basis for the cross-session corpus.
**Raw secrets are never emitted**: redaction (`<redacted:KIND:hash8>`) happens at
the Finding boundary and is enforced by tests.

## Scripts (stdlib only — no new dependencies)

- `skills/session-forensics/scripts/findings.py` — normalized Finding schema,
  fingerprint, and mandatory secret redaction.
- `skills/session-forensics/scripts/parse_transcript.py` — locate, parse, triage,
  report (`--json`, `--dimension`). Analyzer registry; reliability built in.
- `skills/session-forensics/scripts/security_scan.py` — security dimension
  (CI-gatable: non-zero exit on high-severity).
- `skills/session-forensics/scripts/efficiency_scan.py` — efficiency/cost
  dimension (`--price-table` for an optional USD estimate).
- `skills/session-forensics/scripts/watch_transcript.py` — tail + emit one JSONL
  feedback record per new issue (`--once`, `--dimension`).
- `skills/session-forensics/scripts/corpus.py` — `scan` recent transcripts
  into a local redacted JSONL store; `trends` recurring findings.
- `skills/session-forensics/scripts/suggest.py` — propose durable fixes
  (CLAUDE.md / settings.json / BENIGN_PATTERNS) from the corpus; writes nothing.
- `scripts/refresh_docs.sh` — version-matched doc sync.

## Usage

```bash
/mentat-diagnose <session-id|transcript.jsonl> [analyze|recommend|propose|apply] [--dimension all]
/mentat-watch    <session-id|transcript.jsonl> [--once] [--dimension reliability,security]
/mentat-corpus   scan | trends | suggest
/mentat-refresh-docs
```

## Fix contract (agent-to-agent)

mentat establishes a contract with the requester and escalates only as authorized:
`analyze` → `recommend` → `propose` (default, reviewable patch) → `apply`.
**Default is non-destructive.** It never applies edits, force-pushes, or deletes
files without explicit authority. See
`skills/session-forensics/references/remediation-playbook.md`.

For a *negotiated* repair, the `artifact-repair` agent runs a **two-round
handshake** with the top-level session — because a subagent returns one message
and can't hold a live dialogue mid-run:

```text
Round 1  proposal       : diffs + requested authority + risk   (writes nothing)
Round 2  authorization  : top-level approves patches/decisions
         → result        : applies only what was approved, re-validates
```

Default applier is the **top-level session** (mentat emits diffs; the trusted
session writes), unless a patch is explicitly granted `mentat-apply`. Protocol:
`references/fix-contract-protocol.md`; machine-parseable shape:
`references/contract-schema.json`.

## Triage matrix

Loops (scoped to idempotent tools), tool/runtime failures, API errors, tool-
sequence anti-patterns, context-window pressure, corrupt transcript — each with
its false-positive guard. See
`skills/session-forensics/references/triage-matrix.md`.

## Staying current

`/mentat-refresh-docs` pins `claude --version`, fetches the version-keyed
changelog, and records doc reachability. Docs are served at HEAD (no per-version
URLs); the sync record states the gap. See `references/REFRESH.md`.
