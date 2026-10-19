#!/usr/bin/env python3
"""What should the OnlineJobs auto-reply do with one conversation? Pure, no browser, no network.

Split out of onlinejobs-check.py so the rules can be tested (tests/battle/test_onlinejobs_decide.py).
The checker used to look only at *unread* threads and reply once per thread ever. Both were wrong:
anything Jiv had glanced at on his phone was invisible, and a second employer message in the same
thread was never answered. State is now per conversation, keyed by the employer's last message.

Actions returned by decide():
  none         nothing to do (Jiv wrote last, or this exact message was already handled)
  baseline     first time we see this thread and its last message is old: remember it, never reply
  meeting      they moved to booking a call: alarm Jiv, send ONE reply, then hand the thread over
  handoff_msg  Jiv already took over this thread and they wrote again: tell Jiv, do not reply
  notify_only  needs Jiv's own work (read the job post, a take-home, a deadline): tell him, no reply
  cap          bot already replied 3 times this week: stop and tell Jiv
  reply_notify they asked for a video/form: holding reply AND tell Jiv
  reply        ordinary employer message: drafted reply
"""
import hashlib
import re
from datetime import datetime, timedelta

from meeting_signal import meeting_signal

STALE_AFTER = timedelta(hours=48)    # first sight older than this is only baselined
MAX_BOT_REPLIES = 3                  # per thread per 7 days; mirrors the LinkedIn inbox end gate
WINDOW = timedelta(days=7)

# Something only Jiv can produce: a video, a recording, a form. The bot still sends a holding reply.
NEEDS_ASSET_RE = re.compile(
    r"\b(video|loom|vidyard|screen ?record\w*|record(ing)? (yourself|a)|selfie)\b"
    r"|forms\.gle|docs\.google\.com/forms|typeform\.com|tally\.so|airtable\.com/\S*form",
    re.I,
)
# Questions hidden in the job post, "read until the end": a generic reply would be wrong, so no reply.
NEEDS_READ_RE = re.compile(
    r"\b(read|go through|check)\b[^.\n]{0,40}\b(job (description|post(ing)?)|ad|listing)\b[^.\n]{0,40}\b(end|questions?|instructions?)\b"
    r"|\bquestions?\b[^.\n]{0,40}\bin (the|my) (job|post|description|ad)\b",
    re.I,
)

# Work with a deadline (take-home, assignment, "within 24 hours"): a holding reply is worse than none,
# Jiv has to do the work, so alert him and say nothing.
NEEDS_WORK_RE = re.compile(
    r"\btake[- ]?home\b|\b(coding|technical|skills?) (test|challenge|assessment|exercise)\b|\bassignment\b"
    r"|submit(ting)?\b[^.\n]{0,40}\b(pr|pull request|work|task|test|project)\b"
    r"|\bwithin \d+ ?(hours?|hrs?|days?)\b|\bdeadline\b",
    re.I,
)

TS_RE = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M)")


def needs_asset(text):
    return bool(NEEDS_ASSET_RE.search(text or ""))


def needs_read(text):
    return bool(NEEDS_READ_RE.search(text or "") or NEEDS_WORK_RE.search(text or ""))


def last_timestamp(text):
    """Site timestamp of the last message in a thread item, or None. Site clock matches the Mini's."""
    found = TS_RE.findall(text or "")
    if not found:
        return None
    try:
        return datetime.strptime(found[-1], "%b %d, %Y, %I:%M %p")
    except ValueError:
        return None


def signature(text):
    """Stable id for 'this exact employer message', so one message is handled once."""
    return hashlib.sha1(" ".join((text or "").split())[:800].encode()).hexdigest()[:16]


JIV_EMAIL = "jivtuban14@gmail.com"
EMAIL_LINE_RE = re.compile(r"^<[^<>@\s]+@[^<>\s]+>$")
# Below the last message the page prints the composer (job context line, toolbar, buttons). Cut there.
FOOTER_MARKERS = ("First contacted for Job", "Bold")


def parse_thread(page_text):
    """Last message of a conversation page's visible text -> {from_jiv, name, ts, text}, or None.

    Why not the last <li>: a message with paragraphs or bullets spans many <li>, its body is not in
    the header item, and the last one can be a bullet from the middle of the message, so the sender
    cannot be read from it. The expanded last message always carries a `<sender@email>` header line,
    which identifies the sender without guessing. Older collapsed messages have none, so fall back to
    the name on the last timestamp line.
    """
    lines = [l.strip() for l in (page_text or "").splitlines()]
    end = len(lines)
    for i, l in enumerate(lines):
        if any(l.startswith(m) for m in FOOTER_MARKERS) and i > 0:
            end = i
            break
    lines = lines[:end]
    email_idx = [i for i, l in enumerate(lines) if EMAIL_LINE_RE.match(l)]
    if email_idx:
        e = email_idx[-1]
        email = lines[e].strip("<>").lower()
        before = [l for l in lines[:e] if l]
        name = next((l for l in reversed(before) if not TS_RE.fullmatch(l) and len(l) > 3), "an employer")
        ts_line = next((l for l in reversed(before) if TS_RE.fullmatch(l)), "")
        body = [l for l in lines[e + 1:] if l and not TS_RE.fullmatch(l)]
        return {"from_jiv": email == JIV_EMAIL or "jiv" in name.lower(), "name": name[:60],
                "ts": last_timestamp(ts_line), "text": "\n".join(body).strip()}
    ts_idx = [i for i, l in enumerate(lines) if TS_RE.fullmatch(l)]
    if not ts_idx:
        return None
    t = ts_idx[-1]
    rest = [l for l in lines[t + 1:] if l]
    name = next((l for l in rest if len(l) > 3), "an employer")
    return {"from_jiv": "jiv" in name.lower() and "tuban" in name.lower(), "name": name[:60],
            "ts": last_timestamp(lines[t]), "text": "\n".join(rest[1:]).strip()}


def recent_replies(cstate, now):
    return [t for t in (cstate or {}).get("bot_replies", []) if now - datetime.fromtimestamp(t) < WINDOW]


def decide(msg, cstate, now):
    """Return (action, detail). `msg` is parse_thread()'s result; `cstate` is this thread's saved
    state, or None if never seen."""
    if msg is None or msg["from_jiv"]:
        return "none", "Jiv wrote last or nothing readable"
    text = msg["text"]
    sig = signature(text)
    if cstate and cstate.get("sig") == sig:
        return "none", "already handled"
    ts = msg["ts"]
    if (cstate is None or cstate.get("legacy")) and ts and now - ts > STALE_AFTER:
        return "baseline", "first sight and the last message is old"
    if cstate and cstate.get("handoff"):
        return "handoff_msg", "thread already handed to Jiv"
    kind = meeting_signal(text)
    if kind:
        return "meeting", kind
    if needs_read(text):
        return "notify_only", "questionnaire or work with a deadline"
    if len(recent_replies(cstate, now)) >= MAX_BOT_REPLIES:
        return "cap", f"{MAX_BOT_REPLIES} bot replies in 7 days"
    if needs_asset(text):
        return "reply_notify", "video or form requested"
    return "reply", ""
