#!/bin/bash
set -e

# Check if Celery is enabled
USE_CELERY=$(echo "${DEPICTIO_CELERY_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')

if [ "$USE_CELERY" != "true" ]; then
    echo "🚫 CELERY WORKER: Celery DISABLED (DEPICTIO_CELERY_ENABLED=$DEPICTIO_CELERY_ENABLED)"
    echo "🚫 CELERY WORKER: Exiting gracefully - Celery worker not needed"
    echo "   Set DEPICTIO_CELERY_ENABLED=true in docker-compose/.env and use --profile celery to enable"
    exit 0
fi

# Set default values if environment variables are not set
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-2}

echo "✅ CELERY WORKER: Celery ENABLED"
echo "🔧 CELERY WORKER: Starting dedicated Celery worker..."
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"

# Start Celery worker - pointing to celery_worker module (imports flask_dispatcher for task discovery)
exec celery -A depictio.dash.celery_worker:celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKERS"
