#!/bin/bash

# Port allocation script for git worktree-based multi-instance setup
# Uses branch naming convention to assign deterministic port offsets

# Parse command-line arguments
MONGODB_WIPE="false"
while [[ $# -gt 0 ]]; do
  case $1 in
    -w|--wipe)
      MONGODB_WIPE="true"
      echo "⚠️  MongoDB wipe enabled - database will be cleared on startup"
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--wipe|-w]"
      echo "  --wipe, -w  Enable MongoDB wipe (DEPICTIO_MONGODB_WIPE=true)"
      return 1 2>/dev/null || exit 1
      ;;
  esac
done

echo "🔍 Detecting instance configuration..."

# Get current git branch
BRANCH_NAME=$(git branch --show-current 2>/dev/null || echo "unknown")

# Sanitize branch name for use in container/project names
# Replace / with - and remove other special characters
SANITIZED_BRANCH=$(echo "$BRANCH_NAME" | sed 's/\//-/g' | sed 's/[^a-zA-Z0-9-]/-/g' | tr '[:upper:]' '[:lower:]')

# Create unique project name
COMPOSE_PROJECT_NAME="depictio-${SANITIZED_BRANCH}"

# Assign port offset based on branch type
# This ensures deterministic port allocation
case "$BRANCH_NAME" in
  "main")
    PORT_OFFSET=0
    echo "📌 Branch: main (production baseline)"
    ;;
  feat/*)
    # Extract feature name and create hash for deterministic offset
    FEATURE_NAME=$(echo "$BRANCH_NAME" | sed 's/feat\///')
    # Use first characters of md5 hash to generate number between 10-99
    HASH_NUM=$(echo -n "$FEATURE_NAME" | md5sum | tr -cd '0-9' | head -c 2)
    # Ensure it's between 10-89 (allows up to 90 feature branches)
    PORT_OFFSET=$((10 + (HASH_NUM % 80)))
    echo "🚀 Branch: $BRANCH_NAME (feature branch, offset: $PORT_OFFSET)"
    ;;
  hotfix/*)
    # Hotfixes get 90-99 range for quick identification
    HOTFIX_NAME=$(echo "$BRANCH_NAME" | sed 's/hotfix\///')
    HASH_NUM=$(echo -n "$HOTFIX_NAME" | md5sum | tr -cd '0-9' | head -c 2)
    PORT_OFFSET=$((90 + (HASH_NUM % 10)))
    echo "🔥 Branch: $BRANCH_NAME (hotfix branch, offset: $PORT_OFFSET)"
    ;;
  release/*)
    # Releases get 100-109 range
    RELEASE_NAME=$(echo "$BRANCH_NAME" | sed 's/release\///')
    HASH_NUM=$(echo -n "$RELEASE_NAME" | md5sum | tr -cd '0-9' | head -c 2)
    PORT_OFFSET=$((100 + (HASH_NUM % 10)))
    echo "📦 Branch: $BRANCH_NAME (release branch, offset: $PORT_OFFSET)"
    ;;
  *)
    # Unknown branch types get 110+ range
    HASH_NUM=$(echo -n "$BRANCH_NAME" | md5sum | tr -cd '0-9' | head -c 2)
    PORT_OFFSET=$((110 + (HASH_NUM % 40)))
    echo "❓ Branch: $BRANCH_NAME (unknown type, offset: $PORT_OFFSET)"
    ;;
esac

# Calculate actual ports with offset
MONGO_PORT=$((27000 + PORT_OFFSET))
REDIS_PORT=$((6000 + PORT_OFFSET))
FASTAPI_PORT=$((8000 + PORT_OFFSET))
DASH_PORT=$((5000 + PORT_OFFSET))
MINIO_PORT=$((9000 + PORT_OFFSET))
MINIO_CONSOLE_PORT=$((9001 + PORT_OFFSET))

# Generate instance ID for display
INSTANCE_ID="${SANITIZED_BRANCH}-${PORT_OFFSET}"

# Display configuration
echo ""
echo "📋 Instance Configuration:"
echo "   Project Name: ${COMPOSE_PROJECT_NAME}"
echo "   Instance ID:  ${INSTANCE_ID}"
echo ""
echo "🔌 Port Assignments:"
echo "   MongoDB:      ${MONGO_PORT}"
echo "   Redis:        ${REDIS_PORT}"
echo "   FastAPI:      ${FASTAPI_PORT}"
echo "   Dash:         ${DASH_PORT}"
echo "   MinIO API:    ${MINIO_PORT}"
echo "   MinIO Console: ${MINIO_CONSOLE_PORT}"
echo ""
echo "⚙️  Development Settings:"
echo "   Dev Mode:     ✅ enabled"
if [ "${MONGODB_WIPE}" = "true" ]; then
  echo "   MongoDB Wipe: ⚠️  enabled (database will be cleared)"
else
  echo "   MongoDB Wipe: ❌ disabled"
fi
echo ""

# Save configuration to .env.instance for persistence
cat > .env.instance <<EOF
# Auto-generated instance configuration
# Branch: ${BRANCH_NAME}
# Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")

COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}
INSTANCE_ID=${INSTANCE_ID}
BRANCH_NAME=${BRANCH_NAME}
PORT_OFFSET=${PORT_OFFSET}

# Port assignments
MONGO_PORT=${MONGO_PORT}
REDIS_PORT=${REDIS_PORT}
FASTAPI_PORT=${FASTAPI_PORT}
DASH_PORT=${DASH_PORT}
MINIO_PORT=${MINIO_PORT}
MINIO_CONSOLE_PORT=${MINIO_CONSOLE_PORT}

# Internal service URLs (for container-to-container communication)
DEPICTIO_MONGODB_PORT=${MONGO_PORT}
DEPICTIO_REDIS_PORT=${REDIS_PORT}
DEPICTIO_FASTAPI_PORT=${FASTAPI_PORT}
DEPICTIO_DASH_PORT=${DASH_PORT}
DEPICTIO_MINIO_PORT=${MINIO_PORT}
DEPICTIO_MINIO_ENDPOINT_URL=http://minio:9000

# External ports (for browser-to-service communication from host)
DEPICTIO_FASTAPI_EXTERNAL_PORT=${FASTAPI_PORT}
DEPICTIO_DASH_EXTERNAL_PORT=${DASH_PORT}
DEPICTIO_MINIO_EXTERNAL_PORT=${MINIO_PORT}
DEPICTIO_MINIO_EXTERNAL_HOST=localhost
DEPICTIO_FASTAPI_EXTERNAL_HOST=localhost

# MinIO credentials (match docker-compose/.env)
DEPICTIO_MINIO_ROOT_USER=minio
DEPICTIO_MINIO_ROOT_PASSWORD=minio123

# Development settings
DEPICTIO_DEV_MODE=true
DEPICTIO_MONGODB_WIPE=${MONGODB_WIPE}

# Data directory
DATA_DIR=data/${COMPOSE_PROJECT_NAME}
EOF

echo "✅ Configuration saved to .env.instance"
echo ""

# Generate docker-compose.override.yaml for multi-instance container naming
cat > docker-compose.override.yaml <<EOF
# Auto-generated override for multi-instance devcontainer
# Generated: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
# Branch: ${BRANCH_NAME}
# Project: ${COMPOSE_PROJECT_NAME}

services:
  mongo:
    container_name: ${COMPOSE_PROJECT_NAME}-mongo

  redis:
    container_name: ${COMPOSE_PROJECT_NAME}-redis

  minio:
    container_name: ${COMPOSE_PROJECT_NAME}-minio

  depictio-frontend:
    container_name: ${COMPOSE_PROJECT_NAME}-depictio-frontend
    environment:
      - DEPICTIO_FASTAPI_EXTERNAL_PORT=${FASTAPI_PORT}
      - DEPICTIO_DASH_EXTERNAL_PORT=${DASH_PORT}
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=${MONGODB_WIPE}

  depictio-backend:
    container_name: ${COMPOSE_PROJECT_NAME}-depictio-backend
    environment:
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=${MONGODB_WIPE}

  depictio-celery-worker:
    container_name: ${COMPOSE_PROJECT_NAME}-depictio-celery-worker
    environment:
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=${MONGODB_WIPE}
EOF

echo "✅ Generated docker-compose.override.yaml for multi-instance setup"
echo ""

# Export variables for immediate use in current shell
export COMPOSE_PROJECT_NAME
export INSTANCE_ID
export BRANCH_NAME
export PORT_OFFSET
export MONGO_PORT
export REDIS_PORT
export FASTAPI_PORT
export DASH_PORT
export MINIO_PORT
export MINIO_CONSOLE_PORT
export DATA_DIR="data/${COMPOSE_PROJECT_NAME}"
