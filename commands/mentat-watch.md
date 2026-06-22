---
name: mentat-watch
description: "Live-monitor a running Claude Code session transcript and surface loops, tool failures, security risks, and context pressure as agent-to-agent feedback"
argument-hint: "<session-id | path/to/transcript.jsonl> [--once] [--dimension reliability,security,efficiency,all]"
allowed-tools: ["Read", "Bash", "Grep", "Glob", "Skill", "Monitor"]
---

# /mentat-watch

Watch a session transcript and react the moment an actionable error appears — for
mid-run course correction rather than post-mortem.

Argument: `$1` is a **session-id** or **transcript path**. Pass `--once` for a
single synchronous pass (CI or a quick check) instead of a live watch.

Optional `--dimension` selects analyzers. The live watch surfaces security and
efficiency findings mid-run too; **default is `reliability,security`** — the
mid-run-actionable set (a leaked secret or dangerous command is worth catching
the moment it appears). The watcher's `--once` exit is non-zero on a reliability
loop/tool/API issue **or any high-severity finding** (so security highs trigger).

## Do this

1. Invoke the `session-forensics` skill / `transcript-monitor` agent for context.

2. **Live watch — use `Monitor`, not a foreground/background poll loop.** The
   watcher's `--once` pass exits non-zero the moment a loop, tool/runtime
   failure, API error, **or high-severity security finding** appears, so
   `Monitor` can wait on that terminal state and fire **one** notification when
   an error actually shows up — instead of streaming poll ticks the user never
   asked for:

   ```javascript
   Monitor({
     description: "mentat: watch <session/transcript> for loops, tool failures, secrets/dangerous commands",
     command: "W=${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/watch_transcript.py; " +
              "until ! python3 \"$W\" --path \"$1\" --once --dimension reliability,security >/tmp/mentat-watch.$$.jsonl 2>&1; do sleep 2; done; " +
              "cat /tmp/mentat-watch.$$.jsonl",
     timeout_ms: 3600000,
     persistent: false,
   })
   ```

   Resolve a session-id to a path first if `$1` is not already a file
   (`watch_transcript.py` accepts `--session <id>` too). The `until ! … --once`
   form loops while the transcript is clean (exit 0) and terminates on the first
   actionable error (exit non-zero), so the notification body carries the
   triggering `issue` records.

3. **On the notification, run the actions** — for each emitted `issue` record
   relay it as concise feedback (`severity`, `category`, `evidence`,
   `recommendation`, `fix_authority`) and, where the issue warrants a fix,
   hand off to `mentat-diagnose` / the `artifact-repair` agent. `fix_authority`
   is `propose` by default — do not apply fixes without explicit authority.

4. After reacting, re-arm `Monitor` to catch the next error if the session is
   still running. Do not poll the monitor yourself or start a second monitor for
   the same transcript.

## Single pass (`--once`)

For CI or a one-shot check, skip `Monitor` and run the watcher directly — it
emits each `issue` as JSONL and exits non-zero if any actionable error was seen:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/watch_transcript.py --path "$1" --once --dimension reliability,security
```

Cite the transcript signal behind every reported issue. Raw secrets are always
redacted in watch output.
