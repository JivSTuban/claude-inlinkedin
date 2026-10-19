#!/usr/bin/env python3
"""Has the other side moved the conversation to booking a meeting?

The automated replies exist to get to a booked call. When the employer or recruiter reaches that
point, Jiv has to take over fast, so this decides when to raise the alarm. Pure, no network, tested
in tests/battle/test_meeting_signal.py. Used by scripts/linkedin-notify.py (LinkedIn escalations)
and by the OnlineJobs checker on the Mac Mini.

Only feed it THEIR message, never Jiv's own: the bot's reply quotes availability and would trip it.

  kind "link"  they sent a booking or call link (Calendly, Meet, Zoom...): the strongest signal
  kind "ask"   they asked to schedule, asked when Jiv is free, or proposed a day and time
  None         nothing about a meeting
"""
import re
import sys

# A booking or call link. Specific hosts only: a bare "calendar" mention is not a booking.
LINK_RE = re.compile(
    r"calendly\.com|cal\.com/|savvycal\.com|tidycal\.com|hubspot\.com/meetings|meetings\.hubspot|"
    r"calendar\.app\.google|meet\.google\.com|zoom\.us/(j|my)/|teams\.microsoft\.com/l/meetup|"
    r"whereby\.com|usemotion\.com/meet|youcanbook\.me|acuityscheduling\.com|oncehub\.com",
    re.I,
)

# Wording that asks to schedule. "interview" alone is not enough (it also shows up in "after the
# interview we will..."), so it needs a time cue beside it.
ASK_RE = re.compile(
    r"\b(schedule|set up|setup|book|arrange|have|hop on|jump on|get on)\b[^.?!\n]{0,25}"
    r"\b(call|meeting|interview|chat|zoom|google meet|intro)\b"
    r"|\bwhen\s+(are|will|can|would)\s+you\s+(be\s+)?(free|available|able)\b"
    r"|\bare\s+you\s+(free|available)\b"
    r"|\bwhat\s+(time|day)s?\s+(works|work|is good|suits)\b"
    r"|\b(your|share your)\s+availability\b"
    r"|\bwhich\s+(time|day|slot)\s+(works|do you prefer)\b",
    re.I,
)

# "interview ... Tuesday 3pm" style: an interview word plus a concrete day or clock time.
INTERVIEW_RE = re.compile(r"\b(interview|call|meeting)\b", re.I)
WHEN_RE = re.compile(
    r"\b(mon|tues?|wed(nes)?|thu(rs)?|fri|sat(ur)?|sun)(day)?\b|\btomorrow\b|\bnext week\b"
    r"|\b\d{1,2}(:\d{2})?\s?(am|pm)\b",
    re.I,
)


def meeting_signal(text):
    """Return "link", "ask" or None for a message written by the other side."""
    t = text or ""
    if LINK_RE.search(t):
        return "link"
    if ASK_RE.search(t):
        return "ask"
    if INTERVIEW_RE.search(t) and WHEN_RE.search(t):
        return "ask"
    return None


if __name__ == "__main__":
    # CLI for the shell runner and quick checks: prints link/ask/none, exit 0 when there is a signal.
    kind = meeting_signal(" ".join(sys.argv[1:]) or sys.stdin.read())
    print(kind or "none")
    sys.exit(0 if kind else 1)
