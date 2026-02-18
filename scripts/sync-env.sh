#!/bin/bash
# Automatic .env sync script
# Creates a symlink from .env to .env.instance for automatic synchronization

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Check if .env.instance exists
if [ ! -f ".env.instance" ]; then
    echo "❌ Error: .env.instance not found"
    echo "Please create .env.instance first (see docs for format)"
    exit 1
fi

# Remove old .env if it's a regular file
if [ -f ".env" ] && [ ! -L ".env" ]; then
    echo "📝 Removing old .env file..."
    rm -f .env
fi

# Create symlink if it doesn't exist
if [ ! -L ".env" ]; then
    echo "🔗 Creating symlink: .env → .env.instance"
    ln -sf .env.instance .env
    echo "✅ Symlink created successfully"
else
    echo "✅ Symlink already exists: .env → .env.instance"
fi

# Verify symlink
if [ -L ".env" ]; then
    TARGET=$(readlink .env)
    echo "📋 Current setup:"
    echo "   .env → $TARGET"
    echo ""
    echo "🎯 PORT_OFFSET: $(grep "^PORT_OFFSET=" .env.instance | cut -d= -f2)"
    echo "   API Port: $(grep "^DEPICTIO_FASTAPI_EXTERNAL_PORT=" .env.instance | cut -d= -f2)"
    echo "   MinIO Port: $(grep "^DEPICTIO_MINIO_EXTERNAL_PORT=" .env.instance | cut -d= -f2)"
else
    echo "❌ Error: Failed to create symlink"
    exit 1
fi
