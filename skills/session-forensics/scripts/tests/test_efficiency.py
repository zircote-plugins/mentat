#!/usr/bin/env python3
"""Tests for the efficiency & cost analysis pass (efficiency_scan.py)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import efficiency_scan as E  # noqa: E402
import parse_transcript as P  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")


def _scan(name):
    rows = P.load(os.path.join(FIX, name))
    return E.scan(rows, P.analyze(rows), os.path.join(FIX, name)), rows


def _cats(findings):
    return {f["category"]: f for f in findings}


class TokenAccounting(unittest.TestCase):
    def test_token_sums_match_independent_count(self):
        findings, rows = _scan("inefficient.jsonl")
        want = {"input_tokens": 0, "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
        for d in rows:
            u = (d.get("message") or {}).get("usage")
            if isinstance(u, dict):
                for k in want:
                    want[k] += u.get(k, 0)
        detail = _cats(findings)["Token spend"]["detail"]
        for k in want:
            self.assertEqual(detail[k], want[k], f"{k} mismatch")

    def test_token_spend_is_informational_low(self):
        findings, _ = _scan("inefficient.jsonl")
        self.assertEqual(_cats(findings)["Token spend"]["severity"], "low")


class WasteDetectors(unittest.TestCase):
    def setUp(self):
        self.cats = _cats(_scan("inefficient.jsonl")[0])

    def test_redundant_reads(self):
        self.assertIn("Redundant file re-reads", self.cats)
        self.assertIn("worst = 3×", self.cats["Redundant file re-reads"]["evidence"])

    def test_repeated_successful_commands(self):
        self.assertIn("Repeated successful commands", self.cats)

    def test_expensive_uncached_turns(self):
        self.assertIn("Expensive uncached turns", self.cats)

    def test_token_context_pressure(self):
        self.assertIn("Context-window pressure (tokens)", self.cats)


class FailedRepeatsNotCountedAsWaste(unittest.TestCase):
    def test_only_successful_repeats_flagged(self):
        # Same command repeated but always FAILING -> reliability's concern,
        # not an efficiency "repeated successful command".
        rows = []
        for i in range(4):
            rows.append({"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"c{i}", "name": "Bash",
                 "input": {"command": "flaky --run"}}]}})
            rows.append({"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"c{i}", "is_error": True,
                 "content": "boom"}]}})
        cats = _cats(E.scan(rows, P.analyze(rows), None))
        self.assertNotIn("Repeated successful commands", cats)


class CleanIsQuiet(unittest.TestCase):
    def test_no_problem_findings_on_clean(self):
        findings, _ = _scan("clean.jsonl")
        problems = [f for f in findings if f["severity"] in ("medium", "high")]
        self.assertEqual(problems, [])


class Oversized(unittest.TestCase):
    def test_large_tool_result_flagged(self):
        big = "x" * 60_000
        rows = [
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "r", "name": "Read", "input": {"file_path": "/big"}}]}},
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "r", "is_error": False, "content": big}]}},
        ]
        cats = _cats(E.scan(rows, P.analyze(rows), None))
        self.assertIn("Oversized tool_result", cats)


class MissingUsageDegrades(unittest.TestCase):
    def test_no_usage_no_token_finding(self):
        findings, _ = _scan("no_usage.jsonl")
        self.assertNotIn("Token spend", _cats(findings))


class PriceTable(unittest.TestCase):
    def test_optional_usd_estimate(self):
        rows = P.load(os.path.join(FIX, "inefficient.jsonl"))
        table = {"input_per_mtok": 3.0, "output_per_mtok": 15.0,
                 "cache_read_per_mtok": 0.3, "cache_write_per_mtok": 3.75}
        findings = E.scan(rows, P.analyze(rows), None, price_table=table)
        detail = _cats(findings)["Token spend"]["detail"]
        self.assertIn("estimated_usd", detail)
        self.assertGreater(detail["estimated_usd"], 0)


if __name__ == "__main__":
    unittest.main()
