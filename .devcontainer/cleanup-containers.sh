#!/bin/bash

# Cleanup script for dead/exited devcontainers
# Run this to clean up stopped containers and free up disk space
#
# Usage:
#   ./cleanup-containers.sh           # Safe cleanup (containers + networks only)
#   ./cleanup-containers.sh --deep    # Also remove dangling images (slower rebuilds)
#   ./cleanup-containers.sh --volumes # Also remove unused volumes (DANGEROUS!)

CLEAN_IMAGES=false
CLEAN_VOLUMES=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --deep)
            CLEAN_IMAGES=true
            shift
            ;;
        --volumes)
            CLEAN_VOLUMES=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  (none)      Safe cleanup: exited containers + unused networks only"
            echo "  --deep      Also remove dangling images (may slow down rebuilds)"
            echo "  --volumes   Also remove unused volumes (DANGER: removes AI credentials!)"
            echo "  --help      Show this help message"
            exit 0
            ;;
    esac
done

echo "🧹 Cleaning up Docker resources..."
echo ""

# Always remove exited containers (safe)
echo "✓ Removing exited containers..."
docker container prune -f

# Always remove unused networks (safe)
echo "✓ Removing unused networks..."
docker network prune -f

# Optional: Remove dangling images
if [ "$CLEAN_IMAGES" = true ]; then
    echo "⚠️  Removing dangling images (may slow down next rebuild)..."
    docker image prune -f
else
    echo "⊘ Skipping image cleanup (use --deep to remove dangling images)"
fi

# Optional: Remove unused volumes (DANGEROUS!)
if [ "$CLEAN_VOLUMES" = true ]; then
    echo "⚠️⚠️⚠️  REMOVING UNUSED VOLUMES (this will delete Claude Code credentials!)..."
    echo "Press Ctrl+C within 5 seconds to cancel..."
    sleep 5
    docker volume prune -f
else
    echo "⊘ Skipping volume cleanup (use --volumes to remove, but will delete credentials!)"
fi

# Show disk usage
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Current Docker disk usage:"
docker system df
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "💡 Tips:"
echo "   • Use --deep to also remove dangling images (slower rebuilds)"
echo "   • Use --volumes to remove ALL unused volumes (loses credentials!)"
echo "   • Run 'docker system df' to check disk usage anytime"
