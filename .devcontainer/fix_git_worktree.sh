#!/bin/bash
# Fix git configuration for worktree environments
set -e

echo "🔧 Configuring git for devcontainer..."

# Add workspace to git safe directories
git config --global --add safe.directory /workspace 2>/dev/null || true

# Check if this is a worktree (has .git file with gitdir: reference)
if [ -f /workspace/.git ] && grep -q "gitdir:" /workspace/.git 2>/dev/null; then
    echo "📦 Worktree detected"

    # VS Code DevContainers automatically mounts the main repo with --mount-workspace-git-root
    # It should be available somewhere, let's find it
    MAIN_GIT_DIRS=(
        "/workspaces/depictio/.git"
        "/workspace-root/.git"
        "$(dirname "$(dirname /workspace)")/.git"
    )

    MAIN_GIT_DIR=""
    for dir in "${MAIN_GIT_DIRS[@]}"; do
        if [ -d "$dir" ]; then
            MAIN_GIT_DIR="$dir"
            echo "✅ Found main repo git directory: $MAIN_GIT_DIR"
            break
        fi
    done

    if [ -n "$MAIN_GIT_DIR" ]; then
        # Extract worktree name from the original .git file
        WORKTREE_NAME=$(basename "$(grep 'gitdir:' /workspace/.git 2>/dev/null | cut -d' ' -f2)")

        if [ -n "$WORKTREE_NAME" ]; then
            # Add main repo to safe directories
            git config --global --add safe.directory "$(dirname "$MAIN_GIT_DIR")" 2>/dev/null || true

            # Fix .git file to point to mounted location
            echo "gitdir: ${MAIN_GIT_DIR}/worktrees/${WORKTREE_NAME}" > /workspace/.git

            echo "✅ Git configured for worktree: ${WORKTREE_NAME}"
        else
            echo "⚠️  Could not extract worktree name"
        fi
    else
        echo "⚠️  Warning: Main repo .git not found - git operations may be limited"
        echo "   Worktrees need access to main repo's .git directory"
    fi
elif [ -d /workspace/.git ]; then
    # Regular repo with .git directory
    echo "📁 Main repository detected - git ready"
else
    echo "⚠️  No .git found at /workspace"
fi

echo "✅ Git configuration complete"
