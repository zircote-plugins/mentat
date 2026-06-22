---
name: mentat-diagnose
description: "Diagnose a flaky or failed Claude Code session/artifact from its transcript and propose fixes under a non-destructive contract"
argument-hint: "<session-id | path/to/transcript.jsonl> [analyze|recommend|propose|apply] [--dimension reliability|security|efficiency|all]"
allowed-tools: ["Read", "Bash", "Grep", "Glob", "Skill", "AskUserQuestion"]
---

# /mentat-diagnose

Diagnose what went wrong in a Claude Code session and, if the fault is an
artifact, find the structural defect. Then establish a fix contract.

Argument: `$1` is a **session-id** or a **transcript path**. Optional `$2` is the
fix level (`analyze` | `recommend` | `propose` | `apply`); default `propose`.

Optional `--dimension` selects which analyzers run:
`reliability` (loops, tool/API failures, anti-patterns), `security` (secrets,
dangerous commands, prompt injection, exfiltration), `efficiency` (token spend,
redundant work, context pressure), or `all`. **Default for this command is
`all`** — pass `--dimension reliability` for the classic reliability-only view.

## Do this

1. **Environment first.** Suggest `/doctor`, `/context`, and `claude --version`
   if the user hasn't run them.
2. **Invoke the `session-forensics` skill.** Run its parser on `$1` across all
   dimensions (pass `--dimension` to narrow):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/parse_transcript.py --session "$1" --dimension all
   # or, if $1 looks like a path:
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/parse_transcript.py --path "$1" --dimension all
   ```

   Security findings exit non-zero on a high-severity hit (CI-gatable). Raw
   secrets are always redacted in the output.

3. **Triage & report.** For each finding print ROOT CAUSE → FORENSIC EVIDENCE →
   RECOVERY STEP, honoring the false-positive caveats in the triage,
   `security-matrix.md`, and `efficiency-matrix.md` references.
4. **If the root cause is an artifact**, invoke the `artifact-diagnosis` skill on
   it and run `claude plugin validate` where applicable.
5. **Fix contract.** Operate at the level in `$2` (default `propose`):
   - `propose` — show a reviewable patch/diff; write nothing.
   - `apply` — only with explicit authority; confirm exact files first; never
     force-push or delete files.

   To carry out a *negotiated* repair, hand off to the `artifact-repair` agent,
   which runs the two-round handshake with this (top-level) session: round 1 it
   returns a proposal of diffs + requested authority (writes nothing); round 2 it
   applies only what you approve. Default applier is the top-level session. See
   `${CLAUDE_PLUGIN_ROOT}/references/fix-contract-protocol.md`.

State which level you used and why. Cite the transcript signal behind every claim.
