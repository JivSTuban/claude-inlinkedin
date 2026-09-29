#!/bin/bash
# Battle-test one round of the Codex inbox run against the mock LinkedIn, end to end:
# real runner, real skill, real Codex, real Chrome profile; fake LinkedIn.
#   tests/battle/run_battle.sh 1|2|login     (on the Mac Mini)
# Scratch output lives under the outreach folder (Codex's only writable root) in
# .battle-test/<time>-<round>/ and never touches the real tracker or needs-jiv.jsonl.
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
ROUND="${1:?round: 1, 2 or login}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PORT="${BATTLE_PORT:-8765}"
T="$HOME/Work/job-email-bot/marketing/outreach/.battle-test/$(date +%H%M%S)-$ROUND"
mkdir -p "$T"

WALL=""; [ "$ROUND" = login ] && WALL="--login-wall"
python3 "$HERE/mock_linkedin.py" --cases "$HERE/cases.json" --round "$ROUND" --port "$PORT" --out "$T/mock" $WALL &
MOCK=$!
trap 'kill $MOCK 2>/dev/null' EXIT
for _ in $(seq 1 20); do curl -fs "http://127.0.0.1:$PORT/messaging/" >/dev/null && break; sleep 0.5; done

LINKEDIN_TEST_DIR="$T" LINKEDIN_TEST_BASE="http://127.0.0.1:$PORT" \
    "$REPO/scripts/linkedin-codex-runner.sh" inbox
RC=$?

echo "== round $ROUND, runner exit $RC, evidence in $T"
python3 "$HERE/assert_battle.py" --cases "$HERE/cases.json" --round "$ROUND" --dir "$T" --rc "$RC"
