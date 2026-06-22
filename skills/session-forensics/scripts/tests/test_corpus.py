#!/usr/bin/env python3
"""Tests for the cross-session corpus and trend reporting (corpus.py)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import corpus as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
MULTI = os.path.join(FIX, "multisession")
GH_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


class CorpusBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, "corpus.jsonl")

    def _scan(self, *fixtures):
        recs = C.scan([os.path.join(FIX, f) for f in fixtures], recorded_at=1000.0)
        return C.append_records(recs, self.store)


class CrossSessionDedup(CorpusBase):
    def test_same_fingerprint_across_sessions(self):
        C.append_records(C.scan([os.path.join(MULTI, "session_a.jsonl")], 1.0), self.store)
        C.append_records(C.scan([os.path.join(MULTI, "session_b.jsonl")], 2.0), self.store)
        recs = C.read_corpus(self.store)
        tf = [r for r in recs if r["category"] == "Tool / runtime failure"]
        self.assertEqual(len(tf), 2)
        self.assertEqual(len({r["fingerprint"] for r in tf}), 1)  # same fingerprint
        self.assertEqual({r["session_id"] for r in tf}, {"multi-a", "multi-b"})

    def test_rescan_same_session_no_duplicates(self):
        p = os.path.join(MULTI, "session_a.jsonl")
        added1 = C.append_records(C.scan([p], 1.0), self.store)
        added2 = C.append_records(C.scan([p], 2.0), self.store)  # identical re-scan
        self.assertGreater(added1, 0)
        self.assertEqual(added2, 0)


class Redaction(CorpusBase):
    def test_no_raw_secret_in_store(self):
        self._scan("secrets_and_dangerous.jsonl")
        with open(self.store, encoding="utf-8") as fh:
            blob = fh.read()
        self.assertNotIn(GH_TOKEN, blob)
        self.assertNotIn(AWS_SECRET, blob)

    def test_no_detail_stored(self):
        self._scan("secrets_and_dangerous.jsonl")
        for r in C.read_corpus(self.store):
            self.assertNotIn("detail", r)


class Eviction(CorpusBase):
    def test_oldest_evicted_beyond_cap(self):
        os.environ["MENTAT_CORPUS_MAX"] = "3"
        try:
            recs = [{"fingerprint": f"fp{i}", "dimension": "reliability",
                     "category": "C", "severity": "low", "evidence": f"e{i}",
                     "session_id": f"s{i}", "transcript_path": f"/p{i}",
                     "recorded_at": float(i)} for i in range(6)]
            C.append_records(recs, self.store)
            stored = C.read_corpus(self.store)
            self.assertEqual(len(stored), 3)
            # newest kept (s3,s4,s5), oldest evicted
            self.assertEqual({r["session_id"] for r in stored}, {"s3", "s4", "s5"})
        finally:
            del os.environ["MENTAT_CORPUS_MAX"]


class Trends(CorpusBase):
    def test_trends_aggregation(self):
        C.append_records(C.scan([os.path.join(MULTI, "session_a.jsonl")], 1.0), self.store)
        C.append_records(C.scan([os.path.join(MULTI, "session_b.jsonl")], 2.0), self.store)
        t = C.trends(C.read_corpus(self.store))
        tf = [r for r in t["recurring"] if r["category"] == "Tool / runtime failure"]
        self.assertTrue(tf)
        self.assertEqual(tf[0]["distinct_sessions"], 2)

    def test_token_cost_leaders(self):
        self._scan("inefficient.jsonl")
        t = C.trends(C.read_corpus(self.store))
        self.assertTrue(t["token_cost_leaders"])
        self.assertEqual(t["token_cost_leaders"][0]["session_id"], "eff-001")
        self.assertGreater(t["token_cost_leaders"][0]["billed_input_tokens"], 0)


class StorePath(unittest.TestCase):
    def test_env_override(self):
        os.environ["MENTAT_CORPUS"] = "/tmp/custom-mentat-corpus.jsonl"
        try:
            self.assertEqual(C.corpus_path(), "/tmp/custom-mentat-corpus.jsonl")
        finally:
            del os.environ["MENTAT_CORPUS"]


if __name__ == "__main__":
    unittest.main()
