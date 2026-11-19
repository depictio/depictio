#!/bin/bash
# PreToolUse hook (matcher: Bash) for depictio.
#
# Claude Code passes one JSON document on stdin: {"tool_input": {"command": "..."}}.
# Exit 0 approves; exit 2 blocks the command and shows stderr to Claude.
#
# Fail closed: if jq is missing or the payload is not the expected JSON, the raw
# payload is scanned instead, so a dangerous command is never approved only
# because it could not be parsed.

PAYLOAD=$(cat)

COMMAND=""
if command -v jq >/dev/null 2>&1; then
    COMMAND=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // empty' 2>/dev/null)
fi
if [[ -z "$COMMAND" ]]; then
    COMMAND="$PAYLOAD"
fi

# Nothing to check (empty stdin).
if [[ -z "$COMMAND" ]]; then
    exit 0
fi

# Dangerous patterns specific to depictio (extended regex).
# The two rm patterns match the repo or workspace root as the last path component,
# not any path that merely contains the name (a worktree is routinely removed).
BLOCKED_PATTERNS=(
    "docker.*rm.*-f"
    "docker.*system.*prune"
    "docker.*volume.*rm"
    "mongosh.*drop"
    "mongo.*drop"
    "rm +-[a-zA-Z]+ +[^ ]*/depictio/?( |$)"
    "rm +-[a-zA-Z]+ +[^ ]*/(workspace|workspaces|depictio-workspace)/?( |$)"
    "git.*push.*--force.*main"
    "git.*push.*--force.*master"
    "git.*reset.*--hard.*origin"
)

for pattern in "${BLOCKED_PATTERNS[@]}"; do
    if printf '%s' "$COMMAND" | grep -qE -- "$pattern"; then
        echo "Blocked dangerous command pattern: $pattern. This command could cause data loss." >&2
        exit 2
    fi
done

exit 0
