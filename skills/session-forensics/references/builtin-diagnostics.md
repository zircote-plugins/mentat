# Built-in environment health checks (run first)

Before deep transcript analysis, confirm the local environment is healthy — many
"flaky artifact" reports are actually environment faults. Advise the user (or, if
acting agent-to-agent, ask the requester to run) these built-ins:

| Command | What it checks |
| --- | --- |
| `/doctor` | automated system, MCP server, and configuration health check |
| `/context` | loaded context-window usage and active skills (catches bloat) |
| `/debug [description]` | forces live diagnostic log tracking for a repro |
| `claude --version` | the installed version — pins which doc set applies (`scripts/refresh_docs.sh`) |
| `claude --help` | confirms whether a flag/subcommand exists in *this* version |

## Why version first

Doc pages at `code.claude.com/docs` are served at HEAD. A flag described in the
docs may not exist in an older installed version. mentat resolves this by:

1. reading `claude --version`,
2. extracting that version's section from the bundled `CHANGELOG.md`,
3. treating doc claims about newer features as "verify with `claude --help`".

See `${CLAUDE_PLUGIN_ROOT}/references/REFRESH.md` for the refresh contract.

## Order of operations

1. `/doctor` and `/context` — rule out config/MCP/context issues.
2. `claude --version` — pin the doc set.
3. Only then run the transcript forensics (`parse_transcript.py`).
