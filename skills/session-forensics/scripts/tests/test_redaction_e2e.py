#!/usr/bin/env python3
"""End-to-end leak regression: a secret embedded in a command/snippet must never
reach output via ANY dimension's `detail` field (reviewer findings 2/3/7/10)."""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import efficiency_scan as E  # noqa: E402
import parse_transcript as P  # noqa: E402

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def _tokened_failing_rows():
    cmd = f"curl -H 'Authorization: {TOKEN}' https://api.example.com"
    return [
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": cmd}}]}},
        {"toolUseResult": {"command": cmd, "code": 22, "stdout": "", "stderr": "401"},
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "x", "is_error": True,
              "content": f"failed with {TOKEN}"}]}},
    ]


def _tokened_repeated_success_rows():
    cmd = f"curl -H 'Authorization: {TOKEN}' https://api.example.com"
    rows = []
    for i in range(3):
        rows.append({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"c{i}", "name": "Bash", "input": {"command": cmd}}]}})
        rows.append({"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"c{i}", "is_error": False, "content": "ok"}]}})
    return rows


class NoLeakInReliabilityDetail(unittest.TestCase):
    def test_failing_command_token_redacted(self):
        rows = _tokened_failing_rows()
        findings = P.run_analyzers(["reliability"], rows, P.analyze(rows), None)
        self.assertTrue(findings)
        self.assertNotIn(TOKEN, json.dumps(findings))


class NoLeakInEfficiencyDetail(unittest.TestCase):
    def test_repeated_command_token_redacted(self):
        rows = _tokened_repeated_success_rows()
        findings = E.scan(rows, P.analyze(rows), None)
        cats = {f["category"] for f in findings}
        self.assertIn("Repeated successful commands", cats)
        self.assertNotIn(TOKEN, json.dumps(findings))


if __name__ == "__main__":
    unittest.main()
