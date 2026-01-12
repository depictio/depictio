#!/bin/bash

# Source and destination
SRC="CLAUDE.md"
DEST="GEMINI.md"

# Check if source exists
if [ ! -f "$SRC" ]; then
    echo "Error: $SRC not found!"
    exit 1
fi

echo "Syncing $DEST from $SRC..."

# Copy and replace terms
# 1. Claude Code -> Gemini CLI
# 2. Claude -> Gemini
# 3. claude.ai/code -> Gemini CLI
sed -e 's/Claude Code/Gemini CLI/g' \
    -e 's/Claude/Gemini/g' \
    -e 's/claude.ai\/code/Gemini CLI/g' \
    "$SRC" > "$DEST"

echo "Done. $DEST has been updated."
