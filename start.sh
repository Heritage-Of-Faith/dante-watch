#!/bin/zsh
# Start the watchdog in the background. Asks for your Mac password once (sudo).
cd "$(dirname "$0")"
if pgrep -f dante-watch.py >/dev/null; then echo "already running (pid $(pgrep -f dante-watch.py))"; exit 0; fi
sudo -v || exit 1
sudo nohup python3 ./dante-watch.py "$@" >> log/stdout.txt 2>&1 &
sleep 3
if pgrep -f dante-watch.py >/dev/null; then echo "running. tail -f log/$(date +%F).log to watch."; else echo "failed:"; tail -5 log/stdout.txt; fi
