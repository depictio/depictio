#!/bin/bash
# On-stop summary hook for depictio
# Runs when Claude Code session ends
# Provides a summary of changes made

set -e

# Get git status summary
GIT_STATUS=""
if git rev-parse --is-inside-work-tree &>/dev/null; then
    STAGED=$(git diff --cached --stat 2>/dev/null | tail -1 || echo "")
    UNSTAGED=$(git diff --stat 2>/dev/null | tail -1 || echo "")
    UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')

    if [[ -n "$STAGED" || -n "$UNSTAGED" || "$UNTRACKED" -gt 0 ]]; then
        GIT_STATUS="Git changes: "
        [[ -n "$STAGED" ]] && GIT_STATUS+="Staged: $STAGED. "
        [[ -n "$UNSTAGED" ]] && GIT_STATUS+="Unstaged: $UNSTAGED. "
        [[ "$UNTRACKED" -gt 0 ]] && GIT_STATUS+="Untracked files: $UNTRACKED. "
    fi
fi

# Check for any linting issues in recently modified files
LINT_STATUS=""
MODIFIED_PY_FILES=$(git diff --name-only --diff-filter=AM 2>/dev/null | grep -E '\.py$' || true)
if [[ -n "$MODIFIED_PY_FILES" ]] && command -v ruff &>/dev/null; then
    LINT_COUNT=$(echo "$MODIFIED_PY_FILES" | xargs ruff check 2>&1 | grep -c "error\|warning" || echo "0")
    if [[ "$LINT_COUNT" -gt 0 ]]; then
        LINT_STATUS="Warning: $LINT_COUNT lint issues in modified files. Run 'pre-commit run --all-files' before committing."
    fi
fi

# Combine messages
MESSAGE=""
[[ -n "$GIT_STATUS" ]] && MESSAGE+="$GIT_STATUS"
[[ -n "$LINT_STATUS" ]] && MESSAGE+=" $LINT_STATUS"

if [[ -n "$MESSAGE" ]]; then
    echo '{"stdout": "Session summary: '"$MESSAGE"'"}'
fi

exit 0
