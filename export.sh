#!/bin/zsh
# Bundle log + findings + network snapshot into one Markdown file for Claude. ./export.sh [YYYY-MM-DD ...]
cd "$(dirname "$0")"
f=$(python3 export.py "$@") || exit 1
echo "$f"; open -R "$f" 2>/dev/null   # reveal in Finder
