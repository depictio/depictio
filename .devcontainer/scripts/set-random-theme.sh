#!/bin/bash
# Set a random VSCode theme for each devcontainer instance

# Curated list of popular dark themes
THEMES=(
    "Default Dark Modern"
    "Monokai"
    "Solarized Dark"
    "GitHub Dark"
    "One Dark Pro"
    "Dracula"
    "Nord"
    "Atom One Dark"
    "Tokyo Night"
    "Ayu Dark"
)

# Select random theme
RANDOM_THEME="${THEMES[$RANDOM % ${#THEMES[@]}]}"

# VSCode settings file location
SETTINGS_FILE="/home/vscode/.vscode-server/data/Machine/settings.json"
SETTINGS_DIR="$(dirname "$SETTINGS_FILE")"

# Create settings directory if it doesn't exist
mkdir -p "$SETTINGS_DIR"

# Create or update settings.json with the random theme
if [ -f "$SETTINGS_FILE" ]; then
    # File exists, update the theme
    if command -v jq &> /dev/null; then
        jq --arg theme "$RANDOM_THEME" '.["workbench.colorTheme"] = $theme' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp" && mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    else
        # Fallback if jq not available
        echo "{\"workbench.colorTheme\": \"$RANDOM_THEME\"}" > "$SETTINGS_FILE"
    fi
else
    # Create new settings file
    echo "{\"workbench.colorTheme\": \"$RANDOM_THEME\"}" > "$SETTINGS_FILE"
fi

echo "🎨 Set random theme: $RANDOM_THEME"
