#!/bin/bash
# Installs the scheduled /onlinejobs-apply runner. Safe to re-run after any change to these scripts.
#
# Why copies and not a plist pointing at this repo: launchd jobs cannot read ~/Desktop (macOS privacy
# protection), so a job pointing here dies with "/bin/bash: ...: Operation not permitted" on every tick
# and never says so (found 2026-10-22 on a one-off test job; com.jiv.claude-proceed has the same error).
# The runtime files therefore live in ~/.onlinejobs-apply/bin; this repo stays the source of truth.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="$HOME/.onlinejobs-apply"
BIN="$HOME_DIR/bin"
LABEL="com.jiv.onlinejobs-apply"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$BIN" "$HOME_DIR/logs"
for f in onlinejobs-apply-runner.sh onlinejobs_apply_gate.py onlinejobs_apply_report.py onlinejobs_log_outcome.py \
         onlinejobs_decide.py meeting_signal.py; do
  cp "$SRC/$f" "$BIN/$f"
done
chmod +x "$BIN/onlinejobs-apply-runner.sh"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$BIN/onlinejobs-apply-runner.sh</string></array>
    <key>StartInterval</key><integer>3600</integer>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key><string>$HOME_DIR/logs/launchd.out</string>
    <key>StandardErrorPath</key><string>$HOME_DIR/logs/launchd.err</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed: $LABEL every hour, runtime in $BIN"
