#!/usr/bin/env python3
"""DM Jiv on Discord about LinkedIn conversations the Codex run would not answer.

Posts every line of needs-jiv.jsonl that hasn't been posted yet, then records the
count so each escalation is sent once. `--text "..."` posts a one-off alert
(used by the runner for failed runs / an expired LinkedIn session).

The token is read here, never by the model: it comes from the Mini's live Claude
Discord bot (~/.claude/channels/discord/.env). The old job-followup token 401s.
"""
import json
import os
import sys
import urllib.request

HOME = os.path.expanduser("~")
ENV_FILE = os.environ.get("LINKEDIN_NOTIFY_TOKEN_FILE", os.path.join(HOME, ".claude/channels/discord/.env"))
# The bot's DM channel with Jiv (also where job-followup alerts were meant to go).
CHANNEL = os.environ.get("LINKEDIN_NOTIFY_CHANNEL", "1487505450369814680")
QUEUE = os.environ.get("LINKEDIN_NOTIFY_QUEUE", os.path.join(HOME, "Work/job-email-bot/marketing/outreach/needs-jiv.jsonl"))
STATE = os.environ.get("LINKEDIN_NOTIFY_STATE", os.path.join(HOME, ".linkedin_needs_jiv_posted"))
# Test hook: print instead of posting (tests/battle/ and the runner's test mode set it).
DRY = os.environ.get("LINKEDIN_NOTIFY_DRY") == "1"


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


def format_item(item):
    return (
        f"**LinkedIn needs you: {item.get('name', '?')}**\n"
        f"{item.get('thread_url', '')}\n"
        f"They said: {item.get('their_message', '')}\n"
        f"Why I didn't reply: {item.get('why', '')}\n"
        f"Suggested reply:\n> {item.get('suggested_reply', '')}"
    )


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--text":
        post(sys.argv[2])
        return
    if not os.path.exists(QUEUE):
        return
    lines = [l for l in open(QUEUE).read().splitlines() if l.strip()]
    done = int(open(STATE).read().strip() or 0) if os.path.exists(STATE) else 0
    for i in range(done, len(lines)):
        try:
            text = format_item(json.loads(lines[i]))
        except json.JSONDecodeError:
            text = "**LinkedIn needs you** (unparseable entry)\n" + lines[i]
        post(text)
        # Advance after each successful post so a failure mid-batch never re-sends.
        with open(STATE, "w") as f:
            f.write(str(i + 1))


if __name__ == "__main__":
    main()
