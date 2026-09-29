# LinkedIn Growth Automation — Architecture & Learnings

Daily LinkedIn growth automation (connections, follows, post engagement) running on a local Mac via pm2 + Claude Code CLI.

## Mac Mini + Codex (the live setup, since 2026-09-30)

Outreach now runs on the always-on Mac Mini (`admin@100.98.219.58`, Tailscale) with **Codex CLI**, not Claude Code: Codex is authed from `~/.codex/auth.json` there, so headless runs work and cost nothing extra. The pm2 + `/linkedin-grow` path below is the older MacBook setup and is not scheduled anywhere.

```
crontab  17 9,11,14 * * 1-5   (Mini local time = PHT; 11:17 and 14:17 are retries)
  └── scripts/linkedin-codex-runner.sh      (copy lives at ~/agent-work/jobi on the Mini)
        ├── skips if today already succeeded (~/.linkedin_codex_last_run),
        │   another run holds /tmp/linkedin-codex-run.lock, or Chrome has the profile open
        └── codex exec --profile linkedin  -C ~/Desktop/Work/job-email-bot/marketing/outreach
              ├── skill:   ~/.codex/skills/linkedin (Scheduled Automation Mode)
              ├── profile: ~/.codex/linkedin.config.toml  (approval never, sandbox writes
              │            only the outreach folder, folder pre-trusted)
              └── MCP:     linkedin-browser = @playwright/mcp@0.0.83, real Chrome,
                           --user-data-dir ~/.linkedin-codex-profile
```

| What | Where (on the Mini) |
|------|---------------------|
| Tracker + run reports | `~/Desktop/Work/job-email-bot/marketing/outreach/` |
| Runner logs + last summary | `~/Library/Logs/linkedin-codex/<date>.log`, `<date>-summary.md` |
| LinkedIn session | `~/.linkedin-codex-profile` (Chrome, Playwright mock keychain) |

**Scheduled runs only send exact, already-drafted tracker rows.** New cold notes are drafted into the tracker and reported, never sent unattended (the skill's Scheduled Automation Mode). Approve or edit them, then an interactive `$linkedin` run or the next scheduled run sends them.

**Log in / re-log in** (first time, or when a run reports `linkedin_session_expired`): Screen Share to `vnc://100.98.219.58`, then on the Mini:

```bash
cd ~/agent-work/jobi && PLAYWRIGHT_PROFILE=~/.linkedin-codex-profile LOGIN_TIMEOUT_MIN=20 npm run login
```

Sign in with email/password in the Chrome window that opens; it closes itself once the feed loads.

**Mini-specific gotchas:**
- **Don't reuse `~/.playwright-linkedin-profile` on the Mini.** A long-running Claude Code Discord bot (tmux `work`) has its Playwright plugin pointed at it, so sharing it means profile-lock collisions.
- **The global `~/.codex/config.toml` is never edited**: it runs the ChatGPT.app automations with full access. Everything LinkedIn-specific lives in the `linkedin` profile file, which `codex mcp list` without `--profile linkedin` doesn't show.
- **`codex exec` denies MCP tools that aren't read-only** under `approval_policy = "never"` ("MCP tool call requires approval, but approval policy is never"): snapshot works, navigate/click/type don't. The `linkedin-browser` server sets `default_tools_approval_mode = "approve"` (scoped to that server only). Verified 2026-09-30: Codex loaded the feed logged in as Jiv, and a cron-launched headed Chrome found the session.
- **No `timeout` on macOS**: the runner caps a run at 45 min with `perl -e 'alarm ...'` (exit 142 = cap hit), then kills any Chrome left on the profile.
- **Crontab survives reboots, but Chrome is headed**, so it needs the `admin` console session logged in. Auto-login is off on the Mini, so after a reboot, runs fail until someone logs in at the console.

## How It Works

```
pm2 cron (*/15 * * * *)
  └── linkedin-grow-runner.sh
        ├── Phase 1: linkedin-ensure-login.js
        │     └── Opens persistent Playwright/Chrome profile
        │         Waits up to 5 min for login if session is cold
        │         Exits 0 once LinkedIn feed is detected
        └── Phase 2: claude --dangerously-skip-permissions --print "/linkedin-grow"
              └── Runs the /linkedin-grow Claude Code skill
                  Uses Playwright MCP with saved session
                  Sends connections, follows, comments
                  Step 7: decision-maker outreach (personalized pitch DMs)
                          reads/writes ~/.linkedin_outreach_log.jsonl for
                          dedupe + rolling weekly-cap enforcement
```

Runs once per day (8am+ guard), every 15 min polling window.

## Setup

### 1. Install the runner scripts

```bash
cp scripts/linkedin-grow-runner.sh ~/
cp scripts/linkedin-ensure-login.js ~/
chmod +x ~/linkedin-grow-runner.sh
```

### 2. Configure Playwright MCP for persistent sessions

Edit both Playwright MCP config files (find them at `~/.claude/plugins/`):

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

Paths to update:
- `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/playwright/.mcp.json`
- `~/.claude/plugins/cache/claude-plugins-official/playwright/unknown/.mcp.json`

### 3. Register with pm2

```bash
pm2 start ~/linkedin-grow-runner.sh \
  --name linkedin-grow \
  --cron "*/15 * * * *" \
  --interpreter /bin/bash \
  --no-autorestart

pm2 save
pm2 startup  # follow the printed command to survive reboots
```

### 4. One-time login (first run only)

pm2 will open a Chrome window automatically on the first run. Sign in with Google — the session saves to `~/.playwright-linkedin-profile` and all future runs are fully automated.

---

## Key Learnings / Gotchas

### 1. `claude --print` is headless — no Claude-in-Chrome

The `/linkedin-grow` skill is designed to use `mcp__claude-in-chrome__*` tools (which connect to your running Chrome via the desktop app extension). This works in interactive sessions.

**In pm2 / `claude --print`:** The desktop app extension isn't connected to the new isolated CLI session. The skill falls back to Playwright MCP instead.

**Fix:** Accept Playwright as the browser for automated runs. Configure it with a persistent profile.

### 2. Google OAuth is blocked in Playwright Chromium ("Chrome for Testing")

Google rejects OAuth sign-in when the browser is "Google Chrome for Testing" — their policy explicitly blocks it.

**Fix:** Use the real Chrome binary via `--executable-path /Applications/Google Chrome.app/...` or `--browser chrome`.

### 3. Google OAuth is blocked even in real Chrome under WebDriver automation

Playwright sets `navigator.webdriver = true` and launches Chrome with `--enable-automation`. Google detects this and blocks OAuth regardless of which Chrome binary you use.

**Fix (for the one-time login script):**
```javascript
await chromium.launchPersistentContext(profile, {
  ignoreDefaultArgs: ['--enable-automation'],
  args: ['--disable-blink-features=AutomationControlled'],
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
```

Once session cookies are saved, subsequent headless runs don't need OAuth — they reuse the saved session and Google's detection doesn't matter.

### 4. Playwright profile lock between Phase 1 and Phase 2

After the login script (`linkedin-ensure-login.js`) closes the browser, Chrome may not immediately release the profile lock. If Phase 2 (`claude --print`) starts too fast, the Playwright MCP server fails to acquire the lock.

**Fix:** The `linkedin-ensure-login.js` closes the context gracefully (`await ctx.close()`), which releases the lock. A small buffer between phases would help if this recurs.

### 5. `< /dev/null` is required for non-interactive `claude --print`

Without `< /dev/null`, the claude process waits 3 seconds for stdin, produces a warning, and the skill treats the wait as an opportunity to ask for user input — then hangs.

**Fix:** Always run `claude --print "..." < /dev/null` in automation.

### 6. Daily-once guard prevents runaway runs

The 15-min cron means the script fires 96 times a day. Without a guard, it would spam LinkedIn.

**Fix:** Timestamp file at `~/.linkedin_grow_last_run`. Script skips if today's date is already written there.

---

## File Reference

| File | Purpose |
|------|---------|
| `scripts/linkedin-grow-runner.sh` | Main pm2 entry point. Daily guard + two-phase execution. |
| `scripts/linkedin-ensure-login.js` | Phase 1. Opens persistent Chrome profile, waits for LinkedIn login (up to 5 min). |
| `~/.playwright-linkedin-profile/` | Persistent Playwright browser profile. LinkedIn cookies live here. |
| `~/.linkedin_grow_last_run` | Timestamp file. Prevents duplicate runs on same day. |
| `~/.linkedin_outreach_log.jsonl` | Outreach ledger. One line per contacted decision-maker (dedupe + rolling weekly-cap + follow-up tracking). Written by Step 7 of the skill. |
| `~/.claude/skills/linkedin-grow/` | The Claude Code skill that drives the actual LinkedIn actions. |

---

## Cron Schedule

```
*/15 * * * *   — polls every 15 min
```

With the 8am hour guard + daily-once stamp, this effectively runs once per day at the first 15-min window after 8am local time.
