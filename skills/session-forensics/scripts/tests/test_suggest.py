#!/usr/bin/env python3
"""Tests for the improvement feedback loop (suggest.py)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import suggest as SG  # noqa: E402


def _rec(fp, cat, dim, sev, sess):
    return {"fingerprint": fp, "category": cat, "dimension": dim,
            "severity": sev, "session_id": sess, "transcript_path": f"/{sess}",
            "evidence": "e"}


def _recurring_records():
    return [
        _rec("d1", "Dangerous command", "security", "high", "s1"),
        _rec("d1", "Dangerous command", "security", "high", "s2"),
        _rec("r1", "Redundant file re-reads", "efficiency", "medium", "s1"),
        _rec("r1", "Redundant file re-reads", "efficiency", "medium", "s3"),
        _rec("a1", "Tool-sequence anti-pattern", "reliability", "medium", "s1"),
    ]


class SuggestionGeneration(unittest.TestCase):
    def setUp(self):
        self.doc = SG.suggest(_recurring_records(), min_sessions=2)
        self.by_cat = {s["category"]: s for s in self.doc["suggestions"]}

    def test_is_proposal_round_nothing_written(self):
        self.assertEqual(self.doc["round"], "proposal")
        self.assertEqual(self.doc["default_applier"], "top-level")

    def test_recurring_categories_suggested(self):
        self.assertIn("Dangerous command", self.by_cat)
        self.assertIn("Redundant file re-reads", self.by_cat)

    def test_one_off_excluded(self):
        # anti-pattern appears in only 1 session -> not a pattern.
        self.assertNotIn("Tool-sequence anti-pattern", self.by_cat)

    def test_artifact_kinds(self):
        self.assertEqual(self.by_cat["Dangerous command"]["kind"], "settings")
        self.assertEqual(self.by_cat["Redundant file re-reads"]["kind"], "claude-md")

    def test_settings_artifact_is_deny_rules(self):
        art = self.by_cat["Dangerous command"]["proposed_artifact"]
        self.assertIn("deny", art["permissions"])

    def test_all_authority_is_propose(self):
        for s in self.doc["suggestions"]:
            self.assertEqual(s["requested_authority"], "propose")


class MinSessionsThreshold(unittest.TestCase):
    def test_higher_threshold_excludes(self):
        doc = SG.suggest(_recurring_records(), min_sessions=3)
        # nothing recurs across 3 sessions in the fixture set
        self.assertEqual(doc["suggestions"], [])

    def test_empty_corpus_no_suggestions(self):
        doc = SG.suggest([], min_sessions=2)
        self.assertEqual(doc["suggestions"], [])


if __name__ == "__main__":
    unittest.main()
