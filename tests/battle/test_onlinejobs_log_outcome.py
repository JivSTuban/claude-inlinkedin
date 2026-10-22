#!/usr/bin/env python3
"""The one command the headless apply run may use to log. No network:
python3 tests/battle/test_onlinejobs_log_outcome.py"""
import argparse
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import onlinejobs_log_outcome as lo  # noqa: E402
import onlinejobs_apply_gate as gate  # noqa: E402

TRACKER = "# Tracker\n\n| date | role |\n|---|---|\n| 2026-10-20 | Old | Co | Form | ~40 | SKIPPED | x |\n\n**Learning:** keep this.\n"


def args(**kw):
    base = dict(url="https://www.onlinejobs.ph/jobseekers/job/x-1", title="Senior Dev", status="skipped", fit=10,
                note="Misfit", employer="", method="form", form_url="", email="")
    base.update(kw)
    return argparse.Namespace(**base)


class LogOutcome(unittest.TestCase):
    def setUp(self):
        self.skill = tempfile.mkdtemp()
        open(os.path.join(self.skill, "applied.jsonl"), "w").write("")
        open(os.path.join(self.skill, "TRACKER.md"), "w").write(TRACKER)

    def test_row_is_valid_json_and_the_gate_then_treats_the_lead_as_handled(self):
        row = lo.build_row(args(), today="2026-10-22")
        lo.write(row, self.skill)
        applied = gate.read_applied(os.path.join(self.skill, "applied.jsonl"))
        self.assertEqual(applied[0]["status"], "skipped")
        lead = {"url": "https://www.onlinejobs.ph/jobseekers/job/x-1", "employer": "", "title": "Senior Dev"}
        self.assertEqual(gate.open_leads([lead], applied), [])

    def test_tracker_row_lands_before_the_learning_footer(self):
        lo.write(lo.build_row(args(title="A | B"), today="2026-10-22"), self.skill)
        text = open(os.path.join(self.skill, "TRACKER.md")).read()
        self.assertLess(text.index("| 2026-10-22 | A / B |"), text.index("**Learning:**"))
        self.assertIn("**Learning:** keep this.", text)

    def test_email_method_records_the_address_the_dedup_uses(self):
        row = lo.build_row(args(method="email", email="jobs@acme.com", employer="Acme", status="sent"), today="2026-10-22")
        self.assertEqual(row["method"], "email:jobs@acme.com")
        lead = {"url": "other", "apply_email": "Jobs@Acme.com", "employer": ""}
        self.assertEqual(gate.open_leads([lead], [row]), [])

    def test_unnamed_employer_gets_the_placeholder_the_gate_ignores(self):
        row = lo.build_row(args(), today="2026-10-22")
        self.assertEqual(row["employer"], "(not named)")

    def test_tracker_without_a_footer_still_gets_the_row(self):
        open(os.path.join(self.skill, "TRACKER.md"), "w").write("# Tracker\n")
        lo.write(lo.build_row(args(), today="2026-10-22"), self.skill)
        self.assertIn("SKIPPED", open(os.path.join(self.skill, "TRACKER.md")).read())

    def test_bad_status_and_fit_are_rejected(self):
        with self.assertRaises(SystemExit):
            lo.main(["--url", "u", "--title", "t", "--status", "done", "--fit", "5", "--note", "n"])
        with self.assertRaises(SystemExit):
            lo.main(["--url", "u", "--title", "t", "--status", "skipped", "--fit", "500", "--note", "n"])


if __name__ == "__main__":
    unittest.main()
