#!/bin/bash

# Set default values if environment variables are not set
DASH_HOST=${DEPICTIO_DASH_HOST:-0.0.0.0}
DASH_PORT=${DEPICTIO_DASH_PORT:-5080}
DASH_WORKERS=${DEPICTIO_DASH_WORKERS:-4}

if [ "$DEV_MODE" = "true" ]; then
    # Development mode with reload
    # Debug mode is passed to Dash in app.py
    export DEV_MODE=true
    python depictio/dash/app.py
else
    # Production mode with workers
    export DEV_MODE=false
    gunicorn \
        --workers="$DASH_WORKERS" \
        --bind="$DASH_HOST:$DASH_PORT" \
        --timeout=120 \
        --keep-alive=5 \
        --max-requests=1000 \
        --access-logfile=- \
        --error-logfile=- \
        depictio.dash.wsgi:server
fi