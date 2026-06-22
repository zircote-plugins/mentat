# Seed → real-schema mapping

mentat grew from an illustrative `log-diagnose` seed. The seed named JSONL
markers that **do not exist** in real Claude Code transcripts. This file records
how each seed concept was corrected and expanded, so the design is grounded in
the verified schema rather than the seed's guesses.

## Key mapping

| Seed marker (illustrative) | Real schema (verified) | Notes |
| --- | --- | --- |
| `chain_id` (group subagent spawns / turns) | `uuid` + `parentUuid`; `isSidechain: true` | Threading is a parent-pointer tree; subagent lines are flagged `isSidechain`, not grouped by a chain id. |
| `tool_use` (payload to bash/files/MCP) | `message.content[]` block `type:"tool_use"` with `name` + `input`; result in `tool_result` / top-level `toolUseResult` | The seed conflated call and result. Real transcripts split them; the structured result + exit code live in `toolUseResult`. |
| `error` (raw OS/node/npm/API block) | three distinct signals: `tool_result.is_error`, `toolUseResult.code != 0`, `isApiErrorMessage` | One seed field maps to three real, separately-detectable error channels. |

## Framework mapping (seed 4 steps → mentat)

The seed's 4-step framework is **kept and expanded**, not pasted:

1. **Env health first** → `references/builtin-diagnostics.md` (`/doctor`,
   `/context`, `/debug`, plus `claude --version` for version-matched docs).
2. **Parse JSONL** → `references/jsonl-schema.md` + `scripts/parse_transcript.py`
   (real keys; `uuid`/`parentUuid`/`isSidechain` instead of `chain_id`).
3. **Triage matrix** → `references/triage-matrix.md` + the `triage()` detector
   (loops scoped to idempotent tools to avoid false positives; sequence
   anti-patterns; context pressure; runtime/API errors; corrupt transcript).
4. **Remediation plan** → `references/remediation-playbook.md`, emitting
   ROOT CAUSE → FORENSIC EVIDENCE → RECOVERY STEP, extended with a fix-contract
   negotiation (analyze → recommend → propose patch → apply).

## Why this matters

A diagnostic that keys off `chain_id`/`error` would silently find nothing on a
real transcript. mentat's parser is run against real 10k-line sessions and its
detectors fire on verified keys.
