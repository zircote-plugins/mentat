#!/usr/bin/env python3
"""mentat — cross-session finding corpus and trend reporting.

Turns one-off diagnosis into longitudinal signal. ``corpus.py scan`` runs all
analyzer dimensions over recent transcripts and appends compact, **redacted**
finding records to a local JSONL store; ``corpus.py trends`` aggregates the store
into recurring categories, security hotspots, token-cost leaders, and the skills
most associated with findings. Stdlib-only, local-only — no network.

Store location: ``$MENTAT_CORPUS`` if set, else
``$CLAUDE_CONFIG_DIR/mentat/corpus.jsonl`` (falling back to ``$CLAUDE_HOME`` then
``~/.claude``). Each record carries fingerprint + provenance metadata + redacted
evidence ONLY — never the raw ``detail`` (which can hold unredacted reliability
snippets). The store is bounded by ``$MENTAT_CORPUS_MAX`` records (default 5000)
with oldest-record eviction.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_transcript as P  # noqa: E402
from findings import redact  # noqa: E402

DEFAULT_MAX_RECORDS = 5000
# Fields lifted from a finding's detail into a record's `metrics` (non-secret).
_METRIC_KEYS = ("billed_input_tokens", "output_tokens", "uncached_input_tokens")


def corpus_path() -> str:
    override = os.environ.get("MENTAT_CORPUS")
    if override:
        return os.path.expanduser(override)
    base = (os.environ.get("CLAUDE_CONFIG_DIR")
            or os.environ.get("CLAUDE_HOME")
            or "~/.claude")
    return os.path.join(os.path.expanduser(base), "mentat", "corpus.jsonl")


def _max_records() -> int:
    try:
        return int(os.environ.get("MENTAT_CORPUS_MAX", DEFAULT_MAX_RECORDS))
    except ValueError:
        return DEFAULT_MAX_RECORDS


def read_corpus(path: str | None = None) -> list[dict]:
    path = path or corpus_path()
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _record(finding: dict, recorded_at: float) -> dict:
    """Compact, redacted corpus record — fingerprint + metadata + evidence."""
    prov = finding.get("provenance") or {}
    rec = {
        "fingerprint": finding["fingerprint"],
        "dimension": finding["dimension"],
        "category": finding["category"],
        "severity": finding["severity"],
        "confidence": finding.get("confidence"),
        "evidence": redact(finding.get("evidence", "")),  # idempotent; defense-in-depth
        "session_id": prov.get("session_id"),
        "transcript_path": prov.get("transcript_path"),
        "cc_version": prov.get("cc_version"),
        "gitBranch": prov.get("gitBranch"),
        "attributionSkill": prov.get("attributionSkill"),
        "timestamp": prov.get("timestamp"),
        "recorded_at": recorded_at,
    }
    detail = finding.get("detail")
    if isinstance(detail, dict):
        metrics = {k: detail[k] for k in _METRIC_KEYS if isinstance(detail.get(k), int)}
        if metrics:
            rec["metrics"] = metrics
    return rec


def _recent_transcripts(limit: int) -> list[str]:
    files = glob.glob(os.path.join(P.PROJECTS, "*", "*.jsonl"))
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return files[:limit]


def scan(paths: list[str], recorded_at: float) -> list[dict]:
    """Analyze each transcript (all dimensions) -> new corpus records."""
    P.load_optional_analyzers("all")
    dims = P.parse_dimensions("all")
    records = []
    for path in paths:
        rows = P.load(path)
        a = P.analyze(rows)
        for f in P.run_analyzers(dims, rows, a, path):
            records.append(_record(f, recorded_at))
    return records


def append_records(new_records: list[dict], path: str | None = None) -> int:
    """Append records (deduped by (fingerprint, session_id, transcript_path)),
    then evict oldest beyond the max. Returns the number actually added."""
    path = path or corpus_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = read_corpus(path)
    seen = {(r.get("fingerprint"), r.get("session_id"), r.get("transcript_path"))
            for r in existing}
    added = []
    for r in new_records:
        key = (r.get("fingerprint"), r.get("session_id"), r.get("transcript_path"))
        if key in seen:
            continue
        seen.add(key)
        added.append(r)
    if not added:
        return 0
    combined = existing + added
    cap = _max_records()
    if len(combined) > cap:
        combined = combined[-cap:]  # evict oldest
    with open(path, "w", encoding="utf-8") as fh:
        for r in combined:
            fh.write(json.dumps(r) + "\n")
    return len(added)


def _counter(items):
    c = {}
    for it in items:
        c[it] = c.get(it, 0) + 1
    return sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0])))


def trends(records: list[dict], top: int = 10) -> dict:
    """Aggregate corpus records into trend tables."""
    by_fp = {}
    for r in records:
        fp = r.get("fingerprint")
        e = by_fp.setdefault(fp, {"category": r.get("category"),
                                  "dimension": r.get("dimension"),
                                  "severity": r.get("severity"),
                                  "sessions": set(), "count": 0})
        e["count"] += 1
        if r.get("session_id"):
            e["sessions"].add(r["session_id"])

    recurring = sorted(
        ({"fingerprint": fp, "category": e["category"], "dimension": e["dimension"],
          "severity": e["severity"], "occurrences": e["count"],
          "distinct_sessions": len(e["sessions"])}
         for fp, e in by_fp.items()),
        key=lambda d: (-d["distinct_sessions"], -d["occurrences"]))[:top]

    sec = [r for r in records if r.get("dimension") == "security"]
    security_hotspots = [{"category": c, "count": n}
                         for c, n in _counter([r["category"] for r in sec])][:top]

    skills = [{"skill": s, "count": n}
              for s, n in _counter([r["attributionSkill"] for r in records
                                    if r.get("attributionSkill")])][:top]

    leaders = {}
    for r in records:
        m = r.get("metrics") or {}
        if isinstance(m.get("billed_input_tokens"), int) and r.get("session_id"):
            leaders[r["session_id"]] = max(leaders.get(r["session_id"], 0),
                                           m["billed_input_tokens"])
    token_leaders = [{"session_id": s, "billed_input_tokens": t}
                     for s, t in sorted(leaders.items(), key=lambda kv: -kv[1])][:top]

    return {
        "total_records": len(records),
        "distinct_fingerprints": len(by_fp),
        "recurring": recurring,
        "security_hotspots": security_hotspots,
        "token_cost_leaders": token_leaders,
        "skills_with_findings": skills,
    }


def _render_trends(t: dict) -> str:
    out = ["# mentat corpus trends",
           f"records: {t['total_records']}  |  distinct fingerprints: {t['distinct_fingerprints']}",
           "", "## Recurring findings (by distinct sessions)"]
    if not t["recurring"]:
        out.append("(none)")
    for r in t["recurring"]:
        out.append(f"  [{r['severity']}] {r['dimension']}/{r['category']}: "
                   f"{r['distinct_sessions']} session(s), {r['occurrences']} occurrence(s)")
    out.append("\n## Security hotspots")
    out += [f"  {h['category']}: {h['count']}" for h in t["security_hotspots"]] or ["(none)"]
    out.append("\n## Token-cost leaders")
    out += [f"  {ld['session_id']}: {ld['billed_input_tokens']} billed input tokens"
            for ld in t["token_cost_leaders"]] or ["(none)"]
    out.append("\n## Skills associated with findings")
    out += [f"  {s['skill']}: {s['count']}" for s in t["skills_with_findings"]] or ["(none)"]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mentat cross-session finding corpus")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("scan", help="analyze recent transcripts into the corpus")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--path", help="scan one transcript")
    g.add_argument("--session", help="scan one session by id")
    sp.add_argument("--limit", type=int, default=50,
                    help="most-recent N transcripts to scan (default 50)")
    sp.add_argument("--corpus", help="override corpus store path")

    tp = sub.add_parser("trends", help="report trends from the corpus")
    tp.add_argument("--top", type=int, default=10)
    tp.add_argument("--json", action="store_true")
    tp.add_argument("--corpus", help="override corpus store path")

    args = ap.parse_args(argv)
    store = getattr(args, "corpus", None) or corpus_path()

    if args.cmd == "scan":
        if args.path:
            paths = [args.path]
        elif args.session:
            p = P.locate(args.session)
            paths = [p] if p else []
        else:
            paths = _recent_transcripts(args.limit)
        if not paths:
            print("No transcripts found to scan.", file=sys.stderr)
            return 2
        recs = scan(paths, time.time())
        added = append_records(recs, store)
        print(f"Scanned {len(paths)} transcript(s); {len(recs)} finding(s); "
              f"{added} new record(s) added to {store}")
        return 0

    if args.cmd == "trends":
        recs = read_corpus(store)
        t = trends(recs, top=args.top)
        print(json.dumps(t, indent=2) if args.json else _render_trends(t))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
