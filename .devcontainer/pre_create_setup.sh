#!/bin/bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Depictio DevContainer Pre-Create Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Detect if running in GitHub Codespaces
if [ -n "$CODESPACES" ]; then
    echo "🌐 GitHub Codespaces detected"
    echo "   Skipping credential extraction (not available in Codespaces)"
    echo "   AI tools will use Docker volumes - authenticate once in the container"
    echo ""
    # Skip credential checks and jump to port allocation
else
    # Local development - extract credentials from host
    echo "💻 Local development detected"
    echo ""

    # Verify AI tool credentials exist
    echo "🔐 Checking AI tool credentials..."

    # Check if security command exists (macOS only)
    if command -v security &> /dev/null; then
        # Check Claude Code credentials
        CLAUDE_CREDS=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || echo "")
        if [ -n "$CLAUDE_CREDS" ]; then
            # Save full credentials to ~/.claude/.credentials.json (will be mounted)
            mkdir -p ~/.claude
            echo "$CLAUDE_CREDS" > ~/.claude/.credentials.json
            chmod 600 ~/.claude/.credentials.json
            echo "   ✓ Claude Code credentials extracted from Keychain"
        else
            echo "   ⚠️  No Claude Code credentials in keychain"
            echo "      Run 'claude' on your host to authenticate first"
        fi
    else
        echo "   ⚠️  macOS Keychain not available (not on macOS)"
        echo "      Claude Code will use Docker volume - authenticate in container"
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
fi

# Source port allocation script to set up instance configuration
echo "🔧 Configuring instance..."
# shellcheck disable=SC1091
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
else
    # Not a worktree - create empty override to prevent docker-compose errors
    cat > .devcontainer/docker-compose.git-mount.yaml <<'EOF'
# Auto-generated: No worktree detected
# This file intentionally left empty but must exist for docker-compose
services:
  app: {}
EOF
    echo "✓ Git mount configuration created (no worktree, empty file)"
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
