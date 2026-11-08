#!/usr/bin/env bash
# NorthCheck — start the web app (Python standard library only).
set -e
cd "$(dirname "$0")"
export PORT="${PORT:-8790}"
export HOST="${HOST:-127.0.0.1}"
exec python3 app.py
