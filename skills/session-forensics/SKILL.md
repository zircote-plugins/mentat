---
name: session-forensics
description: "Forensic diagnosis of Claude Code sessions from their JSONL transcripts. Use when Claude Code errored out, froze, looped, burned tokens, or a /command, skill, agent, or plugin misbehaved. Takes a session-id or transcript path, parses the real transcript schema, triages failures (loops, tool/runtime errors, sequence anti-patterns, context pressure, API errors), and produces a root-cause report plus a non-destructive fix contract. Triggers on 'diagnose this session', 'why did Claude loop', 'analyze the transcript', 'session froze', 'high CPU', 'figure out what went wrong in session <id>'."
argument-hint: "<session-id | path/to/transcript.jsonl> [analyze|recommend|propose|apply]"
allowed-tools: "Read, Bash, Grep, Glob"
license: MIT
---

# Session forensics

Diagnose a Claude Code session from its JSONL transcript and establish a fix
contract with the requester. Grounded in the **verified** transcript schema
(`references/jsonl-schema.md`), not guesses — see `references/seed-mapping.md`.

## Step 0 — environment health first

Before deep analysis, confirm the environment is healthy. Advise the user (or ask
the requesting agent) to run `/doctor`, `/context`, and `claude --version`. Many
"flaky" reports are config/MCP/context faults. See `references/builtin-diagnostics.md`.

## Step 1 — locate & parse the transcript

Run the parser. It accepts a session-id (located under the transcript root —
`$CLAUDE_CONFIG_DIR/projects/`, falling back to `$CLAUDE_HOME` then `~/.claude`)
or an explicit path:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/parse_transcript.py --session <id>
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/parse_transcript.py --path <file.jsonl>
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/parse_transcript.py --path <f> --json   # machine-readable
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/parse_transcript.py --path <f> --dimension all   # + security + efficiency
```

Stdlib-only (no new dependencies). Threading is `uuid`/`parentUuid`; subagent
lines are `isSidechain`; errors surface as `tool_result.is_error`,
`toolUseResult.code`, and `isApiErrorMessage`.

## Step 2 — triage (multi-dimensional)

The parser runs an **analyzer registry** keyed by dimension and maps signals onto
the matrices:

- **reliability** (default) — `references/triage-matrix.md`: loops (scoped to
  idempotent tools), tool/runtime failures, API errors, sequence anti-patterns,
  context pressure, corrupt transcript.
- **security** — `references/security-matrix.md`: secrets in tool I/O (redacted),
  dangerous commands, prompt injection in tool output, exfiltration. Exits
  non-zero on a high-severity hit (CI-gatable).
- **efficiency** — `references/efficiency-matrix.md`: real token spend
  (`message.usage`), expensive uncached turns, redundant re-reads, repeated
  successful commands, oversized results, token-based context pressure.

Select with `--dimension reliability|security|efficiency|all`. Every finding
carries a stable `fingerprint` for cross-session dedup (see the `corpus.py`
store and `references/corpus-schema.md`). **Raw secrets are always redacted.**
Read the printed report; high-severity findings set exit code 1.

## Step 3 — remediation report

Produce, per finding: **ROOT CAUSE → FORENSIC EVIDENCE (the JSONL snippet/counts)
→ RECOVERY STEP**. See `references/remediation-playbook.md`.

## Step 4 — fix contract

State the level you are operating at and proceed:
`analyze` → `recommend` → `propose` (default, reviewable patch) → `apply`.
**Default is non-destructive.** Never `apply` without explicit authority; before
writing, confirm the exact files and gate on confirmation. Never force-push or
delete files. If the root cause is the artifact's structure, hand off to the
`artifact-diagnosis` skill.

## Live monitoring

For mid-run, agent-to-agent feedback use `scripts/watch_transcript.py` (see the
`transcript-monitor` agent), which emits one JSONL feedback record per new issue
with a `fix_authority` of `propose` by default.
