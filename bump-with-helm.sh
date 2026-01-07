#!/bin/bash
# bump-with-helm.sh
export SKIP=trailing-whitespace,ty-check-models-api-dash-cli

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
    bump2version --allow-dirty "$@"
else
    bump2version "$@"
fi

# Skip helm and git operations if dry run
if [[ "$DRY_RUN" == "true" ]]; then
    echo "Dry run: Skipping helm chart update and git operations"
    exit 0
fi

# Update helm chart version with date and quotes
sed -i '' 's/^version: .*/version: "'"$(date +%Y%m%d)"'.1"/' helm-charts/depictio/Chart.yaml

# Add and amend commit if bump2version created one
if git log -1 --pretty=%B | grep -q "Bump version"; then
    git add helm-charts/depictio/Chart.yaml
    git commit --amend --no-edit
    # git push && git push --tags
fi
