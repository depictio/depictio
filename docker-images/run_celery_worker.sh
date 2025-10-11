#!/bin/bash
set -e

# Set default values if environment variables are not set
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-2}

echo "🔧 CELERY WORKER: Starting dedicated Celery worker..."
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"

# Start Celery worker - pointing to celery_app module
exec celery -A depictio.dash.celery_app:celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKERS"
