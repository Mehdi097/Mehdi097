#!/usr/bin/env bash
# Développement / test : lance le dashboard en mode aperçu (0.0.0.0).
set -e
cd "$(dirname "$0")"
export TRADERDESK_HOST="${TRADERDESK_HOST:-0.0.0.0}"
export TRADERDESK_PORT="${TRADERDESK_PORT:-8770}"
python3 run.py --host "$TRADERDESK_HOST" --port "$TRADERDESK_PORT" --no-browser "$@"
