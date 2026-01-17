#!/bin/bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Depictio DevContainer Pre-Create Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Verify AI tool credentials exist
echo "🔐 Checking AI tool credentials..."

# Check Claude Code credentials (platform-aware)
# macOS uses security keychain, Linux/Codespaces uses file-based credentials
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS: Try to get credentials from keychain
    CLAUDE_CREDS=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || echo "")
    if [ -n "$CLAUDE_CREDS" ]; then
        # Extract access token and save to .env.claude for docker-compose
        ACCESS_TOKEN=$(echo "$CLAUDE_CREDS" | grep -o '"accessToken":"[^"]*"' | cut -d'"' -f4)

        if [ -n "$ACCESS_TOKEN" ]; then
            # Create .env.claude with the token
            echo "ANTHROPIC_API_KEY=${ACCESS_TOKEN}" > .devcontainer/.env.claude
            chmod 600 .devcontainer/.env.claude
            echo "   ✓ Claude Code credentials extracted from keychain"
        fi

        # Also save full credentials to ~/.claude/.credentials.json (will be mounted)
        mkdir -p ~/.claude
        echo "$CLAUDE_CREDS" > ~/.claude/.credentials.json
        chmod 600 ~/.claude/.credentials.json
    else
        echo "   ⚠️  No Claude Code credentials in keychain"
        echo "      Run 'claude' on your host to authenticate first"
        touch .devcontainer/.env.claude
        chmod 600 .devcontainer/.env.claude
    fi
else
    # Linux/Codespaces: Check for file-based credentials or environment variable
    if [ -f ~/.claude/.credentials.json ]; then
        echo "   ✓ Claude Code credentials found in ~/.claude/"
    elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        echo "   ✓ Claude Code API key available via ANTHROPIC_API_KEY"
        echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}" > .devcontainer/.env.claude
        chmod 600 .devcontainer/.env.claude
    else
        echo "   ⚠️  No Claude Code credentials found"
        echo "      Set ANTHROPIC_API_KEY or run 'claude auth login' in the container"
        touch .devcontainer/.env.claude
        chmod 600 .devcontainer/.env.claude
    fi
fi

# Check Gemini credentials
if [ -f ~/.gemini/oauth_creds.json ]; then
    echo "   ✓ Gemini credentials found"
else
    echo "   ⚠️  No Gemini credentials found (run 'gemini' to authenticate)"
fi

# Check Qwen credentials
if [ -f ~/.qwen/oauth_creds.json ]; then
    echo "   ✓ Qwen credentials found"
else
    echo "   ⚠️  No Qwen credentials found (run 'qwen' to authenticate)"
fi

# Source port allocation script to set up instance configuration
echo "🔧 Configuring instance..."
# shellcheck disable=SC1091
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
      - ${MAIN_GIT_PATH}:/workspace-root/.git:rw
EOF
        echo "✓ Git mount configuration created (mounting to /workspace-root/.git)"
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
