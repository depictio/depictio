#!/bin/bash
set -e

# IMPORTANT: Celery worker ALWAYS runs - it's required for:
# - Component design mode (figure preview, interactive editing)
# - Stepper component creation
# - Component editing
#
# The DEPICTIO_CELERY_ENABLED parameter only controls whether DASHBOARD VIEW/EDIT MODE
# uses background callbacks. Design mode always uses background callbacks regardless.

# Set default values if environment variables are not set
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-2}

echo "✅ CELERY WORKER: Starting Celery worker (required for design mode)"
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"
if [ "${DEPICTIO_CELERY_ENABLED:-false}" = "true" ]; then
    echo "🔧 CELERY WORKER: Dashboard view mode will use background callbacks"
else
    echo "🔧 CELERY WORKER: Dashboard view mode will use synchronous callbacks"
fi

# Start Celery worker - pointing to celery_worker module (imports flask_dispatcher for task discovery).
#
# Celery has no built-in autoreload. In dev mode we wrap it in watchmedo
# (watchdog), which restarts the worker whenever a .py under /app/depictio
# changes — the worker equivalent of the backend's uvicorn --reload, so code
# edits land without a manual container restart. `--debug-force-polling`
# because native fs events don't cross the macOS/Colima → Linux VM bind-mount
# boundary (same reason the Vite viewer uses VITE_USE_POLLING). Prod runs
# celery directly (no watcher, no polling cost).
DEV_MODE_LOWER=$(echo "${DEPICTIO_DEV_MODE:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$DEV_MODE_LOWER" = "true" ]; then
    echo "🔁 CELERY WORKER: dev mode — live reload via watchmedo (watching /app/depictio/**/*.py)"
    exec watchmedo auto-restart \
        --directory=/app/depictio \
        --patterns='*.py' \
        --ignore-patterns='*/__pycache__/*;*.pyc' \
        --recursive \
        --debug-force-polling \
        -- celery -A depictio.api.celery_worker:celery_app worker \
            --loglevel=info \
            --concurrency="$CELERY_WORKERS"
else
    exec celery -A depictio.api.celery_worker:celery_app worker \
        --loglevel=info \
        --concurrency="$CELERY_WORKERS"
fi
