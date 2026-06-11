# claude-inlinkedin

Automated LinkedIn growth using a **Claude Code skill** scheduled via **pm2**. Runs daily — sends connection requests, follows relevant accounts, and leaves substantive comments on tech/AI posts — all driven by Claude as the intelligence layer.

## What it does

Every morning at 8am, a pm2 cron job wakes up and:

1. **Ensures LinkedIn is authenticated** — opens a persistent Chrome profile, detects if you're logged in, waits up to 5 min if not (one-time setup only)
2. **Runs `/linkedin-grow`** — a Claude Code skill that navigates LinkedIn, accepts pending invitations, sends ~15 connection requests to relevant engineers/recruiters, follows suggested accounts, and leaves 2–3 quality comments on fresh AI/dev posts

Rate limits are baked into the skill to stay within LinkedIn's safe thresholds (~15–20 connections/day, 5–10 comments/day).

## Stack

| Layer | Tool |
|-------|------|
| Scheduler | pm2 (cron mode) |
| AI agent | Claude Code CLI (`claude --print`) |
| Skill | `/linkedin-grow` (Claude Code custom skill) |
| Browser | Playwright MCP + persistent Chrome profile |
| Auth | One-time Google OAuth → saved session |

## Project structure

```
scripts/
  linkedin-grow-runner.sh     # pm2 entry point — daily guard + 2-phase execution
  linkedin-ensure-login.js    # Phase 1 — persistent Chrome login check (5 min wait)
AUTOMATION.md                 # Full architecture doc + lessons learned
REMOTE-JOBS-RESEARCH.md       # Remote job platform research (Arc.dev, Wellfound, etc.)
```

The actual Claude Code skill lives at `~/.claude/skills/linkedin-grow/` (not in this repo — it's part of your Claude Code installation).

## Setup

### Prerequisites

- [Claude Code](https://claude.ai/code) installed and configured
- pm2: `npm install -g pm2`
- `/linkedin-grow` skill installed in Claude Code

### 1. Copy scripts

```bash
cp scripts/linkedin-grow-runner.sh ~/
cp scripts/linkedin-ensure-login.js ~/
chmod +x ~/linkedin-grow-runner.sh
```

### 2. Configure Playwright MCP for persistent sessions

Find the Playwright MCP config files at:
- `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/playwright/.mcp.json`
- `~/.claude/plugins/cache/claude-plugins-official/playwright/unknown/.mcp.json`

Update both to:

```json
{
  "playwright": {
    "command": "npx",
    "args": [
      "@playwright/mcp@latest",
      "--user-data-dir", "/Users/<you>/.playwright-linkedin-profile",
      "--executable-path", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ]
  }
}
```

### 3. Register with pm2

```bash
pm2 start ~/linkedin-grow-runner.sh \
  --name linkedin-grow \
  --cron "*/15 * * * *" \
  --interpreter /bin/bash \
  --no-autorestart

pm2 save
pm2 startup   # follow the printed command to survive reboots
```

### 4. First run — one-time login

On the first run, pm2 opens a Chrome window at the LinkedIn login page. Sign in with Google (the script uses stealth flags so Google's automation detection is bypassed). Once you hit your LinkedIn feed, the browser closes automatically and the session is saved permanently.

All future runs are fully headless and require no interaction.

## How the automation actually works

The intelligence is entirely in the `/linkedin-grow` Claude Code skill — Claude reads the LinkedIn page, decides who to connect with (mutual connections, relevant titles, `#OPENTOWORK`), writes substantive comments (no "Great post!" generics), and respects rate limits. See [`AUTOMATION.md`](./AUTOMATION.md) for the full architecture and the hard-won lessons building it.

## Profile

Built for: **Jiv Tuban** — AI Engineer | Full Stack Developer | Cebu, PH  
Goal: Remote global opportunities, AI/automation network  
Target: AI engineers, full-stack devs, tech recruiters, engineering managers
