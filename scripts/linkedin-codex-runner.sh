#!/bin/bash
# Mac Mini crontab entry point for the daily Codex `$linkedin` outreach run.
# Runs the Mini's ~/.codex/skills/linkedin skill in Scheduled Automation Mode via
# the `linkedin` Codex profile (~/.codex/linkedin.config.toml), which supplies the
# linkedin-browser Playwright MCP on the dedicated ~/.linkedin-codex-profile.
# Setup + gotchas: AUTOMATION.md, section "Mac Mini + Codex".

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

OUTREACH_DIR="$HOME/Desktop/Work/job-email-bot/marketing/outreach"
PROFILE_DIR="$HOME/.linkedin-codex-profile"
STAMP_FILE="$HOME/.linkedin_codex_last_run"
LOCK_DIR="/tmp/linkedin-codex-run.lock"
LOG_DIR="$HOME/Library/Logs/linkedin-codex"
MAX_SECONDS=2700   # 45 min hard cap; macOS has no `timeout`, so perl alarm below
TODAY=$(date +%Y-%m-%d)
LOG="$LOG_DIR/$TODAY.log"

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1

# Cron fires this more than once a day as a retry; only one success per day counts.
if [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$TODAY" ]; then
    exit 0
fi

# Never overlap: a second run would fight the first for the Chrome profile lock.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date)] Skipping: another run holds $LOCK_DIR"
    exit 0
fi
cleanup() {
    # A killed or crashed run can leave Chrome holding the profile; free it for the next run.
    pkill -f "Google Chrome.*--user-data-dir=$PROFILE_DIR" 2>/dev/null
    rmdir "$LOCK_DIR" 2>/dev/null
}
trap cleanup EXIT

if pgrep -f "Google Chrome.*--user-data-dir=$PROFILE_DIR" >/dev/null; then
    echo "[$(date)] Skipping: Chrome already has $PROFILE_DIR open (manual login in progress?)"
    trap - EXIT; rmdir "$LOCK_DIR"; exit 0
fi

echo "[$(date)] Starting scheduled \$linkedin run for $TODAY"

PROMPT='Scheduled automation run of $linkedin. No human is attached, so never ask a question: follow /Users/admin/.codex/skills/linkedin/SKILL.md in Scheduled Automation Mode. Use the linkedin-browser MCP for every LinkedIn page. Update the tracker, append the run report in this folder, then close the browser.'

perl -e 'alarm shift; exec @ARGV' "$MAX_SECONDS" \
    codex exec --profile linkedin --skip-git-repo-check \
        -C "$OUTREACH_DIR" \
        -o "$LOG_DIR/$TODAY-summary.md" \
        "$PROMPT" < /dev/null
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$TODAY" > "$STAMP_FILE"
    echo "[$(date)] Completed."
else
    echo "[$(date)] Failed with exit code $EXIT_CODE (142 = hit the ${MAX_SECONDS}s cap)"
fi
exit $EXIT_CODE
