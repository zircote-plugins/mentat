#!/usr/bin/env python3
"""Golden-master regression tests for the keystone refactor.

These pin the invariant the Finding-schema refactor must preserve: the human
report, the exit code, and the watch_transcript feedback stream are byte-stable
against goldens captured from the pre-refactor code. The ``--json`` payload is
intentionally allowed to grow (new dimension/fingerprint/confidence/provenance
fields); its contract is checked structurally in test_schema.py, not here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
GOLD = os.path.join(HERE, "golden")
PARSE = "parse_transcript.py"
WATCH = "watch_transcript.py"

FIXTURES = ["clean", "secrets_and_dangerous", "injection",
            "inefficient", "corrupt", "no_usage"]


def _fixture(fx):
    # Relative path, run with cwd=SCRIPTS — matches how goldens were captured,
    # so the echoed transcript path stays machine-portable (no absolute paths
    # baked into committed goldens).
    return os.path.join("tests", "fixtures", f"{fx}.jsonl")


def _run(script, *args):
    p = subprocess.run([sys.executable, script, *args],
                       capture_output=True, text=True, cwd=SCRIPTS)
    return p.stdout + p.stderr, p.returncode


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class ReportRegression(unittest.TestCase):
    def test_report_byte_stable(self):
        for fx in FIXTURES:
            with self.subTest(fixture=fx):
                out, _ = _run(PARSE, "--path", _fixture(fx))
                self.assertEqual(out, _read(os.path.join(GOLD, f"{fx}.report.txt")),
                                 f"report output drifted for {fx}")

    def test_exit_code_stable(self):
        for fx in FIXTURES:
            with self.subTest(fixture=fx):
                _, ec = _run(PARSE, "--path", _fixture(fx))
                expected = int(_read(os.path.join(GOLD, f"{fx}.exit")).strip())
                self.assertEqual(ec, expected, f"exit code drifted for {fx}")


class WatchRegression(unittest.TestCase):
    def test_watch_byte_stable(self):
        for fx in FIXTURES:
            with self.subTest(fixture=fx):
                out, ec = _run(WATCH, "--path", _fixture(fx), "--once")
                self.assertEqual(out, _read(os.path.join(GOLD, f"{fx}.watch.txt")),
                                 f"watch output drifted for {fx}")
                expected = int(_read(os.path.join(GOLD, f"{fx}.watch.exit")).strip())
                self.assertEqual(ec, expected, f"watch exit drifted for {fx}")


if __name__ == "__main__":
    unittest.main()
