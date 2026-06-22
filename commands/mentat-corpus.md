---
name: mentat-corpus
description: "Build a cross-session finding corpus, report recurring-failure trends, and propose durable fixes (CLAUDE.md/settings/BENIGN_PATTERNS) under a non-destructive contract"
argument-hint: "scan | trends | suggest"
allowed-tools: ["Read", "Bash", "Grep", "Glob", "Skill"]
---

# /mentat-corpus

Turn one-off diagnosis into continuous improvement. mentat accumulates findings
across sessions into a local corpus, surfaces what recurs, and proposes durable
fixes — all local-only, redacted, and non-destructive.

Argument `$1` selects the mode (default `trends`):

## `scan` — accumulate findings

Analyze recent transcripts across all dimensions and append **redacted** finding
records (fingerprint + metadata + evidence only — never raw `detail`) to the
local store at `$CLAUDE_CONFIG_DIR/mentat/corpus.jsonl` (override `MENTAT_CORPUS`):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/corpus.py scan --limit 50
# or a single transcript / session:
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/corpus.py scan --path "$2"
```

Records dedup by `(fingerprint, session, transcript)`; the store is bounded
(`MENTAT_CORPUS_MAX`, default 5000) with oldest-record eviction. No network.

## `trends` — what recurs

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/corpus.py trends
```

Reports recurring findings (by distinct sessions — the cross-session
`fingerprint` is the dedup key), security hotspots, token-cost leaders, and the
skills most associated with findings.

## `suggest` — propose durable fixes

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-forensics/scripts/suggest.py
```

Emits a fix-contract `proposal` (round: proposal — **writes nothing**) turning
recurring categories into reviewable CLAUDE.md guidance, settings.json deny
rules, or BENIGN_PATTERNS additions. A suggestion appears only when a category
recurs across ≥2 distinct sessions. The top-level session reviews and applies
what it accepts — default applier is `top-level` (see
`${CLAUDE_PLUGIN_ROOT}/references/fix-contract-protocol.md`).

Relay trends and proposals concisely; cite the recurrence count behind each.
Never apply a suggestion without explicit authority.
