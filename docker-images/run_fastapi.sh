#!/bin/bash
set -euo pipefail

# Set default values if environment variables are not set
FASTAPI_HOST=${DEPICTIO_FASTAPI_HOST:-0.0.0.0}
FASTAPI_PORT=${DEPICTIO_FASTAPI_PORT:-8058}
FASTAPI_WORKERS=${DEPICTIO_FASTAPI_WORKERS:-4}

echo "🚀 Starting FastAPI backend..."
# echo "ℹ️  Note: Celery worker now runs in separate container (depictio-celery-worker)"

# Start FastAPI server (this will block and keep the container running)
# Convert to lowercase for comparison (handle both "true" and "True")
DEV_MODE_LOWER=$(echo "${DEPICTIO_DEV_MODE:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$DEV_MODE_LOWER" = "true" ]; then
    # Development mode with reload
    export DEPICTIO_DEV_MODE=true
    echo "🛠️ Running FastAPI in development mode on $FASTAPI_HOST:$FASTAPI_PORT with $FASTAPI_WORKERS workers"
    # Dev: run.py drives uvicorn --reload, which spawns/respawns child
    # workers. Left without `exec` so this shell stays PID 1 as the reload
    # supervisor's parent; SIGTERM forwarding here differs from prod and is
    # not the production signal path, so we don't exec it (avoids disturbing
    # the reloader's own process tree).
    python depictio/api/run.py
    # uvicorn depictio.api.main:app \
    #     --host "$FASTAPI_HOST" \
    #     --port "$FASTAPI_PORT" \
    #     --reload \
    #     --reload-dir ./depictio/api \
    #     --reload-dir ./depictio/models \
    #     --reload-dir ./depictio/dash \
    #     --reload-dir ./depictio/cli \
    #     --use-colors
else
    # Production mode with workers
    # Use Gunicorn with Uvicorn workers for proper preloading (avoids duplicate initialization logs)
    export DEPICTIO_DEV_MODE=false
    echo "🚀 Running FastAPI in production mode on $FASTAPI_HOST:$FASTAPI_PORT with $FASTAPI_WORKERS workers"
    # exec so gunicorn replaces this shell as PID 1 and receives SIGTERM
    # directly — enables graceful worker shutdown on `docker stop` / pod
    # termination instead of waiting for SIGKILL.
    exec gunicorn \
        depictio.api.main:app \
        --bind "$FASTAPI_HOST:$FASTAPI_PORT" \
        --workers "$FASTAPI_WORKERS" \
        --worker-class uvicorn.workers.UvicornWorker \
        --timeout 120 \
        --keep-alive 5 \
        --preload \
        --config depictio/api/gunicorn_conf.py
fi
