#!/bin/bash
set -e

# Set default values if environment variables are not set
CELERY_WORKERS=${DEPICTIO_CELERY_WORKERS:-2}

echo "🔧 CELERY WORKER: Starting dedicated Celery worker..."
echo "🔧 CELERY WORKER: Workers = $CELERY_WORKERS"

# Start Celery worker with realistic memory management
exec celery -A depictio.dash.app:celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKERS" # REDUCE FOR LARGE DATASETS
    # --max-tasks-per-child=3 \ # FOR LARGE DATASETS
    # --max-memory-per-child=1536000 # FOR LARGE DATASETS (in KB, e.g., 1536000 KB = 1.5 GB)
