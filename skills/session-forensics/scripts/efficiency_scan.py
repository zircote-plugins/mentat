#!/usr/bin/env python3
"""mentat — efficiency & cost analysis pass over a Claude Code transcript.

Registers the ``efficiency`` dimension. Real Claude Code 2.1.x transcripts carry
``message.usage`` (input_tokens, output_tokens, cache_creation_input_tokens,
cache_read_input_tokens, service_tier, …), so token spend is measured, not
guessed. Stdlib-only.

Detectors (see ``references/efficiency-matrix.md``):

  * Token spend          — informational summary of real token usage.
  * Expensive uncached turns — turns billing a large UNcached input (cache miss).
  * Redundant file re-reads  — same file Read ≥N times (token-cost lens).
  * Repeated successful commands — same Bash command succeeding ≥N times (pure
    waste; scoped to SUCCESS so it does not merely restate a reliability loop,
    which also counts failing repeats).
  * Oversized tool_result    — a single tool_result bloating the context window.
  * Context-window pressure (token-based) — total billed input over a threshold.
    This is the precise counterpart to the reliability line-count heuristic,
    which is retained as a coarse fallback for transcripts lacking usage data.

Tokens-only by default. ``--price-table <file>`` (JSON: per-model USD/MTok rates)
adds an optional dollar estimate; no price table is bundled because rates drift.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from findings import Finding, build_provenance  # noqa: E402

DIMENSION = "efficiency"

EXPENSIVE_TURN_INPUT = 20_000        # uncached input tokens in one turn
REDUNDANT_THRESHOLD = 3              # same read/command repeated this many times
OVERSIZED_RESULT_CHARS = 10_000     # a single tool_result this large bloats context
CONTEXT_TOKEN_PRESSURE = 200_000    # total uncached+cached input over this = pressure

_USAGE_FIELDS = ("input_tokens", "output_tokens",
                 "cache_creation_input_tokens", "cache_read_input_tokens")


def _sum_usage(rows: list[dict]) -> dict:
    """Sum message.usage across assistant turns. Missing usage degrades to 0."""
    totals = {k: 0 for k in _USAGE_FIELDS}
    turns = 0
    expensive = 0
    for d in rows:
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        u = m.get("usage")
        if not isinstance(u, dict):
            continue
        turns += 1
        for k in _USAGE_FIELDS:
            v = u.get(k)
            if isinstance(v, int):
                totals[k] += v
        if isinstance(u.get("input_tokens"), int) and u["input_tokens"] >= EXPENSIVE_TURN_INPUT:
            expensive += 1
    totals["turns_with_usage"] = turns
    totals["expensive_uncached_turns"] = expensive
    return totals


def _price(totals: dict, table: dict | None) -> float | None:
    """Optional USD estimate from a per-MTok price table; None if unavailable."""
    if not table:
        return None
    rate_in = table.get("input_per_mtok")
    rate_out = table.get("output_per_mtok")
    rate_cache_read = table.get("cache_read_per_mtok", rate_in)
    rate_cache_write = table.get("cache_write_per_mtok", rate_in)
    if rate_in is None or rate_out is None:
        return None
    usd = (totals["input_tokens"] / 1e6 * rate_in
           + totals["output_tokens"] / 1e6 * rate_out
           + totals["cache_read_input_tokens"] / 1e6 * (rate_cache_read or 0)
           + totals["cache_creation_input_tokens"] / 1e6 * (rate_cache_write or 0))
    return round(usd, 4)


def scan(rows: list[dict], analysis: dict, path: str | None = None,
         price_table: dict | None = None) -> list[dict]:
    """Run the efficiency detectors and return normalized Finding dicts."""
    from parse_transcript import iter_content_blocks

    prov = build_provenance(analysis, path)
    findings = []

    def add(category, severity, confidence, evidence, detail):
        findings.append(Finding(dimension=DIMENSION, category=category, severity=severity,
                                confidence=confidence, evidence=evidence, detail=detail,
                                provenance=prov).to_dict())

    totals = _sum_usage(rows)
    billed_input = (totals["input_tokens"] + totals["cache_read_input_tokens"]
                    + totals["cache_creation_input_tokens"])

    # 1. Token spend summary (informational) — only when usage data exists.
    if totals["turns_with_usage"]:
        detail = {k: totals[k] for k in _USAGE_FIELDS}
        detail["billed_input_tokens"] = billed_input
        detail["turns_with_usage"] = totals["turns_with_usage"]
        usd = _price(totals, price_table)
        if usd is not None:
            detail["estimated_usd"] = usd
        cost = f"; est ${usd}" if usd is not None else ""
        add("Token spend", "low", "high",
            f"{billed_input} billed input tokens, {totals['output_tokens']} output tokens "
            f"over {totals['turns_with_usage']} turn(s){cost}",
            detail)

    # 2. Expensive uncached turns (cache misses on large inputs).
    if totals["expensive_uncached_turns"]:
        add("Expensive uncached turns", "medium", "medium",
            f"{totals['expensive_uncached_turns']} turn(s) billed ≥{EXPENSIVE_TURN_INPUT} "
            f"uncached input tokens ({totals['input_tokens']} uncached total)",
            {"uncached_input_tokens": totals["input_tokens"],
             "cache_read_input_tokens": totals["cache_read_input_tokens"],
             "threshold": EXPENSIVE_TURN_INPUT})

    # collect reads, successful bash commands, oversized results
    reads = Counter()
    bash_by_id = {}
    error_by_id = {}
    oversized = []
    for line, _role, block in iter_content_blocks(rows):
        bt = block.get("type")
        if bt == "tool_use":
            name = block.get("name", "")
            inp = block.get("input", {})
            if name == "Read" and isinstance(inp, dict) and inp.get("file_path"):
                reads[inp["file_path"]] += 1
            if name == "Bash" and isinstance(inp, dict) and block.get("id"):
                bash_by_id[block["id"]] = str(inp.get("command", ""))
        elif bt == "tool_result":
            tid = block.get("tool_use_id")
            if tid is not None:
                error_by_id[tid] = bool(block.get("is_error"))
            text = block.get("content")
            length = len(text) if isinstance(text, str) else len(str(text))
            if length >= OVERSIZED_RESULT_CHARS:
                oversized.append({"line": line, "chars": length})

    # 3. Redundant file re-reads (token-cost lens; see matrix re: reliability overlap)
    redundant = {fp: n for fp, n in reads.items() if n >= REDUNDANT_THRESHOLD}
    if redundant:
        add("Redundant file re-reads", "medium", "medium",
            f"{len(redundant)} file(s) re-read ≥{REDUNDANT_THRESHOLD}× "
            f"(worst = {max(redundant.values())}×)",
            {"files": redundant})

    # 4. Repeated SUCCESSFUL commands (pure waste — excludes failing repeats).
    success_cmds = Counter(cmd for tid, cmd in bash_by_id.items()
                           if not error_by_id.get(tid, False))
    repeated = {cmd: n for cmd, n in success_cmds.items() if n >= REDUNDANT_THRESHOLD}
    if repeated:
        add("Repeated successful commands", "medium", "medium",
            f"{len(repeated)} successful command(s) re-run ≥{REDUNDANT_THRESHOLD}× "
            f"(worst = {max(repeated.values())}×)",
            {"commands": repeated})

    # 5. Oversized tool_result blocks.
    if oversized:
        biggest = max(o["chars"] for o in oversized)
        sev = "medium" if biggest >= OVERSIZED_RESULT_CHARS * 5 else "low"
        add("Oversized tool_result", sev, "high",
            f"{len(oversized)} tool_result block(s) ≥{OVERSIZED_RESULT_CHARS} chars "
            f"(largest = {biggest})",
            {"blocks": oversized[:5]})

    # 6. Token-based context-window pressure (precise counterpart to the
    #    reliability line-count heuristic).
    if billed_input >= CONTEXT_TOKEN_PRESSURE:
        add("Context-window pressure (tokens)", "low", "high",
            f"{billed_input} billed input tokens across the session "
            f"(≥{CONTEXT_TOKEN_PRESSURE}) — consider /compact",
            {"billed_input_tokens": billed_input,
             "threshold": CONTEXT_TOKEN_PRESSURE})

    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="mentat efficiency & cost analysis pass")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--session")
    g.add_argument("--path")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--price-table", help="JSON file: per-model USD/MTok rates")
    args = ap.parse_args()

    from parse_transcript import analyze, load, locate, report

    path = args.path or (locate(args.session) if args.session else None)
    if not path or not os.path.exists(path):
        print(f"ERROR: transcript not found (session={args.session} path={args.path})",
              file=sys.stderr)
        return 2
    table = None
    if args.price_table:
        with open(args.price_table, encoding="utf-8") as fh:
            table = json.load(fh)
    rows = load(path)
    a = analyze(rows)
    findings = scan(rows, a, path, price_table=table)
    if args.json:
        print(json.dumps({"transcript": path, "dimension": DIMENSION,
                          "findings": findings}, indent=2))
    else:
        print(report(path, a, findings))
    # Efficiency findings are advisory (low/medium); never gate CI on them.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
