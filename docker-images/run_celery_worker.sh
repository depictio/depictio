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

# Queues this worker consumes. Defaults to "celery" — the queue everything has
# always landed on, since task_default_queue is pinned to it. Overriding to
# "ingestion" is how the dedicated ingestion worker reuses this same script and
# image without also competing for dashboard callbacks.
CELERY_QUEUES=${DEPICTIO_CELERY_QUEUES:-celery}

# 1 keeps a worker from reserving several 20-minute ingestion tasks up front and
# starving its peers. Harmless for short tasks, decisive for long ones.
CELERY_PREFETCH=${DEPICTIO_CELERY_PREFETCH:-1}

# Recycle after N tasks to bound leaked memory from repeated large DataFrame
# materialisations. Empty means "never", which is Celery's default.
CELERY_MAX_TASKS_PER_CHILD=${DEPICTIO_CELERY_MAX_TASKS_PER_CHILD:-}

# Distinct node name per queue, so `celery inspect ping` and the compose
# healthcheck can address one worker rather than whichever answers first.
CELERY_NODENAME=${DEPICTIO_CELERY_NODENAME:-celery@%h}

EXTRA_ARGS=()
if [ -n "$CELERY_MAX_TASKS_PER_CHILD" ]; then
    EXTRA_ARGS+=(--max-tasks-per-child="$CELERY_MAX_TASKS_PER_CHILD")
fi

echo "✅ CELERY WORKER: Starting Celery worker (required for design mode)"
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"
echo "🔧 CELERY WORKER: Queues = $CELERY_QUEUES"
echo "🔧 CELERY WORKER: Node = $CELERY_NODENAME"
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
            --concurrency="$CELERY_WORKERS" \
            --queues="$CELERY_QUEUES" \
            --prefetch-multiplier="$CELERY_PREFETCH" \
            --hostname="$CELERY_NODENAME" \
            ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
else
    exec celery -A depictio.api.celery_worker:celery_app worker \
        --loglevel=info \
        --concurrency="$CELERY_WORKERS" \
        --queues="$CELERY_QUEUES" \
        --prefetch-multiplier="$CELERY_PREFETCH" \
        --hostname="$CELERY_NODENAME" \
        ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
fi
