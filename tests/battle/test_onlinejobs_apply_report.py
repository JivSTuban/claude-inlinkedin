#!/usr/bin/env python3
"""What the scheduled apply run tells Jiv. No network, no ssh:
python3 tests/battle/test_onlinejobs_apply_report.py"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import onlinejobs_apply_report as r  # noqa: E402


def row(status, title="Backend Engineer", employer="Acme", nxt=""):
    return {"status": status, "title": title, "employer": employer, "next": nxt}


class Summarize(unittest.TestCase):
    def test_skips_are_silent(self):
        self.assertEqual(r.summarize([row("skipped"), row("queued")]), [])

    def test_one_application_is_one_discord_line_no_phone(self):
        out = r.summarize([row("submitted", "Full Stack Developer", "Acme")])
        self.assertEqual(out, [("info", "OnlineJobs: applied", "Applied to 1 job:\n- Full Stack Developer at Acme (form)")])

    def test_several_applications_share_one_message(self):
        out = r.summarize([row("submitted", "A", "X"), row("sent", "B", "Y"), row("skipped")])
        self.assertEqual(len(out), 1)
        self.assertIn("Applied to 2 jobs:", out[0][2])
        self.assertIn("- B at Y (email)", out[0][2])

    def test_handoff_is_the_only_thing_that_pushes(self):
        out = r.summarize([row("handoff", "ML Engineer", "Beta", "Google sign-in expired. Re-login in the browser.")])
        self.assertEqual(out[0][0], "needs")
        self.assertIn("ML Engineer at Beta", out[0][2])
        self.assertTrue(out[0][2].startswith("Google sign-in expired."))     # the action leads, the role follows

    def test_unnamed_employer_placeholder_is_not_printed(self):
        out = r.summarize([row("submitted", "Software Engineer", "(not named; form: Software Engineer)")])
        self.assertNotIn("not named", out[0][2])


class Failures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        r.STATE = os.path.join(self.tmp, "health.json")
        self.sent = []

    def fail(self):
        return r.failed("run", "claude exit 1", sender=lambda *a: self.sent.append(a))

    def test_one_failure_is_silent_two_tell_discord_four_ring_the_phone(self):
        got = [self.fail() for _ in range(5)]
        self.assertEqual(got, [None, "info", None, "needs", None])
        self.assertEqual([s[0] for s in self.sent], ["info", "needs"])

    def test_a_success_resets_the_streak(self):
        self.fail()
        r.ok("run")
        self.assertIsNone(self.fail())     # back to run 1, still silent

    def test_rows_since_reads_only_new_lines(self):
        p = os.path.join(self.tmp, "a.jsonl")
        open(p, "w").write('{"status":"skipped"}\n{"status":"sent","title":"T"}\n')
        self.assertEqual([x["status"] for x in r.rows_since(1, p)], ["sent"])


class Unhandled(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.leads = os.path.join(self.tmp, "leads.jsonl")
        self.applied = os.path.join(self.tmp, "applied.jsonl")

    def write(self, leads, applied):
        open(self.leads, "w").write("".join(json.dumps(l) + "\n" for l in leads))
        open(self.applied, "w").write("".join(json.dumps(a) + "\n" for a in applied))

    def test_a_lead_with_no_logged_outcome_is_unhandled(self):
        self.write([{"url": "u1", "title": "A"}], [])
        self.assertEqual([l["title"] for l in r.unhandled(self.leads, self.applied)], ["A"])

    def test_a_logged_skip_counts_as_handled(self):
        self.write([{"url": "u1", "title": "A"}], [{"id_or_url": "u1", "status": "skipped"}])
        self.assertEqual(r.unhandled(self.leads, self.applied), [])


if __name__ == "__main__":
    unittest.main()
