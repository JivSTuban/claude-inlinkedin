#!/usr/bin/env python3
"""Deterministic tests for scripts/onlinejobs_send_email.py. No network, no Gmail: SMTP is a fake."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scripts"))
import onlinejobs_send_email as S  # noqa: E402

URL = "https://www.onlinejobs.ph/jobseekers/job/ai-engineer-1"
BODY = "Hi Ana,\\n\\nI build agent systems in production.\\n\\ngithub.com/JivSTuban\\nJiv Tuban\\njivtuban14@gmail.com"


class FakeSMTP:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self):
        return self, "jivtuban14@gmail.com"

    def send_message(self, msg):
        if self.fail:
            raise OSError("535 bad credentials")
        self.sent.append(msg)

    def quit(self):
        pass


class Send(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.leads = os.path.join(self.d, "leads.jsonl")
        self.applied = os.path.join(self.d, "applied.jsonl")
        self.send_log = os.path.join(self.d, "email-sends.jsonl")
        self.other = os.path.join(self.d, "linkedin-email-log.jsonl")
        self.resume = os.path.join(self.d, "jiv-resume.pdf")
        open(self.resume, "wb").write(b"%PDF-1.4 fake")
        self.lead({"url": URL, "title": "AI Engineer", "apply_email": "Hiring@Acme.com"})
        S.DISABLED = os.path.join(self.d, "onlinejobs-email.disabled")

    def lead(self, *rows):
        with open(self.leads, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def go(self, smtp=None, **over):
        args = {"--url": URL, "--title": "AI Engineer", "--fit": "80", "--subject": "AI Engineer application",
                "--body": BODY, "--employer": "Acme"}
        args.update(over)
        argv = ["--leads", self.leads, "--resume", self.resume]
        for k, v in args.items():
            argv += [k, v]
        self.smtp = smtp or FakeSMTP()
        return S.main(argv, smtp_factory=self.smtp, applied_path=self.applied, send_log=self.send_log, other_logs=[self.other])

    def rows(self, path):
        return [json.loads(l) for l in open(path)] if os.path.exists(path) else []

    def test_sends_to_the_queued_address_and_logs_sent_once(self):
        self.assertEqual(self.go(), 0)
        msg = self.smtp.sent[0]
        self.assertEqual(msg["To"], "hiring@acme.com")
        self.assertIn("\n\nI build agent systems", msg.get_body().get_content())  # \n became real line breaks
        self.assertEqual([a.get_filename() for a in msg.iter_attachments()], ["Jiv-Tuban-Resume.pdf"])
        applied = self.rows(self.applied)
        self.assertEqual((len(applied), applied[0]["status"], applied[0]["method"]), (1, "sent", "email:hiring@acme.com"))
        self.assertEqual(self.rows(self.send_log)[0]["status"], "sent")
        self.assertIn("SENT", open(os.path.join(self.d, "TRACKER.md")).read())

    def test_second_send_to_same_posting_is_refused(self):
        self.go()
        self.assertEqual(self.go(), 2)
        self.assertEqual(self.smtp.sent, [])

    def test_recipient_emailed_from_linkedin_is_refused(self):
        with open(self.other, "w") as f:
            f.write(json.dumps({"to": "hiring@acme.com", "url": "https://acme.com/jobs", "status": "sent"}) + "\n")
        self.assertEqual(self.go(), 2)

    def test_recipient_emailed_by_the_old_browser_path_is_refused(self):
        with open(self.applied, "w") as f:
            f.write(json.dumps({"id_or_url": "https://x/other", "method": "email:hiring@acme.com", "status": "sent"}) + "\n")
        self.assertEqual(self.go(), 2)

    def test_url_not_in_the_queue_is_refused(self):
        self.assertEqual(self.go(**{"--url": "https://www.onlinejobs.ph/jobseekers/job/other-2"}), 2)
        self.assertEqual(self.smtp.sent, [])

    def test_lead_without_apply_email_is_refused(self):
        self.lead({"url": URL, "title": "AI Engineer", "form_url": "https://forms.gle/x"})
        self.assertEqual(self.go(), 2)

    def test_low_fit_is_refused(self):
        self.assertEqual(self.go(**{"--fit": "60"}), 2)

    def test_bad_drafts_are_refused(self):
        for body in ("I build things \u2014 fast.", "Call me on 09171234567.", "See https://evil.example/x"):
            with self.subTest(body=body):
                self.assertEqual(self.go(**{"--body": body}), 2)
        self.assertFalse(os.path.exists(self.applied))

    def test_daily_cap(self):
        S.DAILY_CAP, old = 1, S.DAILY_CAP
        try:
            self.go()
            self.lead({"url": URL + "x", "title": "B", "apply_email": "jobs@other.com"})
            self.assertEqual(self.go(**{"--url": URL + "x"}), 2)
        finally:
            S.DAILY_CAP = old

    def test_kill_switch_sends_nothing(self):
        open(S.DISABLED, "w").close()
        self.assertEqual(self.go(), 3)
        self.assertEqual(self.smtp.sent, [])

    def test_gmail_failure_logs_failed_not_sent(self):
        self.assertEqual(self.go(smtp=FakeSMTP(fail=True)), 4)
        self.assertFalse(os.path.exists(self.applied))
        self.assertEqual(self.rows(self.send_log)[0]["status"], "failed")

    def test_dry_run_sends_and_logs_nothing(self):
        smtp = FakeSMTP()
        argv = ["--leads", self.leads, "--resume", self.resume, "--dry-run", "--url", URL, "--title", "AI Engineer",
                "--fit", "80", "--subject", "s", "--body", BODY]
        self.assertEqual(S.main(argv, smtp_factory=smtp, applied_path=self.applied, send_log=self.send_log, other_logs=[]), 0)
        self.assertEqual(smtp.sent, [])
        self.assertFalse(os.path.exists(self.applied) or os.path.exists(self.send_log))


if __name__ == "__main__":
    unittest.main(verbosity=1)
