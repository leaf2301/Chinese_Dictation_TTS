#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../../" && pwd)"
cd "$APP_DIR"

export PORT=5010

if [ -x "$APP_DIR/.venv/bin/python" ]; then
    PY="$APP_DIR/.venv/bin/python"
elif [ -x "$APP_DIR/venv/bin/python" ]; then
    PY="$APP_DIR/venv/bin/python"
elif [ -x "$APP_DIR/.venv/bin/python3" ]; then
    PY="$APP_DIR/.venv/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PY="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PY="/usr/local/bin/python3"
else
    PY="python3"
fi

lsof -ti:$PORT | xargs kill -9 2>/dev/null
sleep 0.5

(sleep 2.0 && open "http://127.0.0.1:$PORT/?resume=lesson_20260801_174242") &
exec "$PY" app.py
