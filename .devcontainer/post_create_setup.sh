#!/bin/bash

# Load instance configuration
if [ -f .env.instance ]; then
    # shellcheck disable=SC1091
    source .env.instance
fi

# Initialize Git LFS
echo "🔧 Initializing Git LFS..."
git lfs install
echo "   ✓ Git LFS configured"

# Install and setup pre-commit hooks
echo "🪝 Setting up pre-commit hooks..."
cd /workspace || exit
if [ -f .pre-commit-config.yaml ]; then
    # Install pre-commit using uv (if uv is available) or pip
    if command -v uv &> /dev/null; then
        uv tool install pre-commit || uv pip install pre-commit
    else
        pip install pre-commit
    fi

    # Install the git hook scripts
    pre-commit install

    # Apply environment-agnostic hook (supports Mac, devcontainer, fresh uv install)
    if [ -f .devcontainer/hooks/pre-commit ]; then
        cp .devcontainer/hooks/pre-commit .git/hooks/pre-commit
        chmod +x .git/hooks/pre-commit
        echo "   ✓ Applied environment-agnostic pre-commit hook"
    fi

    echo "   ✓ Pre-commit hooks installed"
else
    echo "   ⚠️  No .pre-commit-config.yaml found, skipping pre-commit setup"
fi

# Fix permissions for AI tool configs
echo "🔐 Setting up AI tool configurations..."

# Fix Claude Code volume permissions (Docker volumes default to root)
if [ -d /home/vscode/.claude ]; then
    echo "   Fixing Claude Code permissions..."
    sudo chown -R vscode:vscode /home/vscode/.claude
    echo "   ✓ Claude Code directory ready"
fi

# Verify other configs
if [ -f /home/vscode/.gemini/oauth_creds.json ]; then
    echo "   ✓ Gemini config mounted"
else
    echo "   ⚠️  Gemini config not found (run 'gemini' on host to authenticate)"
fi

if [ -f /home/vscode/.qwen/oauth_creds.json ]; then
    echo "   ✓ Qwen config mounted"
else
    echo "   ⚠️  Qwen config not found (run 'qwen' on host to authenticate)"
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

# Install depictio in development mode with dev dependencies
cd /workspace || exit
echo "📦 Installing depictio with dev dependencies..."
uv sync --extra dev

# Note: polars-lts-cpu should be automatically installed via pyproject.toml
# If you encounter polars conflicts, the CI workflow shows how to force-reinstall
echo "✅ Dependencies installed (including dev extras: pytest, mongomock-motor, etc.)"

# Install depictio-cli from GitHub
uv venv depictio-cli-venv
# shellcheck disable=SC1091
source depictio-cli-venv/bin/activate
uv pip install git+https://github.com/depictio/depictio-models.git git+https://github.com/depictio/depictio-cli.git
depictio-cli --help
deactivate

# Verify that packages were installed in the container image and check what binaries are available
echo "Verifying installed packages in container..."
npm list -g --depth=0 | grep -i "gemini\|claude\|qwen" || echo "No matching packages found in global install"

# Find out what binaries were actually installed by these packages
echo "Checking for available binaries in npm global bin..."
NPM_GLOBAL_BIN=$(npm bin -g)
echo "Global npm bin directory: $NPM_GLOBAL_BIN"
ls -la "$NPM_GLOBAL_BIN" 2>/dev/null || echo "Global npm bin directory not accessible"

echo "Looking for any executables that might be the AI tools..."
find "$NPM_GLOBAL_BIN" -type f -executable 2>/dev/null | grep -i "gemini\|claude\|qwen\|google\|anthropic\|genai" || echo "No matching executables found in npm bin"

# Show all installed binaries for debugging
echo "All executables in npm global bin:"
find "$NPM_GLOBAL_BIN" -type f -executable 2>/dev/null | head -20

# Also check if the commands might be available through other means
echo "Checking if commands are available in PATH..."
which gemini || echo "gemini command not found in PATH"
which claude || echo "claude command not found in PATH"
which qwen || echo "qwen command not found in PATH"

# Test if the commands exist and work
echo "Testing commands..."
if command -v gemini &> /dev/null; then
    echo "✓ gemini command is available"
    gemini --help 2>&1 | head -5 || echo "gemini help not available"
else
    echo "✗ gemini command is NOT available"
fi

if command -v claude &> /dev/null; then
    echo "✓ claude command is available"
    claude --help 2>&1 | head -5 || echo "claude help not available"
else
    echo "✗ claude command is NOT available"
fi

if command -v qwen &> /dev/null; then
    echo "✓ qwen command is available"
    qwen --help 2>&1 | head -5 || echo "qwen help not available"
else
    echo "✗ qwen command is NOT available"
fi

# Inform user about the situation
echo ""
echo "Note: The volume mounts ensure your credentials from host ~/.gemini, ~/.claude, ~/.qwen"
echo "are accessible in the devcontainer at /home/vscode/.gemini, /home/vscode/.claude, /home/vscode/.qwen"
echo "This allows the tools to access your existing authentication and session data."
echo "If CLI tools are not available as commands, you can use the libraries programmatically in scripts."

# Set up credentials for AI tools
bash /workspace/.devcontainer/setup_credentials.sh

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
