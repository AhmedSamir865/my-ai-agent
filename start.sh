#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-7860}"
echo "Starting on http://${HOST}:${PORT}"
python -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
