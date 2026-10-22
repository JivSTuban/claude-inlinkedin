#!/usr/bin/env python3
"""Tests for scripts/linkedin-outreach-audit.py. Pure: no network, no browser, fake tracker rows."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "audit", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "linkedin-outreach-audit.py"))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

SINCE = 1792700000.0                      # a fixed run start


def ts(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(**kw):
    base = {"name": "Sam Founder", "linkedin_url": "https://www.linkedin.com/in/sam/", "status": "connection_requested",
            "last_action_at": ts(SINCE + 60), "prospect_type": "founder", "location": "Austin, Texas, United States",
            "hire_signal": "Raised seed in September and posted a full-stack opening"}
    base.update(kw)
    return base


class TestPhilippines(unittest.TestCase):
    def test_country_and_city_forms_seen_on_the_live_tracker(self):
        for loc in ("Philippines", "Metro Cebu", "Cebu, Central Visayas, Philippines", "Makati, National Capital Region",
                    "Paranaque, National Capital Region", "Lapu-Lapu, Central Visayas", "Imus, Calabarzon, Philippines", "metro manila"):
            self.assertTrue(A.is_philippines(loc), loc)

    def test_foreign_places_are_not_flagged(self):
        for loc in ("Austin, Texas, United States", "London, England, United Kingdom", "Melbourne, Victoria, Australia",
                    "Singapore", "Berlin, Germany", "Dubai, United Arab Emirates", "San Francisco Bay Area", ""):
            self.assertFalse(A.is_philippines(loc), loc)

    def test_a_place_name_inside_a_longer_word_does_not_match(self):
        # "Lagunamar" or "Cebuano-speaking" must not read as a Philippine city
        self.assertFalse(A.is_philippines("Lagunamar, Spain"))


class TestAudit(unittest.TestCase):
    def test_a_clean_foreign_founder_passes(self):
        self.assertEqual(A.audit([row()], SINCE), [])

    def test_a_philippines_based_founder_is_flagged(self):
        out = A.audit([row(location="Metro Cebu")], SINCE)
        self.assertEqual(len(out), 1)
        self.assertIn("Philippines", out[0][2])

    def test_missing_location_type_or_signal_are_each_flagged(self):
        self.assertIn("no location", A.audit([row(location="")], SINCE)[0][2])
        self.assertIn("prospect_type", A.audit([row(prospect_type="")], SINCE)[0][2])
        self.assertIn("prospect_type", A.audit([row(prospect_type="peer")], SINCE)[0][2])
        self.assertIn("hire_signal", A.audit([row(hire_signal="")], SINCE)[0][2])

    def test_one_foreign_recruiter_per_run_is_allowed_a_second_is_not(self):
        r1 = row(name="R1", prospect_type="recruiter")
        r2 = row(name="R2", prospect_type="recruiter")
        self.assertEqual(A.audit([row(), r1], SINCE), [])
        out = A.audit([row(), r1, r2], SINCE)
        self.assertEqual([o[0] for o in out], ["R2"])
        self.assertIn("second recruiter", out[0][2])

    def test_a_hiring_lead_counts_toward_the_same_single_slot(self):
        out = A.audit([row(name="H", prospect_type="hiring_lead"), row(name="R", prospect_type="recruiter")], SINCE)
        self.assertEqual([o[0] for o in out], ["R"])

    def test_only_connection_requests_from_this_run_are_audited(self):
        old = row(location="Metro Manila", last_action_at=ts(SINCE - 3600))
        other = row(location="Metro Manila", status="replied")
        self.assertEqual(A.audit([old, other], SINCE), [])

    def test_a_row_with_no_timestamp_is_not_audited_as_new(self):
        self.assertEqual(A.audit([row(location="Metro Manila", last_action_at="")], SINCE), [])


class TestCli(unittest.TestCase):
    def run_cli(self, rows, since):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "t.json")
        with open(p, "w") as fh:
            json.dump({"prospects": rows}, fh)
        script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "linkedin-outreach-audit.py")
        return subprocess.run([sys.executable, script, "--tracker", p, "--since", str(since)], capture_output=True, text=True)

    def test_exit_0_when_clean_and_1_with_the_problem_printed(self):
        self.assertEqual(self.run_cli([row()], SINCE).returncode, 0)
        r = self.run_cli([row(name="Pia", location="Makati")], SINCE)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Pia", r.stdout)
        self.assertIn("Philippines", r.stdout)

    def test_unreadable_tracker_is_exit_2_not_silence(self):
        script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "linkedin-outreach-audit.py")
        r = subprocess.run([sys.executable, script, "--tracker", "/nonexistent.json", "--since", "0"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
