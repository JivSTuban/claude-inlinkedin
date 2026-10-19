#!/usr/bin/env python3
"""Meeting detector + notifier routing. No network, no quota: python3 tests/battle/test_meeting_signal.py"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "..", "scripts")
sys.path.insert(0, SCRIPTS)
from meeting_signal import meeting_signal  # noqa: E402


def load_notify(**env):
    for k, v in env.items():
        os.environ[k] = v
    spec = importlib.util.spec_from_file_location("linkedin_notify", os.path.join(SCRIPTS, "linkedin-notify.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Detector(unittest.TestCase):
    def test_links(self):
        for t in ["grab a slot https://calendly.com/acme/intro",
                  "Join: https://meet.google.com/abc-defg-hij",
                  "https://us02web.zoom.us/j/123456789",
                  "book here cal.com/jane/30min"]:
            self.assertEqual(meeting_signal(t), "link", t)

    def test_asks(self):
        for t in ["Can we schedule a call this week?",
                  "When are you available for a quick chat?",
                  "What time works for you tomorrow?",
                  "Let's set up an interview",
                  "Are you free Thursday?",
                  "Please share your availability",
                  "We would like to interview you on Friday 3pm",
                  "How about a call Tuesday at 10am?"]:
            self.assertEqual(meeting_signal(t), "ask", t)

    def test_not_a_meeting(self):
        for t in ["Thanks for applying to Nexus Digital.",
                  "Please keep your response short and direct. If you do not have strong hands-on GoHighLevel experience, please do not apply.",
                  "Watch my video then reply with a link to a 2 to 3 minute video of yourself",
                  "After the interview process we will send an offer",
                  "Please check your calendar for the holidays",
                  "", None]:
            self.assertIsNone(meeting_signal(t), t)

    def test_cooper_real_message_is_not_a_meeting(self):
        # The 2026-10-19 Nexus Digital ask: a video request, handled as needs-you, not an alarm.
        t = ("Hi, thanks for applying to Nexus Digital. Before we go through applications, we ask everyone to "
             "watch a short video from me first: https://www.loom.com/share/c085. Then reply here with a link to "
             "a 2 to 3 minute video of yourself. We watch every video and reply to everyone who sends one.")
        self.assertIsNone(meeting_signal(t))


class Routing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.n = load_notify(
            LINKEDIN_NOTIFY_KEYS=os.path.join(self.tmp, "keys.json"),
            PUSHOVER_ENV_FILE=os.path.join(self.tmp, "po.env"),
        )
        self.discord, self.pushes = [], []
        self.n.post = lambda text: self.discord.append(text)

    def with_pushover(self):
        open(self.n.PUSHOVER_ENV, "w").write('PUSHOVER_TOKEN=tok\nPUSHOVER_USER="usr"\n')

    def capture_push(self, ok=True):
        def fake(req, timeout=0):
            if not ok:
                raise OSError("pushover down")
            self.pushes.append(dict(p.split("=", 1) for p in req.data.decode().split("&")))
        self.n.urllib.request.urlopen = fake

    def test_info_is_discord_only(self):
        self.with_pushover(); self.capture_push()
        self.n.alert("hello", "info")
        self.assertEqual(len(self.discord), 1)
        self.assertEqual(self.pushes, [])

    def test_meeting_is_emergency_with_retry_and_expire(self):
        self.with_pushover(); self.capture_push()
        self.n.alert("they sent calendly", "meeting", "Meeting ready", "https://x.test/c/1")
        p = self.pushes[0]
        self.assertEqual((p["priority"], p["retry"], p["expire"]), ("2", "60", "1800"))
        self.assertTrue(30 <= int(p["retry"]) and int(p["expire"]) <= 10800)  # Pushover's documented bounds
        self.assertIn("url", p)

    def test_needs_is_normal_priority(self):
        self.with_pushover(); self.capture_push()
        self.n.alert("send the video", "needs")
        self.assertEqual(self.pushes[0]["priority"], "0")
        self.assertNotIn("retry", self.pushes[0])

    def test_no_pushover_file_still_sends_discord(self):
        self.capture_push()
        self.n.alert("x", "meeting")
        self.assertEqual(len(self.discord), 1)
        self.assertEqual(self.pushes, [])

    def test_pushover_down_does_not_block_discord(self):
        self.with_pushover(); self.capture_push(ok=False)
        self.n.alert("x", "meeting")
        self.assertEqual(len(self.discord), 1)

    def test_discord_down_still_pushes(self):
        self.with_pushover(); self.capture_push()
        def boom(_): raise OSError("discord down")
        self.n.post = boom
        self.n.alert("x", "meeting")
        self.assertEqual(len(self.pushes), 1)

    def test_everything_down_raises(self):
        self.with_pushover(); self.capture_push(ok=False)
        def boom(_): raise OSError("discord down")
        self.n.post = boom
        with self.assertRaises(SystemExit):
            self.n.alert("x", "meeting")

    def test_key_rings_once(self):
        self.with_pushover(); self.capture_push()
        for _ in range(3):
            self.n.alert("x", "meeting", key="oj:abc:meeting")
        self.assertEqual((len(self.discord), len(self.pushes)), (1, 1))
        self.n.alert("y", "meeting", key="oj:other:meeting")
        self.assertEqual(len(self.pushes), 2)

    def test_failed_send_is_not_marked_sent(self):
        self.with_pushover(); self.capture_push(ok=False)
        def boom(_): raise OSError("discord down")
        self.n.post = boom
        with self.assertRaises(SystemExit):
            self.n.alert("x", "meeting", key="k")
        self.assertFalse(self.n.already_sent("k"))  # next run must retry

    def test_old_text_calls_unchanged(self):
        self.n.parse_flags  # exists
        self.assertEqual(self.n.parse_flags(["--text", "--looks like a flag but is the text"]),
                         {"text": "--looks like a flag but is the text"})

    def test_queue_item_with_meeting_ask_rings_loud(self):
        q = os.path.join(self.tmp, "q.jsonl")
        open(q, "w").write(json.dumps({"name": "Ana", "thread_url": "https://li/x",
                                       "their_message": "Can we schedule a call Tuesday?", "why": "asks to meet"}) + "\n")
        self.n.QUEUE, self.n.STATE = q, os.path.join(self.tmp, "state")
        levels = []
        real = self.n.alert
        self.n.alert = lambda text, level="info", title=None, url=None, key=None: levels.append((level, title))
        sys.argv = ["x"]
        self.n.main()
        self.assertEqual(levels, [("meeting", "LinkedIn meeting: Ana")])


if __name__ == "__main__":
    unittest.main(verbosity=1)
