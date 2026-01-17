#!/bin/bash
# Print the dynamically allocated ports for this instance

if [ -f /workspace/.env.instance ]; then
    source /workspace/.env.instance
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 YOUR CODESPACES PORTS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Add these ports in the VS Code Ports panel:"
echo ""
echo "  📊 Dash Frontend:    ${DASH_PORT:-5080}"
echo "  🔌 FastAPI Backend:  ${FASTAPI_PORT:-8058}"
echo "  📦 MinIO Console:    ${MINIO_CONSOLE_PORT:-9001}"
echo ""
echo "Then click the globe 🌐 icon to open in browser."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
