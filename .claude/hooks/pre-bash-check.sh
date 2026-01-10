#!/bin/bash
# Pre-bash-check hook for depictio
# Validates bash commands before execution
# Environment variables available:
#   TOOL_INPUT - JSON with tool parameters (contains "command" field)
#
# Return JSON with "decision": "approve", "deny", or "block"

set -e

# Parse the command from tool input
COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // empty')

# Allow empty commands (shouldn't happen but be safe)
if [[ -z "$COMMAND" ]]; then
    echo '{"decision": "approve"}'
    exit 0
fi

# Block dangerous patterns specific to depictio
BLOCKED_PATTERNS=(
    "docker.*rm.*-f"
    "docker.*system.*prune"
    "docker.*volume.*rm"
    "mongosh.*drop"
    "mongo.*drop"
    "rm.*-rf.*/depictio"
    "rm.*-rf.*/workspace"
    "git.*push.*--force.*main"
    "git.*push.*--force.*master"
    "git.*reset.*--hard.*origin"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qE "$pattern"; then
        echo '{"decision": "block", "reason": "Blocked dangerous command pattern: '"$pattern"'. This command could cause data loss."}'
        exit 0
    fi
done

# Warn about certain commands but allow them
WARN_PATTERNS=(
    "docker compose"
    "git push"
    "git rebase"
    "git reset"
)

for pattern in "${WARN_PATTERNS[@]}"; do
    if echo "$COMMAND" | grep -qE "$pattern"; then
        # Allow but could log if needed
        break
    fi
done

# Approve the command
echo '{"decision": "approve"}'
exit 0
