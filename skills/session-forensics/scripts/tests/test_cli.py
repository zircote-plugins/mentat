#!/usr/bin/env python3
"""In-process CLI entrypoint tests — exercise each module's main() for exit-code
behavior and coverage of the argparse wrappers (subprocess runs aren't tracked
by coverage)."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corpus as C  # noqa: E402
import efficiency_scan as EFF  # noqa: E402
import parse_transcript as P  # noqa: E402
import security_scan as SEC  # noqa: E402
import suggest as SG  # noqa: E402
import watch_transcript as W  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
CLEAN = os.path.join(FIX, "clean.jsonl")
SECRETS = os.path.join(FIX, "secrets_and_dangerous.jsonl")
INEFF = os.path.join(FIX, "inefficient.jsonl")
MISSING = os.path.join(FIX, "does-not-exist.jsonl")
GH = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def _argv(main, argv):
    """Run a no-arg main() with patched sys.argv; return (stdout, rc)."""
    old = sys.argv
    sys.argv = ["prog", *argv]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = main()
    finally:
        sys.argv = old
    return buf.getvalue(), rc


def _argp(main, argv):
    """Run a main(argv) that accepts an argv list; return (stdout, rc)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return buf.getvalue(), rc


class ParseTranscriptCLI(unittest.TestCase):
    def test_default_runs(self):
        out, rc = _argv(P.main, ["--path", CLEAN])
        self.assertIn("mentat session forensics", out)
        self.assertEqual(rc, 0)

    def test_dimension_all_json(self):
        out, _ = _argv(P.main, ["--path", SECRETS, "--dimension", "all", "--json"])
        self.assertIn('"dimension": "security"', out)

    def test_missing_path_exit_2(self):
        _, rc = _argv(P.main, ["--path", MISSING])
        self.assertEqual(rc, 2)


class SecurityCLI(unittest.TestCase):
    def test_high_severity_exit_1(self):
        _, rc = _argv(SEC.main, ["--path", SECRETS])
        self.assertEqual(rc, 1)

    def test_json_no_raw_secret(self):
        out, _ = _argv(SEC.main, ["--path", SECRETS, "--json"])
        self.assertNotIn(GH, out)

    def test_missing_path_exit_2(self):
        _, rc = _argv(SEC.main, ["--path", MISSING])
        self.assertEqual(rc, 2)


class EfficiencyCLI(unittest.TestCase):
    def test_runs_exit_0(self):
        _, rc = _argv(EFF.main, ["--path", INEFF])
        self.assertEqual(rc, 0)

    def test_price_table(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write('{"input_per_mtok": 3.0, "output_per_mtok": 15.0}')
            tbl = fh.name
        try:
            out, _ = _argv(EFF.main, ["--path", INEFF, "--json", "--price-table", tbl])
            self.assertIn("estimated_usd", out)
        finally:
            os.unlink(tbl)


class WatchCLI(unittest.TestCase):
    def test_once_security_exit_1(self):
        _, rc = _argv(W.main, ["--path", SECRETS, "--once", "--dimension", "security"])
        self.assertEqual(rc, 1)

    def test_once_default_exit_0(self):
        _, rc = _argv(W.main, ["--path", SECRETS, "--once"])
        self.assertEqual(rc, 0)

    def test_missing_path_exit_2(self):
        _, rc = _argv(W.main, ["--path", MISSING, "--once"])
        self.assertEqual(rc, 2)


class CorpusCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, "corpus.jsonl")

    def test_scan_then_trends(self):
        _, rc = _argp(C.main, ["scan", "--path", INEFF, "--corpus", self.store])
        self.assertEqual(rc, 0)
        out, rc2 = _argp(C.main, ["trends", "--corpus", self.store])
        self.assertEqual(rc2, 0)
        self.assertIn("corpus trends", out)

    def test_trends_json(self):
        _argp(C.main, ["scan", "--path", INEFF, "--corpus", self.store])
        out, rc = _argp(C.main, ["trends", "--json", "--corpus", self.store])
        self.assertEqual(rc, 0)
        self.assertIn('"total_records"', out)


class SuggestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, "corpus.jsonl")

    def test_empty_corpus_exit_2(self):
        _, rc = _argp(SG.main, ["--corpus", self.store])
        self.assertEqual(rc, 2)

    def test_with_recurring_records(self):
        recs = [{"fingerprint": "d1", "dimension": "security", "category": "Dangerous command",
                 "severity": "high", "evidence": "e", "session_id": s, "transcript_path": f"/{s}"}
                for s in ("s1", "s2")]
        C.append_records(recs, self.store)
        out, rc = _argp(SG.main, ["--corpus", self.store])
        self.assertEqual(rc, 0)
        self.assertIn("proposal", out)


if __name__ == "__main__":
    unittest.main()
