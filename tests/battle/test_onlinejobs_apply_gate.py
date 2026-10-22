#!/usr/bin/env python3
"""The gate that decides whether a headless /onlinejobs-apply run starts. No network, no ssh:
python3 tests/battle/test_onlinejobs_apply_gate.py
Rows mirror the real queue and applied.jsonl seen on 2026-10-22."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import onlinejobs_apply_gate as g  # noqa: E402

APPLIED = [
    {"id_or_url": "https://www.onlinejobs.ph/jobseekers/job/ts-api-1725981",
     "form_url": "https://forms.gle/68L6jRPFqM6seaq5A", "employer": "(not named; form: Software Engineer)", "method": "form"},
    {"id_or_url": "https://www.onlinejobs.ph/jobseekers/job/crm-role-1600000",
     "employer": "A Man & His Cave", "method": "form"},
    {"id_or_url": "https://www.origami.build/careers/x", "employer": "Origami", "method": "email:careers@origami.build"},
]


def lead(**kw):
    base = {"url": "https://www.onlinejobs.ph/jobseekers/job/new-1", "title": "Dev", "employer": "",
            "form_url": "", "apply_email": "", "applied": False, "closed": False}
    base.update(kw)
    return base


class OpenLeads(unittest.TestCase):
    def test_new_lead_passes(self):
        self.assertEqual(len(g.open_leads([lead(employer="Acme")], APPLIED)), 1)

    def test_same_posting_url_is_dropped(self):
        self.assertEqual(g.open_leads([lead(url="https://www.onlinejobs.ph/jobseekers/job/ts-api-1725981")], APPLIED), [])

    def test_same_form_url_is_dropped(self):
        self.assertEqual(g.open_leads([lead(form_url="https://forms.gle/68L6jRPFqM6seaq5A")], APPLIED), [])

    def test_same_employer_new_posting_is_dropped(self):
        # A Man & His Cave reposted under a new id: the Mini queued it, applied.jsonl already has them.
        self.assertEqual(g.open_leads([lead(employer="a man & his cave")], APPLIED), [])

    def test_same_apply_email_is_dropped(self):
        self.assertEqual(g.open_leads([lead(apply_email="Careers@Origami.build")], APPLIED), [])

    def test_unnamed_employer_never_hides_a_lead(self):
        # applied.jsonl carries "(not named; ...)" placeholders; they must not become an employer key.
        self.assertEqual(len(g.open_leads([lead(employer="(not named; form: Software Engineer)", url="u2")], APPLIED)), 1)
        self.assertEqual(len(g.open_leads([lead(employer="")], APPLIED)), 1)

    def test_flagged_applied_or_closed_is_dropped(self):
        self.assertEqual(g.open_leads([lead(applied=True), lead(closed=True)], APPLIED), [])


class Main(unittest.TestCase):
    def test_unreadable_queue_is_exit_2_not_nothing_to_do(self):
        orig = g.read_leads
        g.read_leads = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ssh failed"))
        try:
            self.assertEqual(g.main(), 2)
        finally:
            g.read_leads = orig


if __name__ == "__main__":
    unittest.main()
