#!/bin/bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Depictio DevContainer Pre-Create Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Source port allocation script to set up instance configuration
echo "🔧 Configuring instance..."
source .devcontainer/scripts/allocate-ports.sh

# Ensure docker-compose/.env exists (create default if missing for Codespaces)
if [ ! -f docker-compose/.env ]; then
    echo ""
    echo "⚠️  docker-compose/.env not found - creating default configuration..."
    mkdir -p docker-compose
    cat > docker-compose/.env <<'ENVEOF'
# Auto-generated default configuration for Codespaces/new setups
DEPICTIO_CONTEXT=server
DEPICTIO_LOGGING_VERBOSITY_LEVEL=DEBUG
DEPICTIO_MINIO_ROOT_USER=minio
DEPICTIO_MINIO_ROOT_PASSWORD=minio123
DEPICTIO_MONGODB_WIPE=false
DEV_MODE=true
DEPICTIO_PLAYWRIGHT_DEV_MODE=false
DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED=false
ENVEOF
    echo "✅ Created default docker-compose/.env"
else
    echo "✓ Environment file found"
fi
echo ""

# Create instance-specific data directory structure
echo "📁 Creating instance-specific data directories..."
DATA_BASE_DIR="data/${COMPOSE_PROJECT_NAME}"

mkdir -p "${DATA_BASE_DIR}"/{depictioDB,minio_data,redis,cache,prof_files}
chmod -R 775 "${DATA_BASE_DIR}"

echo "   Created: ${DATA_BASE_DIR}"

# Create shared directories (not instance-specific)
echo ""
echo "📁 Creating shared directories..."
mkdir -p depictio-example-data && chmod -R 777 depictio-example-data
mkdir -p depictio/keys && chmod -R 775 depictio/keys
mkdir -p depictio/.depictio && chmod -R 775 depictio/.depictio

# Create a .env file in root that sources the instance config for docker compose
echo ""
echo "📝 Creating docker-compose environment file..."
cat > .env <<'EOF'
# Auto-generated from .env.instance
EOF
cat .env.instance >> .env

echo "✓ Environment configuration ready"

# Create worktree-specific docker-compose override if needed
if [ -f .git ] && grep -q "gitdir:" .git; then
    echo ""
    echo "📦 Worktree detected - creating git mount configuration..."

    # Find the main repo's .git directory
    MAIN_GIT_PATH=$(grep 'gitdir:' .git | cut -d' ' -f2 | sed 's|/worktrees/.*||')

    if [ -d "$MAIN_GIT_PATH" ]; then
        cat > .devcontainer/docker-compose.git-mount.yaml <<EOF
# Auto-generated for worktree git support
services:
  app:
    volumes:
      - ${MAIN_GIT_PATH}:/workspaces/depictio/.git:ro
EOF
        echo "✓ Git mount configuration created"
    fi
fi

# Display summary
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Pre-create setup complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Instance Summary:"
echo "   Branch:       ${BRANCH_NAME}"
echo "   Project:      ${COMPOSE_PROJECT_NAME}"
echo "   Data Dir:     ${DATA_BASE_DIR}"
echo ""
echo "🌐 Your services will be available at:"
echo "   MongoDB:      localhost:${MONGO_PORT}"
echo "   FastAPI:      localhost:${FASTAPI_PORT}"
echo "   Dash:         localhost:${DASH_PORT}"
echo "   MinIO Console: localhost:${MINIO_CONSOLE_PORT}"
echo ""
