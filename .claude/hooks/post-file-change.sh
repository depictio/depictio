#!/bin/bash
# Post-file-change hook for depictio
# Runs after Write/Edit operations on Python files
# Environment variables available:
#   TOOL_INPUT - JSON with tool parameters
#   TOOL_OUTPUT - JSON with tool result

set -e

# Parse the file path from tool input
FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // empty')

# Exit if no file path or not a Python file
if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Only process files in depictio/ directory
if [[ ! "$FILE_PATH" =~ ^.*depictio/(models|api|dash|cli|tests)/.*.py$ ]]; then
    exit 0
fi

# Check if the file exists (Write creates, Edit modifies)
if [[ ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# Run quick format check on the specific file
MESSAGES=()

# Check with ruff format (dry-run)
if command -v ruff &> /dev/null; then
    if ! ruff format --check "$FILE_PATH" 2>/dev/null; then
        MESSAGES+=("Format issues detected in $FILE_PATH - consider running 'ruff format $FILE_PATH'")
    fi
fi

# Check with ruff lint (quick check)
if command -v ruff &> /dev/null; then
    LINT_OUTPUT=$(ruff check "$FILE_PATH" 2>&1 || true)
    if [[ -n "$LINT_OUTPUT" && "$LINT_OUTPUT" != *"All checks passed"* ]]; then
        ERROR_COUNT=$(echo "$LINT_OUTPUT" | grep -c "error\|warning" || echo "0")
        if [[ "$ERROR_COUNT" -gt 0 ]]; then
            MESSAGES+=("Lint issues found in $FILE_PATH ($ERROR_COUNT issues) - run 'ruff check --fix $FILE_PATH'")
        fi
    fi
fi

# Output messages if any
if [[ ${#MESSAGES[@]} -gt 0 ]]; then
    echo '{"stdout": "'"$(printf '%s\n' "${MESSAGES[@]}" | jq -Rs .)"'"}'
fi

exit 0
