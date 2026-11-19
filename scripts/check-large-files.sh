#!/usr/bin/env bash
# Reject added or modified files over 500 KB, unless .large-files-allowlist covers them.
#
# Git keeps every version of every file forever: a 5 MB table or a regenerated PNG that
# is committed once stays in every clone, even after the file is deleted. That is how
# this repository reached 350 MB. Large example data belongs behind fixtures.lock
# (scripts/fetch_fixtures.py), not in git.
#
# Usage:
#   scripts/check-large-files.sh               # staged changes (pre-commit hook)
#   scripts/check-large-files.sh --base REF    # commits since REF (CI, pull requests)
#
# LARGE_FILE_LIMIT overrides the limit in bytes (default 512000).
# Allowlist: one glob per line, '#' comments; '*' also matches '/'.
set -euo pipefail

LIMIT="${LARGE_FILE_LIMIT:-512000}"
ROOT="$(git rev-parse --show-toplevel)"
ALLOWLIST="$ROOT/.large-files-allowlist"

base=""
if [ "${1:-}" = "--base" ]; then
    base="${2:?--base needs a ref}"
fi

patterns=()
if [ -f "$ALLOWLIST" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%%#*}"
        line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
        [ -n "$line" ] && patterns+=("$line")
    done <"$ALLOWLIST"
fi

is_allowed() {
    local file="$1" pattern
    for pattern in "${patterns[@]+"${patterns[@]}"}"; do
        # shellcheck disable=SC2053  # the pattern is meant to be a glob
        if [[ "$file" == $pattern ]]; then
            return 0
        fi
    done
    return 1
}

if [ -n "$base" ]; then
    list_cmd=(git diff --name-only -z --diff-filter=AM "$base"...HEAD)
    blob_ref() { printf 'HEAD:%s' "$1"; }
else
    list_cmd=(git diff --cached --name-only -z --diff-filter=AM)
    blob_ref() { printf ':%s' "$1"; }
fi

offenders=()
while IFS= read -r -d '' file; do
    size="$(git cat-file -s "$(blob_ref "$file")" 2>/dev/null || echo 0)"
    if [ "$size" -gt "$LIMIT" ] && ! is_allowed "$file"; then
        offenders+=("$(printf '%8d KB  %s' "$((size / 1000))" "$file")")
    fi
done < <("${list_cmd[@]}")

if [ "${#offenders[@]}" -eq 0 ]; then
    exit 0
fi

echo "Blocked: file(s) over $((LIMIT / 1000)) KB that are not in .large-files-allowlist:"
echo
printf '  %s\n' "${offenders[@]}"
echo
echo "Large example data does not belong in git (every version stays in every clone)."
echo "Options: shrink it (images: magick -colors 128 ...), subsample it, or publish it as"
echo "a release asset and list it in fixtures.lock (scripts/fetch_fixtures.py)."
echo "If it really has to be tracked, add a pattern to .large-files-allowlist."
exit 1
