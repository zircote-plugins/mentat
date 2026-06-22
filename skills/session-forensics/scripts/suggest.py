#!/usr/bin/env python3
"""mentat — improvement feedback loop.

Reads the cross-session corpus (corpus.py) and turns recurring findings into
*proposed* durable artifacts: CLAUDE.md guidance, settings.json permission
entries, and BENIGN_PATTERNS additions for recurring noise. It NEVER writes —
output is a fix-contract ``proposal`` document (analyze → recommend → propose →
apply; see ``references/fix-contract-protocol.md``) that the top-level session
reviews and applies. Stdlib-only.

A suggestion is emitted only when a finding category recurs across at least
``--min-sessions`` distinct sessions (default 2) — one-off findings are not
"patterns" worth a durable change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus as C  # noqa: E402

# category -> proposed artifact template.
#   kind:   claude-md | settings | benign-pattern
#   target: file the top-level would edit
#   body:   the reviewable artifact text
_TEMPLATES = {
    "Tool-sequence anti-pattern": {
        "kind": "claude-md", "target": "CLAUDE.md", "risk": "low",
        "summary": "Add guidance: Read before Edit",
        "body": "- Always Read a file before Editing it; an Edit without a prior "
                "Read in-session is a recurring anti-pattern here.",
    },
    "Redundant file re-reads": {
        "kind": "claude-md", "target": "CLAUDE.md", "risk": "low",
        "summary": "Add guidance: avoid re-reading the same file",
        "body": "- Do not re-read a file you already read this session; reuse the "
                "earlier content. Repeated reads recur and waste tokens.",
    },
    "Repeated successful commands": {
        "kind": "claude-md", "target": "CLAUDE.md", "risk": "low",
        "summary": "Add guidance: don't re-run commands that already succeeded",
        "body": "- Do not re-run a command that already succeeded; cache the "
                "result. Repeated successful commands recur and waste tokens.",
    },
    "Infinite loop / red-herring": {
        "kind": "claude-md", "target": "CLAUDE.md", "risk": "low",
        "summary": "Add guidance: break repeat-call loops by changing strategy",
        "body": "- When a tool call repeats with no progress, change strategy — "
                "read the last result before re-issuing, don't just tweak the args.",
    },
    "Dangerous command": {
        "kind": "settings", "target": ".claude/settings.json", "risk": "medium",
        "summary": "Propose deny rules for recurring dangerous commands",
        "body": {"permissions": {"deny": [
            "Bash(rm -rf:*)", "Bash(curl:*| sh)", "Bash(git push --force:*)"]}},
    },
    "Secret exposure": {
        "kind": "claude-md", "target": "CLAUDE.md", "risk": "low",
        "summary": "Add guidance: never inline secrets",
        "body": "- Never place secrets in commands or echo them in output; "
                "reference environment variables instead. Secret exposure recurs here.",
    },
    "Environment / config warning": {
        "kind": "benign-pattern", "target": "skills/session-forensics/scripts/parse_transcript.py",
        "risk": "low",
        "summary": "If these recurring warnings are benign, suppress via BENIGN_PATTERNS",
        "body": "If this recurring warning is known-benign harness control flow, add "
                "a verified regex to BENIGN_PATTERNS in parse_transcript.py so it "
                "stops being triaged. Confirm it is benign before adding.",
    },
}


def suggest(records: list[dict], min_sessions: int = 2) -> dict:
    """Build a fix-contract proposal document from recurring corpus findings."""
    t = C.trends(records, top=100)
    suggestions = []
    n = 0
    for r in t["recurring"]:
        if r["distinct_sessions"] < min_sessions:
            continue
        tmpl = _TEMPLATES.get(r["category"])
        if not tmpl:
            continue
        n += 1
        suggestions.append({
            "id": f"S{n}",
            "addresses": [r["fingerprint"]],
            "category": r["category"],
            "dimension": r["dimension"],
            "kind": tmpl["kind"],
            "target": tmpl["target"],
            "summary": tmpl["summary"],
            "proposed_artifact": tmpl["body"],
            "rationale": f"{r['category']} recurred across {r['distinct_sessions']} "
                         f"session(s) ({r['occurrences']} occurrence(s)).",
            "requested_authority": "propose",
            "blast_radius": tmpl["target"],
            "risk": tmpl["risk"],
            "verify": "review the proposed artifact; re-run /mentat-corpus trends "
                      "after applying to confirm the pattern's recurrence drops",
        })
    return {
        "contract_version": "1",
        "round": "proposal",
        "source": "corpus",
        "default_applier": "top-level",
        "min_sessions": min_sessions,
        "considered_fingerprints": t["distinct_fingerprints"],
        "suggestions": suggestions,
        "requires_from_top_level": [
            f"review and (if accepted) apply suggestion {s['id']}" for s in suggestions],
    }


def _render(doc: dict) -> str:
    out = ["# mentat improvement proposal (round: proposal — nothing written)",
           f"source: corpus  |  min_sessions: {doc['min_sessions']}  |  "
           f"fingerprints considered: {doc['considered_fingerprints']}",
           f"\n{len(doc['suggestions'])} suggestion(s):"]
    if not doc["suggestions"]:
        out.append("  (no category recurred across enough sessions yet)")
    for s in doc["suggestions"]:
        out.append(f"\n## [{s['id']}] {s['summary']}  ({s['kind']} → {s['target']}, risk {s['risk']})")
        out.append(f"rationale: {s['rationale']}")
        body = s["proposed_artifact"]
        out.append("proposed artifact:")
        out.append("```")
        out.append(json.dumps(body, indent=2) if isinstance(body, (dict, list)) else str(body))
        out.append("```")
        out.append(f"verify: {s['verify']}")
    out.append("\n(authority: propose — the top-level session applies what it accepts)")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mentat improvement feedback loop")
    ap.add_argument("--min-sessions", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--corpus", help="override corpus store path")
    args = ap.parse_args(argv)

    store = args.corpus or C.corpus_path()
    records = C.read_corpus(store)
    if not records:
        print(f"Corpus is empty ({store}). Run `/mentat-corpus scan` first.",
              file=sys.stderr)
        return 2
    doc = suggest(records, min_sessions=args.min_sessions)
    print(json.dumps(doc, indent=2) if args.json else _render(doc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
