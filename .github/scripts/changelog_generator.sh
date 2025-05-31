#!/bin/bash
# changelog_generator.sh - Generate changelog with PR references and commit hashes

# Get range (can be tag, commit, or branch names)
PREVIOUS_TAG=${1:-$(git describe --tags --abbrev=0 HEAD^ 2>/dev/null || echo "")}
CURRENT_REF=${2:-HEAD}
CURRENT_VERSION=${CURRENT_REF#v}

echo "Generating changelog from $PREVIOUS_TAG to $CURRENT_REF"

# Start with Docker Images section
echo "## Docker Images"
echo "\`\`\`"
echo "ghcr.io/depictio/depictio:$CURRENT_VERSION"
echo "ghcr.io/depictio/depictio:latest"
echo "ghcr.io/depictio/depictio:stable"
echo "ghcr.io/depictio/depictio:edge"
echo "\`\`\`"
echo ""

if [ -z "$PREVIOUS_TAG" ]; then
  # If there's no previous tag, use all commits
  COMMITS=$(git log --pretty=format:"* %s [%h]" $CURRENT_REF | grep -v "Merge" | sed '/^$/d')
else
  # Use changes between previous tag and current reference
  COMMITS=$(git log --pretty=format:"* %s [%h]" $PREVIOUS_TAG..$CURRENT_REF | grep -v "Merge" | sed '/^$/d')
fi

# Extract PR numbers and add links
CHANGELOG=$(echo "$COMMITS" | sed -E 's/\(#([0-9]+)\)/([#\1](https:\/\/github.com\/'"${GITHUB_REPOSITORY:-username\/repo}"'\/pull\/\1))/g')

echo "## Changes"
echo ""

# Features
FEATURES=$(echo "$CHANGELOG" | grep -i "feat\|feature\|add" || echo "")
if [ ! -z "$FEATURES" ]; then
  echo "### New Features"
  echo ""
  echo "$FEATURES"
  echo ""
fi

# Bug fixes
FIXES=$(echo "$CHANGELOG" | grep -i "fix\|bug\|issue" || echo "")
if [ ! -z "$FIXES" ]; then
  echo "### Bug Fixes"
  echo ""
  echo "$FIXES"
  echo ""
fi

# Improvements
IMPROVEMENTS=$(echo "$CHANGELOG" | grep -i "improve\|update\|enhance\|refactor" || echo "")
if [ ! -z "$IMPROVEMENTS" ]; then
  echo "### Improvements"
  echo ""
  echo "$IMPROVEMENTS"
  echo ""
fi

# Breaking changes - look in commit bodies
BREAKING=$(git log --pretty=format:"%b" $PREVIOUS_TAG..$CURRENT_REF | grep -i "BREAKING CHANGE:" || echo "")
if [ ! -z "$BREAKING" ]; then
  echo "### Breaking Changes"
  echo ""
  echo "$BREAKING"
  echo ""
fi

# Other changes
OTHER=$(echo "$CHANGELOG" | grep -v -i "feat\|feature\|add\|fix\|bug\|issue\|improve\|update\|enhance\|refactor" || echo "")
if [ ! -z "$OTHER" ]; then
  echo "### Other Changes"
  echo ""
  echo "$OTHER"
  echo ""
fi

echo ""
echo "## Documentation"
echo "Full documentation: https://depictio.github.io/depictio-docs/"
