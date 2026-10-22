#!/bin/bash
# Deterministic checks of scripts/onlinejobs-apply-mini.sh with a fake `claude` and a fake login helper.
# No Chrome, no model, no network, no notifications: every scenario gets its own throwaway HOME, so the
# failure streak never reaches the alert threshold and nothing is sent.
#   bash tests/battle/run_apply_runner_tests.sh
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNNER="$ROOT/scripts/onlinejobs-apply-mini.sh"
FAILS=0
ok()   { echo "PASS $1"; }
bad()  { echo "FAIL $1"; FAILS=$((FAILS + 1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

# scenario <name> <token yes|no> <login exit> <claude mode ok|silent|fail>  -> sets T (temp HOME) and RC
scenario() {
  T=$(mktemp -d); export HOME="$T"
  S="$T/.onlinejobs-apply"; mkdir -p "$S/state" "$S/logs"
  echo fake > "$S/resume.pdf"
  [ "$2" = yes ] && echo "CLAUDE_CODE_OAUTH_TOKEN=tok-fake" > "$S/claude.env"
  local def='{"url":"https://example.test/job/1","title":"Test role","employer":"Acme","apply_email":"jobs@acme.test"}'
  printf '%s\n' "${LEADS_JSON:-$def}" > "$T/leads.jsonl"
  : > "$T/calls"
  cat > "$T/login" <<E
#!/bin/bash
echo "login \$*" >> "$T/calls"; exit $3
E
  cat > "$T/claude" <<E
#!/bin/bash
[ "\$1" = "--version" ] && { echo "9.9.9 (fake)"; exit 0; }
echo "claude \$*" >> "$T/calls"
echo "env key=\${ANTHROPIC_API_KEY:-none} tok=\${CLAUDE_CODE_OAUTH_TOKEN:-none}" >> "$T/calls"
[ "$4" = fail ] && exit 1
[ "$4" = ok ] && python3 "$ROOT/scripts/onlinejobs_log_outcome.py" --url https://example.test/job/1 --title "Test role" --status skipped --fit 10 --note "test"
exit 0
E
  chmod +x "$T/login" "$T/claude"
  OJ_PY=python3 OJ_CLAUDE_BIN="$T/claude" OJ_LOGIN_BIN="$T/login" ANTHROPIC_API_KEY=stray-key-must-be-dropped \
    bash "$RUNNER" --leads "$T/leads.jsonl" > "$T/out" 2>&1
  RC=$?
}

scenario happy yes 0 ok
check "happy path: exit 0 and the lead is logged" '[ $RC -eq 0 ] && grep -q "example.test/job/1" "$T/.onlinejobs-apply/state/applied.jsonl"'
check "the login helper ran BEFORE claude" '[ "$(grep -n -m1 -E "^(login|claude)" "$T/calls" | cut -d: -f2 | cut -d" " -f1)" = login ]'
check "claude gets the browser MCP only, a model, and dontAsk" 'grep -q -e "--strict-mcp-config" "$T/calls" && grep -q -e "--model sonnet" "$T/calls" && grep -q -e "--permission-mode dontAsk" "$T/calls" && grep -q "mcp__onlinejobs-browser__" "$T/calls"'
check "claude cannot use the web or spawn agents" 'grep -q -e "--disallowedTools Agent,WebFetch,WebSearch" "$T/calls"'
check "the OAuth token reaches claude and a stray API key does not" 'grep -q "key=none tok=tok-fake" "$T/calls"'
check "the send command is allowlisted and in the prompt, with the run's lead file" 'grep -q "Bash(python3 $ROOT/scripts/onlinejobs_send_email.py --leads $T/.onlinejobs-apply/leads.jsonl" "$T/calls" && grep -q "onlinejobs_send_email.py --leads .* --url <posting url>" "$T/calls"'
check "the prompt forbids Gmail in the browser" 'grep -q "do NOT use Gmail in the browser" "$T/calls"'
check "no Google Form queued: Google is not checked" 'grep -q "^login *$" "$T/calls"'
check "the prompt carries the exact logging command and the lead" 'grep -q "onlinejobs_log_outcome.py --url <posting url>" "$T/calls" && grep -q "example.test/job/1" "$T/calls"'

scenario notoken no 0 ok
check "no Claude token: claude and login never start, exit 1" '[ $RC -eq 1 ] && ! grep -q "^claude\|^login" "$T/calls"'

for code in 3 5 6; do
  scenario "login$code" yes $code ok
  check "login helper exit $code: claude never starts, exit 1" '[ $RC -eq 1 ] && grep -q "^login" "$T/calls" && ! grep -q "^claude" "$T/calls"'
done

GF='{"url":"https://example.test/job/2","title":"Form role","employer":"Beta","form_url":"https://docs.google.com/forms/d/e/x/viewform"}'
EM='{"url":"https://example.test/job/1","title":"Test role","employer":"Acme","apply_email":"jobs@acme.test"}'
LEADS_JSON="$GF" scenario gonly yes 7 ok
check "only a Google Form queued and Google signed out: checked with --google, claude never starts, exit 1" '[ $RC -eq 1 ] && grep -q "^login --google" "$T/calls" && ! grep -q "^claude" "$T/calls"'
LEADS_JSON="$GF
$EM" scenario gmix yes 7 ok
check "Google signed out with an email lead too: the form is held, the email lead is worked" '[ $RC -eq 0 ] && grep -q "holding 1 Google Form" "$T/out" && grep -q "example.test/job/1" "$T/calls" && ! grep -q "example.test/job/2" "$T/calls"'
check "the held Google Form lead is not counted as unworked" '! grep -q "not worked" "$T/out"'
unset LEADS_JSON

scenario silent yes 0 silent
check "claude exits 0 but logs nothing: counted as a failed run (exit 1)" '[ $RC -eq 1 ] && grep -q "not worked" "$T/out"'

scenario crash yes 0 fail
check "claude exits non-zero: exit 1" '[ $RC -eq 1 ]'

echo; [ $FAILS -eq 0 ] && echo "all passed" || echo "$FAILS FAILED"
exit $FAILS
