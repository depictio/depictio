#!/bin/bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Depictio DevContainer Pre-Create Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Source port allocation script to set up instance configuration
echo "🔧 Configuring instance..."
source .devcontainer/scripts/allocate-ports.sh

# Ensure docker-compose/.env exists
if [ ! -f docker-compose/.env ]; then
    echo ""
    echo "❌ ERROR: docker-compose/.env not found!"
    echo "Please create it with required environment variables."
    exit 1
fi

echo "✓ Environment file found"
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
