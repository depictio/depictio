#!/bin/bash

# Load instance configuration
if [ -f .env.instance ]; then
    # shellcheck disable=SC1091
    source .env.instance
fi

echo "Waiting for services to become ready..."

# Function to wait for a service using bash built-in TCP connection
wait_for_service() {
    local host=$1
    local port=$2
    local service_name=$3

    until timeout 1 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" 2>/dev/null; do
        echo "⏳ Waiting for ${service_name}..."
        sleep 2
    done
    echo "✓ ${service_name} is ready"
}

# Wait for MongoDB
wait_for_service mongo 27018 "MongoDB"

# Wait for Redis
wait_for_service redis 6379 "Redis"

# Wait for MinIO
wait_for_service minio 9000 "MinIO"

# Wait for backend
wait_for_service depictio-backend 8058 "FastAPI backend"

# Wait for frontend
wait_for_service depictio-frontend 5080 "Dash frontend"

echo "All services are ready! Setting up development environment..."

# Install depictio in development mode
cd /workspace || exit
uv sync

# Install depictio-cli from GitHub
uv venv depictio-cli-venv
# shellcheck disable=SC1091
source depictio-cli-venv/bin/activate
uv pip install git+https://github.com/depictio/depictio-models.git git+https://github.com/depictio/depictio-cli.git
depictio-cli --help
deactivate

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ Devcontainer setup complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
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
echo "🌐 External Access (from host machine):"
echo "   FastAPI:      http://localhost:${FASTAPI_PORT:-8058}"
echo "   Dash:         http://localhost:${DASH_PORT:-5080}"
echo "   MinIO Console: http://localhost:${MINIO_CONSOLE_PORT:-9001}"
echo ""
echo "💡 Tip: Each worktree/branch gets its own ports and database!"
echo ""
