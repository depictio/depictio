#!/bin/bash
set -e

# Check if background callbacks are enabled
USE_BACKGROUND=$(echo "${DEPICTIO_USE_BACKGROUND_CALLBACKS:-false}" | tr '[:upper:]' '[:lower:]')

if [ "$USE_BACKGROUND" != "true" ]; then
    echo "🚫 CELERY WORKER: Background callbacks DISABLED (DEPICTIO_USE_BACKGROUND_CALLBACKS=$DEPICTIO_USE_BACKGROUND_CALLBACKS)"
    echo "🚫 CELERY WORKER: Exiting gracefully - Celery worker not needed"
    echo "   Set DEPICTIO_USE_BACKGROUND_CALLBACKS=true in docker-compose/.env to enable"
    exit 0
fi

# Set default values if environment variables are not set
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-2}

echo "✅ CELERY WORKER: Background callbacks ENABLED"
echo "🔧 CELERY WORKER: Starting dedicated Celery worker..."
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"

# Start Celery worker - pointing to celery_worker module (imports flask_dispatcher for task discovery)
exec celery -A depictio.dash.celery_worker:celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKERS"
