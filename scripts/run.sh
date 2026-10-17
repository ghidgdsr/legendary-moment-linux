#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${LEICA_HOST:-0.0.0.0}"
PORT="${LEICA_PORT:-8000}"

exec .venv/bin/python -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT"
