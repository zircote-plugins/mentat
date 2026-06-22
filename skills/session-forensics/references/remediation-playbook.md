# Remediation playbook & fix contract

Every mentat diagnosis ends in a report and a **fix contract** with the
requesting agent or user. The report structure (expanded from the seed):

```text
1. ROOT CAUSE SUMMARY   — exactly what failed and why
2. FORENSIC EVIDENCE     — the JSONL snippet / counts proving it
3. RECOVERY STEP         — the concrete command or edit that resolves it
```

## The fix contract (agent-to-agent)

mentat does not assume how far to go. It establishes a contract with the
requester and assists toward their goal. Four escalating levels:

| Level | mentat does | mutates files? |
| --- | --- | --- |
| `analyze` | parse + triage, print findings | no |
| `recommend` | findings + specific recovery steps | no |
| `propose` (default) | findings + a reviewable patch/diff for each fix | no — patch only |
| `apply` | writes the fix | yes — **only with explicit authority** |

Rules:

- **Default is `propose`** — non-destructive. mentat never jumps to `apply`
  without explicit authority from the requester.
- For a *negotiated* repair, the `artifact-repair` agent runs a two-round
  handshake with the top-level session (proposal → authorization → result). The
  protocol and the machine-parseable contract shape live in
  `${CLAUDE_PLUGIN_ROOT}/references/fix-contract-protocol.md` and
  `${CLAUDE_PLUGIN_ROOT}/references/contract-schema.json`. Default applier is
  the top-level session; mentat writes only patches granted `mentat-apply`.
- mentat states the level it is operating at, the target artifact, and the
  source session, then proceeds.
- Before any `apply`, mentat confirms the specific files it will write and gates
  on confirmation. It never force-pushes or deletes files.
- The live monitor (`watch_transcript.py`) emits `fix_authority:"propose"` by
  default in its feedback records, so a supervising agent must opt in to apply.

## Per-category recovery quick reference

- **Loop** — break the pattern: change strategy, not the argument; read the last
  `tool_result` before re-issuing. For artifacts: tighten the command/skill so it
  can't re-enter the same branch.
- **Tool/runtime failure** — fix the path/command; for a rejected edit, Read the
  file first. For artifacts: correct `allowed-tools` or the bash invocation.
- **API error** — back off, retry once; reduce request size; check `/doctor`.
- **Sequence anti-pattern** — enforce Read-before-Edit; verify outputs.
- **Context pressure** — `/context`, then `/compact` or summarize.
- **Corrupt transcript** — recover from the latest `file-history-snapshot`.

## Artifact-level fixes

When the root cause is the artifact itself (a flaky command/skill/agent/plugin),
hand off to the `artifact-diagnosis` skill for the structural fix (frontmatter,
triggering, scope, manifest), then re-run the session or `claude plugin validate`.
