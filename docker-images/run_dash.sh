#!/bin/bash

# Set default values if environment variables are not set
DASH_HOST=${DEPICTIO_DASH_HOST:-0.0.0.0}
DASH_PORT=${DEPICTIO_DASH_PORT:-5080}
DASH_WORKERS=${DEPICTIO_DASH_WORKERS:-4}

sleep 5 # Allow time for other services to start

# Convert to lowercase for comparison (handle both "true" and "True")
DEV_MODE_LOWER=$(echo "$DEPICTIO_DEV_MODE" | tr '[:upper:]' '[:lower:]')
if [ "$DEV_MODE_LOWER" = "true" ]; then
    # Development mode with reload
    # Debug mode is passed to Dash in flask_dispatcher.py
    export DEPICTIO_DEV_MODE=true
    echo "Running in development mode on $DASH_HOST:$DASH_PORT" with "$DASH_WORKERS" workers
    python depictio/dash/flask_dispatcher.py
    # gunicorn --workers=2 --reload --bind="$DASH_HOST:$DASH_PORT" --timeout=120 depictio.dash.wsgi:server
else
    # Production mode with workers
    export DEPICTIO_DEV_MODE=false
    echo "Running in production mode on $DASH_HOST:$DASH_PORT with $DASH_WORKERS workers"
    gunicorn \
        --workers="$DASH_WORKERS" \
        --bind="$DASH_HOST:$DASH_PORT" \
        --timeout=120 \
        --keep-alive=5 \
        --max-requests=1000 \
        --access-logfile=- \
        --error-logfile=- \
        --preload \
        depictio.dash.wsgi:application
fi
