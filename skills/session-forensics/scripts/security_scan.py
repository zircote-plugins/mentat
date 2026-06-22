#!/usr/bin/env python3
"""mentat — security analysis pass over a Claude Code transcript.

Registers the ``security`` dimension. Detectors run over the same parsed rows as
the reliability triage and emit normalized Findings (findings.Finding), so the
output renders, gates, and dedups identically. Stdlib-only.

What it looks for (each with a documented false-positive guard — see
``references/security-matrix.md``):

  * Secret exposure   — credentials in tool **inputs and outputs**. The raw
    secret is NEVER emitted; evidence/detail are redacted at the Finding
    boundary. Placeholder/env-var values are filtered out.
  * Dangerous command — rm -rf, curl|sh / wget|sh, git force-push, chmod 777,
    --no-verify, and writes to sensitive paths (~/.ssh, .env, credentials).
  * Prompt injection  — override phrases inside **tool_result** content (data the
    model ingested), never the assistant's own prose.
  * Possible exfiltration — a command shipping data to an external host
    (curl/wget --data/-T/-F) especially alongside sensitive-file access.

CI gating: exits non-zero when a high-severity security finding is present.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import findings as F  # noqa: E402
from findings import Finding, build_provenance, redact  # noqa: E402

DIMENSION = "security"

# --- dangerous command signatures: (pattern, label, severity) ----------------
_DANGEROUS = [
    (re.compile(r"\brm\s+-[A-Za-z]*r[A-Za-z]*f|\brm\s+-[A-Za-z]*f[A-Za-z]*r"), "rm -rf", "high"),
    (re.compile(r"\bcurl\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b"), "curl|sh remote exec", "high"),
    (re.compile(r"\bwget\b[^|]*\|\s*(?:sudo\s+)?(?:ba)?sh\b"), "wget|sh remote exec", "high"),
    (re.compile(r"\bgit\s+push\b[^\n]*(?:--force\b|--force-with-lease\b|\s-f\b)"), "git force-push", "high"),
    (re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b"), "chmod 777", "medium"),
    (re.compile(r"--no-verify\b"), "--no-verify (bypass hooks)", "medium"),
]
# writes to sensitive paths via redirection / tee
_SENSITIVE_WRITE = re.compile(
    r"(?:>>?|\btee\b)\s*\S*(?:\.ssh/|id_rsa|\.env\b|\.aws/credentials|\.netrc\b)")
# sensitive paths referenced anywhere (for exfil correlation / Write|Edit targets)
_SENSITIVE_PATH = re.compile(
    r"(?:\.ssh/|\bid_rsa\b|(?:^|/)\.env(?:\.[A-Za-z]+)?\b|\.aws/credentials\b|"
    r"\.netrc\b|credentials\.json\b)")

# --- prompt-injection phrases (scanned ONLY in tool_result content) ----------
_INJECTION = [
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:your\s+|the\s+)?previous\s+instructions"),
    re.compile(r"(?i)disregard\s+(?:your\s+|the\s+|all\s+)?(?:system\s+prompt|previous|prior|instructions)"),
    re.compile(r"(?i)ignore\s+(?:the\s+)?(?:above|system\s+prompt)\b"),
    re.compile(r"(?i)forget\s+(?:everything|all\s+(?:previous|prior))"),
    re.compile(r"(?i)new\s+instructions\s*:"),
    re.compile(r"(?i)you\s+are\s+now\s+(?:a|an|in\s+developer\s+mode)\b"),
]

# --- exfiltration: a command POSTing/uploading data to an external host -------
_EXTERNAL_UPLOAD = re.compile(
    r"\b(?:curl|wget)\b[^\n]*?(?:--data\b|--data-binary\b|-d\b|--upload-file\b|-T\b|-F\b|--form\b)")
_EXTERNAL_URL = re.compile(
    r"https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])[A-Za-z0-9.\-]+")

# values that look secret-ish but are not (placeholders / env refs / low entropy)
_PLACEHOLDER = re.compile(
    r"(?i)^(?:your[_-]|example|placeholder|dummy|changeme|replace[_-]?me|test|"
    r"xxx+|redacted|\.\.\.|<.*>|\$\{?[A-Za-z_]+\}?)")


_VERSION = re.compile(r"^\d+(?:\.\d+)+$")


def _is_placeholder(val: str) -> bool:
    if not val or _PLACEHOLDER.search(val):
        return True
    if val.startswith("$"):
        return True
    if _VERSION.match(val):           # "1.2.3" — a version, not a secret
        return True
    # NOTE: deliberately no "looks like a path" filter — real secrets (e.g. an
    # AWS secret key) contain "/", and over-detecting a path is the safe
    # direction; under-detecting a secret is not.
    return len(set(val)) <= 4         # e.g. "aaaaaaaaaaaa", "xxxxxxxxxxxx"


def _real_secrets(text: str) -> list[tuple[str, str]]:
    """(kind, value) for each real secret in ``text`` (placeholders filtered)."""
    hits = []
    for kind, pat, grp in F.SECRET_PATTERNS:
        for m in pat.finditer(text or ""):
            val = m.group(grp) if grp else m.group(0)
            if _is_placeholder(val):
                continue
            hits.append((kind, val))
    return hits


def _block_text(block: dict) -> str:
    """Flatten a tool_result block's content to text."""
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for part in c:
            if isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(c) if c is not None else ""


class _Acc:
    """Accumulator for one category: dedups by content ``key``, caps detail.

    Dedup is content-based (not line-based) so a command/secret that appears in
    both the ``tool_use`` input and the mirrored ``toolUseResult`` is counted
    once.
    """

    def __init__(self):
        self.seen = set()
        self.examples = []
        self.kinds = set()
        self.max_sev = "low"

    def add(self, line, key, snippet, kind=None, sev="medium"):
        if key in self.seen:
            return
        self.seen.add(key)
        if kind:
            self.kinds.add(kind)
        if {"high": 3, "medium": 2, "low": 1}[sev] > {"high": 3, "medium": 2, "low": 1}[self.max_sev]:
            self.max_sev = sev
        if len(self.examples) < 5:
            self.examples.append({"line": line, "kind": kind or key,
                                  "snippet": redact(snippet)[:160]})

    @property
    def count(self):
        return len(self.seen)


def _scan_command(cmd: str, line: int, dang: _Acc, exfil: _Acc):
    c = cmd.strip()
    for pat, label, sev in _DANGEROUS:
        if pat.search(cmd):
            dang.add(line, f"{label}|{c}", cmd, kind=label, sev=sev)
    if _SENSITIVE_WRITE.search(cmd):
        dang.add(line, f"write-sensitive|{c}", cmd, kind="write to sensitive path", sev="high")
    if _EXTERNAL_UPLOAD.search(cmd) and _EXTERNAL_URL.search(cmd):
        sev = "high" if _SENSITIVE_PATH.search(cmd) else "medium"
        exfil.add(line, f"exfil|{c}", cmd, kind="external data upload", sev=sev)


def scan(rows: list[dict], analysis: dict, path: str | None = None) -> list[dict]:
    """Run the security detectors and return normalized Finding dicts."""
    from parse_transcript import iter_content_blocks

    prov = build_provenance(analysis, path)
    secrets, dang, inject, exfil = _Acc(), _Acc(), _Acc(), _Acc()

    for line, _role, block in iter_content_blocks(rows):
        bt = block.get("type")
        if bt == "tool_use":
            name = block.get("name", "")
            inp = block.get("input", {})
            if isinstance(inp, dict):
                if name == "Bash":
                    cmd = str(inp.get("command", ""))
                    _scan_command(cmd, line, dang, exfil)
                if name in ("Write", "Edit"):
                    fp = str(inp.get("file_path", ""))
                    if _SENSITIVE_PATH.search(fp):
                        dang.add(line, f"write-sensitive|{fp}", fp,
                                 kind="write to sensitive path", sev="high")
                # secrets in any string-valued input field
                for v in inp.values():
                    if isinstance(v, str):
                        for k, val in _real_secrets(v):
                            secrets.add(line, redact(val), v, kind=k, sev="high")
        elif bt == "tool_result":
            text = _block_text(block)
            for k, val in _real_secrets(text):
                secrets.add(line, redact(val), text, kind=k, sev="high")
            for pat in _INJECTION:
                if pat.search(text):
                    inject.add(line, f"injection|{line}", text,
                               kind="injection phrase", sev="high")
                    break

    # top-level toolUseResult (carries command + captured stdout/stderr)
    for i, d in enumerate(rows, 1):
        tr = d.get("toolUseResult")
        if not isinstance(tr, dict):
            continue
        cmd = str(tr.get("command", ""))
        if cmd:
            _scan_command(cmd, i, dang, exfil)
            for k, val in _real_secrets(cmd):
                secrets.add(i, redact(val), cmd, kind=k, sev="high")
        out = str(tr.get("stdout", "")) + "\n" + str(tr.get("stderr", ""))
        for k, val in _real_secrets(out):
            secrets.add(i, redact(val), out, kind=k, sev="high")

    perm = analysis.get("permission_mode")
    findings = []

    def emit(category, acc, severity, confidence, evidence, extra_detail=None):
        detail = {"examples": acc.examples}
        if acc.kinds:
            detail["kinds"] = sorted(acc.kinds)
        if perm:
            detail["permissionMode"] = perm
        if extra_detail:
            detail.update(extra_detail)
        findings.append(Finding(dimension=DIMENSION, category=category, severity=severity,
                                confidence=confidence, evidence=evidence, detail=detail,
                                provenance=prov).to_dict())

    if secrets.count:
        conf = "high" if any(k != "generic-secret" for k in secrets.kinds) else "medium"
        emit("Secret exposure", secrets, "high", conf,
             f"{secrets.count} secret(s) exposed in tool input/output "
             f"(kinds: {', '.join(sorted(secrets.kinds))})")
    if dang.count:
        emit("Dangerous command", dang, dang.max_sev, "high",
             f"{dang.count} dangerous command(s): {', '.join(sorted(dang.kinds))}")
    if inject.count:
        emit("Prompt injection in tool output", inject, "high", "medium",
             f"{inject.count} prompt-injection signature(s) in tool_result content")
    if exfil.count:
        emit("Possible exfiltration", exfil, exfil.max_sev, "medium",
             f"{exfil.count} command(s) shipping data to an external host")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="mentat security analysis pass")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--session")
    g.add_argument("--path")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from parse_transcript import analyze, load, locate, report

    path = args.path or (locate(args.session) if args.session else None)
    if not path or not os.path.exists(path):
        print(f"ERROR: transcript not found (session={args.session} path={args.path})",
              file=sys.stderr)
        return 2
    rows = load(path)
    a = analyze(rows)
    findings = scan(rows, a, path)
    if args.json:
        print(json.dumps({"transcript": path, "dimension": DIMENSION,
                          "findings": findings}, indent=2))
    else:
        print(report(path, a, findings))
    return 1 if any(f["severity"] == "high" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
