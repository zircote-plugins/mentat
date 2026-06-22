# Triage matrix

Maps symptoms found in a transcript to root causes. Each row names the detector
in `scripts/parse_transcript.py` and the caveat that keeps it honest. This is the
**reliability** dimension; the `security` and `efficiency` dimensions have their
own matrices (`security-matrix.md`, `efficiency-matrix.md`) and plug into the
same analyzer registry. All dimensions emit the normalized `findings.Finding`
record (legacy `category`/`severity`/`evidence`/`detail` keys plus
`dimension`/`confidence`/`fingerprint`/`provenance`).

| Category | Severity | Detector signal | Caveat / false-positive guard |
| --- | --- | --- | --- |
| Infinite loop / red-herring | high if a signature repeats ≥6×, else medium | normalized `tool_use` signature (volatile digits/hashes stripped) repeats ≥3× | scoped to **idempotent/read tools** (`Bash`, `Grep`, `Glob`, `Read`, `WebFetch`, `WebSearch`). Repeated `Edit`/`Write` to one file is normal iteration, **not** a loop. Across a very long session, repeated reads of one file may still be legitimate revisiting — confirm intent. |
| Tool / runtime failure | high if ≥3 failures, else medium | `tool_result.is_error` blocks; `toolUseResult.code != 0` with a non-empty `command` | HTTP-status `code` (200) on WebFetch/Agent results is excluded by requiring a `command`. User-rejected tool uses also appear as `is_error` — distinguish "rejected by user" from "failed". Severity scales with clustering: a lone errored block an agent recovered from (a missed Read, one transient timeout, a single grep exit-1) is **medium**, not a high incident. Known-benign harness control flow (e.g. `falsification-gate: skipped` exiting 1 under the one-round rule) is suppressed via `BENIGN_PATTERNS`. |
| API / model error | high | `isApiErrorMessage: true` on assistant lines | transient API errors (retried successfully) are still surfaced; check whether the next turn recovered. |
| Tool-sequence anti-pattern | medium | `Edit` of a file with no prior `Read` in the session | a file Read in an earlier (compacted) window won't be seen; treat as a hint, not proof. |
| Environment / config warning | low | `system` lines with `level` warning/error | informational; correlate with `/doctor`. |
| Corrupt / truncated transcript | medium | unparseable JSONL lines | a crash mid-write truncates the last line; recover from `file-history-snapshot`. |
| Possible context-window pressure | low | >4000 lines and >1000 `tool_result` blocks | Coarse line/block heuristic, retained as a fallback for transcripts **without** usage data. Transcripts DO carry per-turn token counts in `message.usage` (input/output/cache-read/cache-create); when present, the `efficiency` dimension's token-based pressure finding is the accurate signal — see `efficiency-matrix.md`. Verify with `/context`. |

## Reading the loop signal

The normalized signature collapses minor argument mutations so the classic
"re-run grep/bash with a tweaked string" red-herring still groups together.
A high repeat count on a **read/search** tool is the strongest single indicator
that a session is thrashing rather than progressing.
