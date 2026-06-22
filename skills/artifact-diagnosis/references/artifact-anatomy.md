# Artifact anatomy — what a healthy Claude Code artifact looks like

When a transcript points at a flaky **artifact** (not just a one-off runtime
fault), use this to locate the structural defect. Verify against the live spec
at `code.claude.com/docs` and the bundled `claude-code-docs/`.

## Slash command (`commands/<name>.md`)

- YAML frontmatter; name derives from the filename.
- Common keys: `description`, `argument-hint`, `allowed-tools`, optionally
  `model`. Body is the prompt.
- Flaky causes: missing/invalid `allowed-tools` (tool calls silently blocked);
  unescaped colons/`<...>` in frontmatter values breaking YAML; ambiguous
  argument handling.

## Skill (`skills/<name>/SKILL.md`)

- Required frontmatter: `name`, `description`. `description` drives activation —
  vague descriptions = the skill never triggers (or triggers everywhere).
- Optional: `argument-hint`, `allowed-tools`, `license`.
- `references/`, `scripts/`, `examples/` are progressive-disclosure payloads.
- Flaky causes: over-broad/under-specific `description`; YAML parse failure
  (drops all metadata silently); scripts assuming non-stdlib deps.

## Sub-agent (`agents/<name>.md`)

- Frontmatter: `name`, `description` (with triggering examples), `tools`.
- **YAML trap (verified):** putting `<example>` blocks with raw colons inside
  `description:` makes the YAML fail to parse — at runtime the agent loads with
  **empty metadata, all fields silently dropped**. `claude plugin validate`
  flags this. Keep `description` a quoted scalar or a block scalar (`|`).
- Flaky causes: the YAML trap above; missing tools; description that doesn't
  match the intended trigger.

## Plugin (`.claude-plugin/plugin.json`)

- Required: `name`. Strongly recommended: `version` (semver), `description`,
  `author`, `license`, `keywords`.
- `claude plugin validate <path>` checks the manifest, agents, skills, commands.
  `--strict` treats unrecognized fields / missing metadata as errors.
- Flaky causes: missing `version` (warning); malformed JSON; component
  frontmatter errors cascading from agents/skills.

## Validation loop

```text
claude plugin validate plugins/<name>          # tolerant pass
claude plugin validate plugins/<name> --strict # CI-grade
```

Fix every error before declaring an artifact healthy.
