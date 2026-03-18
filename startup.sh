#!/usr/bin/env bash
set -euo pipefail

export DATABASE_URL="${DATABASE_URL:-sqlite:////home/site/wwwroot/classroom_booking.db}"
DB_LOCK_FILE="/home/site/wwwroot/.sqlite-init.lock"

mkdir -p /home/site/wwwroot

if [[ "${DATABASE_URL}" == sqlite:* ]]; then
  echo "[startup] sqlite mode detected: ${DATABASE_URL}"
  flock "${DB_LOCK_FILE}" bash -c '
    python -m flask --app run.py init-db
    python -m flask --app run.py seed-defaults
  '
fi

exec gunicorn --bind=0.0.0.0 --timeout 600 --access-logfile "-" --error-logfile "-" run:app
