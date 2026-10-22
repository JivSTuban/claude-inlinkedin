#!/bin/bash
# Mac Mini launcher for the OnlineJobs external-application run. Docs: AUTOMATION.md "The trigger".
#
#   onlinejobs-apply-mini.sh             a real run, only when the gate finds an unactioned lead
#   onlinejobs-apply-mini.sh --dry-run   gate only: print the leads that would be worked, start nothing
#   onlinejobs-apply-mini.sh --leads F   work exactly the leads in file F (JSON lines), skipping the gate
#
# Why the Mini: it is always on, so the hourly run no longer depends on a laptop lid.
# Why Claude (2026-10-22): the ChatGPT quota behind Codex is shared with the Mini's other automations, so a busy
# LinkedIn day could starve this run. Claude runs on its own subscription, authenticated by a long-lived token in
# $STATE/claude.env (made once by scripts/onlinejobs-claude-token.sh), because the Mini's login keychain is locked
# over ssh/cron and a normal `claude` login cannot be read there.
# Before the model starts, scripts/onlinejobs-ensure-login.js makes sure the browser profile is signed in to
# OnlineJobs and Google, so an expired session is repaired (OnlineJobs) or reported early (Google) instead of
# failing a lead halfway through.
# Cron: 5 * * * * /Users/admin/agent-work/jobi/scripts/onlinejobs-apply-mini.sh >> ~/.onlinejobs-apply/logs/cron.log 2>&1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"

HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="${OJ_APPLY_STATE:-$HOME/.onlinejobs-apply}"
WORK="$STATE/state"                       # claude cwd: holds applied.jsonl, TRACKER.md, the staged resume
LOGDIR="$STATE/logs"
PAUSE="$STATE/PAUSE"                      # touch it to stop every future run
export OJ_SKILL_DIR="$WORK"
PY="${OJ_PY:-/opt/homebrew/bin/python3.10}"
CLAUDE="${OJ_CLAUDE_BIN:-/opt/homebrew/bin/claude}"
# Sonnet: the work is form filling under written gates, not open-ended reasoning, and it keeps the plan's usage low.
MODEL="${OJ_APPLY_MODEL:-sonnet}"
SKILL_DIR="$HOME/.codex/skills/onlinejobs-apply"   # path kept from the Codex port; the skill text is model-neutral
MCP_CONFIG="$STATE/mcp.json"
# The login helper needs node, and cron's PATH has none of the version managers' shims.
NODE=""; for c in /opt/homebrew/bin/node "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node" /usr/local/bin/node; do
  [ -x "$c" ] && { NODE="$c"; break; }
done
LOGIN_BIN="${OJ_LOGIN_BIN:-$NODE $HERE/onlinejobs-ensure-login.js --google}"
# Real Chrome holds the profile as "--user-data-dir=<path>" (with =); the idle Playwright MCP node process uses a
# space and must not count as in use.
CHROME_PAT="user-data-dir=.*\.onlinejobs-apply/browser-profile"
CAP_S="${OJ_APPLY_CAP_S:-2400}"           # macOS has no `timeout`; perl alarm below. A hung browser must not hold the lock.
mkdir -p "$LOGDIR" "$WORK"
find "$LOGDIR" -name 'run-*.log' -mtime +14 -delete 2>/dev/null   # an idle tick still writes a one-line log
LOG="$LOGDIR/run-$(date +%Y-%m-%d-%H%M).log"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
REPORT="$PY $HERE/onlinejobs_apply_report.py"

DRY=0; LEADS_ARG=""
case "$1" in --dry-run) DRY=1 ;; --leads) LEADS_ARG="$2" ;; esac
[ -e "$PAUSE" ] && { say "skip: $PAUSE exists"; exit 0; }
[ -e "$HOME/Work/job-email-bot/onlinejobs-apply.disabled" ] && { say "skip: onlinejobs-apply.disabled exists"; exit 0; }

LOCK="$STATE/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then say "skip: a run is already active"; exit 0; fi
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

LEADS="$STATE/leads.jsonl"
if [ -n "$LEADS_ARG" ]; then cp "$LEADS_ARG" "$LEADS"; GATE=0; else $PY "$HERE/onlinejobs_apply_gate.py" > "$LEADS" 2>>"$LOG"; GATE=$?; fi
case $GATE in
  0) $REPORT ok gate; say "gate: $(wc -l < "$LEADS" | tr -d ' ') open lead(s)" ;;
  3) $REPORT ok gate; say "gate: nothing to apply to"; exit 0 ;;
  *) say "gate: queue unreadable, see log"; $REPORT failed gate "cannot read the lead queue (oj-state.json)"; exit 1 ;;
esac
cat "$LEADS" | tee -a "$LOG" | cut -c1-200
[ "$DRY" = 1 ] && { say "dry run: stopping before Claude"; exit 0; }

# One Chrome per profile. A leftover or interactive Chrome would make the run fail, so wait for the next tick.
if pgrep -f "$CHROME_PAT" >/dev/null; then say "skip: the onlinejobs browser profile is in use"; exit 0; fi
# The browser may only upload files from the working directory, so the resume is staged there every run.
cp "$STATE/resume.pdf" "$WORK/jiv-resume.pdf" 2>/dev/null || { say "skip: $STATE/resume.pdf missing"; $REPORT failed run "resume file missing on the Mini"; exit 1; }

# Claude's token. An ANTHROPIC_API_KEY in the environment would win over it and bill the API, so drop it.
unset ANTHROPIC_API_KEY
[ -f "$STATE/claude.env" ] && { set -a; . "$STATE/claude.env"; set +a; }
if [ -z "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
  say "skip: no Claude token on the Mini"
  $REPORT failed run "Claude has no login on the Mini. On the MacBook run: ssh -t admin@100.98.219.58 ~/agent-work/jobi/scripts/onlinejobs-claude-token.sh" >> "$LOG" 2>&1
  exit 1
fi
# Preflight: a hung Claude must not eat the cap.
if ! perl -e 'alarm shift; exec @ARGV' 30 "$CLAUDE" --version >/dev/null 2>&1 </dev/null; then
  say "skip: claude did not answer --version"; $REPORT failed run "claude is unresponsive on the Mini"; exit 1
fi

# Sign-in, before the model so a dead session never costs a model run. OnlineJobs is re-signed in with the saved
# credentials (one attempt, throttled; see the script); Google can only be reported, since it blocks scripted logins.
say "login check"
if [ -z "$OJ_LOGIN_BIN" ] && [ -z "$NODE" ]; then
  say "skip: node not found"; $REPORT failed login "node is missing on the Mini, so the sign-in check cannot run" >> "$LOG" 2>&1; exit 1
fi
LOGIN_OUT=$(ONLINEJOBS_PROFILE="$STATE/browser-profile" ONLINEJOBS_STATE_FILE="$STATE/login-state.json" \
  ONLINEJOBS_ENV_FILE="$HOME/.onlinejobs.env" perl -e 'alarm shift; exec @ARGV' 180 $LOGIN_BIN </dev/null 2>&1); LRC=$?
echo "$LOGIN_OUT" | sed -E 's/(password|token)=[^ ]*/\1=***/Ig' >> "$LOG"
pkill -f "$CHROME_PAT" 2>/dev/null     # the login helper's Chrome, if the alarm cut it off
case $LRC in
  0) $REPORT ok login ;;
  7) say "login: Google signed out"; $REPORT failed login "Sign in to Google in the Mini browser profile (Gmail sends and Google Forms need it). Google blocks scripted sign-in." >> "$LOG" 2>&1; exit 1 ;;
  3) say "login: needs a human"; $REPORT failed login "OnlineJobs sign-in needs you: a captcha or a code is showing. Sign in once in the Mini browser profile." >> "$LOG" 2>&1; exit 1 ;;
  5) say "login: credentials missing or rejected"; $REPORT failed login "OnlineJobs rejected the saved password. Update ONLINEJOBS_PASSWORD in ~/.onlinejobs.env on the Mini." >> "$LOG" 2>&1; exit 1 ;;
  6) say "login: throttled, waiting"; $REPORT failed login "OnlineJobs sign-in is paused after a recent failed attempt; it retries by itself." >> "$LOG" 2>&1; exit 1 ;;
  *) say "login: helper failed ($LRC)"; $REPORT failed login "The sign-in check crashed (exit $LRC). Log: $LOG" >> "$LOG" 2>&1; exit 1 ;;
esac

sleep 3                                # let Chrome release the profile lock before the MCP opens it
LOGCMD="$PY $HERE/onlinejobs_log_outcome.py"
PROMPT="No human is attached, so never ask a question: read and follow $SKILL_DIR/SKILL.md (its private facts are in $SKILL_DIR/FACTS.md).

Scheduled run. Use ONLY the onlinejobs-browser MCP tools for the browser. Work ONLY these queued leads (already deduped against the tracker). Apply every gate to each one, log EVERY outcome, skips included, and stop when every lead is logged. Log each outcome by running exactly this command (it overrides the form shown in the skill; you cannot edit the tracker files directly):
$LOGCMD --url <posting url> --title <real title from the live page> --status <submitted|sent|handoff|skipped> --fit <0-100> --note <one line why> [--employer <name>] [--method form|email] [--form-url <url>] [--email <address>]
For --status handoff the note must START with the exact action Jiv has to take, under 150 characters, then the reason. If a posting page does not match the queued lead, trust the live page and say so in the note.

$(cat "$LEADS")"

APPLIED="$WORK/applied.jsonl"
BEFORE=$(wc -l < "$APPLIED" 2>/dev/null | tr -d ' '); BEFORE=${BEFORE:-0}
SUM="$STATE/last-summary.txt"
say "starting claude $MODEL (cap ${CAP_S}s)"
cd "$WORK" || exit 1
# dontAsk + a narrow allowlist: the browser MCP, reading the skill, and the one logging command. No shell, no web.
perl -e 'alarm shift; exec @ARGV' "$CAP_S" "$CLAUDE" -p "$PROMPT" --model "$MODEL" \
  --mcp-config "$MCP_CONFIG" --strict-mcp-config --add-dir "$SKILL_DIR" \
  --permission-mode dontAsk --permission-prompts none \
  --allowedTools "mcp__onlinejobs-browser__*,ToolSearch,Read,Bash($LOGCMD:*)" \
  --disallowedTools "Agent,WebFetch,WebSearch" </dev/null > "$SUM" 2>> "$LOG"
RC=$?
cat "$SUM" >> "$LOG" 2>/dev/null
say "claude exit $RC"
# Killed by the alarm (142) or crashed: its Chrome may outlive it and would block every later tick.
[ "$RC" -ne 0 ] && pkill -f "$CHROME_PAT" 2>/dev/null
AFTER=$(wc -l < "$APPLIED" 2>/dev/null | tr -d ' '); AFTER=${AFTER:-0}
say "applied.jsonl: $((AFTER - BEFORE)) new row(s)"
$REPORT outcomes "$BEFORE" >> "$LOG" 2>&1
# claude -p exits 0 even when it could not do its job, and the skill logs every outcome (skips too), so a lead
# with no outcome was not worked: browser signed out, MCP missing, cut off, usage limit.
if [ "$RC" -ne 0 ]; then
  $REPORT failed run "Claude exited $RC (log: $LOG)" >> "$LOG" 2>&1
elif ! LEFT=$($REPORT unhandled "$LEADS" 2>>"$LOG"); then
  say "not worked: $LEFT"
  $REPORT failed run "it finished but did not log an outcome for: $(echo "$LEFT" | tr '\n' ';' | cut -c1-160)" >> "$LOG" 2>&1
  RC=1
else
  $REPORT ok run >> "$LOG" 2>&1
fi
exit "$RC"
