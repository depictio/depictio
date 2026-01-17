#!/bin/bash
# Setup credentials for AI tools in devcontainer
# This script handles credential configuration across different platforms

echo "🔐 Configuring AI tool credentials..."

# Claude Code credentials
if [ -f /home/vscode/.claude/.credentials.json ]; then
    echo "   ✓ Claude Code credentials found"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "   ✓ Claude Code API key available via environment"
else
    echo "   ⚠️  No Claude Code credentials found"
    echo "      To authenticate, run: claude auth login"
fi

# Gemini credentials
if [ -f /home/vscode/.gemini/oauth_creds.json ]; then
    echo "   ✓ Gemini credentials found"
else
    echo "   ⚠️  No Gemini credentials found"
    echo "      To authenticate, run: gemini auth login"
fi

# Qwen credentials
if [ -f /home/vscode/.qwen/oauth_creds.json ]; then
    echo "   ✓ Qwen credentials found"
else
    echo "   ⚠️  No Qwen credentials found"
    echo "      To authenticate, run: qwen auth login"
fi

echo "   ✅ Credential check complete"
