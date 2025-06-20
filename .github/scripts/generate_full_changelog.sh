#!/bin/bash

# Configuration
CHANGELOG_SCRIPT=".github/scripts/changelog_generator.sh" # Path to your changelog_generator.sh script
OUTPUT_FILE="CHANGELOG.md"                  # The file to write the full changelog to

echo "---"
echo "Starting full changelog generation (latest version first)..."
echo "Output will be written to: $OUTPUT_FILE"
echo "---"

# Clear the existing output file
echo "Clearing previous output file..."
cp "$OUTPUT_FILE" "$OUTPUT_FILE.bak" # Backup the existing file
echo "Output file cleared."

echo "---"
echo "Fetching and filtering plain tags..."
# Get all plain version tags, sorted semantically
PLAIN_TAGS=$(git tag --sort=version:refname | tr -d '\r' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V)
echo "Found plain tags: '$PLAIN_TAGS'"
echo "---"

# Convert tags to an array
TAG_ARRAY=()
while IFS= read -r line; do
    TAG_ARRAY+=("$line")
done <<< "$PLAIN_TAGS"

echo "Parsed tags into array. Total tags found: ${#TAG_ARRAY[@]}"

# --- Generate changelogs from LATEST to OLDEST ---
if [ ${#TAG_ARRAY[@]} -gt 0 ]; then
    # Loop from the last tag down to the second tag (to compare with the one before it)
    for (( i=${#TAG_ARRAY[@]}-1; i>0; i-- )); do
        CURRENT_REF="${TAG_ARRAY[i]}"
        PREVIOUS_TAG="${TAG_ARRAY[i-1]}"

        echo "---"
        echo "Generating changelog for version increment: '$PREVIOUS_TAG' to '$CURRENT_REF' (LATEST: $CURRENT_REF)..."

        "$CHANGELOG_SCRIPT" "$PREVIOUS_TAG" "$CURRENT_REF" >> "$OUTPUT_FILE"
        # echo -e "\n---\n" >> "$OUTPUT_FILE" # Add a separator for clarity between versions
        echo "Changelog for '$CURRENT_REF' completed."
    done

    # Handle the very first version's changes (from initial commit up to the first tag)
    FIRST_TAG="${TAG_ARRAY[0]}"
    echo "---"
    echo "Processing initial release / changes before the first tag: '$FIRST_TAG'..."

    FIRST_TAG_COMMIT=$(git rev-list -n 1 "$FIRST_TAG")
    PRE_FIRST_TAG_REF=""
    if [ -n "$FIRST_TAG_COMMIT" ]; then
        PRE_FIRST_TAG_REF=$(git rev-parse "${FIRST_TAG_COMMIT}~1" 2>/dev/null || echo "")
    fi

    if [ -n "$PRE_FIRST_TAG_REF" ]; then
        echo "Detected a commit before the first tag: '$PRE_FIRST_TAG_REF'"
        echo "## Changes before $FIRST_TAG" >> "$OUTPUT_FILE"
        echo "Running changelog_generator.sh for '$PRE_FIRST_TAG_REF' to '$FIRST_TAG'..."
        "$CHANGELOG_SCRIPT" "$PRE_FIRST_TAG_REF" "$FIRST_TAG" >> "$OUTPUT_FILE"
        # echo -e "\n---\n" >> "$OUTPUT_FILE" # Separator
        echo "Initial release changelog section completed."
    else
        echo "No commit detected before '$FIRST_TAG' (it might be the initial commit)."
        echo "## Initial Release: $FIRST_TAG" >> "$OUTPUT_FILE"
        echo "Running changelog_generator.sh for all commits up to '$FIRST_TAG' (no previous tag specified)..."
        "$CHANGELOG_SCRIPT" "" "$FIRST_TAG" >> "$OUTPUT_FILE"
        # echo -e "\n---\n" >> "$OUTPUT_FILE" # Separator
        echo "Initial release changelog section completed."
    fi
    echo "---"
else
    echo "---"
    echo "No plain tags found. Exiting."
    echo "---"
    exit 0 # Exit if no tags are found
fi

echo "---"
echo "All changelog sections generated."
echo "Complete changelog saved to: $OUTPUT_FILE"
echo "---"
echo "Script finished successfully."
