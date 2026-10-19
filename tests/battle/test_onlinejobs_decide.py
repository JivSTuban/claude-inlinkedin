#!/usr/bin/env python3
"""OnlineJobs thread parsing and reply decisions. No browser, no network:
python3 tests/battle/test_onlinejobs_decide.py
Page texts are shaped exactly like the live conversation pages seen on 2026-10-19."""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import onlinejobs_decide as d  # noqa: E402

NOW = datetime(2026, 10, 19, 17, 0)
NAV = "How It Works\nMessage\nJOB BOARD\nMessages\nUnread\nPinned\nSent\n"
FOOT = "\nFirst contacted for Job: AI Systems Engineer\nBold\nItalic\nSEND MESSAGE\nPin\nLabel\nArchive\n"
JIV_OLD = ("Oct 19, 2026, 01:52 PM\nJiv Sabolo Tuban\nDear Hiring Manager, I am excited to apply for the Full Stack "
           "Developer AI Products position at Nexus Digital.\n")


def msg(ts, initials, name, email, body):
    return f"{ts}\n{initials}\n{name}\n<{email}>\n{ts}\n{body}\n"


COOPER = NAV + JIV_OLD + msg(
    "Oct 19, 2026, 03:17 PM", "CL", "Cooper Lanyon", "cooper@nexusdigital.studio",
    "Hi, thanks for applying to Nexus Digital.\n\nBefore we go through applications, we ask everyone to watch a short "
    "video from me first: https://www.loom.com/share/c085\n\nThen reply here with a link to a 2 to 3 minute video of yourself.\n\nCooper") + FOOT
COOPER_AFTER_HOLDING = COOPER.replace(FOOT, "") + msg(
    "Oct 19, 2026, 04:55 PM", "", "Jiv Sabolo Tuban", "jivtuban14@gmail.com",
    "Hi Cooper, thanks for getting back to me. I will watch your video and send mine shortly.") + FOOT
JJ = NAV + msg("Oct 19, 2026, 12:29 PM", "JL", "JJ LLC", "marjorie@getbasicblue.com",
               "Please help me out and kindly read the job description until the end as there are questions that are in need of answers there.") + FOOT
# Goldencredit's message is many paragraphs and bullets: the body is not inside the header block.
GHL = NAV + "Oct 5, 2026, 08:37 AM\nJiv Sabolo Tuban\nDear Hiring Manager, I am excited\n" + msg(
    "Oct 19, 2026, 06:30 AM", "GL", "Goldencreditenterprise LLc", "Mgmt@getgoldencredit.com",
    "Hi, thanks for applying. Before scheduling an interview, I want to make sure you are a fit.\n"
    "I need someone very advanced with GoHighLevel\nGolden Credit\nCredit repair leads\nPlease send me:\n"
    "1-2 examples of advanced GoHighLevel systems you built\nYour hourly rate and availability\n"
    "Please keep your response short and direct. If you do not have strong hands-on GoHighLevel experience, please do not apply.") + FOOT


ORI = NAV + msg("Oct 18, 2026, 07:44 PM", "OM", "Ori Marash", "jobs@framesports.ai",
                "Hi Jiv,\nA quick update on the take-home: we've updated the instructions.\n"
                "2. Your email should include a video of up to 60 seconds, recorded with Loom.\n"
                "Please email your submission to jobs@framesports.ai within 24 hours of this message.") + FOOT
MARIAN = NAV + msg("Oct 19, 2026, 05:19 AM", "MB", "Marian B", "marian@staffseekers.com",
                   "Hi Jiv, please send me a zoom or teams invite for Friday 10/23...we would like to interview for the position.") + FOOT


def page(ts, body, name="Ana Reyes", email="ana@acme.co"):
    return NAV + msg(ts, "AR", name, email, body) + FOOT


PLAIN = page("Oct 19, 2026, 04:00 PM", "Thanks for applying. How many years of Next.js experience do you have?")
CALENDLY = page("Oct 19, 2026, 04:00 PM", "Great, let's talk. Book a time here: https://calendly.com/ana/intro")
ASK = page("Oct 19, 2026, 04:00 PM", "Thanks! When are you available for a quick call this week?")


def act(text, cstate=None, now=NOW):
    return d.decide(d.parse_thread(text), cstate, now)


class Parse(unittest.TestCase):
    def test_cooper_is_the_employer_not_jiv(self):
        m = d.parse_thread(COOPER)
        self.assertEqual((m["from_jiv"], m["name"], m["ts"]), (False, "Cooper Lanyon", datetime(2026, 10, 19, 15, 17)))
        self.assertTrue(m["text"].startswith("Hi, thanks for applying"))
        self.assertNotIn("SEND MESSAGE", m["text"])      # composer footer cut
        self.assertNotIn("First contacted", m["text"])

    def test_jiv_last_after_holding_reply(self):
        m = d.parse_thread(COOPER_AFTER_HOLDING)
        self.assertTrue(m["from_jiv"])
        self.assertTrue(m["text"].startswith("Hi Cooper"))

    def test_multi_paragraph_message_belongs_to_the_employer(self):
        # The old last-<li> logic saw only the final bullet, with no sender at all.
        m = d.parse_thread(GHL)
        self.assertFalse(m["from_jiv"])
        self.assertEqual(m["name"], "Goldencreditenterprise LLc")
        self.assertIn("Please send me:", m["text"])
        self.assertTrue(m["text"].endswith("please do not apply."))

    def test_collapsed_last_jiv_message_without_email(self):
        m = d.parse_thread(NAV + "Oct 19, 2026, 01:52 PM\nJiv Sabolo Tuban\nDear Hiring Manager, I am excited\n" + FOOT)
        self.assertTrue(m["from_jiv"])

    def test_nothing_readable(self):
        self.assertIsNone(d.parse_thread(""))
        self.assertIsNone(d.parse_thread("just some text, no timestamps"))
        self.assertEqual(d.decide(None, None, NOW)[0], "none")

    def test_helpers(self):
        self.assertIsNone(d.last_timestamp("no date here"))
        self.assertEqual(d.signature("a  b"), d.signature("a b"))


class Decide(unittest.TestCase):
    def test_jiv_wrote_last(self):
        self.assertEqual(act(COOPER_AFTER_HOLDING)[0], "none")

    def test_fresh_unseen_plain_message_gets_a_reply(self):
        self.assertEqual(act(PLAIN)[0], "reply")

    def test_same_message_handled_once(self):
        st = {"sig": d.signature(d.parse_thread(PLAIN)["text"]), "bot_replies": []}
        self.assertEqual(act(PLAIN, st)[0], "none")

    def test_second_message_in_same_thread_is_answered(self):
        # The old checker replied once per thread ever and then ignored the employer.
        st = {"sig": d.signature(d.parse_thread(PLAIN)["text"]), "bot_replies": [NOW.timestamp() - 3600]}
        follow = page("Oct 19, 2026, 04:30 PM", "I have 5 years of React, do you use Tailwind?")
        self.assertEqual(act(follow, st)[0], "reply")

    def test_old_unseen_thread_is_baselined_not_replied(self):
        self.assertEqual(act(page("Aug 2, 2026, 09:00 AM", "Can you start Monday?"))[0], "baseline")

    def test_old_message_in_known_thread_still_counts(self):
        st = {"sig": "different", "bot_replies": []}
        self.assertEqual(act(page("Oct 10, 2026, 09:00 AM", "Can you start Monday?"), st)[0], "reply")

    def test_legacy_replied_thread_with_old_message_is_baselined(self):
        st = {"sig": "", "bot_replies": [], "legacy": True}
        self.assertEqual(act(page("Aug 2, 2026, 09:00 AM", "Can you start Monday?"), st)[0], "baseline")

    def test_cooper_video_request_is_holding_reply_plus_notify_not_a_meeting(self):
        self.assertEqual(act(COOPER)[0], "reply_notify")

    def test_read_the_job_post_questionnaire_is_notify_only(self):
        self.assertEqual(act(JJ)[0], "notify_only")

    def test_take_home_with_deadline_is_notify_only_not_a_holding_reply(self):
        # Ori Marash, 2026-10-18: video AND a 24 hour deadline. Saying "I will send it shortly" is wrong here.
        self.assertEqual(act(ORI, {"sig": "x", "bot_replies": []})[0], "notify_only")

    def test_marian_zoom_invite_request_is_a_meeting(self):
        self.assertEqual(act(MARIAN, {"sig": "x", "bot_replies": []}), ("meeting", "ask"))

    def test_goldencredit_gets_a_reply_not_a_meeting_alarm(self):
        # "Before scheduling an interview" is a precondition, not a booking.
        st = {"sig": "x", "bot_replies": []}
        self.assertEqual(act(GHL, st)[0], "reply")

    def test_meeting_link(self):
        self.assertEqual(act(CALENDLY), ("meeting", "link"))

    def test_meeting_ask(self):
        self.assertEqual(act(ASK), ("meeting", "ask"))

    def test_meeting_beats_cap(self):
        st = {"sig": "x", "bot_replies": [NOW.timestamp() - 60 * i for i in range(1, 5)]}
        self.assertEqual(act(ASK, st)[0], "meeting")

    def test_cap_after_three_replies_in_a_week(self):
        st = {"sig": "x", "bot_replies": [NOW.timestamp() - 3600 * i for i in (1, 2, 3)]}
        self.assertEqual(act(PLAIN, st)[0], "cap")

    def test_replies_older_than_a_week_do_not_count(self):
        old = (NOW - timedelta(days=8)).timestamp()
        self.assertEqual(act(PLAIN, {"sig": "x", "bot_replies": [old, old, old]})[0], "reply")

    def test_handoff_thread_never_gets_an_auto_reply(self):
        self.assertEqual(act(PLAIN, {"sig": "x", "bot_replies": [], "handoff": True})[0], "handoff_msg")


if __name__ == "__main__":
    unittest.main(verbosity=1)
