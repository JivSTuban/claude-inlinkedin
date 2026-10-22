#!/bin/bash
# MacBook launcher for /onlinejobs-apply. Docs: AUTOMATION.md "OnlineJobs external applications".
#
#   onlinejobs-apply-runner.sh             a real run, only when the gate finds an unactioned lead
#   onlinejobs-apply-runner.sh --dry-run   gate only: print the leads that would be worked, start nothing
#   onlinejobs-apply-runner.sh --leads F   work exactly the leads in file F (JSON lines), skipping the gate
#
# Why it exists: the Mini finds and queues leads, but applying is this laptop's skill and nothing ever
# triggered it (found 2026-10-22). The gate is a plain script, so an empty queue costs no Claude session.
# Why the laptop and not the Mini: the skill needs the onlinejobs-browser profile, which is signed in to
# Google here, and the Mini's Claude CLI has no login.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"
# MCP servers start through npx/node under nvm, which launchd's PATH lacks (same fix as claude-proceed).
NVM_V="$(cat "$HOME/.nvm/alias/default" 2>/dev/null)"
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/v"${NVM_V#v}"*/bin 2>/dev/null | tail -1)"
[ -n "$NODE_BIN" ] || NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | tail -1)"
[ -n "$NODE_BIN" ] && export PATH="$NODE_BIN:$PATH"

HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="$HOME/.onlinejobs-apply"
LOGDIR="$STATE/logs"
PAUSE="$STATE/PAUSE"                       # touch it to stop every future run
# The Chrome that holds the profile has "--user-data-dir=<path>" (with =). The idle Playwright MCP server of
# every open Claude session has "--user-data-dir <path>" (space) and must NOT count as "in use", or no tick
# would ever run while a session is open; it must never be killed either.
CHROME_PAT="user-data-dir=.*browser-profiles/onlinejobs-apply"
CAP_S="${OJ_APPLY_CAP_S:-2400}"                                 # a hung browser must not hold the lock forever
mkdir -p "$LOGDIR"
LOG="$LOGDIR/run-$(date +%Y-%m-%d-%H%M).log"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
# Messages to Jiv go through onlinejobs_apply_report.py: silent unless something was applied, needs him,
# or the runner keeps failing. No desktop banners: they were the same noise on a different screen.
REPORT="python3 $HERE/onlinejobs_apply_report.py"

DRY=0; LEADS_ARG=""
case "$1" in --dry-run) DRY=1 ;; --leads) LEADS_ARG="$2" ;; esac
[ -e "$PAUSE" ] && { say "skip: $PAUSE exists"; exit 0; }

LOCK="$STATE/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then say "skip: a run is already active"; exit 0; fi
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 1
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

LEADS="$STATE/leads.jsonl"
if [ -n "$LEADS_ARG" ]; then cp "$LEADS_ARG" "$LEADS"; GATE=0; else python3 "$HERE/onlinejobs_apply_gate.py" > "$LEADS" 2>>"$LOG"; GATE=$?; fi
case $GATE in
  0) $REPORT ok gate; say "gate: $(wc -l < "$LEADS" | tr -d ' ') open lead(s)" ;;
  3) $REPORT ok gate; say "gate: nothing to apply to"; exit 0 ;;
  *) say "gate: queue unreadable (Mini or Tailscale down?), see log"; $REPORT failed gate "cannot read the lead queue on the Mini (Tailscale off?)"; exit 1 ;;
esac
cat "$LEADS" | tee -a "$LOG" | cut -c1-200
[ "$DRY" = 1 ] && { say "dry run: stopping before Claude"; exit 0; }

# The browser profile allows ONE Chrome. An interactive session holding it would make this run fail
# with "Browser is already in use" (2026-10-20), so wait for the next tick instead.
if pgrep -f "$CHROME_PAT" >/dev/null; then say "skip: onlinejobs-browser is in use"; exit 0; fi
curl -s -o /dev/null --max-time 8 https://api.anthropic.com || { say "skip: api.anthropic.com unreachable"; exit 0; }
command -v claude >/dev/null || { say "skip: claude not on PATH"; exit 1; }

PROMPT="/onlinejobs-apply

Scheduled headless run. Work ONLY these queued leads (already deduped against applied.jsonl). Skip Discovery and the batch-scan. Apply the fit, honesty, rate and misfit gates to each. Log EVERY outcome, skips included, by running this command and nothing else (you have no permission to edit the tracker files directly; it writes applied.jsonl and TRACKER.md together):
python3 $HERE/onlinejobs_log_outcome.py --url <posting url> --title <real title from the live page> --status <submitted|sent|handoff|skipped> --fit <0-100> --note <one line why> [--employer <name>] [--method form|email] [--form-url <url>] [--email <address>]
For --status handoff the note MUST begin with the exact action Jiv has to take, under 150 characters, then the reason (for example: Record a 60 second intro video, then email it with resume (2).pdf to name@company.com. Strong fit, 82.). His phone shows only the start of it. A lead is not done until that command has run for it. If the posting page does not match the queued lead, trust the live page and say so in --note. Stop when every lead is logged.

$(cat "$LEADS")"

APPLIED="$HOME/.claude/skills/onlinejobs-apply/applied.jsonl"
BEFORE=$(wc -l < "$APPLIED" | tr -d ' ')
say "starting claude (cap ${CAP_S}s)"
cd "$STATE" || exit 1          # not the repo: launchd cannot read ~/Desktop
claude -p "$PROMPT" --permission-mode dontAsk --permission-prompts none \
  --allowedTools "mcp__onlinejobs-browser__*,ToolSearch,Read,Bash(python3 $HERE/onlinejobs_log_outcome.py:*)" \
  --disallowedTools "Agent,WebFetch,WebSearch" </dev/null >> "$LOG" 2>&1 &
CPID=$!
# Watchdog: its output goes nowhere, or the sleep keeps the caller's pipe open for the whole cap.
( sleep "$CAP_S"; kill "$CPID" 2>/dev/null ) >/dev/null 2>&1 & WD=$!
wait "$CPID"; RC=$?
pkill -P "$WD" 2>/dev/null; kill "$WD" 2>/dev/null; wait "$WD" 2>/dev/null
say "claude exit $RC"
# Killed by the watchdog: its Chrome may outlive it and would block every later tick.
[ "$RC" -ge 128 ] && pkill -f "$CHROME_PAT" 2>/dev/null
AFTER=$(wc -l < "$APPLIED" | tr -d ' ')
say "applied.jsonl: $((AFTER - BEFORE)) new row(s)"
$REPORT outcomes "$BEFORE" >> "$LOG" 2>&1
# A run that exits 0 but leaves a lead without a logged outcome is a silent failure (browser signed out,
# MCP missing, cut off). The skill logs every outcome, skips included, so a lead with none was not worked.
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
