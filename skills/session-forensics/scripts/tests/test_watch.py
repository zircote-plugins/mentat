#!/usr/bin/env python3
"""Tests for watch_transcript --dimension routing and actionable-exit logic."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
WATCH = "watch_transcript.py"
SECRETS = "tests/fixtures/secrets_and_dangerous.jsonl"
GH_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _run(*args):
    p = subprocess.run([sys.executable, WATCH, *args],
                       capture_output=True, text=True, cwd=SCRIPTS)
    return p.stdout, p.returncode


class DimensionRouting(unittest.TestCase):
    def test_security_dimension_emits_and_exits_nonzero(self):
        out, ec = _run("--path", SECRETS, "--once", "--dimension", "security")
        self.assertIn("Secret exposure", out)
        self.assertIn("Dangerous command", out)
        self.assertEqual(ec, 1)  # high-severity security finding is actionable

    def test_default_dimension_silent_on_secrets(self):
        # Reliability-only default finds nothing in this fixture -> exit 0.
        out, ec = _run("--path", SECRETS, "--once")
        self.assertNotIn('"event": "issue"', out)
        self.assertEqual(ec, 0)

    def test_no_raw_secret_in_watch_output(self):
        out, _ = _run("--path", SECRETS, "--once", "--dimension", "all")
        self.assertNotIn(GH_TOKEN, out)
        self.assertNotIn(AWS_SECRET, out)


if __name__ == "__main__":
    unittest.main()
