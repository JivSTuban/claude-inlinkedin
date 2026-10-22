#!/usr/bin/env python3
"""OnlineJobs external-application discovery. No browser, no network:
python3 tests/battle/test_onlinejobs_forms.py
Posting texts are shaped exactly like the live pages seen on 2026-10-20 (nav on top, JOB OVERVIEW,
SHARE THIS POST and the site footer below)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import onlinejobs_forms as f  # noqa: E402

NAV = "How it Works\nMessages 0\nJOB BOARD\nPAYMENTS\n Account \n REPORT\n< Back to search results\n"
FOOT = ("\nSHARE THIS POST\n  \nEMPLOYERS\nWORKERS\nTALENTED VA'S\nOTHER GOODS\nCONTACT US\n"
        "support@onlinejobs.ph\n Copyright © 2026 OnlineJobs.ph. All rights reserved.")


def posting(title, wage, body, hours="40", applied=False, employer=""):
    mid = "\nApplied\n\nDate Applied: 2026-10-20\n" if applied else "APPLY FOR THIS JOB\n"
    head = (f" {employer}\n" if employer else "") + title + "\n"
    return (NAV + head + mid + f" Bookmark\nTYPE OF WORK\n\nFull Time\n\nWAGE / SALARY\n\n{wage}\n\n"
            f"HOURS PER WEEK\n\n{hours}\n\nDATE UPDATED\n\nOct 20, 2026\n\n JOB OVERVIEW\n\n{body}" + FOOT)


URL = "https://www.onlinejobs.ph/jobseekers/job/senior-ai-full-stack-software-developer-remote-1723774"

FORM_ROLE = posting(
    "Senior Software Developer, TypeScript API and Infrastructure", "$2,500 - $3,500/month",
    "Build APIs.\nApply here: https://forms.gle/68L6jRPFqM6seaq5A.\nWe reply within a week.")
EMAIL_ROLE = posting(
    "Full-Stack Developer (Rails, React, TypeScript)", "$12-13/hour - take-home first",
    "HOW TO APPLY\nEmail your submission to jobs@framesports.ai within 48 hours.")


class TestParsing(unittest.TestCase):
    def test_form_link_found_and_trailing_dot_stripped(self):
        lead = f.parse_posting(URL, FORM_ROLE)
        self.assertEqual(lead["method"], "FORM")
        self.assertEqual(lead["form_url"], "https://forms.gle/68L6jRPFqM6seaq5A")
        self.assertEqual(lead["title"], "Senior Software Developer, TypeScript API and Infrastructure")

    def test_google_forms_viewform_link_keeps_its_query(self):
        t = posting("Zoho Developer", "$20/hr",
                    "Apply: https://docs.google.com/forms/d/e/1FAIpQLSdnDD/viewform?usp=header today")
        self.assertEqual(f.parse_posting(URL, t)["form_url"],
                         "https://docs.google.com/forms/d/e/1FAIpQLSdnDD/viewform?usp=header")

    def test_typeform_and_ats_hosts_count_as_external(self):
        for link in ("https://form.typeform.com/to/kSL16bvX", "https://jobs.lever.co/acme/123/apply",
                     "https://boards.greenhouse.io/acme/jobs/1", "https://jobs.ashbyhq.com/acme/abc"):
            self.assertEqual(f.parse_posting(URL, posting("Backend Engineer", "$3000/month", f"Apply {link}"))["method"],
                             "FORM", link)

    def test_link_shorteners_count_as_a_form_link(self):
        # A Technical Delivery Manager post carried a bit.ly form and was judged native (2026-10-22).
        for link in ("https://bit.ly/3xYzAbC", "https://tinyurl.com/yc8x2abc", "https://forms.office.com/r/AbC123"):
            lead = f.parse_posting(URL, posting("Backend Engineer", "$3000/month", f"Apply here {link}."))
            self.assertEqual((lead["method"], lead["form_url"]), ("FORM", link), link)

    def test_a_shortener_lookalike_host_is_not_a_form(self):
        lead = f.parse_posting(URL, posting("Backend Engineer", "$3000/month", "See notbit.ly/abc or xtinyurl.com/q for our blog"))
        self.assertEqual(lead["method"], "native")

    def test_email_only_posting(self):
        lead = f.parse_posting(URL, EMAIL_ROLE)
        self.assertEqual((lead["method"], lead["apply_email"]), ("EMAIL", "jobs@framesports.ai"))

    def test_site_support_email_is_never_an_apply_address(self):
        lead = f.parse_posting(URL, posting("Backend Engineer", "$3000/month", "Apply on the site."))
        self.assertEqual((lead["method"], lead["apply_email"]), ("native", ""))

    def test_applied_marker_and_closed_posting(self):
        self.assertTrue(f.parse_posting(URL, posting("Backend Engineer", "$3000/month", "x", applied=True))["applied"])
        gone = NAV.replace("< Back to search results\n", "") + "Job No Longer Posted\nThis job post has been deleted.\n" + FOOT
        lead = f.parse_posting(URL, gone)
        self.assertTrue(lead["closed"])
        self.assertEqual(lead["method"], "native")

    def test_employer_line_above_the_title_is_not_the_title(self):
        t = posting("Full-Stack Developer (AI-Fluent)", "20", "https://forms.gle/abc123", employer="A Man & His Cave")
        lead = f.parse_posting(URL, t)
        self.assertEqual((lead["employer"], lead["title"]), ("A Man & His Cave", "Full-Stack Developer (AI-Fluent)"))

    def test_applied_page_title_skips_the_applied_banner(self):
        lead = f.parse_posting(URL, posting("Backend Engineer", "$3000/month", "x", applied=True))
        self.assertEqual(lead["title"], "Backend Engineer")

    def test_closed_banner_under_the_title_marks_it_closed_and_is_not_the_title(self):
        t = posting("Full Stack Developer (Rails)", "$20/hr", "jobs@framesports.ai").replace(
            "Full Stack Developer (Rails)\nAPPLY FOR THIS JOB\n", "Full Stack Developer (Rails)\nThis job has been closed.\n")
        lead = f.parse_posting(URL, t)
        self.assertTrue(lead["closed"])
        self.assertEqual((lead["title"], lead["employer"]), ("Full Stack Developer (Rails)", ""))
        self.assertEqual(f.judge(lead), (False, "closed"))

    def test_id_and_search_url(self):
        self.assertEqual(f.posting_id(URL), "1723774")
        self.assertIn("jobkeyword=full%20stack%20developer", f.search_url("full stack developer"))
        self.assertIn("/jobsearch/30?", f.search_url("ai engineer", 30))


class TestWage(unittest.TestCase):
    def test_wage_variants_seen_on_the_live_board(self):
        cases = {
            "$1,000 – $4,000/month": 4000, "$1500 USD per month": 1500, "$1500": 1500,
            "$2,000-3,000": 3000, "$2000~$3000/month": 3000, "$10-$20 p hr based on experience": 3200,
            "$20 - $30 USD per hour": 4800, "$14/hr": 2240, "$3 / hour": 480, "$100 hourly": 16000,
            "$12-13/hour - take-home first": 2080,
            "20": 3200, "1-20": 3200, "55,000": round(55000 / 56, 6), "Php 35,000 - DOE": 625,
            "6-8 Euros per hour": 1280,
        }
        for wage, want in cases.items():
            self.assertAlmostEqual(f.monthly_usd(wage), want, places=3, msg=wage)

    def test_no_number_is_unknown_not_zero(self):
        self.assertIsNone(f.monthly_usd(""))
        self.assertIsNone(f.monthly_usd("Negotiable"))

    def test_hours_per_week_scales_an_hourly_wage(self):
        self.assertEqual(f.monthly_usd("$20/hr", 20), 1600)


class TestJudge(unittest.TestCase):
    def verdict(self, text):
        return f.judge(f.parse_posting(URL, text))

    def test_developer_role_with_form_passes(self):
        self.assertEqual(self.verdict(FORM_ROLE), (True, ""))

    def test_email_role_at_the_floor_passes(self):
        self.assertEqual(self.verdict(EMAIL_ROLE), (True, ""))

    def test_below_rate_floor_skips(self):
        t = posting("Senior AI and Full-Stack Software Developer", "$5–$6/hr", "https://forms.gle/JZT7GhjDKA4W4VhG8")
        self.assertEqual(self.verdict(t), (False, "below_rate_floor"))

    def test_peso_wage_below_the_floor_skips(self):
        t = posting("Zoho Developer", "55,000", "https://forms.gle/abc123")
        self.assertEqual(self.verdict(t), (False, "below_rate_floor"))

    def test_bare_hourly_number_on_a_good_role_passes(self):
        t = posting("Full-Stack Developer (AI-Fluent)", "20", "https://forms.gle/abc123", employer="A Man & His Cave")
        self.assertEqual(self.verdict(t), (True, ""))

    def test_unknown_wage_is_kept_for_a_human_read(self):
        t = posting("AI Automation Engineer", "Negotiable", "https://forms.gle/abc123")
        self.assertEqual(self.verdict(t), (True, ""))

    def test_non_engineering_roles_are_misfits(self):
        for title in ("Talent Acquisition Specialist", "HubSpot Specialist", "E-Commerce Operations Specialist (Webshop)",
                      "Cloud Phone Handler Home Based", "SEO Specialist"):
            t = posting(title, "$3000/month", "https://forms.gle/abc123")
            self.assertEqual(self.verdict(t), (False, "misfit_role"), title)

    def test_native_applied_and_closed_are_out(self):
        self.assertEqual(self.verdict(posting("Backend Engineer", "$3000/month", "Apply on site.")), (False, "native"))
        self.assertEqual(self.verdict(posting("Backend Engineer", "$3000/month", "https://forms.gle/abc123", applied=True)),
                         (False, "applied_on_site"))


class TestWageClauses(unittest.TestCase):
    def test_same_pay_stated_in_two_units_is_read_per_clause(self):
        # 100 x hourly was $16,000/month; it is $5/hr = $800 or $100/week = $400.
        self.assertEqual(f.monthly_usd("$5 USD/hour ($100/week at 20 hours)"), 800)
        self.assertEqual(f.monthly_usd("$100/week at 20 hours"), 400)

    def test_single_clause_wages_are_unchanged(self):
        self.assertEqual(f.monthly_usd("$12-25/hr"), 25 * 160)
        self.assertAlmostEqual(f.monthly_usd("PHP 100,000 - PHP 140,000"), 140000 / f.PESO_PER_USD)
        self.assertEqual(f.monthly_usd("$3000/month"), 3000)
        self.assertEqual(f.monthly_usd("1-20"), 20 * 160)
        self.assertIsNone(f.monthly_usd("Negotiable"))

    def test_a_low_hourly_with_a_weekly_note_is_below_the_floor(self):
        t = posting("Base44 Web Developer & Technical Support | Part-Time", "$5 USD/hour ($100/week at 20 hours)",
                    "Send applications to saige.radke@junkpunks.com", hours="20")
        self.assertEqual(f.judge(f.parse_posting(URL, t)), (False, "below_rate_floor"))


class TestSearchPlan(unittest.TestCase):
    def test_every_keyword_page_one_and_page_two_for_the_broadest(self):
        plan = f.search_plan()
        self.assertEqual(len(plan), len(set(plan)))                       # nothing scanned twice
        for kw in f.SEARCH_KEYWORDS + f.EXTRA_KEYWORDS:
            self.assertIn((kw, 0), plan)
        self.assertEqual([k for k, o in plan if o == 30], f.SEARCH_KEYWORDS[:3] + ["developer", "engineer"])
        for kw in ("developer", "engineer", "node js", "nodejs"):         # the blind spots found 2026-10-22
            self.assertIn((kw, 0), plan)
        self.assertIn("/jobsearch/30?", f.search_url("ai engineer", 30))


class TestMisfitRegressions(unittest.TestCase):
    """Both were queued and alerted on 2026-10-21/22 before being skipped by hand."""
    def test_titles_that_passed_only_on_a_stray_ai_or_engineer(self):
        for title in ("Remote IT Project Engineer III", "Senior Flooring Estimator / QS \u2013 MeasureSquare M8 & AI",
                      "Network Engineer", "Systems Administrator (AI Ops)", "IT Help Desk Technician"):
            t = posting(title, "$3000/month", "https://forms.gle/abc123")
            self.assertEqual(f.judge(f.parse_posting(URL, t)), (False, "misfit_role"), title)

    def test_real_engineering_roles_with_infrastructure_in_the_title_still_pass(self):
        t = posting("Senior Software Developer (TypeScript & API Infrastructure)", "$3200/month", "https://forms.gle/abc123")
        self.assertEqual(f.judge(f.parse_posting(URL, t)), (True, ""))


if __name__ == "__main__":
    unittest.main()
