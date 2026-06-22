#!/usr/bin/env python3
"""mentat — Claude Code session transcript forensic parser.

Stdlib-only. Accepts a session-id OR an explicit transcript path, locates the
matching ``.jsonl`` under the Claude Code transcript root (``$CLAUDE_CONFIG_DIR``
or ``$CLAUDE_HOME``, default ``~/.claude``; see ``_projects_root``), parses it
against the real transcript schema (references/jsonl-schema.md), and emits a
structured diagnostic summary.

Schema facts this parser relies on (verified against Claude Code 2.x):
  * Each line is one JSON object with a ``type`` field:
    user | assistant | system | attachment | mode | file-history-snapshot |
    last-prompt
  * Conversation threading is by ``uuid`` / ``parentUuid`` (NOT ``chain_id``).
  * Subagent / Task spawns are flagged by ``isSidechain: true``.
  * ``message.content`` is a list of typed blocks: text | thinking | tool_use |
    tool_result | server_tool_use | advisor_tool_result.
  * Tool errors surface three ways: a ``tool_result`` block with
    ``is_error: true``; a top-level ``toolUseResult`` object with a non-zero
    ``code``; and an assistant line with ``isApiErrorMessage: true``.
  * Each line carries the producing Claude Code ``version`` and ``gitBranch``.

Usage:
    parse_transcript.py --session <id>          # locate under $CLAUDE_CONFIG_DIR/projects
    parse_transcript.py --path <file.jsonl>     # explicit path
    parse_transcript.py --path <f> --json       # machine-readable output only
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

# Make sibling modules importable whether run as a script or imported by
# watch_transcript (which inserts this dir on sys.path before importing us).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from findings import Finding, build_provenance  # noqa: E402


def _projects_root() -> str:
    """Resolve the Claude Code transcript root from the environment.

    CLAUDE_CONFIG_DIR is the variable Claude Code actually sets; CLAUDE_HOME is
    honored as an alternate; ~/.claude is the documented default. The
    transcripts live under ``<root>/projects/<slugified-cwd>/<id>.jsonl``.
    """
    base = (os.environ.get("CLAUDE_CONFIG_DIR")
            or os.environ.get("CLAUDE_HOME")
            or "~/.claude")
    return os.path.join(os.path.expanduser(base), "projects")


PROJECTS = _projects_root()

# Loop detection: how many repeats of one normalized tool signature counts as
# a suspected loop. Three identical-intent calls is the smallest run that is
# better evidence than coincidence (see CLAUDE.md scope heuristic).
LOOP_THRESHOLD = 3
# Near-duplicate Bash/grep mutation run length that counts as a "red herring".
MUTATION_THRESHOLD = 4
# Loops are only suspicious for idempotent / read / search tools. Repeatedly
# Editing the same file is normal iterative work, not a loop, so those tools
# are deliberately excluded to avoid false positives.
LOOP_PRONE = {"Bash", "Grep", "Glob", "Read", "WebFetch", "WebSearch"}

# Known-benign non-zero exits / errored tool_results emitted by harness control
# flow (not faults). The falsification gate intentionally exits 1 when it skips
# an already-gated finding under the one-round rule; flagging it as a "tool
# failure" is a false positive. Conservative list — extend only with verified
# expected-failure signatures.
BENIGN_PATTERNS = (
    re.compile(r"falsification-gate:\s*skipped"),
)


def _is_benign(text: str) -> bool:
    return any(p.search(text or "") for p in BENIGN_PATTERNS)


def locate_subagents(transcript_path: str, session: str | None) -> list[tuple[str, str, str]]:
    """Return (path, agentType, description) for each subagent transcript of a
    session. Claude Code 2.x externalizes Task/Agent spawns to
    ``<project>/<session>/subagents/agent-*.jsonl`` with an ``agent-*.meta.json``
    sidecar — NOT inline ``isSidechain`` rows — so they must be read separately.
    """
    base = os.path.dirname(transcript_path)
    sid = session or os.path.splitext(os.path.basename(transcript_path))[0]
    out = []
    for f in sorted(glob.glob(os.path.join(base, sid, "subagents", "agent-*.jsonl"))):
        atype = desc = ""
        meta = f[:-len(".jsonl")] + ".meta.json"
        if os.path.exists(meta):
            try:
                with open(meta, encoding="utf-8") as fh:
                    md = json.load(fh)
                atype = md.get("agentType") or md.get("subagent_type") or ""
                desc = md.get("description", "")
            except (OSError, json.JSONDecodeError):
                pass
        out.append((f, atype, desc))
    return out


def locate(session: str) -> str | None:
    """Find a transcript by session-id under the projects dir."""
    # Escape glob metacharacters in the (externally-supplied) session id so a
    # crafted value can't expand the pattern unexpectedly.
    hits = glob.glob(os.path.join(PROJECTS, "*", f"{glob.escape(session)}.jsonl"))
    if hits:
        return hits[0]
    # Fall back to scanning sessionId fields (handles resumed/renamed files).
    for f in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            with open(f, encoding="utf-8") as fh:
                first = fh.readline()
            if session in first:
                return f
        except OSError:
            continue
    return None


def load(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                rows.append({"type": "_parse_error", "_line": n, "_err": str(e)})
    return rows


def iter_content_blocks(rows: list[dict]):
    """Yield ``(line_no, role, block)`` for every message.content block.

    Shared by the security/efficiency analyzers so they walk the transcript the
    same way the reliability parser does. ``line_no`` is 1-based for provenance.
    """
    for i, d in enumerate(rows, 1):
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        role = m.get("role")
        for b in content:
            if isinstance(b, dict):
                yield i, role, b


def _norm_tool_sig(name: str, inp: object) -> str:
    """Collapse a tool call to an intent signature so minor string mutations
    (the classic loop red-herring) still group together."""
    if not isinstance(inp, dict):
        return name
    key = ""
    for field in ("command", "pattern", "file_path", "path", "query", "url"):
        if field in inp:
            val = str(inp[field])
            # Strip volatile tails: line numbers, hashes, timestamps, counters.
            val = re.sub(r"\b\d{3,}\b", "#", val)
            val = re.sub(r"[0-9a-f]{7,40}", "#", val)
            key = f"{field}={val[:120]}"
            break
    return f"{name}:{key}" if key else name


def analyze(rows: list[dict]) -> dict:
    by_type = Counter()
    blocks = Counter()
    tools = Counter()
    versions = Counter()
    branches = Counter()
    perm_modes = Counter()
    attribution_skills = Counter()
    tool_sigs = Counter()
    sidechain_lines = 0
    parse_errors = []
    tool_errors = []          # (tool_name, snippet)
    api_errors = []           # snippets
    system_warns = []         # (level, snippet)
    nonzero_exits = []        # (command, code)
    reads = set()
    writes_without_read = []  # file paths Edited/Written w/o a prior Read
    last_user_ts = first_ts = None
    sessions = set()

    for d in rows:
        t = d.get("type", "?")
        by_type[t] += 1
        if t == "_parse_error":
            parse_errors.append(d)
            continue
        if d.get("sessionId"):
            sessions.add(d["sessionId"])
        if d.get("version"):
            versions[d["version"]] += 1
        if d.get("gitBranch"):
            branches[d["gitBranch"]] += 1
        if d.get("isSidechain"):
            sidechain_lines += 1
        if d.get("permissionMode"):
            perm_modes[d["permissionMode"]] += 1
        if d.get("attributionSkill"):
            attribution_skills[d["attributionSkill"]] += 1
        if d.get("isApiErrorMessage"):
            api_errors.append(_snippet(d))
        if first_ts is None and d.get("timestamp"):
            first_ts = d["timestamp"]
        if d.get("timestamp"):
            last_user_ts = d["timestamp"]
        if t == "system":
            lvl = d.get("level", "info")
            if lvl in ("warning", "error"):
                system_warns.append((lvl, str(d.get("content", ""))[:160]))

        # Top-level structured tool result (carries exit code).
        tr = d.get("toolUseResult")
        if isinstance(tr, dict):
            code = tr.get("code")
            cmd = str(tr.get("command", ""))
            # Only a Bash result carries a shell exit code alongside a command;
            # WebFetch/Agent results reuse `code` for an HTTP status (e.g. 200),
            # so require a non-empty command to avoid false positives.
            if isinstance(code, int) and code != 0 and cmd.strip():
                stdout = str(tr.get("stdout", "")) + str(tr.get("stderr", ""))
                if not _is_benign(cmd) and not _is_benign(stdout):
                    nonzero_exits.append((cmd[:100], code))

        m = d.get("message")
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type", "?")
            blocks[bt] += 1
            if bt == "tool_use":
                name = b.get("name", "?")
                tools[name] += 1
                inp = b.get("input", {})
                if name in LOOP_PRONE:
                    tool_sigs[_norm_tool_sig(name, inp)] += 1
                if name == "Read" and isinstance(inp, dict):
                    fp = inp.get("file_path")
                    if fp:
                        reads.add(fp)
                if name in ("Edit", "Write") and isinstance(inp, dict):
                    fp = inp.get("file_path")
                    if fp and fp not in reads and name == "Edit":
                        writes_without_read.append(fp)
            elif bt == "tool_result" and b.get("is_error"):
                snip = _snippet_block(b)
                if not _is_benign(snip):
                    tool_errors.append(snip)

    # ---- derive signals ----
    loops = {s: c for s, c in tool_sigs.items() if c >= LOOP_THRESHOLD}
    return {
        "sessions": sorted(sessions),
        "lines": sum(by_type.values()),
        "by_type": dict(by_type),
        "block_types": dict(blocks),
        "tools": dict(tools.most_common()),
        "versions": dict(versions),
        "branches": dict(branches),
        "permission_mode": perm_modes.most_common(1)[0][0] if perm_modes else None,
        "attribution_skill": attribution_skills.most_common(1)[0][0] if attribution_skills else None,
        "sidechain_lines": sidechain_lines,
        "first_timestamp": first_ts,
        "last_timestamp": last_user_ts,
        "signals": {
            "parse_errors": [{"line": p.get("_line"), "err": p.get("_err")} for p in parse_errors],
            "loops": dict(sorted(loops.items(), key=lambda kv: -kv[1])),
            "tool_errors": tool_errors[:25],
            "api_errors": api_errors[:25],
            "nonzero_exits": nonzero_exits[:25],
            "system_warnings": system_warns[:25],
            "edit_without_read": sorted(set(writes_without_read))[:25],
        },
    }


def _snippet(d: dict) -> str:
    m = d.get("message", {})
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                return str(b.get("text", ""))[:200]
    return str(c)[:200] if c else "<api error>"


def _snippet_block(b: dict) -> str:
    c = b.get("content")
    if isinstance(c, list):
        for part in c:
            if isinstance(part, dict) and "text" in part:
                return str(part["text"])[:200]
    return str(c)[:200]


def triage(a: dict, path: str | None = None) -> list[dict]:
    """Map detected reliability signals onto the triage matrix (severity-ranked).

    Returns normalized Finding dicts (legacy keys first, so report()/watch stay
    byte-stable; new dimension/confidence/fingerprint/provenance appended).
    """
    s = a["signals"]
    prov = build_provenance(a, path)

    def _f(category, severity, confidence, evidence, detail):
        return Finding(dimension="reliability", category=category, severity=severity,
                       confidence=confidence, evidence=evidence, detail=detail,
                       provenance=prov).to_dict()

    out = []
    if s["loops"]:
        worst = max(s["loops"].values())
        out.append(_f(
            "Infinite loop / red-herring",
            "high" if worst >= 6 else "medium",
            "high",
            f"{len(s['loops'])} tool-call signature(s) repeated "
            f"≥{LOOP_THRESHOLD}×; worst = {worst}×",
            s["loops"],
        ))
    fail_count = len(s["nonzero_exits"]) + len(s["tool_errors"])
    if fail_count:
        # Severity scales with clustering. A lone errored block an agent
        # recovered from (a missed Read, one transient timeout, a single grep
        # exit-1) is not a HIGH incident; a cluster is. ≥3 = sustained struggle.
        out.append(_f(
            "Tool / runtime failure",
            "high" if fail_count >= 3 else "medium",
            "high",
            f"{len(s['nonzero_exits'])} non-zero exit(s), "
            f"{len(s['tool_errors'])} errored tool_result block(s)",
            {"exits": s["nonzero_exits"][:5], "errors": s["tool_errors"][:5]},
        ))
    if s["api_errors"]:
        out.append(_f(
            "API / model error",
            "high",
            "high",
            f"{len(s['api_errors'])} assistant line(s) flagged isApiErrorMessage",
            s["api_errors"][:5],
        ))
    if s["edit_without_read"]:
        out.append(_f(
            "Tool-sequence anti-pattern",
            "medium",
            "medium",
            f"{len(s['edit_without_read'])} Edit(s) with no prior Read of the file",
            s["edit_without_read"][:5],
        ))
    if s["system_warnings"]:
        out.append(_f(
            "Environment / config warning",
            "low",
            "low",
            f"{len(s['system_warnings'])} system warning/error line(s)",
            s["system_warnings"][:5],
        ))
    if s["parse_errors"]:
        out.append(_f(
            "Corrupt / truncated transcript",
            "medium",
            "high",
            f"{len(s['parse_errors'])} unparseable JSONL line(s)",
            s["parse_errors"][:5],
        ))
    # Context-exhaustion heuristic: very large transcript dominated by tool I/O.
    if a["lines"] > 4000 and a["block_types"].get("tool_result", 0) > 1000:
        out.append(_f(
            "Possible context-window pressure",
            "low",
            "low",
            f"{a['lines']} lines, "
            f"{a['block_types'].get('tool_result', 0)} tool_result blocks "
            f"— verify with /context",
            {},
        ))
    return out


# --- analyzer registry --------------------------------------------------------
# Each dimension registers a callable(rows, analysis, path) -> list[Finding dict].
# security_scan / efficiency_scan register their dimensions on import, so the
# command layer can request --dimension security|efficiency|all without this
# module importing them eagerly. Bare invocation defaults to reliability only,
# which keeps existing output byte-stable.
DIMENSION_ORDER = ("reliability", "security", "efficiency")
ANALYZERS: dict = {}


def register_analyzer(dimension: str, fn) -> None:
    ANALYZERS[dimension] = fn


def _reliability_analyzer(rows, analysis, path=None):
    del rows  # reliability triage works off the analysis summary, not raw rows
    return triage(analysis, path)


register_analyzer("reliability", _reliability_analyzer)


def parse_dimensions(spec: str) -> list[str]:
    """Resolve a --dimension spec into an ordered, registered dimension list."""
    if not spec or spec.strip() == "all":
        return [d for d in DIMENSION_ORDER if d in ANALYZERS]
    want = [d.strip() for d in spec.split(",") if d.strip()]
    return [d for d in DIMENSION_ORDER if d in want and d in ANALYZERS]


def run_analyzers(dimensions, rows, analysis, path=None) -> list[dict]:
    findings = []
    for dim in dimensions:
        fn = ANALYZERS.get(dim)
        if fn:
            findings.extend(fn(rows, analysis, path))
    return findings


# Optional dimensions live in sibling modules, imported only when requested so a
# bare reliability run pulls in nothing extra (and stays byte-stable). We
# register HERE from the module's DIMENSION/scan attributes rather than letting
# the module import us back — that sidesteps the __main__ double-import trap when
# parse_transcript runs as a script.
_OPTIONAL_DIMENSION_MODULES = {"security": "security_scan", "efficiency": "efficiency_scan"}


def load_optional_analyzers(spec: str) -> None:
    """Lazily import + register the optional dimension modules named in ``spec``."""
    import importlib
    if not spec:
        return
    want = (list(_OPTIONAL_DIMENSION_MODULES)
            if spec.strip() == "all"
            else [d.strip() for d in spec.split(",")])
    for dim in want:
        modname = _OPTIONAL_DIMENSION_MODULES.get(dim)
        if not modname or dim in ANALYZERS:
            continue
        try:
            mod = importlib.import_module(modname)
            register_analyzer(getattr(mod, "DIMENSION", dim), mod.scan)
        except Exception as e:  # pragma: no cover - defensive
            print(f"WARNING: could not load analyzer {modname}: {e}", file=sys.stderr)


def report(path: str, a: dict, findings: list[dict]) -> str:
    ver = ", ".join(a["versions"]) or "unknown"
    lines = [
        "# mentat session forensics",
        f"transcript : {path}",
        f"session    : {', '.join(a['sessions']) or 'n/a'}",
        f"cc version : {ver}",
        f"lines      : {a['lines']}  |  inline sidechain lines: {a['sidechain_lines']} "
        f"(subagents externalized to <session>/subagents/ — see below)",
        f"tools      : {a['tools']}",
        "",
        f"## Triage ({len(findings)} finding(s))",
    ]
    if not findings:
        lines.append("No anomalies matched the triage matrix. Transcript looks healthy.")
    for f in sorted(findings, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["severity"]]):
        lines.append(f"\n### [{f['severity'].upper()}] {f['category']}")
        lines.append(f"FORENSIC EVIDENCE: {f['evidence']}")
        if f["detail"]:
            lines.append("```json")
            lines.append(json.dumps(f["detail"], indent=2)[:1200])
            lines.append("```")
    return "\n".join(lines)


def _subagent_report(all_subs: list, flagged: list) -> str:
    n = len(all_subs)
    if n == 0:
        return "\n## Subagents\nNo externalized subagent transcripts for this session."
    out = [f"\n## Subagents ({n} transcript(s); {len(flagged)} with findings)"]
    if not flagged:
        out.append("All subagent transcripts clean under the triage matrix.")
    for s in flagged:
        out.append(f"\n### [{s['agentType'] or 'unknown'}] {os.path.basename(s['path'])} "
                   f"({s['lines']} lines) — {s['description']}")
        for f in s["findings"]:
            out.append(f"  - [{f['severity'].upper()}] {f['category']}: {f['evidence']}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="mentat transcript forensic parser")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--session", help="Claude Code session-id")
    g.add_argument("--path", help="explicit path to a .jsonl transcript")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument("--dimension", default="reliability",
                    help="comma-separated analyzer dimensions: "
                         "reliability,security,efficiency,all (default: reliability)")
    args = ap.parse_args()

    path = args.path or locate(args.session)
    if not path or not os.path.exists(path):
        print(f"ERROR: transcript not found (session={args.session} path={args.path})",
              file=sys.stderr)
        print(f"  searched: {PROJECTS}/*/<session>.jsonl", file=sys.stderr)
        return 2

    load_optional_analyzers(args.dimension)
    dims = parse_dimensions(args.dimension)
    rows = load(path)
    a = analyze(rows)
    findings = run_analyzers(dims, rows, a, path)
    # Descend into externalized subagent transcripts — where swarm/orchestrator
    # workloads do their real work and where the coordinator view sees nothing.
    all_subs = locate_subagents(path, args.session)
    subagents = []
    for sub_path, atype, desc in all_subs:
        sub_rows = load(sub_path)
        sa = analyze(sub_rows)
        sf = run_analyzers(dims, sub_rows, sa, sub_path)
        if sf:
            subagents.append({"path": sub_path, "agentType": atype,
                              "description": desc, "lines": sa["lines"],
                              "findings": sf})
    if args.json:
        print(json.dumps({"transcript": path, "analysis": a, "triage": findings,
                          "subagents": subagents}, indent=2))
    else:
        print(report(path, a, findings))
        print(_subagent_report(all_subs, subagents))
    # Exit 1 if any high-severity finding (coordinator or subagent), so callers
    # can gate on it.
    sub_high = any(f["severity"] == "high"
                   for s in subagents for f in s["findings"])
    return 1 if any(f["severity"] == "high" for f in findings) or sub_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
