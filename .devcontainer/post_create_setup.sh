#!/bin/bash

# Load instance configuration
if [ -f .env.instance ]; then
    # shellcheck disable=SC1091
    source .env.instance
fi

echo "Waiting for services to become ready..."

# Wait for MongoDB
until nc -z mongo 27018; do
  echo "⏳ Waiting for MongoDB..."
  sleep 2
done
echo "✓ MongoDB is ready"

# Wait for Redis
until nc -z redis 6379; do
  echo "⏳ Waiting for Redis..."
  sleep 2
done
echo "✓ Redis is ready"

# Wait for MinIO
until nc -z minio 9000; do
  echo "⏳ Waiting for MinIO..."
  sleep 2
done
echo "✓ MinIO is ready"

# Wait for backend
until nc -z depictio-backend 8058; do
  echo "⏳ Waiting for FastAPI backend..."
  sleep 2
done
echo "✓ FastAPI backend is ready"

# Wait for frontend
until nc -z depictio-frontend 5080; do
  echo "⏳ Waiting for Dash frontend..."
  sleep 2
done
echo "✓ Dash frontend is ready"

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
