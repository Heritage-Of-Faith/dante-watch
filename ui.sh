#!/bin/zsh
# Start the live web UI (ui/server.py) in the background if it is not already
# running, print the URL(s), and open it in the default browser. No sudo needed.
cd "$(dirname "$0")"
PORT="${PORT:-8787}"
mkdir -p log

if ! pgrep -f "ui/server.py" >/dev/null; then
  nohup python3 ui/server.py --port "$PORT" >> log/ui.txt 2>&1 &
  # wait up to 5 s for it to answer
  for i in {1..25}; do
    curl -s -o /dev/null "http://localhost:$PORT/api/status" && break
    sleep 0.2
  done
  if ! pgrep -f "ui/server.py" >/dev/null; then
    echo "failed to start:"; tail -5 log/ui.txt; exit 1
  fi
else
  echo "already running (pid $(pgrep -f 'ui/server.py' | head -1))"
fi

echo "http://localhost:$PORT"
# Every non-loopback, non-self-assigned IPv4 on this Mac (Wi-Fi/office LAN) for a phone to use.
ifconfig | awk '/inet / && $2 !~ /^(127\.|169\.254\.)/ {print "http://" $2 ":'"$PORT"'  (phone on the same Wi-Fi)"}'
open "http://localhost:$PORT"
