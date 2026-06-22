# Corpus schema

The cross-session finding corpus (`scripts/corpus.py`) is a local JSONL store —
one finding record per line — that accumulates across sessions so recurring
problems become visible. **Local-only, no network.**

## Location

`$MENTAT_CORPUS` if set, else `$CLAUDE_CONFIG_DIR/mentat/corpus.jsonl` (falling
back to `$CLAUDE_HOME`, then `~/.claude`). Bounded by `$MENTAT_CORPUS_MAX`
records (default 5000) with oldest-record eviction.

## Record shape

Each record stores **fingerprint + provenance metadata + redacted evidence
only** — never the raw `detail` (which can carry unredacted reliability
snippets). Raw secrets never reach the store.

| field | source | notes |
| --- | --- | --- |
| `fingerprint` | finding | `hash(dimension + category + normalized_evidence)` — the cross-session dedup key (volatile counts normalized out) |
| `dimension` | finding | `reliability` \| `security` \| `efficiency` |
| `category`, `severity`, `confidence` | finding | as triaged |
| `evidence` | finding | redacted (idempotent — re-redacted on write) |
| `session_id`, `transcript_path` | provenance | which session/file this instance came from |
| `cc_version`, `gitBranch`, `attributionSkill`, `timestamp` | provenance | context |
| `recorded_at` | corpus | epoch seconds when scanned |
| `metrics` | finding detail | optional non-secret numbers lifted for trends (e.g. `billed_input_tokens`) |

## Dedup

Append dedups by `(fingerprint, session_id, transcript_path)`, so re-scanning a
session does not double-count. The **same `fingerprint` across different
sessions** is the recurrence signal — that is the whole point: it survives
volatile counts and per-session paths.

## Trends & suggestions

`corpus.py trends` aggregates by fingerprint (distinct sessions), security
category, token-cost-by-session, and `attributionSkill`. `suggest.py` reads the
same store and emits a fix-contract `proposal` (round: proposal — writes nothing)
when a category recurs across ≥2 distinct sessions. See
`fix-contract-protocol.md`.
