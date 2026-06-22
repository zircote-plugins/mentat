---
name: artifact-diagnosis
description: "Diagnose and repair a flaky Claude Code artifact itself — a slash command, skill, sub-agent, or plugin whose structure causes misbehaviour. Use when session-forensics traces a fault to an artifact, or when asked 'why won't my skill trigger', 'my agent ignores its frontmatter', 'this command's tools are blocked', 'validate my plugin', 'fix my SKILL.md'. Checks frontmatter validity, triggering/description quality, allowed-tools, manifest fields, and runs claude plugin validate. Proposes reviewable fixes by default."
argument-hint: "<path-to-artifact-or-plugin-dir> [analyze|recommend|propose|apply]"
allowed-tools: "Read, Edit, Write, Bash, Grep, Glob"
license: MIT
---

# Artifact diagnosis

Find and fix the structural defect in a Claude Code artifact. Use after
`session-forensics` points at an artifact, or directly when an artifact is flaky.
Reference: `${CLAUDE_PLUGIN_ROOT}/skills/artifact-diagnosis/references/artifact-anatomy.md`
and the bundled docs in `${CLAUDE_PLUGIN_ROOT}/references/claude-code-docs/`.

## Procedure

1. **Identify the artifact type** — command, skill, agent, or plugin — and
   read it.
2. **Check frontmatter validity.** The most common silent failure: an agent or
   skill whose `description` contains raw colons or `<example>` blocks, breaking
   YAML so all metadata is dropped at runtime. Keep descriptions quoted scalars.
3. **Check triggering quality.** A `description` too vague never activates; too
   broad activates everywhere. Tighten to the real intent.
4. **Check capabilities.** Missing/incorrect `allowed-tools`/`tools` silently
   blocks tool calls. Manifests need `name` (+ `version` recommended).
5. **Validate.**

   ```bash
   claude plugin validate <plugin-dir>
   claude plugin validate <plugin-dir> --strict   # CI-grade
   ```

6. **Fix under contract.** Default `propose` — show the diff. Only `apply`
   (write) with explicit authority; confirm files first; never force-push/delete.

## Output

Per defect: ROOT CAUSE → FORENSIC EVIDENCE (the offending lines) → RECOVERY STEP
(the precise frontmatter/manifest edit), then re-validate to prove it is fixed.
