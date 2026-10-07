#!/bin/zsh
cd "$(dirname "$0")"
pgrep -f dante-watch.py >/dev/null && echo "RUNNING" || echo "NOT RUNNING"
echo "--- last 15 log lines"; tail -15 log/$(date +%F).log 2>/dev/null || echo "(no log today)"
