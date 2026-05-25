#!/usr/bin/env bash
# run.sh — launch the MaudeSignal Streamlit dashboard
# Usage: ./run.sh [--port PORT]
set -euo pipefail

PORT="${MAUDESIGNAL_PORT:-8501}"

if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

exec python3.12 -m streamlit run src/maudesignal/dashboard/app.py \
    --server.port "$PORT" \
    --server.headless true \
    --server.enableCORS false \
    "$@"
