#!/bin/bash
# bump-with-helm.sh
export SKIP=trailing-whitespace,ty-check-models-api-cli

# Parse arguments for dry-run flag
DRY_RUN=false
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=true
        break
    fi
done

# Check if git is clean, if not add --allow-dirty
if ! git diff-index --quiet HEAD --; then
    uv run bump2version --allow-dirty "$@"
else
    uv run bump2version "$@"
fi

# Skip helm and git operations if dry run
if [[ "$DRY_RUN" == "true" ]]; then
    echo "Dry run: Skipping helm chart update and git operations"
    exit 0
fi

# Update helm chart version with date and quotes
sed -i '' 's/^version: .*/version: "'"$(date +%Y%m%d)"'.1"/' helm-charts/depictio/Chart.yaml

# Ensure uv.lock is up to date after pyproject.toml changes
uv lock

NEW_VERSION=$(cat VERSION)

# Pin the public docker-compose.yaml to the released version on STABLE releases
# only, so a fresh `docker compose up -d` (no .env) pulls the exact release.
# Betas intentionally keep the previous stable pin — the quick start stays on
# stable while beta images are published under their own version tags.
PIN_COMPOSE=false
if [[ "$NEW_VERSION" != *-b* ]]; then
    sed -i '' -E "s#(ghcr\.io/depictio/depictio-[a-z]+:\\\$\{DEPICTIO_VERSION:-)[^}]*(\})#\1${NEW_VERSION}\2#g" docker-compose.yaml
    PIN_COMPOSE=true
fi

# Add and amend commit if bump2version created one
if git log -1 --pretty=%B | grep -q "Bump version"; then
    git add helm-charts/depictio/Chart.yaml uv.lock
    [[ "$PIN_COMPOSE" == "true" ]] && git add docker-compose.yaml
    git commit --amend --no-edit
    # git push && git push --tags
fi

# Move the 'stable' tag for non-beta releases
if [[ "$NEW_VERSION" != *-b* ]]; then
    echo "Stable release detected (v${NEW_VERSION}) — moving 'stable' tag"
    git tag -f stable "v${NEW_VERSION}"
    echo "Remember to push with: git push origin refs/tags/stable --force"
fi
