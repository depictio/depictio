#!/bin/bash
# Note: intentionally no `set -e` — this script is sourced by pre_create_setup.sh
# and set -e would leak into the interactive shell, breaking readline (Esc, Ctrl+R, etc.).

# Port allocation for git worktree-based multi-instance dev setups.
#
# Strategy: scan offsets 100..250 and pick the first one whose 8-port window
# (mongo, redis, fastapi, dash, minio-api, minio-console, viewer, flower) is
# entirely free on the host. No persistence — every `source` re-allocates,
# so ports may shift between runs if neighbours boot first. Acceptable for
# pure dev worktrees; if you need stable URLs, pin them by hand.

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
      exit 1
      ;;
  esac
done

echo "🔍 Detecting instance configuration..."

# Get current git branch
BRANCH_NAME=$(git branch --show-current 2>/dev/null || echo "unknown")

# Sanitize branch name for use in container/project names
SANITIZED_BRANCH=$(echo "$BRANCH_NAME" | sed 's/\//-/g' | sed 's/[^a-zA-Z0-9-]/-/g' | tr '[:upper:]' '[:lower:]')

# Create unique project name
COMPOSE_PROJECT_NAME="depictio-${SANITIZED_BRANCH}"

# Returns 0 if something is LISTENing on the TCP port, 1 otherwise.
# lsof is present on macOS by default and in most Linux dev images; the
# /dev/tcp probe is a fallback that catches anything accepting connections.
port_in_use() {
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  (exec 3<>/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1 && { exec 3<&-; exec 3>&-; return 0; }
  return 1
}

# Host-side port bases. Each instance binds (base + offset) for each entry.
PORT_BASES=(27000 6000 8000 5000 9000 9500 5500 7000)

PORT_OFFSET=""
for candidate in $(seq 100 250); do
  collision=0
  for base in "${PORT_BASES[@]}"; do
    if port_in_use $((base + candidate)); then
      collision=1
      break
    fi
  done
  if [ "$collision" -eq 0 ]; then
    PORT_OFFSET=$candidate
    break
  fi
done

if [ -z "$PORT_OFFSET" ]; then
  echo "❌ No free 8-port window found in offsets 100-250."
  echo "   Stop some containers or other listeners and re-source this script."
  # Dual-mode bail: `return` works when this script is sourced, `exit` runs
  # when it's executed directly. shellcheck can't tell `return` may fail.
  # shellcheck disable=SC2317
  return 1 2>/dev/null || exit 1
fi

echo "🎯 Branch: $BRANCH_NAME (allocated offset: $PORT_OFFSET)"

# Calculate actual ports with offset
MONGO_PORT=$((27000 + PORT_OFFSET))
REDIS_PORT=$((6000 + PORT_OFFSET))
FASTAPI_PORT=$((8000 + PORT_OFFSET))
DASH_PORT=$((5000 + PORT_OFFSET))
MINIO_PORT=$((9000 + PORT_OFFSET))
MINIO_CONSOLE_PORT=$((9500 + PORT_OFFSET))
VIEWER_DEV_PORT=$((5500 + PORT_OFFSET))
FLOWER_PORT=$((7000 + PORT_OFFSET))

INSTANCE_ID="${SANITIZED_BRANCH}-${PORT_OFFSET}"

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
echo "   Viewer (Vite): ${VIEWER_DEV_PORT}"
echo "   Flower:       ${FLOWER_PORT}"
echo ""
echo "⚙️  Development Settings:"
echo "   Dev Mode:     ✅ enabled"
if [ "${MONGODB_WIPE}" = "true" ]; then
  echo "   MongoDB Wipe: ⚠️  enabled (database will be cleared)"
else
  echo "   MongoDB Wipe: ❌ disabled"
fi
echo ""

# Development auth settings (default: single-user mode for devcontainers)
DEPICTIO_AUTH_SINGLE_USER_MODE=${DEPICTIO_AUTH_SINGLE_USER_MODE:-true}

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
VIEWER_DEV_PORT=${VIEWER_DEV_PORT}
FLOWER_PORT=${FLOWER_PORT}

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
DEPICTIO_AUTH_SINGLE_USER_MODE=${DEPICTIO_AUTH_SINGLE_USER_MODE}
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
      - DEPICTIO_AUTH_SINGLE_USER_MODE=${DEPICTIO_AUTH_SINGLE_USER_MODE}

  depictio-backend:
    container_name: ${COMPOSE_PROJECT_NAME}-depictio-backend
    environment:
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=${MONGODB_WIPE}
      - DEPICTIO_AUTH_SINGLE_USER_MODE=${DEPICTIO_AUTH_SINGLE_USER_MODE}
      - DEPICTIO_DASH_EXTERNAL_PORT=${DASH_PORT}

  depictio-celery-worker:
    container_name: ${COMPOSE_PROJECT_NAME}-depictio-celery-worker
    environment:
      - DEPICTIO_DEV_MODE=true
      - DEPICTIO_MONGODB_WIPE=${MONGODB_WIPE}

  depictio-viewer-dev:
    container_name: ${COMPOSE_PROJECT_NAME}-depictio-viewer-dev

  flower:
    container_name: ${COMPOSE_PROJECT_NAME}-flower
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
export VIEWER_DEV_PORT
export FLOWER_PORT
export DATA_DIR="data/${COMPOSE_PROJECT_NAME}"
