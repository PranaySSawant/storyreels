#!/usr/bin/env bash
# called by cron every 30 min
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
exec ./venv/bin/python -m storyreels.main run "$@"
