#!/usr/bin/env bash
# Start the FastAPI backend (API + agents) on :8000.
set -euo pipefail
cd "$(dirname "$0")/../backend"
.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
