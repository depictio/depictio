#!/bin/bash
# Setup script to install pre-commit hooks with environment detection
# Works on Mac, Linux, devcontainer, and fresh uv installs

set -e

echo "🪝 Setting up pre-commit hooks..."

# Check if .pre-commit-config.yaml exists
if [ ! -f .pre-commit-config.yaml ]; then
    echo "❌ Error: .pre-commit-config.yaml not found"
    echo "   Are you in the repository root?"
    exit 1
fi

# Install pre-commit if not already installed
if ! command -v pre-commit &> /dev/null; then
    echo "📦 Installing pre-commit..."
    if command -v uv &> /dev/null; then
        uv tool install pre-commit || uv pip install pre-commit
    elif command -v pip &> /dev/null; then
        pip install pre-commit
    else
        echo "❌ Error: Cannot find uv or pip to install pre-commit"
        exit 1
    fi
fi

# Install the git hook scripts
echo "🔧 Installing pre-commit hooks..."
pre-commit install

# Apply environment-agnostic hook
if [ -f .devcontainer/hooks/pre-commit ]; then
    echo "✨ Applying environment-agnostic hook..."
    cp .devcontainer/hooks/pre-commit .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
    echo "   ✓ Hook updated to support multiple environments"
else
    echo "⚠️  Warning: .devcontainer/hooks/pre-commit not found"
    echo "   Using default pre-commit hook (may not work in all environments)"
fi

echo ""
echo "✅ Pre-commit hooks setup complete!"
echo ""
echo "📋 Supported environments:"
echo "   ✓ Mac with depictio-venv-*"
echo "   ✓ Linux with .venv"
echo "   ✓ Devcontainer with uv tools"
echo "   ✓ System-wide pre-commit installation"
echo ""
echo "💡 Test it: git commit -m 'test'"
