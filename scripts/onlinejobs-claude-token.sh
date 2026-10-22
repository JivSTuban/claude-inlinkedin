#!/bin/bash
# One-time, run by Jiv on the Mini: gives the unattended OnlineJobs apply job its own Claude login.
#
#   ssh -t admin@100.98.219.58 ~/agent-work/jobi/scripts/onlinejobs-claude-token.sh
#
# Why a token: `claude` stores its normal login in the macOS login keychain, which is locked in cron and over ssh.
# `claude setup-token` makes a long-lived token for exactly this; it is read from $STATE/claude.env (chmod 600) by
# onlinejobs-apply-mini.sh. The token is typed into this terminal only and never passes through any chat or log.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
STATE="$HOME/.onlinejobs-apply"
mkdir -p "$STATE"
echo "1/2  Sign in. Open the URL it prints, approve, paste the code back here. It then prints a token."
claude setup-token || { echo "setup-token failed"; exit 1; }
printf "\n2/2  Paste the token it printed (input is hidden): "
read -rs TOKEN; echo
[ -n "$TOKEN" ] || { echo "no token entered, nothing saved"; exit 1; }
# Prove it works before saving it, so a typo never replaces nothing with a broken file.
if OUT=$(CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" ANTHROPIC_API_KEY= claude -p "reply with the single word ok" </dev/null 2>&1) && echo "$OUT" | grep -qi '^ok'; then
  ( umask 077; printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" > "$STATE/claude.env" )
  echo "OK: Claude works on the Mini and the token is saved to $STATE/claude.env"
else
  echo "The token did not work: ${OUT:0:200}"; exit 1
fi
