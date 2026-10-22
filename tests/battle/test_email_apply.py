#!/usr/bin/env python3
"""Deterministic tests for scripts/linkedin-email.py. No network, no Gmail, no Codex, no quota."""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("linkedin_email", os.path.join(HERE, "..", "..", "scripts", "linkedin-email.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
M.notify = lambda text: None  # never DM during tests

ORIGAMI = ('<html><head><title>AI Forward-Deployed Engineer | Origami AI</title></head><body><h1>Role</h1>'
           '<p>You bring ownership.</p><a href="mailto:careers@origami.build?subject=AI%20Forward-Deployed%20Engineer%20%E2%80%94%20application">Apply</a>'
           '<script>var x="mailto:evil@x.com"</script></body></html>')
GOOD_BODY = "Hi team,\n\nI build agent systems.\n\ngithub.com/JivSTuban | linkedin.com/in/jiv-tuban | farfolio.vercel.app\njivtuban14@gmail.com"


class Pure(unittest.TestCase):
    def test_registrable(self):
        self.assertEqual(M.registrable("www.origami.build"), "origami.build")
        self.assertEqual(M.registrable("jobs.acme.co.uk"), "acme.co.uk")
        self.assertEqual(M.registrable("acme.com"), "acme.com")

    def test_origami_page_is_email_apply(self):
        c = M.classify(ORIGAMI, "https://www.origami.build/careers/ai-forward-deployed-engineer")
        self.assertEqual((c["kind"], c["to"]), ("email", "careers@origami.build"))
        self.assertIn("application", c["subject_hint"])
        self.assertNotIn("evil@x.com", c["text"])  # script contents are not page text

    def test_mailto_on_another_domain_is_not_trusted(self):
        c = M.classify('<a href="mailto:hr@gmail.com">x</a>', "https://acme.com/jobs/1")
        self.assertEqual((c["kind"], c["why"]), ("other", "recipient_domain_mismatch"))

    def test_page_with_application_form_is_not_email_apply(self):
        html = '<form><input name=a><input name=b><textarea></textarea></form><a href="mailto:hr@acme.com">Contact</a>'
        self.assertEqual(M.classify(html, "https://acme.com/jobs/1")["why"], "has_application_form")

    def test_no_mailto(self):
        self.assertEqual(M.classify("<p>Apply on our portal</p>", "https://acme.com/j")["kind"], "other")

    def test_draft_validation(self):
        self.assertIsNone(M.validate_draft("AI Forward-Deployed Engineer application", GOOD_BODY))
        self.assertIn("dash", M.validate_draft("Role — application", GOOD_BODY))
        self.assertIn("phone", M.validate_draft("Hi", "call +639171234567"))
        self.assertIn("allowlist", M.validate_draft("Hi", "see https://evil.example.com/steal"))
        self.assertIn("empty", M.validate_draft("", "x"))
        self.assertIn("too long", M.validate_draft("Hi", "x" * 3001))

    def test_ssrf_guard(self):
        for host in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "100.98.219.58", "169.254.169.254", "localhost"):
            self.assertFalse(M.host_is_public(host), host)
        self.assertTrue(M.host_is_public("8.8.8.8"))
        with self.assertRaises(ValueError):
            M.fetch("http://127.0.0.1:8080/x")
        with self.assertRaises(ValueError):
            M.fetch("file:///etc/passwd")


class RealFetch(unittest.TestCase):
    """fetch() against a real local HTTP server, so the opener/redirect code actually runs."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(h):
                if h.path == "/redir":
                    h.send_response(302)
                    h.send_header("Location", "/final")
                    h.end_headers()
                elif h.path == "/to-private":
                    h.send_response(302)
                    h.send_header("Location", "http://10.0.0.5/secret")
                    h.end_headers()
                else:
                    h.send_response(200)
                    h.send_header("Content-Type", "text/html")
                    h.end_headers()
                    h.wfile.write(b"<a href='mailto:hr@localhost.test'>apply</a>")

            def log_message(h, *a):
                pass

        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls._orig = M.host_is_public
        # Loopback is blocked in production; allow it here, but keep rejecting the private hop.
        M.host_is_public = lambda host: host == "127.0.0.1"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        M.host_is_public = cls._orig

    def test_fetches_follows_a_safe_redirect(self):
        url, html = M.fetch(f"http://127.0.0.1:{self.port}/redir")
        self.assertTrue(url.endswith("/final"))
        self.assertIn("mailto:hr@localhost.test", html)

    def test_redirect_to_a_private_host_is_refused(self):
        with self.assertRaises(ValueError):
            M.fetch(f"http://127.0.0.1:{self.port}/to-private")


class Flow(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = lambda n: os.path.join(self.d, n)
        open(self.p("resume.pdf"), "wb").write(b"%PDF-1.4 test")
        self.sent = []

        class FakeSMTP:
            def send_message(inner, msg):
                self.sent.append(msg)

            def quit(inner):
                pass

        self.factory = lambda: (FakeSMTP(), "jiv@example.com")

    def cands(self, n=1):
        json.dump({"candidates": [{"id": str(i), "url": f"https://co{i}.com/job", "to": f"hr@co{i}.com", "title": f"Role {i}", "shared_by": "Ana"} for i in range(1, n + 1)]}, open(self.p("c.json"), "w"))

    def run_send(self, drafts, **kw):
        json.dump(drafts, open(self.p("d.json"), "w"))
        a = types.SimpleNamespace(candidates=self.p("c.json"), drafts=self.p("d.json"), log=self.p("log.jsonl"), resume=self.p("resume.pdf"),
                                  disabled_file=kw.get("disabled"), dry_run=kw.get("dry", False))
        return M.send(a, smtp_factory=self.factory)

    def draft(self, i=1, **kw):
        return {"id": str(i), "apply": True, "fit": 85, "reason": "fit", "subject": "AI Engineer application", "body": GOOD_BODY, **kw}

    def test_sends_once_with_attachment_to_the_scanned_recipient(self):
        self.cands()
        rc = self.run_send([self.draft(to="attacker@evil.com")])  # a "to" from Codex must be ignored
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["To"], "hr@co1.com")
        self.assertEqual([p.get_filename() for p in self.sent[0].iter_attachments()], ["Jiv-Tuban-Resume.pdf"])

    def test_never_emails_the_same_recipient_twice(self):
        self.cands()
        self.run_send([self.draft()])
        rc = self.run_send([self.draft()])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(rc, 4)
        self.assertIn("already emailed", open(self.p("log.jsonl")).read())

    def test_daily_cap(self):
        self.cands(7)
        self.run_send([self.draft(i) for i in range(1, 8)])
        self.assertEqual(len(self.sent), M.DAILY_CAP)

    def test_kill_switch_file_sends_nothing(self):
        self.cands()
        open(self.p("off"), "w").write("stop")
        self.assertEqual(self.run_send([self.draft()], disabled=self.p("off")), 0)
        self.assertEqual(self.sent, [])

    def test_dry_run_sends_nothing_and_is_not_remembered(self):
        self.cands()
        self.run_send([self.draft()], dry=True)
        self.assertEqual(self.sent, [])
        self.assertEqual(M.read_log(self.p("log.jsonl")), [])  # dry rows never count as sent

    def test_low_fit_or_bad_draft_is_not_sent(self):
        self.cands(3)
        rc = self.run_send([self.draft(1, fit=60), self.draft(2, body="call +639171234567"), self.draft(3, apply=False)])
        self.assertEqual(self.sent, [])
        self.assertEqual(rc, 4)  # the phone-number draft is a rejection

    def test_candidate_without_a_draft_is_recorded_not_reoffered(self):
        self.cands(2)
        self.run_send([self.draft(1)])
        statuses = {r["to"]: r["status"] for r in M.read_log(self.p("log.jsonl"))}
        self.assertEqual(statuses, {"hr@co1.com": "sent", "hr@co2.com": "no_decision"})

    def test_smtp_failure_is_logged_and_does_not_stop_the_rest(self):
        self.cands(2)
        calls = []

        class Flaky:
            def send_message(inner, msg):
                calls.append(msg["To"])
                if len(calls) == 1:
                    raise OSError("boom")

            def quit(inner):
                pass

        self.factory = lambda: (Flaky(), "jiv@example.com")
        rc = self.run_send([self.draft(1), self.draft(2)])
        self.assertEqual((rc, calls), (4, ["hr@co1.com", "hr@co2.com"]))


class Scan(unittest.TestCase):
    def test_scan_routes_email_pages_to_codex_and_forms_to_jiv(self):
        d = tempfile.mkdtemp()
        p = lambda n: os.path.join(d, n)
        json.dump({"job_leads": [{"name": "Ana", "thread_url": "t1", "linkedin_job_ids": [],
                                  "external": ["https://www.origami.build/careers/x", "https://acme.com/apply"]}]}, open(p("dg.json"), "w"))
        pages = {"https://www.origami.build/careers/x": ORIGAMI, "https://acme.com/apply": "<form><input><input><input></form>"}
        M.fetch = lambda url: (url, pages[url])
        a = types.SimpleNamespace(digest=p("dg.json"), out=p("out.json"), log=p("log.jsonl"), needs_jiv=p("nj.jsonl"), dry_run=False)
        self.assertEqual(M.scan(a), 0)
        out = json.load(open(p("out.json")))["candidates"]
        self.assertEqual([c["to"] for c in out], ["careers@origami.build"])
        nj = [json.loads(l) for l in open(p("nj.jsonl"))]
        self.assertEqual(len(nj), 1)
        self.assertIn("https://acme.com/apply", nj[0]["their_message"])
        # second scan: the form page is remembered, nothing told twice
        self.assertEqual(M.scan(a), 0)
        self.assertEqual(len(open(p("nj.jsonl")).read().splitlines()), 1)

    def test_scan_skips_a_recipient_already_emailed(self):
        d = tempfile.mkdtemp()
        p = lambda n: os.path.join(d, n)
        json.dump({"job_leads": [{"name": "Ana", "thread_url": "t", "linkedin_job_ids": [], "external": ["https://www.origami.build/careers/x"]}]}, open(p("dg.json"), "w"))
        open(p("log.jsonl"), "w").write(json.dumps({"at": "2026-10-15T00:00:00+00:00", "url": "https://elsewhere/old", "to": "careers@origami.build", "status": "sent"}) + "\n")
        M.fetch = lambda url: (url, ORIGAMI)
        a = types.SimpleNamespace(digest=p("dg.json"), out=p("out.json"), log=p("log.jsonl"), needs_jiv=None, dry_run=False)
        M.scan(a)
        self.assertEqual(json.load(open(p("out.json")))["candidates"], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
