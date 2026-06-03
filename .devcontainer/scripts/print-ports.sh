#!/bin/bash
# Print the dynamically allocated ports for this instance

if [ -f /workspace/.env.instance ]; then
    # shellcheck source=/dev/null
    source /workspace/.env.instance
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 YOUR CODESPACES PORTS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Add these ports in the VS Code Ports panel:"
echo ""
echo "  ⚡ Viewer (Vite HMR): ${VIEWER_DEV_PORT:-5173}"
echo "  🔌 FastAPI Backend:  ${FASTAPI_PORT:-8058}"
echo "  📦 MinIO Console:    ${MINIO_CONSOLE_PORT:-9001}"
echo ""
echo "Then click the globe 🌐 icon to open in browser."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
