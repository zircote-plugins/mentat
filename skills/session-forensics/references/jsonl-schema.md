# Claude Code transcript JSONL schema (verified)

Transcripts live at `<root>/projects/<slugified-cwd>/<session-id>.jsonl`, where
`<root>` resolves from `$CLAUDE_CONFIG_DIR` (the variable Claude Code sets), then
`$CLAUDE_HOME`, defaulting to `~/.claude`.
Each line is one JSON object. This is the **real** schema, profiled directly
from live transcripts (Claude Code 2.1.x) — not the illustrative seed.

## Line types (`type`)

| `type` | meaning |
| --- | --- |
| `user` | a user turn (or a tool_result fed back to the model) |
| `assistant` | a model turn (text / thinking / tool_use blocks) |
| `system` | runtime/system notice; has `level` (info/warning/error) + `subtype` |
| `attachment` | injected context (files, reminders) |
| `mode` | mode marker (e.g. plan/auto) |
| `file-history-snapshot` | editor snapshot for undo (`snapshot`, `messageId`) |
| `last-prompt` | pointer to the last prompt leaf (`leafUuid`) |

## Common top-level keys

`uuid`, `parentUuid` (threading), `sessionId`, `timestamp`, `version`
(the Claude Code version that produced the line), `gitBranch`, `cwd`,
`userType`, `entrypoint`, `isSidechain`, `isMeta`.

- **Threading is `uuid` → `parentUuid`.** Walk parents to reconstruct turn
  order; there is no `chain_id`.
- **`isSidechain: true`** marks lines belonging to a spawned subagent / Task.
- **`version`** is how mentat ties a session to the right doc set.

## Message content blocks (`message.content[]`)

`message` is `{role, content[]}`. Each content block has a `type`:

| block `type` | key fields |
| --- | --- |
| `text` | `text` |
| `thinking` | `thinking` |
| `tool_use` | `name`, `input`, `id` |
| `tool_result` | `tool_use_id`, `content`, `is_error` |
| `server_tool_use` | server-side tool invocation |
| `advisor_tool_result` | advisor responses |

## Where errors actually surface (three places)

1. **`tool_result` block with `is_error: true`** — the tool returned an error
   (bad path, rejected edit, `<tool_use_error>…</tool_use_error>`).
2. **Top-level `toolUseResult` object with non-zero `code`** — a Bash result
   carries the shell exit code *and* the `command`. NOTE: WebFetch/Agent results
   reuse `code` for an HTTP status (e.g. `200`); mentat requires a non-empty
   `command` before treating `code` as a shell exit.
3. **`assistant` line with `isApiErrorMessage: true`** — an API/model error turn.

## Token usage (`message.usage`) — verified present

Each `assistant` turn carries a `message.usage` object with **real token
counts** (profiled from Claude Code 2.1.x):

| field | meaning |
| --- | --- |
| `input_tokens` | uncached input billed this turn |
| `output_tokens` | output generated this turn |
| `cache_creation_input_tokens` | input written to the prompt cache |
| `cache_read_input_tokens` | input served from the cache (cheap) |
| `service_tier`, `speed`, `iterations` | tier/latency metadata |

The `efficiency` dimension sums these for true token spend; do **not** assume
"no token counts in the transcript" (an older, now-corrected caveat).

## Other useful keys

`requestId`, `durationMs`, `toolUseID`, and the rich `toolUseResult` object
(keys include `command`, `code`, `interrupted`, `filePath`, `oldString`,
`newString`, `content`, `matches`, `agentId`, …).

- **`permissionMode`** — the active permission mode for the turn
  (`default`/`acceptEdits`/`bypassPermissions`/`plan`); the `security` dimension
  reads it for context (a dangerous command under `bypassPermissions` is worse).
- **`attributionSkill`** — the skill a line is attributed to, when a skill is
  active; recorded in finding provenance and aggregated by the corpus.
