#!/bin/bash
# pm2 entry point for the daily /linkedin-grow run. Fires every 15 min; the
# hour window + daily stamp below make it act once per day.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TIMESTAMP_FILE="$HOME/.linkedin_grow_last_run"
PROFILE_DIR="$HOME/.playwright-linkedin-profile"
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# Pinned so an upstream release can't silently break an unattended run.
PLAYWRIGHT_MCP_VERSION="0.0.83"
TODAY=$(date +%Y-%m-%d)
CURRENT_HOUR=$((10#$(date +%H)))
START_HOUR=8
END_HOUR=20   # a Mac that wakes late at night should not start a LinkedIn session

# pm2 does not source the login shell, so node/npx/claude may be missing from PATH.
export PATH="$(dirname "$(command -v node 2>/dev/null || echo /usr/local/bin/node)"):/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ "$CURRENT_HOUR" -lt "$START_HOUR" ] || [ "$CURRENT_HOUR" -ge "$END_HOUR" ]; then
    exit 0
fi

if [ -f "$TIMESTAMP_FILE" ] && [ "$(cat "$TIMESTAMP_FILE")" = "$TODAY" ]; then
    exit 0
fi

echo "[$(date)] Starting /linkedin-grow for $TODAY..."

# Phase 1: ensure LinkedIn session is active (waits up to 5 min for login if needed)
node "$SCRIPT_DIR/linkedin-ensure-login.js"
LOGIN_CODE=$?

if [ $LOGIN_CODE -ne 0 ]; then
    echo "[$(date)] Login timed out or failed (exit $LOGIN_CODE). Aborting." >&2
    exit 1
fi

# Chrome can hold the profile lock briefly after Phase 1 closes (AUTOMATION.md gotcha 4).
sleep 5

# Phase 2: run the skill with a Playwright MCP scoped to this run only, so the
# global Playwright plugin config never needs editing and no other MCPs load.
MCP_CONFIG="$(mktemp -t linkedin-mcp).json"
trap 'rm -f "$MCP_CONFIG"' EXIT
cat > "$MCP_CONFIG" <<EOF
{
  "mcpServers": {
    "linkedin-browser": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION",
               "--user-data-dir", "$PROFILE_DIR",
               "--executable-path", "$CHROME_PATH"]
    }
  }
}
EOF

cd "$REPO_DIR"
claude --dangerously-skip-permissions --print \
    --mcp-config "$MCP_CONFIG" --strict-mcp-config \
    "/linkedin-grow automated" < /dev/null
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$TODAY" > "$TIMESTAMP_FILE"
    echo "[$(date)] Completed successfully."
else
    echo "[$(date)] Failed with exit code $EXIT_CODE" >&2
fi

exit $EXIT_CODE
