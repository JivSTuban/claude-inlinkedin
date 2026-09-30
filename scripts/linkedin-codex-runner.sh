#!/bin/bash
# Mac Mini crontab entry point for the Codex `$linkedin` runs.
#   linkedin-codex-runner.sh outreach   daily: inbox replies, follow-ups, pre-drafted sends, new drafts
#   linkedin-codex-runner.sh inbox      every 2h: inbox auto-replies + escalations only
#   linkedin-codex-runner.sh apply      LinkedIn Easy Apply: scan, Codex decides fit, script fills + submits,
#                                       one Codex pass answers what the script could not derive
#   add --dry-run to any: decide everything, send nothing (apply mode fills every form but stops at Review)
# The inbox pass never lets Codex touch the browser: scripts/linkedin-inbox.js reads the
# inbox into a small digest, Codex (profile `linkedin-inbox`, no browser MCP) decides and
# writes the replies to a file, then linkedin-inbox.js sends and verifies them. Codex
# browsing the inbox itself cost ~3M tokens a run and ate the ChatGPT quota on 2026-09-30.
# The outreach part still runs the Mini's ~/.codex/skills/linkedin skill via the `linkedin`
# profile (~/.codex/linkedin.config.toml), which supplies the linkedin-browser Playwright MCP
# on the dedicated ~/.linkedin-codex-profile. Setup + gotchas: AUTOMATION.md,
# section "Mac Mini + Codex".
#
# Test hooks (used by tests/battle/, never set by cron):
#   LINKEDIN_TEST_DIR   scratch folder replacing the outreach folder, state files and logs;
#                       alerts are printed to the log instead of DMed
#   LINKEDIN_TEST_BASE  origin of the mock LinkedIn the skill should browse instead
#   LINKEDIN_MAX_SECONDS  override the run cap
#   LINKEDIN_CODEX_BIN  stand-in for `codex` (tests exercise the cap and usage-limit paths
#                       without spending ChatGPT quota)
#   LINKEDIN_INBOX_BIN  stand-in for `node scripts/linkedin-inbox.js` (same reason: no Chrome)

set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

MODE="${1:-outreach}"
DRY_RUN=""; [ "${2:-}" = "--dry-run" ] && DRY_RUN=1
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEST_DIR="${LINKEDIN_TEST_DIR:-}"
PROFILE_DIR="$HOME/.linkedin-codex-profile"
LOCK_DIR="/tmp/linkedin-codex-run.lock"
# WHY not plain `codex`: PATH starts with /opt/homebrew/bin, which holds the brew cask
# 0.155.0. After the Codex app self-updated on 2026-09-30 that binary hung on everything,
# even `--version`, and both battle rounds sat out the whole 45 min cap with no output.
# The app keeps ~/.codex/packages/standalone/current current, so prefer it.
CODEX_STANDALONE="$HOME/.codex/packages/standalone/current/bin/codex"
if [ -x "$CODEX_STANDALONE" ]; then CODEX_DEFAULT="$CODEX_STANDALONE"; else CODEX_DEFAULT=codex; fi
CODEX="${LINKEDIN_CODEX_BIN:-$CODEX_DEFAULT}"
PREFLIGHT_SECONDS="${LINKEDIN_PREFLIGHT_SECONDS:-20}"
INBOX_BIN="${LINKEDIN_INBOX_BIN:-node $SCRIPT_DIR/linkedin-inbox.js}"
APPLY_BIN="${LINKEDIN_APPLY_BIN:-node $SCRIPT_DIR/linkedin-apply.js}"
MAX_SECONDS="${LINKEDIN_MAX_SECONDS:-2700}"   # 45 min cap; macOS has no `timeout`, so perl alarm below
TODAY=$(date +%Y-%m-%d)

if [ -n "$TEST_DIR" ]; then
    OUTREACH_DIR="$TEST_DIR"
    STATE_DIR="$TEST_DIR/.state"
    LOG_DIR="$TEST_DIR/.logs"
    export LINKEDIN_NOTIFY_QUEUE="$TEST_DIR/needs-jiv.jsonl"
    export LINKEDIN_NOTIFY_STATE="$STATE_DIR/needs_jiv_posted"
    export LINKEDIN_NOTIFY_DRY=1
else
    # Real path, not ~/Desktop/Work: that is a symlink and Codex rejects symlinked writable roots.
    OUTREACH_DIR="$HOME/Work/job-email-bot/marketing/outreach"
    STATE_DIR="$HOME"
    LOG_DIR="$HOME/Library/Logs/linkedin-codex"
fi
STAMP_FILE="$STATE_DIR/.linkedin_codex_last_run"   # outreach: one success per day
ALERT_FILE="$STATE_DIR/.linkedin_codex_alerted"    # failure alerts: one DM per day
DASH_ALERT_FILE="$STATE_DIR/.linkedin_dash_alerted"
BLOCKED_FILE="$STATE_DIR/.linkedin_codex_blocked_until"   # epoch; set when ChatGPT quota runs out
LOG="$LOG_DIR/$TODAY.log"

case "$MODE" in outreach|inbox|apply) ;; *) echo "usage: $0 outreach|inbox|apply [--dry-run]" >&2; exit 2 ;; esac

mkdir -p "$LOG_DIR" "$STATE_DIR"
exec >>"$LOG" 2>&1

# The ChatGPT plan behind Codex has a usage limit shared with the Mini's other
# automations. Once hit, every run fails until the reset, so wait it out quietly.
if [ -f "$BLOCKED_FILE" ] && [ "$(date +%s)" -lt "$(cat "$BLOCKED_FILE")" ]; then
    echo "[$(date)] $MODE: skipping, Codex usage limit until $(date -r "$(cat "$BLOCKED_FILE")" '+%H:%M')"
    exit 0
fi

if [ "$MODE" = outreach ] && [ -z "$DRY_RUN" ] && [ -f "$STAMP_FILE" ] && [ "$(cat "$STAMP_FILE")" = "$TODAY" ]; then
    echo "[$(date)] $MODE: skipping, already succeeded today"
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

echo "[$(date)] $MODE${DRY_RUN:+ (dry run)}${TEST_DIR:+ (TEST)}: starting \$linkedin run"

SKILL='No human is attached, so never ask a question: follow /Users/admin/.codex/skills/linkedin/SKILL.md in Scheduled Automation Mode.'
SUMMARY="$LOG_DIR/$TODAY-$MODE-$(date +%H%M%S)-summary.md"
INBOX_DIR="$OUTREACH_DIR/.inbox"
LOG_START=$(wc -c < "$LOG")

prefix() {   # DRY RUN / TEST MODE framing shared by every Codex prompt
    local p="$1"
    [ -n "$DRY_RUN" ] && p="DRY RUN: send nothing, follow the skill's Dry run rules. $p"
    [ -n "$TEST_DIR" ] && p="TEST MODE: LinkedIn origin is ${LINKEDIN_TEST_BASE:-https://www.linkedin.com} and the outreach folder is $TEST_DIR; follow the skill's Test Mode section. $p"
    echo "$p"
}
run_codex() {   # run_codex <profile> <summary file> <prompt>
    # Preflight: a Codex that cannot even print its version would burn the whole cap
    # silently. Fail in seconds, return 5, and let the alert name the real cause.
    if ! perl -e 'alarm shift; exec @ARGV' "$PREFLIGHT_SECONDS" "$CODEX" --version >/dev/null 2>&1 < /dev/null; then
        echo "Codex ($CODEX) did not answer --version within ${PREFLIGHT_SECONDS}s, not starting a run. RUN_STATUS=blocked:codex_unresponsive" > "$2"
        return 5
    fi
    perl -e 'alarm shift; exec @ARGV' "$MAX_SECONDS" \
        "$CODEX" exec --profile "$1" --skip-git-repo-check -C "$OUTREACH_DIR" -o "$2" "$3" < /dev/null
}
# codex exec exits 0 even when the run couldn't do its job (the first dry run did
# exactly that), so every pass must end with RUN_STATUS=ok for the run to count.
status_of() { grep -o 'RUN_STATUS=[^[:space:]`]*' "$1" 2>/dev/null | tail -1; }

# Inbox pass: linkedin-inbox.js reads, Codex decides with no browser, linkedin-inbox.js
# sends + verifies. Writes its RUN_STATUS to $1; returns Codex's exit code (142 = cap).
inbox_pass() {
    local sum="$1" rc n
    rm -rf "$INBOX_DIR"; mkdir -p "$INBOX_DIR"
    $INBOX_BIN read --out "$INBOX_DIR/digest.json" ${LINKEDIN_TEST_BASE:+--base "$LINKEDIN_TEST_BASE"}
    rc=$?
    if [ $rc -eq 3 ]; then
        echo "Inbox: LinkedIn showed a login wall, nothing read. RUN_STATUS=blocked:linkedin_session_expired" > "$sum"; return 0
    elif [ $rc -ne 0 ] || [ ! -s "$INBOX_DIR/digest.json" ]; then
        echo "Inbox: reader failed (exit $rc). RUN_STATUS=blocked:inbox_reader_failed" > "$sum"; return 0
    fi
    n=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["threads"]))' "$INBOX_DIR/digest.json" 2>/dev/null || echo 0)
    if [ "$n" = 0 ]; then
        echo "Inbox: no conversation awaits a reply, Codex not started. RUN_STATUS=ok" > "$sum"; return 0
    fi
    run_codex linkedin-inbox "$sum" "$(prefix "INBOX DIGEST run of \$linkedin. $SKILL Follow its Inbox Digest Mode section: the runner already read the inbox into $INBOX_DIR/digest.json ($n conversations whose last message is from the other person). You have no browser in this run; never try to open LinkedIn. Apply the Inbox Auto-Reply rules to every thread in the digest, write the auto-replies to $INBOX_DIR/actions.json, append escalations to needs-jiv.jsonl, record the tracker rows, and stop. No tracking pass, no search, no connection notes.")"
    rc=$?
    [ $rc -ne 0 ] && return $rc
    [ -n "$DRY_RUN" ] && return 0
    [ "$(status_of "$sum")" = "RUN_STATUS=ok" ] || return 0
    $INBOX_BIN send --actions "$INBOX_DIR/actions.json" --digest "$INBOX_DIR/digest.json" \
        --log "$OUTREACH_DIR/inbox-sent.jsonl" ${LINKEDIN_TEST_BASE:+--base "$LINKEDIN_TEST_BASE"}
    rc=$?
    if [ $rc -eq 3 ]; then echo "RUN_STATUS=blocked:linkedin_session_expired" >> "$sum"
    elif [ $rc -ne 0 ]; then echo "RUN_STATUS=blocked:inbox_send_failed (see inbox-sent.jsonl)" >> "$sum"; fi
    return 0
}

# Apply pass: linkedin-apply.js scans and fills, Codex (profile `linkedin-apply`, NO browser)
# only decides fit and answers what the script could not derive from apply-profile.json.
# Returns Codex's exit code (142 = cap, 5 = unresponsive); a login wall or empty scan never starts Codex.
APPLY_DIR="$OUTREACH_DIR/.apply"
APPLY_SKILL='No human is attached, so never ask a question: follow /Users/admin/.codex/skills/linkedin-apply/SKILL.md'
jobs_in() { python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get(sys.argv[2],[])))' "$1" "${2:-jobs}" 2>/dev/null || echo 0; }
apply_pass() {
    local sum="$1" rc n arc npend ids sum2 files
    local dry=""; [ -n "$DRY_RUN" ] && dry="--dry-run"
    local base=""; [ -n "${LINKEDIN_TEST_BASE:-}" ] && base="--base $LINKEDIN_TEST_BASE"
    files="--digest $APPLY_DIR/digest.json --profile $OUTREACH_DIR/apply-profile.json --bank $OUTREACH_DIR/apply-answer-bank.json --log $OUTREACH_DIR/apply-log.jsonl"
    rm -rf "$APPLY_DIR"; mkdir -p "$APPLY_DIR"
    $APPLY_BIN scan --out "$APPLY_DIR/digest.json" --applied "$OUTREACH_DIR/apply-log.jsonl" $base
    rc=$?
    if [ $rc -eq 3 ]; then
        echo "Apply: LinkedIn showed a login wall, nothing scanned. RUN_STATUS=blocked:linkedin_session_expired" > "$sum"; return 0
    elif [ $rc -ne 0 ] || [ ! -s "$APPLY_DIR/digest.json" ]; then
        echo "Apply: scan failed (exit $rc). RUN_STATUS=blocked:apply_scan_failed" > "$sum"; return 0
    fi
    n=$(jobs_in "$APPLY_DIR/digest.json")
    if [ "$n" = 0 ]; then
        echo "Apply: no new eligible jobs, Codex not started. RUN_STATUS=ok" > "$sum"; return 0
    fi
    if [ ! -s "$OUTREACH_DIR/apply-profile.json" ]; then
        echo "Apply: $OUTREACH_DIR/apply-profile.json is missing. RUN_STATUS=blocked:apply_profile_missing" > "$sum"; return 0
    fi
    run_codex linkedin-apply "$sum" "$(prefix "APPLY DECIDE run of the linkedin-apply skill. $APPLY_SKILL, section APPLY DECIDE. Inputs: $APPLY_DIR/digest.json ($n jobs), $OUTREACH_DIR/apply-profile.json, $OUTREACH_DIR/apply-resume.md. Write $APPLY_DIR/decisions.json and stop. You have no browser; never open LinkedIn.")"
    rc=$?
    [ $rc -ne 0 ] && return $rc
    [ "$(status_of "$sum")" = "RUN_STATUS=ok" ] || return 0
    if [ ! -s "$APPLY_DIR/decisions.json" ]; then echo "RUN_STATUS=blocked:apply_no_decisions" >> "$sum"; return 0; fi
    $APPLY_BIN apply $files --decisions "$APPLY_DIR/decisions.json" --pending "$APPLY_DIR/pending.json" $dry $base
    arc=$?
    if [ $arc -eq 3 ]; then echo "RUN_STATUS=blocked:linkedin_session_expired" >> "$sum"; return 0; fi
    npend=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$APPLY_DIR/pending.json" 2>/dev/null || echo 0)
    if [ "$npend" -gt 0 ]; then
        sum2="${sum%-summary.md}-answers-summary.md"
        run_codex linkedin-apply "$sum2" "$(prefix "APPLY ANSWER run of the linkedin-apply skill. $APPLY_SKILL, section APPLY ANSWER. Inputs: $APPLY_DIR/pending.json ($npend jobs), $OUTREACH_DIR/apply-profile.json, $OUTREACH_DIR/apply-resume.md. Write $APPLY_DIR/answers.json and stop. You have no browser; never open LinkedIn.")"
        rc=$?
        [ $rc -ne 0 ] && return $rc
        if [ "$(status_of "$sum2")" = "RUN_STATUS=ok" ] && [ -s "$APPLY_DIR/answers.json" ]; then
            ids=$(python3 -c 'import json,sys; print(",".join(j["job_id"] for j in json.load(open(sys.argv[1]))))' "$APPLY_DIR/pending.json")
            $APPLY_BIN apply $files --decisions "$APPLY_DIR/decisions.json" --only "$ids" --answers "$APPLY_DIR/answers.json" --pending "$APPLY_DIR/pending2.json" $dry $base
            arc=$?
            if [ $arc -eq 3 ]; then echo "RUN_STATUS=blocked:linkedin_session_expired" >> "$sum"; return 0; fi
        else
            echo "Apply: answer pass wrote nothing usable; those jobs stay unanswered for now." >> "$sum"
        fi
    fi
    [ $arc -eq 4 ] && echo "RUN_STATUS=blocked:apply_failed (see apply-log.jsonl)" >> "$sum"
    return 0
}

if [ "$MODE" = inbox ]; then
    inbox_pass "$SUMMARY"
    EXIT_CODE=$?
elif [ "$MODE" = apply ]; then
    apply_pass "$SUMMARY"
    EXIT_CODE=$?
else
    INBOX_SUMMARY="${SUMMARY%-summary.md}-inbox-summary.md"
    inbox_pass "$INBOX_SUMMARY"
    EXIT_CODE=$?
    INBOX_STATUS=$(status_of "$INBOX_SUMMARY")
    if [ $EXIT_CODE -eq 0 ] && ! grep -q linkedin_session_expired "$INBOX_SUMMARY" \
        && ! tail -c +$((LOG_START + 1)) "$LOG" | grep -q 'hit your usage limit'; then
        run_codex linkedin "$SUMMARY" "$(prefix "Scheduled automation run of \$linkedin. $SKILL Use the linkedin-browser MCP for every LinkedIn page. The runner already did the Inbox Auto-Reply pass this run (results in inbox-sent.jsonl), so skip it and start with the tracking pass, then the rest of the scheduled flow. Update the tracker, append the run report in this folder, then close the browser.")"
        EXIT_CODE=$?
    else
        cp "$INBOX_SUMMARY" "$SUMMARY" 2>/dev/null
    fi
    # A failed inbox pass fails the run even when the outreach part went fine.
    [ $EXIT_CODE -eq 0 ] && [ "$INBOX_STATUS" != "RUN_STATUS=ok" ] \
        && echo "${INBOX_STATUS:-RUN_STATUS=missing} (inbox pass)" >> "$SUMMARY"
fi

RUN_STATUS=$(status_of "$SUMMARY")
echo "[$(date)] $MODE: ${RUN_STATUS:-RUN_STATUS missing}"
if [ $EXIT_CODE -eq 0 ] && [ "$RUN_STATUS" != "RUN_STATUS=ok" ]; then
    EXIT_CODE=3
fi

# Usage limit: "You've hit your usage limit ... try again at 11:14 AM". Record the reset
# (tomorrow if that clock time already passed), alert once, and let later runs skip.
LIMIT_AT=$(tail -c +$((LOG_START + 1)) "$LOG" | grep -o 'hit your usage limit.*try again at [0-9:]* [AP]M' | tail -1 | grep -o '[0-9]*:[0-9]* [AP]M')
if [ -n "$LIMIT_AT" ]; then
    UNTIL=$(date -j -f "%Y-%m-%d %I:%M %p" "$TODAY $LIMIT_AT" +%s 2>/dev/null)
    [ -n "$UNTIL" ] && [ "$UNTIL" -le "$(date +%s)" ] && UNTIL=$((UNTIL + 86400))
    [ -n "$UNTIL" ] && echo "$UNTIL" > "$BLOCKED_FILE"
    echo "[$(date)] $MODE: Codex usage limit hit, runs paused until $LIMIT_AT"
    [ -z "$DRY_RUN" ] && python3 "$SCRIPT_DIR/linkedin-notify.py" --text "Codex (ChatGPT plan) hit its usage limit on the Mini. LinkedIn runs are paused until $LIMIT_AT, then resume on their own."
    EXIT_CODE=4
fi

# Escalations first, whatever the exit code: a run can fail late after writing them.
[ -z "$DRY_RUN" ] && python3 "$SCRIPT_DIR/linkedin-notify.py"

# Jiv's hard rule: no em/en-dashes in anything Codex writes. The skill checks before
# every send; this catches what slips through (those files hold sent + drafted text).
DASHED=$(grep -l -e $'\xe2\x80\x94' -e $'\xe2\x80\x93' "$OUTREACH_DIR/linkedin-outreach-tracker.json" \
    "$OUTREACH_DIR/needs-jiv.jsonl" "$SUMMARY" 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')
if [ -n "$DASHED" ] && [ -z "$DRY_RUN" ] && [ "$(cat "$DASH_ALERT_FILE" 2>/dev/null)" != "$TODAY" ]; then
    echo "[$(date)] $MODE: em/en-dash found in: $DASHED"
    python3 "$SCRIPT_DIR/linkedin-notify.py" --text "Codex wrote an em/en-dash in LinkedIn text on the Mini (in: $DASHED). Check $OUTREACH_DIR." \
        && echo "$TODAY" > "$DASH_ALERT_FILE"
fi

if grep -q "linkedin_session_expired" "$SUMMARY" 2>/dev/null; then
    alert_once "LinkedIn session on the Mini expired. Screen Share to vnc://100.98.219.58, then: cd ~/agent-work/jobi && PLAYWRIGHT_PROFILE=~/.linkedin-codex-profile LOGIN_TIMEOUT_MIN=20 npm run login"
fi

if [ $EXIT_CODE -eq 4 ]; then
    :   # usage limit: already alerted above with the reset time
elif [ $EXIT_CODE -eq 0 ]; then
    [ "$MODE" = outreach ] && [ -z "$DRY_RUN" ] && echo "$TODAY" > "$STAMP_FILE"
    echo "[$(date)] $MODE: completed."
else
    echo "[$(date)] $MODE: failed with exit code $EXIT_CODE (142 = hit the ${MAX_SECONDS}s cap, 3 = RUN_STATUS not ok, 4 = usage limit, 5 = Codex unresponsive)"
    alert_once "LinkedIn $MODE run on the Mini failed (exit $EXIT_CODE, ${RUN_STATUS:-no RUN_STATUS}). Log: $LOG"
fi
exit $EXIT_CODE
