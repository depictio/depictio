#!/bin/bash
# Forward ports from sibling containers to the devcontainer
# This makes them visible to VS Code's port auto-detection

if [ -f /workspace/.env.instance ]; then
    source /workspace/.env.instance
fi

DASH_PORT=${DASH_PORT:-5080}
FASTAPI_PORT=${FASTAPI_PORT:-8058}
MINIO_CONSOLE_PORT=${MINIO_CONSOLE_PORT:-9001}

echo "🔌 Starting port forwarding..."
echo "   Dash: $DASH_PORT -> depictio-frontend:5080"
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
socat TCP-LISTEN:$DASH_PORT,fork,reuseaddr TCP:depictio-frontend:5080 &
socat TCP-LISTEN:$FASTAPI_PORT,fork,reuseaddr TCP:depictio-backend:8058 &
socat TCP-LISTEN:$MINIO_CONSOLE_PORT,fork,reuseaddr TCP:minio:9001 &

echo "✅ Port forwarding started!"
echo ""
echo "Ports should now appear in VS Code Ports panel."
echo "If not, manually add: $DASH_PORT, $FASTAPI_PORT, $MINIO_CONSOLE_PORT"
