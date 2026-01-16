#!/bin/bash
# Environment setup script for depictio
# This is sourced when activating the pixi environment

# Set PYTHONPATH to include the project root
export PYTHONPATH="${PIXI_PROJECT_ROOT:-$(pwd)}:${PYTHONPATH}"

# Set playwright browser path (optional - uses default if not set)
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"

# Check if playwright browsers are installed
if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH/chromium-"* ] 2>/dev/null; then
    echo "Note: Playwright browsers not installed. Run 'pixi run install-browsers' to install."
fi

# Default environment variables for local development
export DEPICTIO_CONTEXT="${DEPICTIO_CONTEXT:-dash}"
export DEPICTIO_DEV_MODE="${DEPICTIO_DEV_MODE:-true}"
export DEPICTIO_LOGGING_VERBOSITY_LEVEL="${DEPICTIO_LOGGING_VERBOSITY_LEVEL:-DEBUG}"
