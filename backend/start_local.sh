#!/bin/bash
# Runs the backend on this machine with the local demo database instead of Neon.
# The Gemini key still comes from backend/.env.
#
#   bash backend/start_local.sh
#
# The API is then at http://localhost:8000 (docs: http://localhost:8000/docs).
cd "$(dirname "$0")" || exit 1
sudo service postgresql start >/dev/null 2>&1 || true
source .venv/bin/activate
export DATABASE_URL="postgresql://knightscribe:knightscribe@127.0.0.1:5432/knightscribe"
exec uvicorn main:app --host 0.0.0.0 --port 8000
