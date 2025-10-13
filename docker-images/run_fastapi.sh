#!/bin/bash
set -e

# Set default values if environment variables are not set
FASTAPI_HOST=${DEPICTIO_FASTAPI_HOST:-0.0.0.0}
FASTAPI_PORT=${DEPICTIO_FASTAPI_PORT:-8058}
FASTAPI_WORKERS=${DEPICTIO_FASTAPI_WORKERS:-4}

echo "🚀 Starting FastAPI backend..."
# echo "ℹ️  Note: Celery worker now runs in separate container (depictio-celery-worker)"

# Start FastAPI server (this will block and keep the container running)
if [ "$DEV_MODE" = "true" ]; then
    # Development mode with reload
    export DEV_MODE=true
    echo "🛠️ Running FastAPI in development mode on $FASTAPI_HOST:$FASTAPI_PORT with $FASTAPI_WORKERS workers"
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
    export DEV_MODE=false
    echo "🚀 Running FastAPI in production mode on $FASTAPI_HOST:$FASTAPI_PORT with $FASTAPI_WORKERS workers"
    uvicorn \
        depictio.api.main:app \
        --host "$FASTAPI_HOST" \
        --port "$FASTAPI_PORT" \
        --workers "$FASTAPI_WORKERS" \
        --timeout-keep-alive 5 \
        --log-level info \
        --access-log
fi
