#!/bin/bash
set -euo pipefail

# IMPORTANT: Celery worker ALWAYS runs - it's required for:
# - Component design mode (figure preview, interactive editing)
# - Stepper component creation
# - Component editing
#
# The DEPICTIO_CELERY_ENABLED parameter only controls whether DASHBOARD VIEW/EDIT MODE
# uses background callbacks. Design mode always uses background callbacks regardless.

# Set default values if environment variables are not set
# Default raised from 2 → 4: figure/MultiQC builds are CPU-bound and run on the
# default prefork pool, so each extra worker is a real parallel build slot.
# Tune per host RAM (each prefork process holds its own DataFrame/multiqc.report
# copies) via DEPICTIO_CELERY_WORKERS.
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-4}

# Recycle each prefork child after N tasks so the DataFrame / multiqc.report
# memory it accumulated is actually returned to the OS. Celery's own default is
# unlimited, so without this children grow for the lifetime of the container.
#
# `CeleryConfig.worker_max_tasks_per_child = 50` already declares this intent in
# settings_models.py, but it is dead config here: the `celery_app.conf.update()`
# block in depictio/api/celery_app.py is commented out, so nothing in that class
# reaches the worker. We pass it on the CLI rather than reviving that block —
# doing so would also apply `default_queue`, which routes work to a queue no
# worker consumes and silently stops every task (see the comments in
# celery_app.py before touching it).
CELERY_MAX_TASKS_PER_CHILD=${DEPICTIO_CELERY_MAX_TASKS_PER_CHILD:-50}

echo "✅ CELERY WORKER: Starting Celery worker (required for design mode)"
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS, max tasks/child = $CELERY_MAX_TASKS_PER_CHILD"
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
#
# `--interval=5` (watchdog's default is 1s): polling means a full stat() snapshot
# of every watched entry on each tick, so the tick rate is the cost driver. 5s is
# ample for a worker — you rarely iterate on task code in a tight loop — and it
# cuts the watcher's idle CPU fivefold. Note `--patterns` filters *events*, not
# the walk, so it does nothing for that cost; only the interval and the watched
# directory set do. The two heaviest trees (depictio/cli/.venv, depictio/tests)
# are masked out of the container in docker-compose.dev.yaml.
DEV_MODE_LOWER=$(echo "${DEPICTIO_DEV_MODE:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$DEV_MODE_LOWER" = "true" ]; then
    echo "🔁 CELERY WORKER: dev mode — live reload via watchmedo (watching /app/depictio/**/*.py)"
    exec watchmedo auto-restart \
        --directory=/app/depictio \
        --patterns='*.py' \
        --ignore-patterns='*/__pycache__/*;*.pyc' \
        --recursive \
        --debug-force-polling \
        --interval=5 \
        -- celery -A depictio.api.celery_worker:celery_app worker \
            --loglevel=info \
            --max-tasks-per-child="$CELERY_MAX_TASKS_PER_CHILD" \
            --concurrency="$CELERY_WORKERS"
else
    exec celery -A depictio.api.celery_worker:celery_app worker \
        --loglevel=info \
        --max-tasks-per-child="$CELERY_MAX_TASKS_PER_CHILD" \
        --concurrency="$CELERY_WORKERS"
fi
