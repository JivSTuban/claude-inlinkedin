#!/opt/homebrew/bin/python3.10
"""
OnlineJobs.ph Message Checker
Logs into onlinejobs.ph via Playwright (Python), checks the inbox,
and auto-replies to employer messages using the Codex CLI (ChatGPT plan; the Claude CLI on this Mini is not logged in).

Config: ~/.job-followup-config.json
State:  ~/Work/job-email-bot/oj-state.json  (per conversation: last handled message, bot reply times, handoff)
Cron:   */30 * * * *   (the run window below limits it to 16:00-22:59 UTC)
Goal:   the replies exist to reach a booked meeting. When an employer proposes one, Jiv is alarmed on
        his iPhone (scripts/linkedin-notify.py --level meeting) and the thread is handed to him.
Rules:  scripts/onlinejobs_decide.py (tested in tests/battle/test_onlinejobs_decide.py)
Deploy: scp this file to ~/Work/job-email-bot/ and onlinejobs_decide.py + meeting_signal.py to
        ~/agent-work/jobi/scripts/ on the Mini. Mini-only, not a git checkout.
"""

import json
import fcntl
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

# Shared decision logic and notifier live with the LinkedIn scripts the Mini already deploys.
SCRIPTS_DIR = os.path.expanduser("~/agent-work/jobi/scripts")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # repo checkout: scripts/ sits beside this file
import onlinejobs_decide as decide_mod  # noqa: E402
import onlinejobs_forms as forms_mod  # noqa: E402
from meeting_signal import booking_links  # noqa: E402

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.expanduser("~/.job-followup-config.json")
STATE_FILE  = os.path.join(BASE_DIR, "oj-state.json")
LOG_FILE    = os.path.join(BASE_DIR, "followup.log")
LOCK_FILE   = os.path.join(BASE_DIR, "onlinejobs-check.lock")
# Own kill switch, NOT the shared job-email-bot.disabled. That file (2026-07-18, repeated interview
# scheduling emails) still gates job-followup.py and oj-apply.py; this script has its own reply guard
# (oj-state.json) and was split off 2026-10-19. Create this file to stop only the OnlineJobs reply.
DISABLE_FILE = os.path.join(BASE_DIR, "onlinejobs-check.disabled")
# Scoped kill switch for the external-application scan only; replies keep running. Create it to stop the scan.
FORMS_DISABLE_FILE = os.path.join(BASE_DIR, "onlinejobs-forms.disabled")
FORMS_SCAN_EVERY_S = 3 * 3600   # new postings land all day, but a scan costs a page load per unseen posting
FORMS_MAX_FETCH = 80            # unseen postings opened per run; a bigger backlog finishes on the next run
FORMS_KEEP_DAYS = 14            # a lead nobody acted on in two weeks is stale
PROFILE_FILE = os.path.join(BASE_DIR, "profile-kb.md")
FACTS_FILE   = os.path.join(BASE_DIR, "oj-profile-facts.md")   # verified current facts, versioned in the jobi repo
MAX_THREADS = 25   # inbox rows scanned per run; each costs a page load
AI_WORK_PROFILE_FILE = "/Users/admin/Documents/ai-work-kb/streams/personal/JOB_PROFILE.md"

SENDER_NAME  = "Jiv Tuban"
ROLE         = "Full-Stack Developer & AI Engineer"
AVAILABILITY = "Monday to Friday: 10 PM – 12 AM PHT (2 PM – 4 PM UTC | 10 AM – 12 PM EST)"
# Standalone codex, NOT /opt/homebrew/bin/codex: the brew cask 0.155.0 hung on every call (even
# --version) after the Codex app self-updated on 2026-09-30. Same pick as linkedin-codex-runner.sh.
CODEX_STANDALONE = os.path.expanduser("~/.codex/packages/standalone/current/bin/codex")
CODEX_BIN    = CODEX_STANDALONE if os.path.exists(CODEX_STANDALONE) else "/opt/homebrew/bin/codex"

OJ_EMAIL    = ""
OJ_PASSWORD = ""


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] [OJ] {msg}"
    # cron redirects stdout into this same file, so printing there as well wrote every line twice.
    if sys.stdout.isatty():
        print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

if os.path.exists(DISABLE_FILE):
    log(f"Automation disabled by {DISABLE_FILE}; exiting before OnlineJobs login or reply")
    sys.exit(0)

_lock_handle = None

def acquire_lock():
    global _lock_handle
    _lock_handle = open(LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another OnlineJobs check instance is already running, exiting")
        sys.exit(0)


def load_profile_context():
    """Verified facts first (they must never be cut off), then as much of the profile as fits. The
    profile file alone predates his current roles and says nothing about GoHighLevel or Traciety, so a
    draft built from it denied experience he has."""
    parts = []
    for path in (FACTS_FILE, os.path.join(SCRIPTS_DIR, "oj-profile-facts.md")):
        try:
            with open(path) as f:
                parts.append(f.read().strip())
            break
        except Exception:
            pass
    for path in (AI_WORK_PROFILE_FILE, PROFILE_FILE):
        try:
            with open(path) as f:
                parts.append(f.read().strip()[:3500])
            break
        except Exception:
            pass
    return "\n\n".join(parts) or f"{SENDER_NAME}, {ROLE}. Availability: {AVAILABILITY}"


def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("replied", [])   # legacy: threads the old once-per-thread logic had answered
    state.setdefault("convs", {})     # id -> {"sig": last handled employer message, "bot_replies": [epoch], "handoff": bool}
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_bad_claude_output(text):
    low = (text or "").strip().lower()
    bad_markers = [
        "not logged in",
        "please log in",
        "run /login",
        "claude.ai/code",
        "authentication",
        "api key",
    ]
    return any(marker in low for marker in bad_markers)


def clean_reply(text):
    """No em/en-dashes in anything sent to an employer (Jiv's standing rule); models reach for them."""
    return text.replace("\u2014", ", ").replace("\u2013", "-").strip()


def run_claude(prompt):
    """Draft a reply with codex. Name kept so the call site is unchanged; it no longer uses Claude."""
    out_path = None
    try:
        fd, out_path = tempfile.mkstemp(prefix="oj-reply-", suffix=".txt")
        os.close(fd)
        # read-only + ephemeral: this only has to write text, never touch files or keep a session.
        result = subprocess.run(
            [CODEX_BIN, "exec", "--skip-git-repo-check", "-s", "read-only", "--ephemeral",
             "-C", "/tmp", "-o", out_path, prompt],
            capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()[-2:]
            log(f"  codex failed ({result.returncode}): {' | '.join(detail)}")
            return ""
        with open(out_path) as f:
            output = f.read().strip()
        if is_bad_claude_output(output):
            log(f"  codex unavailable/auth required: {output[:80]}")
            return ""
        return clean_reply(output)
    except Exception as e:
        log(f"  codex error: {e}")
        return ""
    finally:
        if out_path and os.path.exists(out_path):
            os.remove(out_path)


def _squash(t):
    return " ".join((t or "").split())


def reply_posted(page, url, reply_text):
    """True only if the reply is visible in the reloaded thread. Clicking SEND proves nothing:
    a validation error or expired session leaves the text in the box and the click still 'works'."""
    probe = _squash(reply_text)[:60]
    if not probe:
        return False
    page.goto(url)
    page.wait_for_timeout(2500)
    items = page.eval_on_selector_all("li", "i => i.map(li => li.innerText.trim())")
    return any(probe in _squash(t) for t in items)


NOTIFY_SCRIPT = os.path.join(SCRIPTS_DIR, "linkedin-notify.py")


def notify_jiv(text, level="needs", title=None, url=None, key=None, links_from=""):
    """Reuse the shared notifier (Discord DM, plus Pushover for needs/meeting). `key` rings once per
    event, so a meeting thread does not alarm again on every 30 minute run. The alert carries the
    conversation link (`url`) and any booking link found in `links_from`."""
    cmd = ["python3", NOTIFY_SCRIPT, "--text", text, "--level", level]
    # Booking links come from the FULL message: the preview in `text` is cut at 400 chars and may lose one.
    calendar = " ".join(booking_links(links_from))
    for flag, val in (("--title", title), ("--url", url), ("--key", key), ("--calendar", calendar)):
        if val:
            cmd += [flag, val]
    try:
        subprocess.run(cmd, timeout=40, check=True, capture_output=True, stdin=subprocess.DEVNULL)
        return True
    except Exception as e:
        log(f"  notify failed ({level}): {e}")
        return False


def send_reply(page, url, reply_text):
    """Fill the reply box, click SEND MESSAGE, then confirm the text is in the thread.
    Returns True only if the reply is verifiably posted."""
    goto_retry(page, url)
    page.wait_for_timeout(2000)
    box = page.query_selector('div[contenteditable="true"], [role="textbox"], textarea')
    if not box:
        log("  \u274c No reply box found")
        return False
    box.fill(reply_text)
    page.wait_for_timeout(500)
    send_btn = page.query_selector('button:has-text("SEND MESSAGE")')
    if not send_btn:
        log("  \u274c No SEND MESSAGE button found")
        return False
    send_btn.click()
    page.wait_for_timeout(2500)
    return reply_posted(page, url, reply_text)


STANDING_FACTS = (
    "Standing facts you may use when asked (never invent others): full-time, 40 hours a week, any timezone, "
    "can start immediately; rate expectation $1,000 to $4,000 per month (about $6 to $25 per hour, higher for more senior scope), open to a "
    "fixed price or a paid trial; internet 50 Mbps down and 163 Mbps up; based in Lapu-Lapu City, Cebu, Philippines."
)


def goto_retry(page, url, tries=2):
    """page.goto with one retry: onlinejobs.ph occasionally answers net::ERR_ABORTED to a first navigation."""
    for attempt in range(tries):
        try:
            page.goto(url)
            return
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3)


def expand_thread(page):
    """Open every collapsed message so its full text is readable (older messages show a one-line preview
    otherwise, hiding links sent earlier). Client side only: nothing is written to the account."""
    opened = 0
    for btn in page.query_selector_all('button[id^="radix-"][aria-expanded="false"]:not([aria-haspopup])'):
        try:
            btn.click(timeout=2000)
            opened += 1
        except Exception:
            pass
    if opened:
        page.wait_for_timeout(600)
    return opened


def read_thread(page):
    """Expand, then parse the whole conversation. Returns (msg, messages) or (None, [])."""
    expand_thread(page)
    text = page.inner_text("body")
    messages = decide_mod.parse_messages(text)
    msg = dict(messages[-1]) if messages else decide_mod.parse_thread(text)
    if msg is None:
        return None, []
    # Booking links from EVERY message they wrote, not just the latest; and a short readable history.
    msg["links_text"] = " ".join(decide_mod.thread_booking_links(messages))
    msg["conversation"] = "\n\n".join(
        f"{'Me' if m['from_jiv'] else m['name']}: {m['text'][:500]}" for m in messages[-6:]) or msg["text"]
    return msg, messages


def health(state, now, kind, text):
    """The automation itself is in trouble. Never silent, but never a false alarm either: a blip that
    heals on the next run says nothing. Discord hears at 3 failed runs in a row, the phone at 6
    (decide_mod.health_step). Call healthy() on the success path to reset the streak."""
    level = decide_mod.health_step(state, kind, True, now)
    if level is None:
        return
    runs = state["health"][kind]["streak"]
    decide_mod.record_event(state, "health", kind, kind, now)
    notify_jiv(f"{text} It has failed {runs} runs in a row (about {runs * 30} minutes).",
               level="needs" if level == "push" else "info", title="OnlineJobs automation problem",
               key=f"oj:health:{kind}:{level}:{now:%Y-%m-%d-%H}")


def healthy(state, now, kind):
    decide_mod.health_step(state, kind, False, now)


def send_digest(state, now):
    """Once a day, after 09:00 local, a short Discord summary (info level: no Pushover) of the last 24h and
    what is still open for Jiv. Skipped when there is nothing to say."""
    today = f"{now:%Y-%m-%d}"
    if now.hour < 9 or state.get("digest_date") == today:
        return
    state["digest_date"] = today
    text = decide_mod.build_digest(state, now)
    if text:
        notify_jiv(text, level="info", key=f"oj:digest:{today}")


def scan_forms(page, state, now):
    """Find postings that send the candidate OUT of the site (Google Form, Typeform, ATS page, apply
    email) and queue them in state["forms"]["leads"] for the /onlinejobs-apply skill, which does the
    filling. Native postings are autonomousapply.com's job and never queued. Alert-only: this sends
    nothing to any employer. Never raises: a broken scan must not stop the reply path.

    state["forms"] = {last_scan, seen: {id: [verdict, epoch]}, leads: {id: lead + first_seen/alerted}, fails}
    """
    fs = state.setdefault("forms", {})
    fs.setdefault("seen", {})
    fs.setdefault("leads", {})
    if os.path.exists(FORMS_DISABLE_FILE):
        return
    if now.timestamp() - fs.get("last_scan", 0) < FORMS_SCAN_EVERY_S:
        return
    try:
        found = {}
        for kw, offset in forms_mod.search_plan():
            goto_retry(page, forms_mod.search_url(kw, offset))
            page.wait_for_timeout(2000)
            for href in page.eval_on_selector_all("a[href*='/jobseekers/job/']", "els => els.map(e => e.href)"):
                found.setdefault(forms_mod.posting_id(href), href)
        fresh = [(i, u) for i, u in found.items() if i not in fs["seen"]]
        batch, backlog = fresh[:FORMS_MAX_FETCH], max(0, len(fresh) - FORMS_MAX_FETCH)
        new_leads, skips = [], {}
        for pid, url in batch:
            try:
                goto_retry(page, url)
                page.wait_for_timeout(900)
                lead = forms_mod.parse_posting(url, page.inner_text("body"))
            except Exception as e:
                log(f"  forms: could not read posting {pid}: {type(e).__name__}")
                continue
            ok, why = forms_mod.judge(lead)
            fs["seen"][pid] = ["lead" if ok else why, now.timestamp()]
            if ok:
                lead.update(first_seen=now.timestamp(), alerted=False)
                fs["leads"][pid] = lead
            else:
                skips[why] = skips.get(why, 0) + 1
        # No alert per lead any more (2026-10-22): they were raw URLs, "N/A" wages and obvious misfits, and
        # applying is the MacBook runner's job, which reports what it DID. `alerted` stays for old state.
        unalerted = [l for l in fs["leads"].values() if not l.get("alerted")]
        for l in unalerted:
            l["alerted"] = True
        cutoff = (now - timedelta(days=FORMS_KEEP_DAYS)).timestamp()
        fs["leads"] = {i: l for i, l in fs["leads"].items() if l["first_seen"] >= cutoff}
        fs["seen"] = {i: v for i, v in fs["seen"].items() if v[1] >= cutoff - 14 * 86400}
        if not backlog:
            fs["last_scan"] = now.timestamp()   # unset while a backlog remains, so the next run continues
        fs["fails"] = 0
        log(f"  forms: {len(found)} on page 1, {len(batch)} opened, {len(unalerted)} new lead(s), skipped {skips or 0}, backlog {backlog}")
    except Exception as e:
        fs["fails"] = fs.get("fails", 0) + 1
        log(f"  forms scan error ({fs['fails']}): {type(e).__name__}: {e}")
        if fs["fails"] >= 3:
            health(state, now, "forms", f"The OnlineJobs external-form scan failed {fs['fails']} runs in a row ({type(e).__name__}). "
                                        "Replies are unaffected. The board layout may have changed.")


def run():
    global OJ_EMAIL, OJ_PASSWORD

    # Replies only go out 12 AM-6 AM PHT (16:00-22:59 UTC), but the scan and the ALERTS run all day:
    # a meeting request at 10 AM must ring Jiv at 10 AM, not at midnight. Outside the window the run
    # is alert-only and leaves every reply-needing thread untouched for the night run.
    utc_hour = datetime.now(timezone.utc).hour
    can_reply = 16 <= utc_hour <= 22
    acquire_lock()

    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        OJ_EMAIL    = cfg["email"]
        OJ_PASSWORD = cfg.get("oj_password", cfg.get("app_password", "")).replace(" ", "")
    except Exception as e:
        log(f"Config error: {e}")
        sys.exit(1)

    state = load_state()
    now = datetime.now()
    log("OnlineJobs.ph check starting...")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("playwright not installed — run: /opt/homebrew/bin/python3.10 -m pip install playwright && python3.10 -m playwright install chromium")
        sys.exit(1)

    problems = []     # reply-side trouble this run, alerted once at the end

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        goto_retry(page, "https://v2.onlinejobs.ph/login")
        page.wait_for_timeout(2000)

        if "/login" in page.url:
            try:
                # Use page.type() to trigger React change events (page.fill doesn't work)
                page.click('input[name="email"]')
                page.type('input[name="email"]', OJ_EMAIL, delay=30)
                page.click('input[name="password"]')
                page.type('input[name="password"]', OJ_PASSWORD, delay=30)
                page.click('button[type="submit"]')
                page.wait_for_timeout(4000)
            except Exception as e:
                log(f"Login error: {e}")
                health(state, now, "login", f"The OnlineJobs checker could not log in ({type(e).__name__}). Replies and alerts are paused until it can.")
                save_state(state)
                browser.close()
                return

        if "/login" in page.url:
            log("Login failed — check credentials")
            health(state, now, "login", "The OnlineJobs login was rejected (password changed or a captcha). Replies and alerts are paused until you fix it in ~/.job-followup-config.json.")
            save_state(state)
            browser.close()
            return

        log("Logged in successfully")
        healthy(state, now, "login")

        # The whole inbox, not ?unread=true: a thread Jiv opened on his phone is no longer "unread" but
        # may still be waiting on a reply. Rows have no links (data-cy="thread-<id>", click to open),
        # so state is keyed by that numeric id and a row is only opened when its preview text changed.
        goto_retry(page, "https://v2.onlinejobs.ph/message")
        page.wait_for_timeout(2500)
        try:
            rows = page.eval_on_selector_all(
                'div[data-cy^="thread-"][data-selected]',
                "els => els.map(el => [el.getAttribute('data-cy').replace('thread-', ''), el.innerText.trim().replace(/\\s+/g, ' ')])")
        except Exception as e:
            log(f"Could not read the inbox rows: {e}")
            health(state, now, "inbox", f"The OnlineJobs inbox could not be read ({type(e).__name__}). The page layout may have changed.")
            save_state(state)
            browser.close()
            return
        if not rows and state["convs"]:
            # It had threads before and now sees none: a late render or a changed page, not an empty inbox.
            # Seen 3 times in 3 days and healed each time, so it only counts once it persists.
            health(state, now, "inbox", "The OnlineJobs inbox shows 0 conversations but it had some before, so nothing is being watched.")
        else:
            healthy(state, now, "inbox")
        rows = rows[:MAX_THREADS]
        log(f"Found {len(rows)} conversation(s) in the inbox")
        changed = False
        read_errors = 0

        for thread_id, row_text in rows:
            known = state["convs"].get(thread_id)
            # Reminder for an alarmed meeting Jiv has not answered. Checked for EVERY known thread, before the
            # unchanged-row skip: a thread deferred to the night run has no saved row and would never get here.
            n = decide_mod.nudge_due(known, now)
            if n is not None:
                hours = int((now - datetime.fromtimestamp(known["alarm_ts"])).total_seconds() // 3600)
                if notify_jiv(f"{known.get('who', 'A thread')} is still waiting for your answer about a meeting ({hours}h).",
                              level="needs", title=f"Still waiting: {known.get('who', 'meeting')}",
                              url=known.get("link"), links_from=" ".join(known.get("calendar", [])),
                              key=f"oj:{known.get('code', thread_id)}:nudge{n}"):
                    known["nudges"] = n + 1
                    decide_mod.record_event(state, "nudge", known.get("who", ""), thread_id, now)
                    changed = True
            if known is not None and known.get("row") == row_text:
                continue                      # nothing new since the last look
            try:
                goto_retry(page, "https://v2.onlinejobs.ph/message")
                page.wait_for_timeout(1500)
                row_sel = f'div[data-cy="thread-{thread_id}"]'
                page.wait_for_selector(row_sel, timeout=10000)   # the list can render late
                page.click(row_sel, timeout=10000)
                page.wait_for_url("**/message/conversation/**", timeout=10000)
                page.wait_for_timeout(1500)
                link = page.url
                conv_id = link.rstrip("/").split("/")[-1]
                msg, _messages = read_thread(page)
            except Exception as e:
                log(f"  Error reading thread {thread_id}: {str(e).splitlines()[0][:120]}")
                read_errors += 1
                continue

            cstate = known
            # A thread the old once-per-thread logic answered, with no state yet, is not "first sight".
            if cstate is None and conv_id in state["replied"]:
                cstate = {"sig": "", "bot_replies": [now.timestamp()], "legacy": True}
            action, detail = decide_mod.decide(msg, cstate, now)
            cs = state["convs"].setdefault(thread_id, {"sig": "", "bot_replies": [], "handoff": False})
            if cstate is not None and cstate.get("legacy"):
                cs.update({k: v for k, v in cstate.items() if k not in cs or not cs[k]})
            cs["row"] = row_text
            cs["code"] = conv_id
            cs["link"] = link
            changed = True
            if decide_mod.jiv_took_over(msg, cs):
                cs["resolved"] = True         # Jiv answered himself: no more reminders, off the digest
                cs.pop("needs_you", None)
            if action == "none":
                continue

            who = msg["name"]
            body = decide_mod.tidy(msg["text"])
            sig = decide_mod.signature(msg["text"])
            cs["who"] = who
            log(f"  {thread_id}/{conv_id} ({who}): {action} {detail}".rstrip())

            if action == "baseline":
                cs["sig"] = sig
                continue

            if action == "meeting":
                # Alarm first: Jiv booking the call matters more than the courtesy reply succeeding.
                if not cs.get("alarm_ts"):
                    cs["alarm_ts"] = now.timestamp()
                    cs["nudges"] = 0
                    cs.pop("resolved", None)
                    decide_mod.record_event(state, "meeting", who, thread_id, now)
                cs["calendar"] = decide_mod.thread_booking_links(_messages)
                # Emergency alarm only with something to act on (a booking link or a concrete time).
                level = decide_mod.alarm_level(msg["text"] + " " + msg["links_text"])
                notify_jiv(f"{who} wants to meet: {body}",
                           level=level, title=(f"Meeting ready: {who}" if level == "meeting" else f"Meeting request: {who}"),
                           url=link, links_from=msg["links_text"], key=f"oj:{conv_id}:meeting")
                if not can_reply:
                    cs.pop("row", None)       # night run still sends the courtesy reply; the key stops a second ring
                    continue
                if _reply(page, link, conv_id, cs, sig, who, msg, now, state, problems, meeting=True):
                    cs["handoff"] = True      # the bot never talks in this thread again
                    cs["sig"] = sig
                continue

            if action in ("handoff_msg", "notify_only", "cap"):
                why = {"handoff_msg": "wrote again in a thread you took over",
                       "notify_only": "wants your own work (questions, a take-home or a deadline)",
                       "cap": "wrote again; auto-replies are paused after 3 this week"}[action]
                if notify_jiv(f"{who} {why}: {body}", level="needs", title=f"OnlineJobs: {who}", url=link,
                              links_from=msg["links_text"], key=f"oj:{conv_id}:{sig}"):
                    cs["sig"] = sig
                    cs["needs_you"] = {"handoff_msg": "new message after you took over", "notify_only": "your own work asked for",
                                       "cap": "bot paused after 3 replies"}[action]
                    cs.pop("resolved", None)
                    decide_mod.record_event(state, "needs", who, thread_id, now)
                continue

            # reply / reply_notify
            if not can_reply:
                if action == "reply_notify":  # a video/form ask is Jiv's work: tell him now, reply tonight
                    notify_jiv(f"{who} asked for a video or form. A holding reply goes out tonight: {body}",
                               level="needs", title=f"OnlineJobs needs you: {who}", url=link, links_from=msg["links_text"],
                               key=f"oj:{conv_id}:{sig}")
                    cs["needs_you"] = "video or form requested"
                    cs.pop("resolved", None)
                cs.pop("row", None)           # leave it unrecorded so the night run replies
                continue
            _reply(page, link, conv_id, cs, sig, who, msg, now, state, problems, asset=(action == "reply_notify"))

        if read_errors >= 3:
            health(state, now, "read", f"The OnlineJobs checker could not open {read_errors} conversations in one run.")
        else:
            healthy(state, now, "read")
        if problems:
            health(state, now, "reply", "The OnlineJobs reply step had trouble:\n- " + "\n- ".join(problems[:5]))
        else:
            healthy(state, now, "reply")
        scan_forms(page, state, now)
        send_digest(state, now)
        healthy(state, now, "crash")      # reached the end: the earlier crash streak is over
        state["last_run"] = now.timestamp()
        save_state(state)
        browser.close()

    log(f"  Done. {sum(len(c.get('bot_replies', [])) for c in state['convs'].values())} bot reply(ies) on record.\n")


def draft_reply(msg, who, asset, meeting, now, prior_fail=""):
    """Ask codex for the reply; returns the text or ''. Only facts in the profile and STANDING_FACTS may appear."""
    prompt = (
        "You are Jiv Tuban, a Full-Stack Developer & AI Engineer, replying to an employer on OnlineJobs.ph. "
        "Write ONE message that will be sent exactly as written. Rules:\n"
        "- Answer exactly what they asked first, in plain language. If you cannot answer from the facts below, say you will "
        "follow up with it. Never guess.\n"
        "- Use only the profile and standing facts below. Never invent employers, numbers, links, tools or times.\n"
        "- Mention availability only if they asked about scheduling, a call or hours.\n"
        "- 2 to 5 short sentences. No filler, no hype, no em dashes or en dashes, no placeholders in brackets.\n"
        f"- Greet them by name if it is a real name (theirs: {who}). End with the signature on separate lines: "
        f"{SENDER_NAME} then {ROLE}.\n\n"
        f"Profile:\n{load_profile_context()}\n\n"
        f"{STANDING_FACTS}\nAvailability for calls: {decide_mod.availability_text(now.date())}\n\n"
        f"Conversation so far, oldest to newest:\n{msg['conversation']}\n\n"
        f"Their latest message:\n{msg['text'][-700:]}"
    )
    if asset:
        prompt += ("\n\nThey are asking for something only you can produce (a video, recording or form). "
                   "Do NOT say it is done and do not invent links. Say you will send it shortly.")
    if meeting:
        prompt += ("\n\nThey want to book a meeting. Say you are glad to meet and give your availability window. "
                   "If they asked YOU to send the invite or link, say you will send it shortly (do not ask them to send it). "
                   "If they sent a booking link, say you will pick a slot now. If they asked when you are free, just answer. "
                   "Do not invent times outside your availability.")
    if prior_fail:
        prompt += f"\n\nYour previous draft was rejected because: {prior_fail}. Fix that."
    return run_claude(prompt)


def _reply(page, link, conv_id, cs, sig, who, msg, now, state, problems, asset=False, meeting=False):
    """Draft (with a safety check and one retry), send, verify. On success records the handled message,
    the reply time and what the bot said. Returns True if sent."""
    allowed = decide_mod.URL_RE.findall(load_profile_context()) + decide_mod.URL_RE.findall(msg["conversation"])
    reply_text, fail = "", ""
    for _ in range(2):
        reply_text = draft_reply(msg, who, asset, meeting, now, fail)
        if not reply_text:
            fail = "no draft was produced"
            continue
        ok, fail = decide_mod.reply_ok(reply_text, allowed)
        if ok:
            break
        log(f"  Draft for {conv_id} rejected: {fail}")
        reply_text = ""
    if not reply_text:
        cs["draft_fails"] = cs.get("draft_fails", 0) + 1
        log(f"  No safe reply drafted for {conv_id} ({fail}), attempt {cs['draft_fails']}")
        if cs["draft_fails"] >= 2:
            # Stop retrying every 30 minutes: hand it to Jiv and mark this message handled.
            notify_jiv(f"The bot could not write a safe reply to {who} ({fail}): {decide_mod.tidy(msg['text'])}",
                       level="needs", title=f"OnlineJobs needs you: {who}", url=link, links_from=msg["links_text"],
                       key=f"oj:{conv_id}:{sig}")
            cs["sig"] = sig
            cs["needs_you"] = "bot could not draft a safe reply"
            decide_mod.record_event(state, "needs", who, conv_id, now)
        else:
            problems.append(f"{who}: no safe draft ({fail})")
        return False
    try:
        if not send_reply(page, link, reply_text):
            log(f"  \u274c Reply to {conv_id} not confirmed in the thread; not recorded, will retry")
            problems.append(f"{who}: reply not confirmed in the thread")
            return False
    except Exception as e:
        log(f"  Send error for {conv_id}: {e}")
        problems.append(f"{who}: send error {type(e).__name__}")
        return False
    log(f"  \u2705 Replied to {conv_id} (verified in thread)")
    cs["sig"] = sig
    cs["draft_fails"] = 0
    cs["bot_probe"] = decide_mod._squash(reply_text)[:60]   # so Jiv's own later reply can be told apart
    cs.setdefault("bot_replies", []).append(now.timestamp())
    decide_mod.record_event(state, "reply", who, conv_id, now)
    if asset:
        cs["needs_you"] = "video or form requested (holding reply sent)"
        cs.pop("resolved", None)
        decide_mod.record_event(state, "needs", who, conv_id, now)
        notify_jiv(f"{who} asked for a video or form. A holding reply is sent; you owe them the real thing: {decide_mod.tidy(msg['text'])}",
                   level="needs", title=f"OnlineJobs needs you: {who}", url=link, links_from=msg["links_text"],
                   key=f"oj:{conv_id}:{sig}")
    return True


def main():
    """Run, and if the checker itself crashes tell Jiv once a day instead of failing silently."""
    try:
        run()
    except SystemExit:
        raise
    except Exception as e:
        log(f"Unhandled error: {type(e).__name__}: {e}")
        state = load_state()
        health(state, datetime.now(), "crash",
               f"The OnlineJobs checker crashed ({type(e).__name__}: {(str(e).splitlines() or [''])[0][:120]}). Replies and alerts are not running.")
        save_state(state)
        sys.exit(1)


if __name__ == "__main__":
    main()
