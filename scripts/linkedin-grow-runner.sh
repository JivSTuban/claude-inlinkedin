#!/bin/bash

TIMESTAMP_FILE="$HOME/.linkedin_grow_last_run"
TODAY=$(date +%Y-%m-%d)
CURRENT_HOUR=$((10#$(date +%H)))
SCHEDULED_HOUR=8

if [ "$CURRENT_HOUR" -lt "$SCHEDULED_HOUR" ]; then
    echo "[$(date)] Skipping: before 8am (current hour=$CURRENT_HOUR)"
    exit 0
fi

if [ -f "$TIMESTAMP_FILE" ] && [ "$(cat "$TIMESTAMP_FILE")" = "$TODAY" ]; then
    echo "[$(date)] Skipping: already ran today ($TODAY)"
    exit 0
fi

echo "[$(date)] Starting /linkedin-grow for $TODAY..."

# Phase 1: ensure LinkedIn session is active (waits up to 5 min for login if needed)
node /Users/jivtuban/linkedin-ensure-login.js
LOGIN_CODE=$?

if [ $LOGIN_CODE -ne 0 ]; then
    echo "[$(date)] Login timed out or failed (exit $LOGIN_CODE). Aborting." >&2
    exit 1
fi

# Phase 2: run the automation with the saved session
cd /Users/jivtuban/Desktop/jobi
/opt/homebrew/bin/claude --dangerously-skip-permissions --print "/linkedin-grow" < /dev/null
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$TODAY" > "$TIMESTAMP_FILE"
    echo "[$(date)] Completed successfully."
else
    echo "[$(date)] Failed with exit code $EXIT_CODE" >&2
fi

exit $EXIT_CODE
