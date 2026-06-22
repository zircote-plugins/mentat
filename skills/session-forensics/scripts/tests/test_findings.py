#!/usr/bin/env python3
"""Unit tests for the normalized Finding schema, redaction, and fingerprints."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import findings as F  # noqa: E402

GH_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS_LINE = f"AWS_SECRET_ACCESS_KEY={AWS_SECRET}"


class Redaction(unittest.TestCase):
    def test_github_token_redacted(self):
        out = F.redact(f"export GITHUB_TOKEN={GH_TOKEN}")
        self.assertNotIn(GH_TOKEN, out)
        self.assertIn("<redacted:", out)

    def test_aws_secret_redacted_keeps_key_name(self):
        out = F.redact(AWS_LINE)
        self.assertNotIn(AWS_SECRET, out)
        self.assertIn("AWS_SECRET_ACCESS_KEY", out)  # context preserved

    def test_same_secret_same_token(self):
        # Stable mask → corpus can count recurrences without storing the secret.
        self.assertEqual(F.redact(GH_TOKEN), F.redact(GH_TOKEN))

    def test_uuid_not_redacted(self):
        uuid = "0aff9e18-8092-4ffd-915a-7f9f3d7f67cb"
        self.assertEqual(F.redact(f"session {uuid}"), f"session {uuid}")
        self.assertEqual(F.contains_secret(uuid), [])

    def test_git_sha_not_redacted(self):
        sha = "dbd1f30ac1b2c3d4e5f60718293a4b5c6d7e8f90"
        self.assertEqual(F.redact(f"commit {sha}"), f"commit {sha}")

    def test_empty_input(self):
        self.assertEqual(F.redact(None), "")
        self.assertEqual(F.redact(""), "")
        self.assertEqual(F.contains_secret(None), [])


class RedactObj(unittest.TestCase):
    def test_redacts_nested_string_leaves(self):
        obj = {"cmd": f"curl {GH_TOKEN}", "list": [f"x {GH_TOKEN}", 1],
               "nested": {"k": f"{AWS_LINE}"}}
        out = F.redact_obj(obj)
        blob = repr(out)
        self.assertNotIn(GH_TOKEN, blob)
        self.assertNotIn(AWS_SECRET, blob)

    def test_redacts_dict_keys(self):
        out = F.redact_obj({f"Bash:command=curl {GH_TOKEN}": 3})
        self.assertNotIn(GH_TOKEN, repr(out))

    def test_non_strings_passthrough(self):
        self.assertEqual(F.redact_obj({"n": 5, "b": True, "x": None}),
                         {"n": 5, "b": True, "x": None})


class FindingDetailRedaction(unittest.TestCase):
    def test_detail_redacted_at_boundary(self):
        fd = F.Finding(dimension="reliability", category="Tool / runtime failure",
                       severity="high", evidence="1 errored",
                       detail={"errors": [f"failed: {GH_TOKEN}"]})
        self.assertNotIn(GH_TOKEN, repr(fd.to_dict()["detail"]))


class Fingerprint(unittest.TestCase):
    def test_stable_across_volatile_counts(self):
        a = F.make_fingerprint("reliability", "Tool / runtime failure",
                               "1 non-zero exit(s), 1 errored tool_result block(s)")
        b = F.make_fingerprint("reliability", "Tool / runtime failure",
                               "7 non-zero exit(s), 3 errored tool_result block(s)")
        self.assertEqual(a, b)

    def test_dimension_changes_fingerprint(self):
        a = F.make_fingerprint("reliability", "X", "same evidence")
        b = F.make_fingerprint("security", "X", "same evidence")
        self.assertNotEqual(a, b)

    def test_category_changes_fingerprint(self):
        a = F.make_fingerprint("security", "A", "same")
        b = F.make_fingerprint("security", "B", "same")
        self.assertNotEqual(a, b)

    def test_secret_never_in_fingerprint_input(self):
        # Even if evidence carries a secret, the fingerprint of the redacted
        # form must equal that of an already-redacted form.
        raw = F.make_fingerprint("security", "Secret exposure", f"token {GH_TOKEN}")
        red = F.make_fingerprint("security", "Secret exposure", f"token {F.redact(GH_TOKEN)}")
        self.assertEqual(raw, red)


class FindingDataclass(unittest.TestCase):
    def test_legacy_key_order_first(self):
        d = F.Finding(dimension="reliability", category="C", severity="medium",
                      evidence="e", detail={"x": 1}).to_dict()
        self.assertEqual(list(d)[:4], ["category", "severity", "evidence", "detail"])
        self.assertEqual(list(d)[4:],
                         ["dimension", "confidence", "fingerprint", "provenance"])

    def test_evidence_redacted_on_construction(self):
        fd = F.Finding(dimension="security", category="Secret exposure",
                       severity="high", evidence=f"saw {GH_TOKEN}")
        self.assertNotIn(GH_TOKEN, fd.evidence)
        self.assertNotIn(GH_TOKEN, fd.to_dict()["evidence"])

    def test_autocomputed_fingerprint(self):
        fd = F.Finding(dimension="efficiency", category="Token spend",
                       severity="low", evidence="100 tokens")
        self.assertTrue(fd.fingerprint)
        self.assertEqual(fd.fingerprint,
                         F.make_fingerprint("efficiency", "Token spend", "100 tokens"))

    def test_rejects_bad_dimension(self):
        with self.assertRaises(ValueError):
            F.Finding(dimension="bogus", category="C", severity="low", evidence="e")

    def test_rejects_bad_severity(self):
        with self.assertRaises(ValueError):
            F.Finding(dimension="reliability", category="C", severity="critical", evidence="e")


if __name__ == "__main__":
    unittest.main()
