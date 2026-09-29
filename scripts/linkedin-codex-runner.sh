#!/bin/bash
# Mac Mini crontab entry point for the Codex `$linkedin` runs.
#   linkedin-codex-runner.sh outreach   daily: inbox replies, follow-ups, pre-drafted sends, new drafts
#   linkedin-codex-runner.sh inbox      every 2h: inbox auto-replies + escalations only
#   add --dry-run to either: decide everything, send nothing (writes needs-jiv.dryrun.jsonl)
# Runs the Mini's ~/.codex/skills/linkedin skill via the `linkedin` Codex profile
# (~/.codex/linkedin.config.toml), which supplies the linkedin-browser Playwright MCP
# on the dedicated ~/.linkedin-codex-profile. Setup + gotchas: AUTOMATION.md,
# section "Mac Mini + Codex".

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

MODE="${1:-outreach}"
DRY_RUN=""; [ "${2:-}" = "--dry-run" ] && DRY_RUN=1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Real path, not ~/Desktop/Work: that is a symlink and Codex rejects symlinked writable roots.
OUTREACH_DIR="$HOME/Work/job-email-bot/marketing/outreach"
PROFILE_DIR="$HOME/.linkedin-codex-profile"
STAMP_FILE="$HOME/.linkedin_codex_last_run"      # outreach: one success per day
ALERT_FILE="$HOME/.linkedin_codex_alerted"       # failure alerts: one DM per day
LOCK_DIR="/tmp/linkedin-codex-run.lock"
LOG_DIR="$HOME/Library/Logs/linkedin-codex"
MAX_SECONDS=2700   # 45 min hard cap; macOS has no `timeout`, so perl alarm below
TODAY=$(date +%Y-%m-%d)
LOG="$LOG_DIR/$TODAY.log"

case "$MODE" in outreach|inbox) ;; *) echo "usage: $0 outreach|inbox [--dry-run]" >&2; exit 2 ;; esac

mkdir -p "$LOG_DIR"
exec >>"$LOG" 2>&1

if [ "$MODE" = outreach ] && [ -z "$DRY_RUN" ] && [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$TODAY" ]; then
    exit 0
fi

# Never overlap: a second run would fight the first for the Chrome profile lock.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date)] $MODE: skipping, another run holds $LOCK_DIR"
    exit 0
fi
cleanup() {
    # A killed or crashed run can leave Chrome holding the profile; free it for the next run.
    pkill -f "Google Chrome.*--user-data-dir=$PROFILE_DIR" 2>/dev/null
    rmdir "$LOCK_DIR" 2>/dev/null
}
trap cleanup EXIT

if pgrep -f "Google Chrome.*--user-data-dir=$PROFILE_DIR" >/dev/null; then
    echo "[$(date)] $MODE: skipping, Chrome already has $PROFILE_DIR open (manual login in progress?)"
    trap - EXIT; rmdir "$LOCK_DIR"; exit 0
fi

alert_once() {
    [ -n "$DRY_RUN" ] && return
    [ -f "$ALERT_FILE" ] && [ "$(cat "$ALERT_FILE")" = "$TODAY" ] && return
    python3 "$SCRIPT_DIR/linkedin-notify.py" --text "$1" && echo "$TODAY" > "$ALERT_FILE"
}

echo "[$(date)] $MODE${DRY_RUN:+ (dry run)}: starting \$linkedin run"

BASE='No human is attached, so never ask a question: follow /Users/admin/.codex/skills/linkedin/SKILL.md in Scheduled Automation Mode. Use the linkedin-browser MCP for every LinkedIn page.'
if [ "$MODE" = inbox ]; then
    PROMPT="Scheduled INBOX-ONLY run of \$linkedin. $BASE Do the Inbox Auto-Reply pass and the tracking pass only: no search, no new connection notes. Close the browser when done."
else
    PROMPT="Scheduled automation run of \$linkedin. $BASE Start with the Inbox Auto-Reply pass, then the rest of the scheduled flow. Update the tracker, append the run report in this folder, then close the browser."
fi
[ -n "$DRY_RUN" ] && PROMPT="DRY RUN: send nothing, follow the skill's Dry run rules. $PROMPT"

SUMMARY="$LOG_DIR/$TODAY-$MODE-$(date +%H%M)-summary.md"
perl -e 'alarm shift; exec @ARGV' "$MAX_SECONDS" \
    codex exec --profile linkedin --skip-git-repo-check \
        -C "$OUTREACH_DIR" \
        -o "$SUMMARY" \
        "$PROMPT" < /dev/null
EXIT_CODE=$?

# codex exec exits 0 even when the run couldn't do its job (the first dry run did
# exactly that), so the skill must end with RUN_STATUS=ok for the run to count.
RUN_STATUS=$(grep -o 'RUN_STATUS=[^[:space:]`]*' "$SUMMARY" 2>/dev/null | tail -1)
echo "[$(date)] $MODE: ${RUN_STATUS:-RUN_STATUS missing}"
if [ $EXIT_CODE -eq 0 ] && [ "$RUN_STATUS" != "RUN_STATUS=ok" ]; then
    EXIT_CODE=3
fi

# Escalations first, whatever the exit code: a run can fail late after writing them.
[ -z "$DRY_RUN" ] && python3 "$SCRIPT_DIR/linkedin-notify.py"

# Jiv's hard rule: no em/en-dashes in anything Codex writes. The skill checks before
# every send; this catches what slips through (those files hold sent + drafted text).
DASHED=$(grep -l -e $'\xe2\x80\x94' -e $'\xe2\x80\x93' "$OUTREACH_DIR/linkedin-outreach-tracker.json" \
    "$OUTREACH_DIR/needs-jiv.jsonl" "$SUMMARY" 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')
if [ -n "$DASHED" ] && [ -z "$DRY_RUN" ] && [ "$(cat "$HOME/.linkedin_dash_alerted" 2>/dev/null)" != "$TODAY" ]; then
    echo "[$(date)] $MODE: em/en-dash found in: $DASHED"
    python3 "$SCRIPT_DIR/linkedin-notify.py" --text "Codex wrote an em/en-dash in LinkedIn text on the Mini (in: $DASHED). Check ~/Work/job-email-bot/marketing/outreach." \
        && echo "$TODAY" > "$HOME/.linkedin_dash_alerted"
fi

if grep -q "linkedin_session_expired" "$SUMMARY" 2>/dev/null; then
    alert_once "LinkedIn session on the Mini expired. Screen Share to vnc://100.98.219.58, then: cd ~/agent-work/jobi && PLAYWRIGHT_PROFILE=~/.linkedin-codex-profile LOGIN_TIMEOUT_MIN=20 npm run login"
fi

if [ $EXIT_CODE -eq 0 ]; then
    [ "$MODE" = outreach ] && [ -z "$DRY_RUN" ] && echo "$TODAY" > "$STAMP_FILE"
    echo "[$(date)] $MODE: completed."
else
    echo "[$(date)] $MODE: failed with exit code $EXIT_CODE (142 = hit the ${MAX_SECONDS}s cap, 3 = RUN_STATUS not ok)"
    alert_once "LinkedIn $MODE run on the Mini failed (exit $EXIT_CODE, ${RUN_STATUS:-no RUN_STATUS}). Log: ~/Library/Logs/linkedin-codex/$TODAY.log"
fi
exit $EXIT_CODE
