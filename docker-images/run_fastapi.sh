#!/bin/bash

# Set default values if environment variables are not set
FASTAPI_HOST=${DEPICTIO_FASTAPI_HOST:-0.0.0.0}
FASTAPI_PORT=${DEPICTIO_FASTAPI_PORT:-8058}
FASTAPI_WORKERS=${DEPICTIO_FASTAPI_WORKERS:-1}

if [ "$DEV_MODE" = "true" ]; then
    # Development mode with reload
    # Debug mode is passed to FastAPI in main.py
    export DEV_MODE=true
    python -m uvicorn depictio.api.main:app --host "$FASTAPI_HOST" --port "$FASTAPI_PORT" --reload
else
    # Production mode with workers
    export DEV_MODE=false
    uvicorn \
        depictio.api.main:app \
        --host "$FASTAPI_HOST" \
        --port "$FASTAPI_PORT" \
        --workers "$FASTAPI_WORKERS" \
        --timeout-keep-alive 5 \
        --log-level info \
        --access-log
fi
