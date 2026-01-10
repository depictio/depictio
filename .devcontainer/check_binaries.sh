#!/bin/bash

echo "Checking if AI tool binaries are accessible..."

# Check if the commands exist
echo "Checking for gemini command..."
if command -v gemini &> /dev/null; then
    echo "✓ gemini command is available"
    gemini --version 2>&1 || echo "(version check failed, but command exists)"
else
    echo "✗ gemini command is NOT available"
fi

echo ""
echo "Checking for claude command..."
if command -v claude &> /dev/null; then
    echo "✓ claude command is available"
    claude --version 2>&1 || echo "(version check failed, but command exists)"
else
    echo "✗ claude command is NOT available"
fi

echo ""
echo "Checking for qwen command..."
if command -v qwen &> /dev/null; then
    echo "✓ qwen command is available"
    qwen --version 2>&1 || echo "(version check failed, but command exists)"
else
    echo "✗ qwen command is NOT available"
fi

echo ""
echo "Checking npm global packages..."
npm list -g --depth=0 | grep -i "gemini\|claude\|qwen" || echo "No matching global packages found"

echo ""
echo "Checking PATH for npm binaries..."
echo "PATH: $PATH"

echo ""
echo "Checking for npm bin directory..."
NPM_BIN=$(npm bin -g)
echo "Global npm bin directory: $NPM_BIN"
ls -la "$NPM_BIN" 2>/dev/null || echo "Global npm bin directory not accessible or empty"

echo ""
echo "Done checking binaries."
