# Efficiency matrix

Maps cost/efficiency signals to findings. Each row names the detector in
`scripts/efficiency_scan.py`. Findings are emitted in the `efficiency` dimension.
Token counts are **measured** from `message.usage` (real in Claude Code 2.1.x),
not estimated.

| Category | Severity | Confidence | Detector signal | Caveat / scope |
| --- | --- | --- | --- | --- |
| Token spend | low (informational) | high | sum of `message.usage` (input/output/cache-read/cache-create) across assistant turns | Not a fault — a cost summary. Emitted only when usage data is present. `--price-table` adds an optional USD estimate. |
| Expensive uncached turns | medium | medium | turns billing ≥20000 **uncached** `input_tokens` (cache miss on a large input) | First reads legitimately create cache; a few expensive turns can be unavoidable. Counts turns, not waste — read alongside cache-read totals in detail. |
| Redundant file re-reads | medium | medium | same `file_path` Read ≥3× | **Overlaps the reliability loop detector** (Read is loop-prone) by design — this is the *cost* lens (which file, how many times) vs reliability's *thrashing* lens. A corpus keeps both as distinct dimensional views. Long sessions may re-read legitimately. |
| Repeated successful commands | medium | medium | same `Bash` command with a **non-error** result ≥3× | Scoped to SUCCESS so it does not merely restate a reliability loop (which also counts failing repeats). Idempotent re-runs (e.g. re-running tests to confirm) can be intentional. |
| Oversized tool_result | medium if ≥50000 chars, else low | high | a single `tool_result` whose content length ≥10000 chars | Character length, not tokens (the block itself carries no per-block usage). One large necessary read is not waste; many are context bloat. |
| Context-window pressure (tokens) | low | high | total billed input (uncached + cache-read + cache-create) ≥200000 | The precise counterpart to the reliability line-count heuristic. The reliability one is **retained** as a coarse fallback for transcripts without usage data (older sessions); this token-based one supersedes it when usage is present. |

## Relationship to the reliability line-count heuristic

`references/triage-matrix.md` documents a reliability "Possible context-window
pressure" finding based on line/`tool_result` counts. That heuristic predates
usage data in transcripts. It is kept (so reliability output stays byte-stable
and still works on usage-less transcripts), but when `message.usage` is present
the `efficiency` dimension's token-based pressure finding is the accurate signal.

## Gating

Efficiency findings are advisory (low/medium only); `efficiency_scan.py` always
exits 0. Do not gate CI on efficiency — gate on `security` (high) and
`reliability` (high) instead.
