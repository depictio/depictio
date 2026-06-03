#!/bin/bash
# Forward ports from sibling containers to the devcontainer
# This makes them visible to VS Code's port auto-detection

if [ -f /workspace/.env.instance ]; then
    # shellcheck source=/dev/null
    source /workspace/.env.instance
fi

FASTAPI_PORT=${FASTAPI_PORT:-8058}
MINIO_CONSOLE_PORT=${MINIO_CONSOLE_PORT:-9001}
VIEWER_DEV_PORT=${VIEWER_DEV_PORT:-5173}

echo "🔌 Starting port forwarding..."
echo "   Viewer (Vite HMR): $VIEWER_DEV_PORT -> depictio-viewer-dev:5173"
echo "   FastAPI: $FASTAPI_PORT -> depictio-backend:8058"
echo "   MinIO Console: $MINIO_CONSOLE_PORT -> minio:9001"

# Check if socat is installed
if ! command -v socat &> /dev/null; then
    echo "Installing socat..."
    sudo apt-get update -qq && sudo apt-get install -qq -y socat
fi

# Kill any existing socat processes
pkill -f "socat.*TCP-LISTEN" 2>/dev/null || true

# Start port forwarding in background
socat TCP-LISTEN:"$VIEWER_DEV_PORT",fork,reuseaddr TCP:depictio-viewer-dev:5173 &
socat TCP-LISTEN:"$FASTAPI_PORT",fork,reuseaddr TCP:depictio-backend:8058 &
socat TCP-LISTEN:"$MINIO_CONSOLE_PORT",fork,reuseaddr TCP:minio:9001 &

echo "✅ Port forwarding started!"
echo ""
echo "Ports should now appear in VS Code Ports panel."
echo "If not, manually add: $VIEWER_DEV_PORT, $FASTAPI_PORT, $MINIO_CONSOLE_PORT"
