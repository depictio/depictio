#!/bin/bash
# Forward ports from sibling containers into the devcontainer (the compose
# `app` service). This is what makes them visible to VS Code / Codespaces
# automatic port forwarding.
#
# Why this is needed: depictio's services run as *sibling* containers
# (docker-outside-of-docker) and publish to the HOST's 127.0.0.1. Codespaces
# only auto-detects ports listening INSIDE the devcontainer, so we use socat
# to create matching listeners here that proxy to the siblings over the
# compose network (by service name).
#
# Why setsid/nohup: this script is invoked from postStartCommand via
# `docker exec`. Plain `socat … &` children get SIGHUP'd when that exec
# session closes, so the listeners vanish and nothing is left to forward.
# `setsid nohup … & disown` detaches them into their own session so they
# survive.

if [ -f /workspace/.env.instance ]; then
    # shellcheck source=/dev/null
    source /workspace/.env.instance
fi

FASTAPI_PORT=${FASTAPI_PORT:-8058}
MINIO_CONSOLE_PORT=${MINIO_CONSOLE_PORT:-9001}
VIEWER_DEV_PORT=${VIEWER_DEV_PORT:-5173}

LOG_DIR=/tmp/depictio-port-forward
mkdir -p "$LOG_DIR"

echo "🔌 Starting port forwarding..."
echo "   Viewer (Vite HMR): $VIEWER_DEV_PORT -> depictio-viewer-dev:5173"
echo "   FastAPI:           $FASTAPI_PORT -> depictio-backend:8058"
echo "   MinIO Console:     $MINIO_CONSOLE_PORT -> minio:9001"

# Check if socat is installed
if ! command -v socat &> /dev/null; then
    echo "Installing socat..."
    sudo apt-get update -qq && sudo apt-get install -qq -y socat
fi

# Kill any existing socat forwarders so re-runs are idempotent.
pkill -f "socat.*TCP-LISTEN" 2>/dev/null || true

# Start a detached, self-restarting forwarder for one port.
#   $1 local listen port, $2 target host, $3 target port
start_forward() {
    local listen_port=$1 target_host=$2 target_port=$3
    local log="$LOG_DIR/${listen_port}.log"
    # The `while true` keeps the proxy up if the target restarts; setsid +
    # nohup + disown detach it from this exec session so it persists.
    setsid nohup bash -c "
        while true; do
            socat TCP-LISTEN:${listen_port},fork,reuseaddr TCP:${target_host}:${target_port}
            echo \"[\$(date)] socat ${listen_port} exited, restarting in 2s\" >> '${log}'
            sleep 2
        done
    " >> "$log" 2>&1 &
    disown
}

start_forward "$VIEWER_DEV_PORT" depictio-viewer-dev 5173
start_forward "$FASTAPI_PORT" depictio-backend 8058
start_forward "$MINIO_CONSOLE_PORT" minio 9001

# Give the listeners a moment to bind so Codespaces detects them on this pass.
sleep 1

echo "✅ Port forwarding started (logs in ${LOG_DIR})."
echo ""
echo "Ports should now appear in the VS Code / Codespaces PORTS panel."
echo "If not, run 'ports' to list them and add them manually:"
echo "   $VIEWER_DEV_PORT, $FASTAPI_PORT, $MINIO_CONSOLE_PORT"
