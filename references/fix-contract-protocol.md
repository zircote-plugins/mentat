# Fix-contract protocol (agent-to-top-level negotiation)

How mentat's `artifact-repair` agent negotiates a fix with the **top-level
session** that invoked it. This is the operational form of the contract levels in
`${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/references/remediation-playbook.md`
(`analyze → recommend → propose → apply`).

## Why a handshake, not a conversation

A Claude Code subagent runs to completion and returns a single message; the
top-level session sees only that return, not the subagent's intermediate steps,
and the subagent cannot pause to await a reply. Therefore negotiation is a
**two-round handshake across two invocations**, each round's return being a
structured contract document (see `contract-schema.json`).

```text
Round 1  PROPOSAL        (read-only — writes nothing)
  top-level ──▶ artifact-repair { session, target_artifact }
  artifact-repair ──▶ { round:"proposal", diagnosis[], fixes[ diff, authority,
                        risk, verify ], open_decisions[], default_applier }

Round 2  AUTHORIZATION → RESULT
  top-level ──▶ artifact-repair { round:"authorization", approved_patch_ids,
                                  granted_authority{}, decisions{} }
  artifact-repair ──▶ { round:"result", applied[], applied_by, verification,
                        remaining[] }
```

## Who holds the pen

`default_applier` is `"top-level"`: mentat emits the final approved diffs and the
**top-level session writes them**. mentat writes a patch itself only when the
authorization sets that patch's `granted_authority` to `"mentat-apply"`. Either
way mentat writes nothing in round 1, and never force-pushes or deletes.

## Round 1 — proposal (the offer)

`artifact-repair` returns one `proposal` object:

- `diagnosis[]` — `{id, category, severity, root_cause, evidence}`
- `fixes[]` — `{id, addresses[], file, summary, diff, requested_authority,
  blast_radius, risk, verify}` where `diff` is a unified diff (computed, not
  applied) and `verify` is the command that proves the fix (e.g.
  `claude plugin validate <plugin>`).
- `open_decisions[]` — `{id, question, options[], default}` for choices only the
  top-level can make.
- `requires_from_top_level[]` — plain-language asks (e.g. "authorize P1",
  "decide D1").

## Round 2 — authorization (the acceptance) → result

The top-level re-invokes with an `authorization` object:

- `approved_patch_ids[]`
- `granted_authority` — map of patch id → `"top-level-apply"` | `"mentat-apply"`
- `decisions` — map of decision id → chosen option

`artifact-repair` then:

1. For `top-level-apply` patches: re-emits the final diff (writes nothing).
2. For `mentat-apply` patches: applies exactly those, runs each `verify`.
3. Returns a `result` object: `applied[]`, `applied_by`, `verification`,
   `remaining[]`.

## Invariants

- No writes in round 1.
- Apply only approved patches, exactly — no scope creep.
- Re-validate after every apply; report failures honestly.
- The top-level is always free to take the diffs and apply them itself.
