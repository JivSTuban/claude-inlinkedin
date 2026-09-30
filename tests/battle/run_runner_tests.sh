#!/bin/bash
# Deterministic failure-path tests for scripts/linkedin-codex-runner.sh and
# scripts/linkedin-notify.py (on the Mac Mini). Everything runs in test mode or with
# env overrides, so nothing touches the real tracker, state files, or Discord DMs.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
RUNNER="$REPO/scripts/linkedin-codex-runner.sh"
NOTIFY="$REPO/scripts/linkedin-notify.py"
PROFILE="$HOME/.linkedin-codex-profile"
LOCK=/tmp/linkedin-codex-run.lock
ROOT="$HOME/Work/job-email-bot/marketing/outreach/.battle-test/runner-$(date +%H%M%S)"
TODAY=$(date +%Y-%m-%d)
FAILS=0
ok()   { echo "PASS $1"; }
bad()  { echo "FAIL $1"; FAILS=$((FAILS+1)); }
chk()  { if eval "$1"; then ok "$2"; else bad "$2"; fi; }
fresh() { T="$ROOT/$1"; mkdir -p "$T"; LOGF="$T/.logs/$TODAY.log"; }
run()  { LINKEDIN_TEST_DIR="$T" LINKEDIN_TEST_BASE="http://127.0.0.1:8766" "$RUNNER" "$@"; }

[ -d "$LOCK" ] && { echo "ABORT: a real run holds $LOCK"; exit 2; }
REAL="$HOME/Work/job-email-bot/marketing/outreach"
snap() { for f in "$REAL/linkedin-outreach-tracker.json" "$REAL/needs-jiv.jsonl" "$HOME/.linkedin_codex_last_run" "$HOME/.linkedin_codex_alerted" "$HOME/.linkedin_needs_jiv_posted"; do [ -e "$f" ] && stat -f "%N %m" "$f"; done; }
BEFORE=$(snap)

# 1. usage error
fresh usage; run bogus; chk '[ $? -eq 2 ]' "bad mode exits 2"

# 2. overlap lock: a held lock makes the run skip and leaves the lock alone
fresh lock; mkdir "$LOCK"; run inbox; RC=$?
chk '[ $RC -eq 0 ] && grep -q "another run holds" "$LOGF" && [ -d "$LOCK" ]' "overlap: skips, keeps the other run's lock"
rmdir "$LOCK"

# 3. Chrome already open on the profile: skip, release lock, don't kill that Chrome
fresh chrome
bash -c "exec -a 'Google Chrome --user-data-dir=$PROFILE' sleep 60" & FAKE=$!
sleep 1; run inbox; RC=$?
chk '[ $RC -eq 0 ] && grep -q "Chrome already has" "$LOGF" && [ ! -d "$LOCK" ] && kill -0 $FAKE 2>/dev/null' "chrome open: skips, releases lock, leaves Chrome running"
kill $FAKE 2>/dev/null

# 4. outreach already succeeded today: skip
fresh stamp; mkdir -p "$T/.state"; echo "$TODAY" > "$T/.state/.linkedin_codex_last_run"; run outreach
chk 'grep -q "already succeeded today" "$LOGF"' "outreach: second success of the day is skipped"

# 5. time cap + alert once per day + dash audit. A fake codex opens a fake
#    "Chrome" on the profile and hangs, so the cap and cleanup are proven without quota.
SHIMS="$ROOT/shims"; mkdir -p "$SHIMS"
cat > "$SHIMS/codex-hang" <<SH
#!/bin/bash
[ "\$1" = --version ] && { echo codex-cli shim; exit 0; }
bash -c "exec -a 'Google Chrome --user-data-dir=$PROFILE' sleep 300" &
sleep 300
SH
cat > "$SHIMS/codex-limit" <<'SH'
#!/bin/bash
[ "$1" = --version ] && { echo codex-cli shim; exit 0; }
touch "$(dirname "$0")/limit-called"
echo "ERROR: You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at ${LIMIT_TIME:-11:59 PM}."
exit 1
SH
# Stand-in for linkedin-inbox.js: one thread awaiting a reply, so the runner reaches Codex.
cat > "$SHIMS/inbox-one" <<'SH'
#!/bin/bash
[ "$1" = read ] && echo '{"threads":[{"n":1,"name":"T","thread_url":"http://x/messaging/thread/t/"}]}' > "$3"
exit 0
SH
chmod +x "$SHIMS"/codex-* "$SHIMS/inbox-one"
export LINKEDIN_INBOX_BIN="$SHIMS/inbox-one"
fresh cap
printf '{"note":"seeded \xe2\x80\x94 dash"}\n' > "$T/linkedin-outreach-tracker.json"
LINKEDIN_CODEX_BIN="$SHIMS/codex-hang" LINKEDIN_MAX_SECONDS=5 run inbox; RC1=$?
sleep 2
LEFT=$(pgrep -f "Google Chrome.*--user-data-dir=$PROFILE" | wc -l | tr -d ' ')
chk '[ $RC1 -eq 142 ]' "cap: killed at the limit, exit 142 (got $RC1)"
chk '[ "$LEFT" = 0 ] && [ ! -d "$LOCK" ]' "cap: Chrome left on the profile is killed, lock released"
chk '[ $(grep -c "notify dry\] LinkedIn inbox run on the Mini failed" "$LOGF") -eq 1 ]' "cap: failure alert sent"
chk '[ $(grep -c "notify dry\] Codex wrote an em/en-dash" "$LOGF") -eq 1 ]' "dash audit: alert sent"
LINKEDIN_CODEX_BIN="$SHIMS/codex-hang" LINKEDIN_MAX_SECONDS=5 run inbox; RC2=$?
pkill -f "sleep 300" 2>/dev/null
chk '[ $RC2 -eq 142 ] && [ $(grep -c "notify dry\] LinkedIn inbox run on the Mini failed" "$LOGF") -eq 1 ]' "failure alert: only once per day"
chk '[ $(grep -c "notify dry\] Codex wrote an em/en-dash" "$LOGF") -eq 1 ]' "dash alert: only once per day"

# 5b. ChatGPT usage limit: pause until the reset, alert once, don't even start Codex meanwhile
fresh limit
LINKEDIN_CODEX_BIN="$SHIMS/codex-limit" LIMIT_TIME="11:59 PM" run inbox; RC=$?
UNTIL=$(cat "$T/.state/.linkedin_codex_blocked_until" 2>/dev/null || echo 0)
chk '[ $RC -eq 4 ] && [ "$(date -r "$UNTIL" +%H:%M)" = "23:59" ]' "usage limit: exit 4, paused until 23:59 (got $RC, $(date -r "$UNTIL" '+%F %H:%M'))"
chk '[ $(grep -c "notify dry\] Codex (ChatGPT plan) hit its usage limit" "$LOGF") -eq 1 ] && [ $(grep -c "notify dry\] LinkedIn inbox run on the Mini failed" "$LOGF") -eq 0 ]' "usage limit: one limit alert, no generic failure alert"
rm -f "$SHIMS/limit-called"
LINKEDIN_CODEX_BIN="$SHIMS/codex-limit" run inbox; RC=$?
chk '[ $RC -eq 0 ] && grep -q "skipping, Codex usage limit until 23:59" "$LOGF" && [ ! -e "$SHIMS/limit-called" ]' "usage limit: next run skips without calling Codex"
fresh limit-past
LINKEDIN_CODEX_BIN="$SHIMS/codex-limit" LIMIT_TIME="12:01 AM" run inbox
UNTIL=$(cat "$T/.state/.linkedin_codex_blocked_until" 2>/dev/null || echo 0)
chk '[ "$(date -r "$UNTIL" +%F)" = "$(date -v+1d +%F)" ]' "usage limit: a reset time already past means tomorrow"

# 5b2. Codex that cannot answer --version (the 2026-09-30 brew 0.155.0 hang): fail in
#      seconds with exit 5 and a named alert, never start the real run, never sit out the cap.
cat > "$SHIMS/codex-dead" <<'SH'
#!/bin/bash
[ "$1" = --version ] && { touch "$(dirname "$0")/dead-version-called"; sleep 300; }
touch "$(dirname "$0")/dead-run-called"
SH
chmod +x "$SHIMS/codex-dead"
fresh dead; rm -f "$SHIMS"/dead-*-called
START=$(date +%s)
LINKEDIN_CODEX_BIN="$SHIMS/codex-dead" LINKEDIN_PREFLIGHT_SECONDS=3 LINKEDIN_MAX_SECONDS=600 run inbox; RC=$?
ELAPSED=$(( $(date +%s) - START ))
pkill -f "sleep 300" 2>/dev/null
chk '[ $RC -eq 5 ] && [ $ELAPSED -lt 30 ]' "dead codex: exit 5 in seconds, not the cap (got $RC after ${ELAPSED}s)"
chk '[ -e "$SHIMS/dead-version-called" ] && [ ! -e "$SHIMS/dead-run-called" ]' "dead codex: preflight ran, the real run never started"
chk '[ $(grep -c "notify dry\] LinkedIn inbox run on the Mini failed (exit 5, RUN_STATUS=blocked:codex_unresponsive" "$LOGF") -eq 1 ]' "dead codex: alert names codex_unresponsive"

# 5c. inbox reader paths that must never spend quota: login wall and an empty inbox
printf '#!/bin/bash\nexit 3\n' > "$SHIMS/inbox-wall"
printf '#!/bin/bash\n[ "$1" = read ] && echo %s > "$3"\nexit 0\n' "'{\"threads\":[]}'" > "$SHIMS/inbox-empty"
chmod +x "$SHIMS/inbox-wall" "$SHIMS/inbox-empty"
fresh wall; rm -f "$SHIMS/limit-called"
LINKEDIN_INBOX_BIN="$SHIMS/inbox-wall" LINKEDIN_CODEX_BIN="$SHIMS/codex-limit" run inbox; RC=$?
chk '[ $RC -eq 3 ] && [ ! -e "$SHIMS/limit-called" ] && grep -q "notify dry\] LinkedIn session on the Mini expired" "$LOGF"' "inbox: login wall exits 3, alerts, never starts Codex (got $RC)"
fresh empty
LINKEDIN_INBOX_BIN="$SHIMS/inbox-empty" LINKEDIN_CODEX_BIN="$SHIMS/codex-limit" run inbox; RC=$?
chk '[ $RC -eq 0 ] && [ ! -e "$SHIMS/limit-called" ]' "inbox: nothing awaiting a reply, Codex never started (got $RC)"

# 5d. apply mode: scan -> Codex decides -> script fills -> Codex answers the rest -> script retries.
#     Fakes stand in for linkedin-apply.js and Codex, so no quota and no real LinkedIn is touched.
cat > "$SHIMS/apply-fake" <<'SH'
#!/bin/bash
D="$(dirname "$0")"; echo "$*" >> "$D/apply-calls"
get() { local n="$1"; shift; while [ $# -gt 0 ]; do [ "$1" = "$n" ] && { echo "$2"; return; }; shift; done; }
case "$1" in
  scan)
    [ -n "${FAKE_WALL:-}" ] && exit 3
    OUT=$(get --out "$@")
    if [ -n "${FAKE_EMPTY:-}" ]; then echo '{"jobs":[]}' > "$OUT"
    else echo '{"jobs":[{"n":1,"id":"111","title":"AI Engineer","company":"Acme","location":"Philippines (Remote)","jd":"x"}]}' > "$OUT"; fi ;;
  apply)
    PEND=$(get --pending "$@")
    if echo "$*" | grep -q -- "--answers"; then echo '[]' > "$PEND"
    else echo '[{"job_id":"111","company":"Acme","title":"AI Engineer","jd":"x","questions":[{"label":"Years with Okta?","kind":"text"}]}]' > "$PEND"; fi ;;
esac
exit 0
SH
cat > "$SHIMS/codex-apply" <<'SH'
#!/bin/bash
D="$(dirname "$0")"
[ "$1" = --version ] && { echo codex-cli shim; exit 0; }
C=""; O=""; PROMPT="${@: -1}"; A=("$@")
for i in "${!A[@]}"; do [ "${A[$i]}" = "-C" ] && C="${A[$((i+1))]}"; [ "${A[$i]}" = "-o" ] && O="${A[$((i+1))]}"; done
case "$PROMPT" in
  *"APPLY DECIDE"*) touch "$D/decide-called"; echo '[{"id":"111","apply":true,"fit":85,"reason":"fits"}]' > "$C/.apply/decisions.json" ;;
  *"APPLY ANSWER"*) touch "$D/answer-called"; echo '[{"job_id":"111","label":"Years with Okta?","answer":"0","reusable":true}]' > "$C/.apply/answers.json" ;;
esac
echo "done. RUN_STATUS=ok" > "$O"
SH
chmod +x "$SHIMS/apply-fake" "$SHIMS/codex-apply"
mkapply() { echo '{"first_name":"T"}' > "$T/apply-profile.json"; rm -f "$SHIMS"/apply-calls "$SHIMS"/decide-called "$SHIMS"/answer-called; }
fresh apply-ok; mkapply
LINKEDIN_APPLY_BIN="$SHIMS/apply-fake" LINKEDIN_CODEX_BIN="$SHIMS/codex-apply" run apply; RC=$?
chk '[ $RC -eq 0 ] && [ -e "$SHIMS/decide-called" ] && [ -e "$SHIMS/answer-called" ]' "apply: decide pass and answer pass both ran, exit 0 (got $RC)"
chk '[ "$(grep -c "^scan" "$SHIMS/apply-calls")" = 1 ] && [ "$(grep -c "^apply" "$SHIMS/apply-calls")" = 2 ] && grep "^apply" "$SHIMS/apply-calls" | tail -1 | grep -q -- "--only 111 .*--answers\|--answers .*--only 111\|--only 111"' "apply: one scan, first fill, then a retry limited to the pending job"
chk 'grep -q "\-\-answers" "$SHIMS/apply-calls" && ! grep "^apply" "$SHIMS/apply-calls" | head -1 | grep -q -- "--answers"' "apply: answers only reach the retry, not the first fill"
fresh apply-dry; mkapply
LINKEDIN_APPLY_BIN="$SHIMS/apply-fake" LINKEDIN_CODEX_BIN="$SHIMS/codex-apply" run apply --dry-run >/dev/null; 
chk '[ "$(grep "^apply" "$SHIMS/apply-calls" | grep -c -- "--dry-run")" = 2 ]' "apply: --dry-run reaches every fill call (nothing can be submitted)"
fresh apply-wall; mkapply
FAKE_WALL=1 LINKEDIN_APPLY_BIN="$SHIMS/apply-fake" LINKEDIN_CODEX_BIN="$SHIMS/codex-apply" run apply; RC=$?
chk '[ $RC -eq 3 ] && [ ! -e "$SHIMS/decide-called" ] && grep -q "notify dry\] LinkedIn session on the Mini expired" "$LOGF"' "apply: login wall exits 3, alerts, never starts Codex (got $RC)"
fresh apply-empty; mkapply
FAKE_EMPTY=1 LINKEDIN_APPLY_BIN="$SHIMS/apply-fake" LINKEDIN_CODEX_BIN="$SHIMS/codex-apply" run apply; RC=$?
chk '[ $RC -eq 0 ] && [ ! -e "$SHIMS/decide-called" ]' "apply: nothing new to apply to, Codex never started (got $RC)"
fresh apply-noprofile; mkapply; rm -f "$T/apply-profile.json"
LINKEDIN_APPLY_BIN="$SHIMS/apply-fake" LINKEDIN_CODEX_BIN="$SHIMS/codex-apply" run apply; RC=$?
chk '[ $RC -eq 3 ] && [ ! -e "$SHIMS/decide-called" ] && grep -q "apply_profile_missing" "$LOGF"' "apply: missing apply-profile.json blocks before Codex (got $RC)"

# 6. notifier: each escalation once, malformed line survives, state advances
fresh notify; Q="$T/q.jsonl"; S="$T/state"
n() { LINKEDIN_NOTIFY_QUEUE="$Q" LINKEDIN_NOTIFY_STATE="$S" LINKEDIN_NOTIFY_DRY=1 python3 "$NOTIFY" | grep -c "notify dry"; }
printf '{"name":"A","thread_url":"u1","their_message":"m","why":"w","suggested_reply":"r"}\n{"name":"B"}\n' > "$Q"
chk '[ "$(n)" = 2 ]' "notify: posts 2 new escalations"
chk '[ "$(n)" = 0 ]' "notify: re-run posts nothing"
printf 'not json\n' >> "$Q"
chk '[ "$(n)" = 1 ]' "notify: malformed line still posted once"

# 7. notifier failure (bad channel, real API, nothing delivered): state must NOT advance
echo '{"name":"C"}' >> "$Q"
LINKEDIN_NOTIFY_QUEUE="$Q" LINKEDIN_NOTIFY_STATE="$S" LINKEDIN_NOTIFY_CHANNEL=1 python3 "$NOTIFY" >/dev/null 2>&1; RC=$?
chk '[ $RC -ne 0 ] && [ "$(cat "$S")" = 3 ]' "notify: Discord failure exits non-zero, keeps the escalation queued"
LINKEDIN_NOTIFY_QUEUE="$Q" LINKEDIN_NOTIFY_STATE="$S" LINKEDIN_NOTIFY_TOKEN_FILE=/nonexistent python3 "$NOTIFY" >/dev/null 2>&1; RC=$?
chk '[ $RC -ne 0 ] && [ "$(cat "$S")" = 3 ]' "notify: missing token file fails loudly, keeps queue"

AFTER=$(snap)
chk '[ "$BEFORE" = "$AFTER" ]' "real tracker, needs-jiv and state files untouched"
echo; [ $FAILS -eq 0 ] && echo "RUNNER TESTS: PASS" || echo "RUNNER TESTS: FAIL ($FAILS)"
exit $FAILS
