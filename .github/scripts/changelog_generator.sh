#!/bin/bash
# changelog_generator.sh - Generate changelog with PR references and commit hashes

# Removed the initial "---" from here. It will now be handled by the wrapper.
# echo "" # Add an extra blank line before the version header for spacing

# Get range (can be tag, commit, or branch names)
PREVIOUS_TAG=${1:-""}
CURRENT_REF=${2:-HEAD}

# If no previous tag provided, try to find the last release tag (excluding current)
if [ -z "$PREVIOUS_TAG" ] && [ "$CURRENT_REF" != "HEAD" ]; then
  PREVIOUS_TAG=$(git tag -l --sort=-version:refname | grep -v "^${CURRENT_REF}$" | head -1)
fi

# Final fallback to git describe if still no tag found
if [ -z "$PREVIOUS_TAG" ]; then
  PREVIOUS_TAG=$(git describe --tags --abbrev=0 HEAD^ 2>/dev/null || echo "")
fi
CURRENT_VERSION=${CURRENT_REF#v}

# echo "## $CURRENT_VERSION" # Version header
# echo "" # Add a blank line after the main version header

# Start with Docker Images section
echo "### Docker Images 🐳"
echo "" # Add a blank line after the sub-header
echo "\`\`\`plaintext"
echo "ghcr.io/depictio/depictio:$CURRENT_VERSION"
echo "ghcr.io/depictio/depictio:latest"
echo "ghcr.io/depictio/depictio:stable"
echo "ghcr.io/depictio/depictio:edge"
echo "\`\`\`"
echo "" # Ensure a blank line after the code block

if [ -z "$PREVIOUS_TAG" ]; then
  COMMITS=$(git log --pretty=format:"* %s [%h]" "$CURRENT_REF" | grep -v "Merge" | sed '/^$/d')
else
  COMMITS=$(git log --pretty=format:"* %s [%h]" "$PREVIOUS_TAG".."$CURRENT_REF" | grep -v "Merge" | sed '/^$/d')
fi

# Extract PR numbers and add links
CHANGELOG=$(echo "$COMMITS" | sed -E 's|\(#([0-9]+)\)|([#\1](https://github.com/'"${GITHUB_REPOSITORY:-username/repo}"'/pull/\1))|g')


echo -e "\n<details>\n<summary>Click to expand the changelog for $CURRENT_VERSION</summary>\n" # Start details section with a summary

echo "### Changes 📜"
echo "" # Add a blank line after the sub-header

# Features
FEATURES=$(echo "$CHANGELOG" | grep -E "^\\* (feat|feature|add):" || echo "")
if [ -n "$FEATURES" ]; then
  echo "#### New Features ✨"
  echo "" # Add a blank line after the sub-sub-header
  echo "$FEATURES"
  echo "" # Add a blank line after the list
fi

# Bug fixes
FIXES=$(echo "$CHANGELOG" | grep -E "^\\* (fix|bug|issue):" || echo "")
if [ -n "$FIXES" ]; then
  echo "#### Bug Fixes 🐛"
  echo "" # Add a blank line after the sub-sub-header
  echo "$FIXES"
  echo "" # Add a blank line after the list
fi

# Improvements
IMPROVEMENTS=$(echo "$CHANGELOG" | grep -E "^\\* (refactor|perf|style|improve|update|enhance):" || echo "")
if [ -n "$IMPROVEMENTS" ]; then
  echo "#### Improvements 🚀"
  echo "" # Add a blank line after the sub-sub-header
  echo "$IMPROVEMENTS"
  echo "" # Add a blank line after the list
fi

# Breaking changes - look in commit bodies
BREAKING=$(git log --pretty=format:"%b" "$PREVIOUS_TAG".."$CURRENT_REF" | grep -i "BREAKING CHANGE:" || echo "")
if [ -n "$BREAKING" ]; then
  echo "#### Breaking Changes ⚠️"
  echo "" # Add a blank line after the sub-sub-header
  echo "$BREAKING"
  echo "" # Add a blank line after the list
fi

# Chores
CHORES=$(echo "$CHANGELOG" | grep -E "^\\* (chore|build|ci):" || echo "")
if [ -n "$CHORES" ]; then
  echo "#### Chores 🧹"
  echo "" # Add a blank line after the sub-sub-header
  echo "$CHORES"
  echo "" # Add a blank line after the list
fi

# Documentation (separate section based on commit type 'docs:')
DOCS_COMMITS=$(echo "$CHANGELOG" | grep -E "^\\* (docs):" || echo "")
if [ -n "$DOCS_COMMITS" ]; then
  echo "#### Documentation Updates 📚"
  echo "" # Add a blank line after the sub-sub-header
  echo "$DOCS_COMMITS"
  echo "" # Add a blank line after the list
fi

# Other changes
OTHER=$(echo "$CHANGELOG" | grep -v -E "^\\* (feat|feature|add|fix|bug|issue|refactor|perf|style|improve|update|enhance|chore|build|ci|docs):" || echo "")
if [ -n "$OTHER" ]; then
  echo "#### Other Changes 📝"
  echo "" # Add a blank line after the sub-sub-header
  echo "$OTHER"
  echo "" # Add a blank line after the list
fi

# echo "---" # End of changelog section

echo -e "\n</details>\n" # Close the details section with a blank line before it

# Documentation section
echo "### Documentation 📖"
echo "" # Add a blank line after the sub-header
echo "For more details, please refer to the [documentation](https://depictio.github.io/depictio-docs/)"
