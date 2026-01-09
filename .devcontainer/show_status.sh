#!/bin/bash

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Depictio DevContainer Status"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Load instance configuration if it exists
if [ -f /workspace/.env.instance ]; then
    # shellcheck disable=SC1091
    source /workspace/.env.instance

    echo "📊 Instance Information:"
    echo "   Branch:       ${BRANCH_NAME:-unknown}"
    echo "   Project:      ${COMPOSE_PROJECT_NAME:-depictio}"
    echo "   Instance ID:  ${INSTANCE_ID:-default}"
    echo ""
    echo "🔌 Internal Service URLs (container-to-container):"
    echo "   MongoDB:      mongo:27018"
    echo "   Redis:        redis:6379"
    echo "   MinIO:        minio:9000"
    echo "   FastAPI:      depictio-backend:8058"
    echo "   Dash:         depictio-frontend:5080"
    echo ""
    echo "🌐 External Access (from host machine/browser):"
    echo "   FastAPI:      http://localhost:${FASTAPI_PORT:-8058}"
    echo "   Dash:         http://localhost:${DASH_PORT:-5080}"
    echo "   MinIO Console: http://localhost:${MINIO_CONSOLE_PORT:-9001}"
    echo ""
else
    echo "⚠️  Instance configuration not found (.env.instance missing)"
    echo "   This may be the first startup - configuration will be created shortly."
    echo ""
fi

# Check if services are running
echo "🔍 Service Status:"
if command -v docker &> /dev/null; then
    # Check specific containers
    for service in mongo redis minio depictio-backend depictio-frontend; do
        if docker ps --format '{{.Names}}' | grep -q "$service" 2>/dev/null; then
            echo "   ✅ $service: running"
        else
            echo "   ⏳ $service: starting or not found"
        fi
    done
else
    echo "   ℹ️  Docker not available in this container"
fi

echo ""
echo "💡 Tips:"
echo "   • View setup logs: cat /workspace/.devcontainer/*.log (if exists)"
echo "   • Reload status: bash /workspace/.devcontainer/show_status.sh"
if [ -n "$CODESPACE_NAME" ]; then
    echo "   • This is a GitHub Codespace: ports are automatically forwarded"
fi
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
