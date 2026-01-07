#!/bin/bash

# Set default values if environment variables are not set
DASH_HOST=${DEPICTIO_DASH_HOST:-0.0.0.0}
DASH_PORT=${DEPICTIO_DASH_PORT:-5080}
DASH_WORKERS=${DEPICTIO_DASH_WORKERS:-4}

# Check for s3fs availability

# Try to find s3fs in common locations
S3FS_PATH=""
if command -v s3fs &> /dev/null; then
    S3FS_PATH="s3fs"
else
    # Check in same directory as python (likely conda environment)
    if [ -x "$PYTHON_DIR/s3fs" ]; then
        S3FS_PATH="$PYTHON_DIR/s3fs"
        echo "DEBUG: Found s3fs at: $S3FS_PATH"
    else
        echo "DEBUG: s3fs not found in $PYTHON_DIR"
    fi
fi

# Mount S3 if s3fs is available and mount point is configured
if [ -n "$S3FS_PATH" ] && [ -n "$DEPICTIO_S3_MOUNT_POINTS" ]; then
    echo "s3fs found, attempting to mount S3..."

    # Parse first mount point from comma-separated list
    MOUNT_POINT=$(echo "$DEPICTIO_S3_MOUNT_POINTS" | cut -d',' -f1)

    if [ -n "$MOUNT_POINT" ]; then
        # Mount point should already exist from Dockerfile
        echo "DEBUG: Mount point: $MOUNT_POINT"

        # Create dynamic credentials file from environment variables
        echo "${DEPICTIO_MINIO_ROOT_USER:-minio}:${DEPICTIO_MINIO_ROOT_PASSWORD:-minio123}" > /tmp/s3fs-passwd
        chmod 600 /tmp/s3fs-passwd

        # Try to mount S3 bucket using the found s3fs path
        echo "DEBUG: Attempting s3fs mount with dynamic credentials"
        echo "DEBUG: $S3FS_PATH depictio-bucket $MOUNT_POINT -o url=${DEPICTIO_MINIO_ENDPOINT_URL:-http://minio:9000} -o use_path_request_style -o allow_other -o nonempty -o uid=$(id -u) -o gid=$(id -g)"

        # Try mount with error capture
        "$S3FS_PATH" depictio-bucket "$MOUNT_POINT" \
            -o url="${DEPICTIO_MINIO_ENDPOINT_URL:-http://minio:9000}" \
            -o use_path_request_style \
            -o allow_other \
            -o nonempty \
            -o uid="$(id -u)" \
            -o gid="$(id -g)" \
            -o passwd_file=/tmp/s3fs-passwd \
            -o dbglevel=info \
            -f 2>&1 &

        MOUNT_PID=$!
        sleep 2  # Give mount time to initialize

        # Check if mount succeeded
        if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
            echo "S3 mounted successfully at $MOUNT_POINT"
        else
            echo "S3 mount failed. Error details:"
            echo "DEBUG: Mount process PID: $MOUNT_PID"
            echo "DEBUG: Checking for FUSE support: $(ls -la /dev/fuse 2>/dev/null || echo '/dev/fuse not found')"
            echo "DEBUG: User permissions: uid=$(id -u) gid=$(id -g)"
            echo "S3 mount failed, continuing without mount (caching still works)"
            # Kill the background mount process if it's still running
            kill $MOUNT_PID 2>/dev/null || true
        fi
    fi
else
    echo "s3fs not found or DEPICTIO_S3_MOUNT_POINTS not set, skipping S3 mount"
fi

sleep 5 # Allow time for other services to start

if [ "$DEV_MODE" = "true" ]; then
    # Development mode with reload
    # Debug mode is passed to Dash in flask_dispatcher.py
    export DEV_MODE=true
    echo "Running in development mode on $DASH_HOST:$DASH_PORT" with "$DASH_WORKERS" workers
    python depictio/dash/flask_dispatcher.py
    # gunicorn --workers=2 --reload --bind="$DASH_HOST:$DASH_PORT" --timeout=120 depictio.dash.wsgi:server
else
    # Production mode with workers
    export DEV_MODE=false
    echo "Running in production mode on $DASH_HOST:$DASH_PORT with $DASH_WORKERS workers"
    gunicorn \
        --workers="$DASH_WORKERS" \
        --bind="$DASH_HOST:$DASH_PORT" \
        --timeout=120 \
        --keep-alive=5 \
        --max-requests=1000 \
        --access-logfile=- \
        --error-logfile=- \
        depictio.dash.wsgi:application
fi
