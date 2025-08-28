#!/bin/bash
set -e

# Set default values if environment variables are not set
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-2}

echo "🔧 CELERY WORKER: Starting dedicated Celery worker..."
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"

# Start Celery worker - following same pattern as run_fastapi.sh
exec celery -A depictio.dash.app:celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKERS"
