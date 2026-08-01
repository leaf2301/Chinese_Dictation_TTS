#!/bin/bash
cd "$(dirname "$0")"

# Find official Python 3 binary to avoid Apple's Developer Tools prompt
if [ -x "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" ]; then
    PY="/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PY="/usr/local/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PY="/opt/homebrew/bin/python3"
else
    PY="python3"
fi

# Kill any existing process on port 5000
lsof -ti:5000 | xargs kill -9 2>/dev/null
sleep 0.5

# Auto-cleanup when Terminal is closed
trap 'lsof -ti:5000 | xargs kill -9 2>/dev/null; exit' EXIT HUP TERM INT

# Install dependencies silently
"$PY" -m pip install -q -r requirements.txt 2>/dev/null

# Open browser after server starts
(sleep 2 && open "http://127.0.0.1:5000") &

# Run Flask
"$PY" app.py
