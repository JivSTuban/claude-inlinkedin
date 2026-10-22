#!/bin/bash
# Mac Mini launcher for the OnlineJobs external-application run. Docs: AUTOMATION.md "The trigger".
#
#   onlinejobs-apply-mini.sh             a real run, only when the gate finds an unactioned lead
#   onlinejobs-apply-mini.sh --dry-run   gate only: print the leads that would be worked, start nothing
#   onlinejobs-apply-mini.sh --leads F   work exactly the leads in file F (JSON lines), skipping the gate
#
# Why the Mini: it is always on, so the hourly run no longer depends on a laptop lid. The model is Codex
# (already signed in here, proven by the LinkedIn runner), because the Mini's Claude CLI has no login.
# This replaces the MacBook's onlinejobs-apply-runner.sh, which is switched off once this is live.
# Cron: 5 * * * * /Users/admin/agent-work/jobi/scripts/onlinejobs-apply-mini.sh >> ~/.onlinejobs-apply/logs/cron.log 2>&1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"

HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="$HOME/.onlinejobs-apply"
WORK="$STATE/state"                       # codex cwd: holds applied.jsonl, TRACKER.md, the staged resume
LOGDIR="$STATE/logs"
PAUSE="$STATE/PAUSE"                      # touch it to stop every future run
export OJ_SKILL_DIR="$WORK"
PY=/opt/homebrew/bin/python3.10
# The standalone Codex, not the brew cask (0.155.0 hangs on every call; see AUTOMATION.md, LinkedIn on the Mini).
CODEX="$HOME/.codex/packages/standalone/current/bin/codex"; [ -x "$CODEX" ] || CODEX=codex
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
[ "$DRY" = 1 ] && { say "dry run: stopping before Codex"; exit 0; }

# One Chrome per profile. A leftover or interactive Chrome would make the run fail, so wait for the next tick.
if pgrep -f "$CHROME_PAT" >/dev/null; then say "skip: the onlinejobs browser profile is in use"; exit 0; fi
# The browser may only upload files from the working directory, so the resume is staged there every run.
cp "$STATE/resume.pdf" "$WORK/jiv-resume.pdf" 2>/dev/null || { say "skip: $STATE/resume.pdf missing"; $REPORT failed run "resume file missing on the Mini"; exit 1; }
# Preflight: a hung Codex must not eat the cap.
if ! perl -e 'alarm shift; exec @ARGV' 30 "$CODEX" --version >/dev/null 2>&1 </dev/null; then
  say "skip: codex did not answer --version"; $REPORT failed run "codex is unresponsive on the Mini"; exit 1
fi

PROMPT="No human is attached, so never ask a question: follow /Users/admin/.codex/skills/onlinejobs-apply/SKILL.md.

Scheduled run. Use ONLY the onlinejobs-browser MCP tools for the browser (never cua_repl, node_repl or computer use). Work ONLY these queued leads (already deduped against the tracker). Apply every gate to each one, log EVERY outcome, skips included, with the logging command in the skill, and stop when every lead is logged. For a handoff the note must START with the exact action Jiv has to take, under 150 characters, then the reason. If a posting page does not match the queued lead, trust the live page and say so in the note.

$(cat "$LEADS")"

APPLIED="$WORK/applied.jsonl"
BEFORE=$(wc -l < "$APPLIED" 2>/dev/null | tr -d ' '); BEFORE=${BEFORE:-0}
SUM="$STATE/last-summary.txt"
say "starting codex (cap ${CAP_S}s)"
cd "$WORK" || exit 1
perl -e 'alarm shift; exec @ARGV' "$CAP_S" "$CODEX" exec --profile onlinejobs-apply --skip-git-repo-check -C "$WORK" -o "$SUM" "$PROMPT" </dev/null >> "$LOG" 2>&1
RC=$?
say "codex exit $RC"
# Killed by the alarm (142) or crashed: its Chrome may outlive it and would block every later tick.
[ "$RC" -ne 0 ] && pkill -f "$CHROME_PAT" 2>/dev/null
AFTER=$(wc -l < "$APPLIED" 2>/dev/null | tr -d ' '); AFTER=${AFTER:-0}
say "applied.jsonl: $((AFTER - BEFORE)) new row(s)"
$REPORT outcomes "$BEFORE" >> "$LOG" 2>&1
# codex exec exits 0 even when it could not do its job, and the skill logs every outcome (skips too), so a lead
# with no outcome was not worked: browser signed out, MCP missing, cut off, quota out.
if [ "$RC" -ne 0 ]; then
  $REPORT failed run "Codex exited $RC (log: $LOG)" >> "$LOG" 2>&1
elif ! LEFT=$($REPORT unhandled "$LEADS" 2>>"$LOG"); then
  say "not worked: $LEFT"
  $REPORT failed run "it finished but did not log an outcome for: $(echo "$LEFT" | tr '\n' ';' | cut -c1-160)" >> "$LOG" 2>&1
  RC=1
else
  $REPORT ok run >> "$LOG" 2>&1
fi
exit "$RC"
