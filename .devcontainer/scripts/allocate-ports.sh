#!/bin/bash

# Port allocation script for git worktree-based multi-instance setup
# Uses branch naming convention to assign deterministic port offsets

echo "🔍 Detecting instance configuration..."

# Try to get current git branch from multiple sources
# Priority: 1) GITHUB_REF env var (Codespaces), 2) git command, 3) fallback to "codespace"
if [ -n "$GITHUB_REF" ]; then
    # In Codespaces, GITHUB_REF is set (e.g., refs/heads/feat/my-branch)
    BRANCH_NAME="${GITHUB_REF#refs/heads/}"
    echo "📍 Detected from GITHUB_REF: $BRANCH_NAME"
elif [ -n "$CODESPACE_NAME" ]; then
    # Running in Codespaces but no GITHUB_REF - use git with fallback
    BRANCH_NAME=$(git branch --show-current 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "codespace")
    echo "📍 Detected from git: $BRANCH_NAME"
else
    # Local development
    BRANCH_NAME=$(git branch --show-current 2>/dev/null || echo "unknown")
    echo "📍 Detected from git: $BRANCH_NAME"
fi

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

# MinIO credentials (match docker-compose/.env)
DEPICTIO_MINIO_ROOT_USER=minio
DEPICTIO_MINIO_ROOT_PASSWORD=minio123

# Data directory
DATA_DIR=data/${COMPOSE_PROJECT_NAME}
EOF

echo "✅ Configuration saved to .env.instance"
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
