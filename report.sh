#!/bin/zsh
# Summarise one day's log (default today): ./report.sh [YYYY-MM-DD]
cd "$(dirname "$0")"; f=log/${1:-$(date +%F)}.log
[ -f "$f" ] || { echo "no log $f"; exit 1; }
echo "== $f"; echo "events by type:"; awk '{print $2}' "$f" | sort | uniq -c
echo; echo "clock events:"; grep ' CLOCK ' "$f" | grep -v 'master now' || echo "  none"
echo; echo "master changes:"; grep 'master now' "$f"
echo; echo "device loss:"; grep ' PING ' "$f" || echo "  none"
echo; echo "link:"; grep ' LINK ' "$f" || echo "  none"
