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

# Start Celery worker - pointing to celery_worker module (imports flask_dispatcher for task discovery)
exec celery -A depictio.dash.celery_worker:celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKERS"
