# LinkedIn Growth Automation — Architecture & Learnings

Daily LinkedIn growth automation (connections, follows, post engagement) running on a local Mac via pm2 + Claude Code CLI.

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
| `~/.claude/skills/linkedin-grow/` | The Claude Code skill that drives the actual LinkedIn actions. |

---

## Cron Schedule

```
*/15 * * * *   — polls every 15 min
```

With the 8am hour guard + daily-once stamp, this effectively runs once per day at the first 15-min window after 8am local time.
