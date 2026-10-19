#!/usr/bin/env python3
"""DM Jiv on Discord about LinkedIn conversations the Codex run would not answer.

Posts every line of needs-jiv.jsonl that hasn't been posted yet, then records the
count so each escalation is sent once. `--text "..."` posts a one-off alert
(used by the runner for failed runs / an expired LinkedIn session).

The token is read here, never by the model: it comes from the Mini's live Claude
Discord bot (~/.claude/channels/discord/.env). The old job-followup token 401s.

Every automation on the Mini (LinkedIn runner, linkedin-email.py, the OnlineJobs checker) alerts
through this one script. Levels decide how loud it gets:

  --level info     Discord DM only (default; what every old `--text` call still gets)
  --level needs    Discord DM + Pushover normal priority (Jiv has to do something)
  --level meeting  Discord DM + Pushover EMERGENCY: the conversation reached a booked meeting.
                   iOS Critical Alert, breaks through silent/Do Not Disturb, repeats until Jiv taps
                   Acknowledge (Pushover is the only push service Apple approved for that).

Pushover keys live in ~/.pushover.env (PUSHOVER_TOKEN, PUSHOVER_USER; chmod 600), never in the
repo. Without that file the Pushover leg is skipped and Discord still goes out.
`--key X` sends a given alert once: a conversation that reaches "meeting" rings one time, not
every 30 minute run.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meeting_signal import meeting_signal  # noqa: E402

HOME = os.path.expanduser("~")
ENV_FILE = os.environ.get("LINKEDIN_NOTIFY_TOKEN_FILE", os.path.join(HOME, ".claude/channels/discord/.env"))
# The bot's DM channel with Jiv (also where job-followup alerts were meant to go).
CHANNEL = os.environ.get("LINKEDIN_NOTIFY_CHANNEL", "1487505450369814680")
QUEUE = os.environ.get("LINKEDIN_NOTIFY_QUEUE", os.path.join(HOME, "Work/job-email-bot/marketing/outreach/needs-jiv.jsonl"))
STATE = os.environ.get("LINKEDIN_NOTIFY_STATE", os.path.join(HOME, ".linkedin_needs_jiv_posted"))
# Test hook: print instead of posting (tests/battle/ and the runner's test mode set it).
DRY = os.environ.get("LINKEDIN_NOTIFY_DRY") == "1"
PUSHOVER_ENV = os.environ.get("PUSHOVER_ENV_FILE", os.path.join(HOME, ".pushover.env"))
SENT_KEYS = os.environ.get("LINKEDIN_NOTIFY_KEYS", os.path.join(HOME, ".notify_sent_keys.json"))
LEVELS = ("info", "needs", "meeting")
# Pushover emergency (priority 2) needs retry (>= 30 s) and expire (<= 10800 s). Ring every minute
# for 30 minutes, then stop: long enough to reach him, short enough not to nag all night.
EMERGENCY_RETRY_S = 60
EMERGENCY_EXPIRE_S = 1800


def token():
    for line in open(ENV_FILE):
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("DISCORD_BOT_TOKEN missing from " + ENV_FILE)


def post(text):
    if DRY:
        print("[notify dry] " + text.replace("\n", " | ")[:1990], flush=True)
        return
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{CHANNEL}/messages",
        data=json.dumps({"content": text[:1990]}).encode(),
        headers={
            "Authorization": "Bot " + token(),
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (linkedin-notify, 1)",
        },
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15)


def pushover_creds():
    """(token, user) from ~/.pushover.env, or None if Pushover is not set up on this machine."""
    try:
        vals = {}
        with open(PUSHOVER_ENV) as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"')
        return (vals["PUSHOVER_TOKEN"], vals["PUSHOVER_USER"])
    except (OSError, KeyError):
        return None


def push(level, text, title=None, url=None):
    """Pushover leg. Returns True sent, False failed, None not applicable (info level or not set up)."""
    if level == "info":
        return None
    creds = pushover_creds()
    if creds is None and not DRY:
        return None
    fields = {
        "token": creds[0] if creds else "dry",
        "user": creds[1] if creds else "dry",
        "title": (title or ("Meeting ready" if level == "meeting" else "Needs you"))[:250],
        "message": text[:1024],
        "priority": "2" if level == "meeting" else "0",
    }
    if level == "meeting":
        fields.update(retry=str(EMERGENCY_RETRY_S), expire=str(EMERGENCY_EXPIRE_S), sound="persistent")
    if url:
        fields.update(url=url[:512], url_title="Open conversation")
    if DRY:
        print(f"[pushover dry] priority={fields['priority']} {fields['title']}: {text.replace(chr(10), ' | ')[:200]}", flush=True)
        return True
    try:
        req = urllib.request.Request("https://api.pushover.net/1/messages.json",
                                     data=urllib.parse.urlencode(fields).encode(), method="POST")
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"[notify] pushover failed: {e}", file=sys.stderr, flush=True)
        return False


def already_sent(key):
    try:
        return key in json.load(open(SENT_KEYS))
    except (OSError, ValueError):
        return False


def mark_sent(key):
    try:
        keys = json.load(open(SENT_KEYS))
    except (OSError, ValueError):
        keys = {}
    keys[key] = True
    with open(SENT_KEYS, "w") as f:
        json.dump(keys, f)


def alert(text, level="info", title=None, url=None, key=None):
    """Send one alert on every channel the level calls for. Discord and Pushover fail independently:
    one being down must never swallow the other. Raises only if nothing went out."""
    if key and not DRY and already_sent(key):
        return
    sent = []
    try:
        post(text)
        sent.append(True)
    except Exception as e:
        print(f"[notify] discord failed: {e}", file=sys.stderr, flush=True)
        sent.append(False)
    pushed = push(level, text, title, url)
    if pushed is not None:
        sent.append(pushed)
    if not any(sent):
        raise SystemExit("[notify] no channel delivered the alert")
    if key and not DRY:
        mark_sent(key)


def format_item(item):
    text = (
        f"**LinkedIn needs you: {item.get('name', '?')}**\n"
        f"{item.get('thread_url', '')}\n"
        f"They said: {item.get('their_message', '')}\n"
        f"Why I didn't reply: {item.get('why', '')}"
    )
    # Job links the runner could not apply to carry no draft reply; an empty "> " quote is noise.
    if item.get('suggested_reply'):
        text += f"\nSuggested reply:\n> {item['suggested_reply']}"
    return text


def parse_flags(argv):
    """--text TEXT [--level L] [--title T] [--url U] [--key K]; flags may come in any order."""
    out, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            out[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    return out


def main():
    flags = parse_flags(sys.argv[1:])
    if "text" in flags:
        level = flags.get("level", "info")
        if level not in LEVELS:
            raise SystemExit(f"--level must be one of {LEVELS}")
        alert(flags["text"], level, flags.get("title"), flags.get("url"), flags.get("key"))
        return
    if not os.path.exists(QUEUE):
        return
    lines = [l for l in open(QUEUE).read().splitlines() if l.strip()]
    done = int(open(STATE).read().strip() or 0) if os.path.exists(STATE) else 0
    for i in range(done, len(lines)):
        try:
            item = json.loads(lines[i])
            text = format_item(item)
            # The goal of the replies is a booked meeting: if they just proposed one, ring loudly.
            kind = meeting_signal(item.get("their_message", ""))
            level = "meeting" if kind else "needs"
            title = f"LinkedIn meeting: {item.get('name', '?')}" if kind else f"LinkedIn: {item.get('name', '?')}"
            url = item.get("thread_url")
        except json.JSONDecodeError:
            text, level, title, url = "**LinkedIn needs you** (unparseable entry)\n" + lines[i], "needs", None, None
        alert(text, level, title, url)
        # Advance after each successful post so a failure mid-batch never re-sends.
        with open(STATE, "w") as f:
            f.write(str(i + 1))


if __name__ == "__main__":
    main()
