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
from datetime import datetime, timezone

# Shared decision logic and notifier live with the LinkedIn scripts the Mini already deploys.
SCRIPTS_DIR = os.path.expanduser("~/agent-work/jobi/scripts")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # repo checkout: scripts/ sits beside this file
import onlinejobs_decide as decide_mod  # noqa: E402

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.expanduser("~/.job-followup-config.json")
STATE_FILE  = os.path.join(BASE_DIR, "oj-state.json")
LOG_FILE    = os.path.join(BASE_DIR, "followup.log")
LOCK_FILE   = os.path.join(BASE_DIR, "onlinejobs-check.lock")
# Own kill switch, NOT the shared job-email-bot.disabled. That file (2026-07-18, repeated interview
# scheduling emails) still gates job-followup.py and oj-apply.py; this script has its own reply guard
# (oj-state.json) and was split off 2026-10-19. Create this file to stop only the OnlineJobs reply.
DISABLE_FILE = os.path.join(BASE_DIR, "onlinejobs-check.disabled")
PROFILE_FILE = os.path.join(BASE_DIR, "profile-kb.md")
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
ANTHROPIC_KEY = ""


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] [OJ] {msg}"
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
    for path in (AI_WORK_PROFILE_FILE, PROFILE_FILE):
        try:
            with open(path) as f:
                return f.read().strip()[:4000]
        except Exception:
            pass
    return f"{SENDER_NAME}, {ROLE}. Availability: {AVAILABILITY}"


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


def notify_jiv(text, level="needs", title=None, url=None, key=None):
    """Reuse the shared notifier (Discord DM, plus Pushover for needs/meeting). `key` rings once per
    event, so a meeting thread does not alarm again on every 30 minute run."""
    cmd = ["python3", NOTIFY_SCRIPT, "--text", text, "--level", level]
    for flag, val in (("--title", title), ("--url", url), ("--key", key)):
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
    page.goto(url)
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


def run():
    global OJ_EMAIL, OJ_PASSWORD, ANTHROPIC_KEY

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
        ANTHROPIC_KEY = cfg.get("anthropic_key", "")
    except Exception as e:
        log(f"Config error: {e}")
        sys.exit(1)

    state = load_state()
    log("OnlineJobs.ph check starting...")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("playwright not installed — run: /opt/homebrew/bin/python3.10 -m pip install playwright && python3.10 -m playwright install chromium")
        sys.exit(1)

    conversations = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        page.goto("https://v2.onlinejobs.ph/login")
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
                browser.close()
                return

        if "/login" in page.url:
            log("Login failed — check credentials")
            browser.close()
            return

        log("Logged in successfully")

        # The whole inbox, not ?unread=true: a thread Jiv opened on his phone is no longer "unread" but
        # may still be waiting on a reply. Rows have no links (data-cy="thread-<id>", click to open),
        # so state is keyed by that numeric id and a row is only opened when its preview text changed.
        page.goto("https://v2.onlinejobs.ph/message")
        page.wait_for_timeout(2500)
        try:
            rows = page.eval_on_selector_all(
                'div[data-cy^="thread-"][data-selected]',
                "els => els.map(el => [el.getAttribute('data-cy').replace('thread-', ''), el.innerText.trim().replace(/\\s+/g, ' ')])")
        except Exception as e:
            log(f"Could not read the inbox rows: {e}")
            browser.close()
            return
        rows = rows[:MAX_THREADS]
        log(f"Found {len(rows)} conversation(s) in the inbox")
        now = datetime.now()
        changed = False

        for thread_id, row_text in rows:
            known = state["convs"].get(thread_id)
            if known is not None and known.get("row") == row_text:
                continue                      # nothing new since the last look
            try:
                page.goto("https://v2.onlinejobs.ph/message")
                page.wait_for_timeout(1500)
                page.click(f'div[data-cy="thread-{thread_id}"]')
                page.wait_for_url("**/message/conversation/**", timeout=10000)
                page.wait_for_timeout(1500)
                link = page.url
                conv_id = link.rstrip("/").split("/")[-1]
                msg = decide_mod.parse_thread(page.inner_text("body"))
                thread = page.inner_text("body")[-2000:]
            except Exception as e:
                log(f"  Error reading thread {thread_id}: {e}")
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
            changed = True
            if action == "none":
                continue

            who = msg["name"]
            body = msg["text"][:400]
            sig = decide_mod.signature(msg["text"])
            log(f"  {thread_id}/{conv_id} ({who}): {action} {detail}".rstrip())

            if action == "baseline":
                cs["sig"] = sig
                changed = True
                continue

            if action == "meeting":
                # Alarm first: Jiv booking the call matters more than the courtesy reply succeeding.
                notify_jiv(f"{who} wants to book a meeting ({detail}). Take over now.\n{body}",
                           level="meeting", title=f"Meeting ready: {who}", url=link,
                           key=f"oj:{conv_id}:meeting")
                if not can_reply:
                    cs.pop("row", None)       # night run still sends the courtesy reply; the key stops a second ring
                    continue
                _reply(page, link, conv_id, cs, sig, who, thread, msg, now, meeting=True)
                cs["handoff"] = True          # the bot never talks in this thread again
                cs["sig"] = sig
                changed = True
                continue

            if action in ("handoff_msg", "notify_only", "cap"):
                why = {"handoff_msg": "New message in a thread you took over.",
                       "notify_only": "Needs you: it asks you to read the job post and answer its questions. No reply sent.",
                       "cap": "Auto-reply paused: 3 replies this week. Needs you."}[action]
                if notify_jiv(f"{why}\n{who}: {body}", level="needs", title=f"OnlineJobs: {who}", url=link,
                              key=f"oj:{conv_id}:{sig}"):
                    cs["sig"] = sig
                    changed = True
                continue

            # reply / reply_notify
            if not can_reply:
                if action == "reply_notify":  # a video/form ask is Jiv's work: tell him now, reply tonight
                    notify_jiv(f"{who} asked for a video or form. A holding reply goes out tonight.\n{body}",
                               level="needs", title=f"OnlineJobs needs you: {who}", url=link,
                               key=f"oj:{conv_id}:{sig}")
                cs.pop("row", None)           # leave it unrecorded so the night run replies
                continue
            _reply(page, link, conv_id, cs, sig, who, thread, msg, now, asset=(action == "reply_notify"))

        if changed:
            save_state(state)
        browser.close()

    log(f"  Done. {sum(len(c.get('bot_replies', [])) for c in state['convs'].values())} bot reply(ies) on record.\n")


def _reply(page, link, conv_id, cs, sig, who, thread, msg, now, asset=False, meeting=False):
    """Draft, send, verify. On success records the handled message and the reply time. Returns True if sent."""
    prompt = (
        f"You are Jiv Tuban, a Full-Stack Developer & AI Engineer applying for jobs on OnlineJobs.ph. "
        f"An employer just messaged you. Write a brief, professional reply.\n\n"
        f"Profile KB:\n{load_profile_context()}\n\n"
        f"Thread context:\n{thread}\n\n"
        f"Their latest message:\n{msg['text'][-500:]}\n\n"
        f"Include your availability: {AVAILABILITY}\n"
        f"Sign as: {SENDER_NAME}, {ROLE}\n"
        f"Keep it concise (3-5 sentences). Be genuine and professional."
    )
    if asset:
        prompt += ("\n\nThey are asking for something only you can produce (a video, recording or form). "
                   "Do NOT say it is done and do not invent links. Say you will send it shortly.")
    if meeting:
        prompt += ("\n\nThey want to book a meeting. Say you are glad to meet, give your availability, and if they "
                   "sent a booking link say you will pick a slot now. Do not invent times outside your availability.")
    reply_text = run_claude(prompt)
    if not reply_text:
        log(f"  No reply drafted for {conv_id}, skipping")
        return False
    try:
        if not send_reply(page, link, reply_text):
            log(f"  \u274c Reply to {conv_id} not confirmed in the thread; not recorded, will retry")
            return False
    except Exception as e:
        log(f"  Send error for {conv_id}: {e}")
        return False
    log(f"  \u2705 Replied to {conv_id} (verified in thread)")
    cs["sig"] = sig
    cs.setdefault("bot_replies", []).append(now.timestamp())
    if asset:
        notify_jiv(f"{who} asked for a video/form. A holding reply is sent. You owe them the real thing.\n{msg['text'][:400]}",
                   level="needs", title=f"OnlineJobs needs you: {who}", url=link, key=f"oj:{conv_id}:{sig}")
    return True


if __name__ == "__main__":
    run()
