#!/bin/bash
# Opens the Mini's OnlineJobs apply browser profile for a person to sign in to Google (and OnlineJobs if asked),
# then checks the result the way the runner will see it. Run it in the Mini's own Terminal (Screen Share to
# vnc://100.98.219.58), never over ssh: the window must appear on the Mini's screen.
#
#   ~/agent-work/jobi/scripts/onlinejobs-browser-signin.sh
#
# Why a script and not `open -na "Google Chrome" --args --user-data-dir=...`: the runner's browser is Chrome started
# by Playwright, and cookies saved by any other kind of launch were unreadable to it, so Chrome threw them away and
# both sessions were lost (2026-10-23, twice: plain Chrome, then Chrome with Playwright's keychain flags copied).
# onlinejobs-browser-signin.js opens the window THROUGH Playwright, so what you sign in to is what the runner gets.
# Also sign in HERE, on the Mini, rather than copying a profile from another Mac: Chrome 147+ on macOS can bind a
# Google session to the Mac's Secure Enclave, so a copied session dies within hours (seen 2026-10-22).
PROFILE="$HOME/.onlinejobs-apply/browser-profile"
HERE="$(cd "$(dirname "$0")" && pwd)"
PAT="user-data-dir=.*\.onlinejobs-apply/browser-profile"

if pgrep -f "$PAT" >/dev/null; then
  echo "The profile is open in another Chrome (maybe a scheduled run). Wait a minute and run this again."; exit 1
fi
PAUSE="$HOME/.onlinejobs-apply/PAUSE"            # keeps the hourly run off the profile while you sign in
if [ ! -e "$PAUSE" ]; then touch "$PAUSE"; trap 'rm -f "$PAUSE"' EXIT; fi
echo "Sign in to Google in the window that opens, then QUIT Chrome (Cmd+Q). The OnlineJobs tab is optional: the script signs in there for you."
ONLINEJOBS_PROFILE="$PROFILE" /opt/homebrew/bin/node "$HERE/onlinejobs-browser-signin.js" || { echo "The sign-in window could not open; see above."; exit 1; }
echo "Chrome closed. Signing in to OnlineJobs if needed, then checking Google the way the scheduled run will..."
# The same helper and flags as the runner: OnlineJobs is re-signed in with the saved credentials, Google is only read.
ONLINEJOBS_PROFILE="$PROFILE" ONLINEJOBS_STATE_FILE="$HOME/.onlinejobs-apply/login-state.json" \
  ONLINEJOBS_ENV_FILE="$HOME/.onlinejobs.env" /opt/homebrew/bin/node "$HERE/onlinejobs-ensure-login.js" --google
case $? in
  0) echo "OK: signed in to OnlineJobs and Google." ;;
  7) echo "Google is still signed out. Run this again." ;;
  *) echo "OnlineJobs sign-in did not finish (see above); Google was not checked. Sign in on the OnlineJobs tab and run this again." ;;
esac
