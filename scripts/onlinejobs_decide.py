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

from meeting_signal import WHEN_RE, meeting_signal

STALE_AFTER = timedelta(hours=48)    # first sight older than this is only baselined
MAX_BOT_REPLIES = 3                  # per thread per 7 days; mirrors the LinkedIn inbox end gate
WINDOW = timedelta(days=7)

# Something only Jiv can produce: a video, a recording, a form. The bot still sends a holding reply.
NEEDS_ASSET_RE = re.compile(
    r"\b(video|loom|vidyard|screen ?record\w*|record(ing)? (yourself|a)|selfie)\b"
    r"|forms\.gle|docs\.google\.com/forms|typeform\.com|tally\.so|airtable\.com/\S*form"
    # Asking for specific examples of his work: only Jiv can pick and send them, so the bot must not improvise.
    r"|\bexamples? of\b|\bcase stud(y|ies)\b|\b(send|share|provide|attach|show)\b[^.\n]{0,30}\b(examples?|samples?|portfolio|case stud\w+)\b",
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


# ---------------------------------------------------------------------------------------------
# Whole-thread parsing, follow-up nudges, draft safety and the daily digest (added 2026-10-19).
# ---------------------------------------------------------------------------------------------
from meeting_signal import booking_links  # noqa: E402


def parse_messages(page_text):
    """Every message in a conversation page, oldest first: [{from_jiv, name, ts, text}].

    Needs the thread EXPANDED first (the checker clicks the collapsed headers): collapsed older
    messages show only a one-line preview, so a calendar link sent three messages ago is invisible
    until then. Each expanded message carries its own `<sender@email>` header line, so the page text
    is split at those. Messages that are still collapsed have no email line and are skipped."""
    lines = [l.strip() for l in (page_text or "").splitlines()]
    end = len(lines)
    for i, l in enumerate(lines):
        if any(l.startswith(m) for m in FOOTER_MARKERS) and i > 0:
            end = i
            break
    lines = lines[:end]
    email_idx = [i for i, l in enumerate(lines) if EMAIL_LINE_RE.match(l)]
    starts = []
    for e in email_idx:
        s = e
        for k in range(1, 4):                      # header is [timestamp, initials?, name, <email>]
            if e - k >= 0 and TS_RE.fullmatch(lines[e - k]):
                s = e - k
                break
        starts.append(s)
    out = []
    for n, e in enumerate(email_idx):
        nxt = starts[n + 1] if n + 1 < len(starts) else len(lines)
        header = [l for l in lines[starts[n]:e] if l]
        name = next((l for l in reversed(header) if not TS_RE.fullmatch(l) and len(l) > 3), "an employer")
        ts_line = next((l for l in header if TS_RE.fullmatch(l)), "")
        email = lines[e].strip("<>").lower()
        body = [l for l in lines[e + 1:nxt] if l and not TS_RE.fullmatch(l)]
        out.append({"from_jiv": email == JIV_EMAIL or "jiv" in name.lower(), "name": name[:60],
                    "ts": last_timestamp(ts_line), "text": "\n".join(body).strip()})
    return out


def thread_booking_links(messages):
    """Booking links from every message THEY wrote, newest first, deduped. Jiv's own messages are
    skipped: his application text carries his portfolio links, and a reply may quote availability."""
    seen = []
    for m in reversed(messages or []):
        if m["from_jiv"]:
            continue
        for link in booking_links(m["text"]):
            if link not in seen:
                seen.append(link)
    return seen


# --- follow-up when an alarmed meeting thread goes quiet --------------------------------------
NUDGE_AFTER = (timedelta(hours=4), timedelta(hours=24))   # then stop: two reminders, not a siren


def nudge_due(cstate, now):
    """Index (0 or 1) of the next unsent reminder for an alarmed thread Jiv has not answered, else None."""
    if not cstate or not cstate.get("alarm_ts") or cstate.get("resolved"):
        return None
    sent = cstate.get("nudges", 0)
    if sent >= len(NUDGE_AFTER):
        return None
    age = now - datetime.fromtimestamp(cstate["alarm_ts"])
    return sent if age >= NUDGE_AFTER[sent] else None


def _squash(t):
    return " ".join((t or "").split())


def jiv_took_over(msg, cstate):
    """Jiv's message in an alarmed or needs-you thread counts as taking over. The bot's own courtesy reply is also
    sent from Jiv's account, so it must not: compare against the text the bot recorded sending."""
    if not msg or not msg["from_jiv"] or not cstate or not (cstate.get("alarm_ts") or cstate.get("needs_you")):
        return False
    probe = cstate.get("bot_probe", "")
    return not (probe and _squash(msg["text"]).startswith(probe))


# --- draft safety: never send something obviously broken to an employer ----------------------
BAD_DRAFT_RE = re.compile(
    r"\[[^\]]{1,40}\]|\{[^}]{1,40}\}|<[^>]{1,40}>|\bas an ai\b|\blanguage model\b|\bi (can't|cannot) (assist|help)\b"
    r"|\bundefined\b|\bnull\b|\bTODO\b|\blorem ipsum\b|```",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s)>\]]+", re.I)


def reply_ok(draft, allowed_urls=()):
    """(True, "") if the drafted reply is safe to send, else (False, reason)."""
    t = (draft or "").strip()
    if len(t) < 40:
        return False, "too short"
    if len(t) > 1200:
        return False, "too long"
    if BAD_DRAFT_RE.search(t):
        return False, "placeholder or model boilerplate in the draft"
    if "—" in t or "–" in t:
        return False, "dash left in the draft"
    if "jiv" not in t.lower():
        return False, "missing the Jiv Tuban sign-off"
    allowed = tuple(allowed_urls)
    for url in URL_RE.findall(t):
        if not any(url.rstrip(".,;") .startswith(a.rstrip("/")) or a.rstrip("/").startswith(url.rstrip(".,;/")) for a in allowed):
            return False, f"invented link: {url[:60]}"
    return True, ""


# --- event log + daily digest -----------------------------------------------------------------
EVENT_KEEP = timedelta(days=14)


def record_event(state, kind, who, thread_id, now):
    """Append to state['events'] (kinds: reply, meeting, needs, nudge, health) and drop old ones."""
    ev = state.setdefault("events", [])
    ev.append({"t": now.timestamp(), "k": kind, "who": who, "id": thread_id})
    cutoff = (now - EVENT_KEEP).timestamp()
    state["events"] = [e for e in ev if e["t"] >= cutoff]


def build_digest(state, now, hours=24):
    """One short text for the daily Discord digest, or None when there is nothing to say."""
    since = (now - timedelta(hours=hours)).timestamp()
    ev = [e for e in state.get("events", []) if e["t"] >= since]
    count = lambda k: sum(1 for e in ev if e["k"] == k)
    open_items = []
    for tid, c in state.get("convs", {}).items():
        if c.get("resolved"):
            continue
        if c.get("alarm_ts"):
            open_items.append(f"{c.get('who', tid)}: meeting, no reply from you yet")
        elif c.get("needs_you"):
            open_items.append(f"{c.get('who', tid)}: {c['needs_you']}")
    if not ev and not open_items:
        return None
    # Only what happened: "0 bot replies, 0 meetings, 0 problems" is a line of zeros nobody reads.
    parts = [f"{n} {label}" for n, label in ((count('reply'), "bot replies"), (count('meeting'), "meeting requests"),
                                              (count('needs'), "needing you"), (count('health'), "automation problems"))
             if n]
    lines = [f"**OnlineJobs, last {hours}h:** " + (", ".join(parts) if parts else "quiet.")]
    if open_items:
        lines.append("Still open for you:")
        lines += [f"- {x}" for x in open_items[:8]]
        if len(open_items) > 8:
            lines.append(f"- and {len(open_items) - 8} more")
    return "\n".join(lines)


# --- alert hygiene (added 2026-10-22) ---------------------------------------------------------
# The phone got a push for every transient blip (a 30 s login timeout, an inbox that rendered late) and
# an emergency alarm for a mass "join our Discord" message. Seven false "problems" in three days, all
# self-healed on the next run. A problem is now news only if it persists, and an alarm only if there is
# something to act on: a booking link or a concrete time.
HEALTH_INFO_AT = 3    # consecutive failed runs (30 min apart) before Discord hears about it
HEALTH_PUSH_AT = 6    # ...and before the phone does


def health_step(state, kind, failed, now):
    """Track consecutive failures of one automation check. Returns None, "info" (tell Discord) or
    "push" (tell the phone). Each level fires ONCE per streak, on the run that reaches it; a success
    resets the streak silently, so a blip that heals itself is never mentioned."""
    h = state.setdefault("health", {})
    if not failed:
        h.pop(kind, None)
        return None
    rec = h.setdefault(kind, {"streak": 0, "since": now.timestamp()})
    rec["streak"] += 1
    if rec["streak"] == HEALTH_PUSH_AT:
        return "push"
    if rec["streak"] == HEALTH_INFO_AT:
        return "info"
    return None


APPLY_HEARTBEAT_STALE_S = 150 * 60   # runner ticks hourly: one missed tick plus slack, not a blip


def heartbeat_stale(beat_ts, now_ts, limit_s=APPLY_HEARTBEAT_STALE_S):
    """Dead-man check for the MacBook apply runner, which writes a timestamp to the Mini every tick.
    Why here and not on the laptop: a sleeping or closed laptop cannot report its own silence, the
    always-on Mini can. None (no heartbeat ever written) is not stale: nothing is late yet."""
    return beat_ts is not None and now_ts - beat_ts > limit_s


def tidy(text, limit=220):
    """A readable preview of an employer message: greeting and sign-off dropped, whitespace squashed,
    cut at a sentence end if one fits, else at a word, never mid-word."""
    t = _squash(text)
    t = re.sub(r"^(hi|hello|hey|good (morning|afternoon|evening)|dear)\b[^,.!]{0,40}[,.!]\s*", "", t, flags=re.I)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end >= limit * 0.5:
        return cut[:end + 1]
    return cut[:cut.rfind(" ")].rstrip(",;:") + "..." if " " in cut else cut + "..."


def alarm_level(text):
    """"meeting" (the iPhone emergency alarm that repeats until acknowledged) only when there is a
    booking link or a concrete time to act on. A bare "we will set up an interview" is a normal push."""
    kind = meeting_signal(text)
    if kind == "link":
        return "meeting"
    if kind == "ask" and (WHEN_RE.search(text or "") or re.search(r"\b(are you (free|available)|when (are|can|will|would) you|your availability|what (time|day))", text or "", re.I)):
        return "meeting"
    return "needs"


# --- availability text that stays correct across the US daylight-saving change ----------------
def availability_text(on):
    """His call window is fixed in Manila time (10 PM to 12 AM PHT, Monday to Friday). New York moves an
    hour on 2026-11-01, so a hardcoded "EST" is wrong half the year; convert for the given date."""
    from zoneinfo import ZoneInfo
    start = datetime(on.year, on.month, on.day, 22, 0, tzinfo=ZoneInfo("Asia/Manila"))
    ny = ZoneInfo("America/New_York")
    s, e = start.astimezone(ny), (start + timedelta(hours=2)).astimezone(ny)
    fmt = lambda d: d.strftime("%I %p").lstrip("0")
    return f"Monday to Friday, 10 PM to 12 AM PHT (2 PM to 4 PM UTC, {fmt(s)} to {fmt(e)} {s.tzname()})"
