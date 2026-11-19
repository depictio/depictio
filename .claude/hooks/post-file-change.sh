#!/bin/bash
# PostToolUse hook (matcher: Write|Edit) for depictio.
#
# Claude Code passes one JSON document on stdin: {"tool_input": {"file_path": "..."}}.
# After a Python file under depictio/ is written or edited, run a quick ruff check on
# that file and hand any findings back to Claude as additional context. Never blocks.

PAYLOAD=$(cat)

command -v jq >/dev/null 2>&1 || exit 0
command -v ruff >/dev/null 2>&1 || exit 0

FILE_PATH=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

if [[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# Only Python files of the packages that exist.
if [[ ! "$FILE_PATH" =~ depictio/(models|api|cli|tests|catalog|project_builder|dev_scripts)/.*\.py$ ]]; then
    exit 0
fi

MESSAGES=()

if ! ruff format --check "$FILE_PATH" >/dev/null 2>&1; then
    MESSAGES+=("Format issues in $FILE_PATH: run 'ruff format $FILE_PATH'.")
fi

if ! ruff check "$FILE_PATH" >/dev/null 2>&1; then
    MESSAGES+=("Lint issues in $FILE_PATH: run 'ruff check --fix $FILE_PATH'.")
fi

if [[ ${#MESSAGES[@]} -gt 0 ]]; then
    jq -n --arg msg "$(printf '%s\n' "${MESSAGES[@]}")" \
        '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $msg}}'
fi

exit 0
