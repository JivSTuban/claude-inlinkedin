#!/bin/bash
# One-shot release gate for the live LinkedIn runs (Mac Mini crontab, tagged BATTLE-ONESHOT).
# Runs every battle round; on a full pass re-enables the production cron lines that were
# parked as "#BATTLE-GATE ...", otherwise leaves them parked. DMs Jiv the verdict either
# way and removes its own crontab line so it fires once.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
HERE="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$HERE/../../scripts/linkedin-notify.py"
OUT="$HOME/Library/Logs/linkedin-codex/battle-$(date +%F-%H%M).txt"
mkdir -p "$(dirname "$OUT")"

{
    for r in 1 2 login; do
        "$HERE/run_battle.sh" "$r"
        echo "ROUND_EXIT $r $?"
    done
} > "$OUT" 2>&1

FAILED=$(grep -E '^ROUND_EXIT [^ ]+ [1-9]' "$OUT" | awk '{print $2}' | tr '\n' ' ')
TMP=$(mktemp)
crontab -l | grep -v 'BATTLE-ONESHOT' > "$TMP"
if [ -z "$FAILED" ]; then
    sed 's/^#BATTLE-GATE //' "$TMP" | crontab -
    MSG="LinkedIn battle test PASSED (all rounds). Live inbox + outreach runs are re-enabled. Report: $OUT"
else
    crontab - < "$TMP"
    MSG="LinkedIn battle test FAILED (rounds: $FAILED). Live runs stay paused. Failing checks: $(grep '^FAIL' "$OUT" | head -6 | tr '\n' ';') Report: $OUT"
fi
rm -f "$TMP"
python3 "$NOTIFY" --text "$MSG"
echo "$MSG" >> "$OUT"
