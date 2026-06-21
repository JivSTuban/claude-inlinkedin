# claude-inlinkedin

Automated LinkedIn growth using a **Claude Code skill** scheduled via **pm2**. Runs daily — sends connection requests, follows relevant accounts, and leaves substantive comments on tech/AI posts — all driven by Claude as the intelligence layer.

## What it does

Every morning at 8am, a pm2 cron job wakes up and:

1. **Ensures LinkedIn is authenticated** — opens a persistent Chrome profile, detects if you're logged in, waits up to 5 min if not (one-time setup only)
2. **Runs `/linkedin-grow`** — a Claude Code skill that navigates LinkedIn, accepts pending invitations, sends ~15 connection requests to relevant people in your niche, follows suggested accounts, and leaves 2–3 quality comments on fresh posts

Rate limits are baked into the skill to stay within LinkedIn's safe thresholds (~15–20 connections/day, 5–10 comments/day).

## Stack

| Layer | Tool |
|-------|------|
| Scheduler | pm2 (cron mode) |
| AI agent | Claude Code CLI (`claude --print`) |
| Skill | `/linkedin-grow` (Claude Code custom skill — included in this repo) |
| Browser | Playwright MCP + persistent Chrome profile |
| Auth | One-time email/password login → saved session |

## Project structure

```
scripts/
  linkedin-grow-runner.sh     # pm2 entry point — daily guard + 2-phase execution
  linkedin-ensure-login.js    # Phase 1 — persistent Chrome login check (5 min wait)
skills/
  linkedin-grow/
    SKILL.md                  # The Claude Code skill — edit YOUR PROFILE section
AUTOMATION.md                 # Full architecture doc + lessons learned
```

---

## Setup

### Prerequisites

- [Claude Code](https://claude.ai/code) installed (`claude` in PATH)
- Node.js + npm
- pm2: `npm install -g pm2`
- playwright: `npm install -g playwright && npx playwright install chromium`
- Google Chrome installed at `/Applications/Google Chrome.app` (Mac) — or set `CHROME_PATH` env var

### 1. Edit the skill with your profile

Open `skills/linkedin-grow/SKILL.md` and fill in the `YOUR PROFILE` section at the top:

```
Name:     Your Name
Title:    Your LinkedIn headline
Location: Your city, country
Niche:    Your target topics (e.g. AI Engineering, DevOps, ...)
Target connections: roles you want to connect with
Hashtags: hashtags to engage with
```

This is what Claude uses to decide who to connect with and how to write comments.

### 2. Install the skill into Claude Code

```bash
mkdir -p ~/.claude/skills/linkedin-grow
cp skills/linkedin-grow/SKILL.md ~/.claude/skills/linkedin-grow/SKILL.md
```

### 3. Configure Playwright MCP for persistent sessions

Find the Playwright MCP config — it's typically at one of:
- `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/playwright/.mcp.json`
- `~/.claude/plugins/cache/claude-plugins-official/playwright/unknown/.mcp.json`

Update both files to use your persistent Chrome profile:

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

Replace `<you>` with your macOS username. This makes the Playwright session persistent so Claude can see your logged-in LinkedIn.

### 4. Register with pm2

```bash
chmod +x scripts/linkedin-grow-runner.sh

pm2 start "$(pwd)/scripts/linkedin-grow-runner.sh" \
  --name linkedin-grow \
  --cron "*/15 * * * *" \
  --interpreter /bin/bash \
  --no-autorestart

pm2 save
pm2 startup   # follow the printed command to survive reboots
```

The `*/15 * * * *` cron fires every 15 minutes, but the script has a daily-once guard — it only actually runs once per day (after 8am), then exits immediately on all subsequent checks.

### 5. First run — one-time login

On the first run, a Chrome window opens at the LinkedIn login page. Sign in with **email/password** (not Google — Google OAuth is blocked under automation). Once you reach your LinkedIn feed, the browser closes and the session is saved to `~/.playwright-linkedin-profile`.

All future runs are fully headless and require no interaction.

---

## Customization

| What | Where |
|------|-------|
| Change run time (default 8am) | Edit `SCHEDULED_HOUR` in `scripts/linkedin-grow-runner.sh` |
| Change Chrome path (non-Mac) | Set `CHROME_PATH` env var, or edit `CHROMIUM` in `scripts/linkedin-ensure-login.js` |
| Change profile directory | Set `PLAYWRIGHT_PROFILE` env var |
| Change what Claude does on LinkedIn | Edit `skills/linkedin-grow/SKILL.md` |

---

## How it works

The intelligence is entirely in the `/linkedin-grow` skill — Claude reads the LinkedIn page, decides who to connect with, writes substantive comments, and respects rate limits. See [`AUTOMATION.md`](./AUTOMATION.md) for the full architecture and lessons learned building this.

---

## Troubleshooting

**`playwright` module not found** — run `npm install playwright` in the repo root (or globally).

**Login keeps timing out** — make sure you're signing in with email/password, not Google. Google OAuth detects automation and blocks it even in real Chrome.

**pm2 logs show "already ran today"** — that's correct behavior. It will run again tomorrow after 8am.

**Claude can't see the LinkedIn page** — the Playwright MCP config isn't pointing to your persistent profile. Re-check step 3.

**View pm2 logs:**
```bash
pm2 logs linkedin-grow
```
