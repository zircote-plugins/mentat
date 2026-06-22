#!/usr/bin/env python3
"""mentat — normalized Finding schema shared across all analyzer dimensions.

Every detector (reliability triage, security_scan, efficiency_scan) emits the
same record shape so findings are uniform to render, gate on, and — crucially —
**deduplicate across sessions** via a stable ``fingerprint``. Stdlib-only.

A Finding's ``to_dict()`` deliberately keeps the legacy reliability keys
(``category``/``severity``/``evidence``/``detail``) first and in their original
order, then appends the new fields (``dimension``/``confidence``/``fingerprint``/
``provenance``). That keeps ``parse_transcript.report()`` and
``watch_transcript`` (which subscript those legacy keys) byte-stable while the
``--json`` payload gains fields additively.

Redaction is mandatory at the Finding boundary: ``redact()`` replaces any secret
with a stable, non-reversible ``<redacted:KIND:hash8>`` token. The same secret
always maps to the same token, so redaction does not break fingerprint stability
and a corpus can still count recurrences without ever storing the raw value.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

DIMENSIONS = ("reliability", "security", "efficiency")
SEVERITIES = ("high", "medium", "low")

# --- secret patterns (shared by security_scan; used here for redaction) -------
# (name, compiled-pattern, value-group). value-group 0 = mask whole match;
# a positive int masks only that capture group (so "secret=" context survives).
SECRET_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    ("github-pat", re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), 0),
    ("github-pat-fine", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"), 0),
    ("github-token", re.compile(r"\bgh[osu]_[A-Za-z0-9]{36}\b"), 0),
    ("aws-akid", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 0),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"), 0),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 0),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}\b"), 0),
    # generic "<identifier-containing-keyword> = value" — mask only the value
    # (group 2). The identifier may carry a prefix/suffix (AWS_SECRET_ACCESS_KEY),
    # so the keyword is embedded in a wider identifier match, not anchored alone.
    ("generic-secret", re.compile(
        r"(?i)\b([A-Za-z0-9_]*(?:secret|token|passwd|password|api[_-]?key|"
        r"access[_-]?key|client[_-]?secret|auth)[A-Za-z0-9_]*)"
        r"[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9/+_\-\.]{12,})"), 2),
]


def _mask(kind: str, secret: str) -> str:
    """Stable, non-reversible placeholder for a detected secret."""
    h = hashlib.sha256(secret.encode("utf-8", "replace")).hexdigest()[:8]
    return f"<redacted:{kind}:{h}>"


def redact(text: str | None) -> str:
    """Replace every recognized secret in ``text`` with a stable placeholder.

    Idempotent and order-independent enough for evidence strings: the same
    secret always yields the same token, so redacted output is deterministic.
    """
    if not text:
        return text or ""
    out = text
    for kind, pat, grp in SECRET_PATTERNS:
        if grp == 0:
            out = pat.sub(lambda m, k=kind: _mask(k, m.group(0)), out)
        else:
            def _repl(m, k=kind, g=grp):
                return m.group(0).replace(m.group(g), _mask(k, m.group(g)))
            out = pat.sub(_repl, out)
    return out


def redact_obj(obj):
    """Recursively redact every string leaf (and dict key) in a structure.

    ``detail`` is arbitrary nested JSON (loop signatures, command strings, error
    snippets) and reaches both ``--json`` and ``report()`` output, so it must be
    redacted at the Finding boundary just like ``evidence``. Redacting a value
    that was not actually a secret is harmless over-redaction; missing one is not.
    """
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {redact(k) if isinstance(k, str) else k: redact_obj(v)
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj


def contains_secret(text: str | None) -> list[str]:
    """Return the kinds of secret detected in ``text`` (empty if none)."""
    if not text:
        return []
    kinds = []
    for kind, pat, _ in SECRET_PATTERNS:
        if pat.search(text):
            kinds.append(kind)
    return kinds


def _normalize_evidence(evidence: str) -> str:
    """Collapse volatile counts so the same logical finding dedups across runs.

    Evidence strings embed counts ("3 errored block(s)") that differ session to
    session; stripping digits makes the fingerprint stable for cross-session
    aggregation. Redact first so a secret never reaches the hash input.
    """
    s = redact(evidence or "")
    s = re.sub(r"\d+", "#", s)
    return s.strip()


def make_fingerprint(dimension: str, category: str, evidence: str) -> str:
    """Stable dedup key: hash(dimension + category + normalized_evidence)."""
    norm = _normalize_evidence(evidence)
    return hashlib.sha256(f"{dimension}|{category}|{norm}".encode("utf-8")).hexdigest()[:16]


@dataclass
class Finding:
    """One normalized finding from any analyzer dimension."""

    dimension: str
    category: str
    severity: str
    evidence: str
    detail: object = None
    confidence: str = "high"
    provenance: dict = field(default_factory=dict)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"unknown dimension: {self.dimension!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        # Evidence is operator-facing AND hashed — redact before anything else.
        self.evidence = redact(self.evidence)
        # detail reaches --json and report() output too; redact every string leaf
        # so a secret embedded in a command/error snippet never surfaces raw.
        self.detail = redact_obj(self.detail)
        if not self.fingerprint:
            self.fingerprint = make_fingerprint(self.dimension, self.category, self.evidence)

    def to_dict(self) -> dict:
        """Legacy keys first (byte-stable for report/watch), new keys appended."""
        return {
            "category": self.category,
            "severity": self.severity,
            "evidence": self.evidence,
            "detail": self.detail,
            "dimension": self.dimension,
            "confidence": self.confidence,
            "fingerprint": self.fingerprint,
            "provenance": self.provenance,
        }


def build_provenance(analysis: dict, path: str | None = None,
                     first_seen_line: int | None = None) -> dict:
    """Assemble the non-volatile provenance block from an analysis dict.

    ``fingerprint`` deliberately excludes provenance so the same finding from
    two sessions collides; provenance records *where* each instance came from.
    """
    sessions = analysis.get("sessions") or []
    versions = list(analysis.get("versions") or {})
    branches = list(analysis.get("branches") or {})
    return {
        "session_id": sessions[0] if sessions else None,
        "transcript_path": path,
        "cc_version": versions[0] if versions else None,
        "gitBranch": branches[0] if branches else None,
        "attributionSkill": analysis.get("attribution_skill"),
        "permissionMode": analysis.get("permission_mode"),
        "first_seen_line": first_seen_line,
        "timestamp": analysis.get("last_timestamp"),
    }
