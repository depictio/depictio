#!/bin/bash
# Configure MongoDB and Redis VSCode extensions with allocated ports

# Load instance configuration
if [ -f .env.instance ]; then
    # shellcheck disable=SC1091
    source .env.instance
else
    echo "⚠️  No .env.instance found, using default ports"
    MONGO_PORT=27018
    REDIS_PORT=6379
    COMPOSE_PROJECT_NAME="depictio"
fi

# VSCode settings file location
SETTINGS_FILE="/home/vscode/.vscode-server/data/Machine/settings.json"
SETTINGS_DIR="$(dirname "$SETTINGS_FILE")"

# Create settings directory if it doesn't exist
mkdir -p "$SETTINGS_DIR"

# MongoDB connection string
MONGODB_CONNECTION="mongodb://localhost:${MONGO_PORT}/depictioDB"

# Redis connection details
REDIS_HOST="localhost"

# Create settings with database connections
cat > "$SETTINGS_FILE" <<EOF
{
  "mongodb.connections": [
    {
      "id": "depictio-${COMPOSE_PROJECT_NAME}",
      "name": "Depictio (${COMPOSE_PROJECT_NAME})",
      "connectionString": "${MONGODB_CONNECTION}",
      "defaultDatabase": "depictioDB"
    }
  ],
  "redis-client.connections": [
    {
      "name": "Depictio Redis (${COMPOSE_PROJECT_NAME})",
      "host": "${REDIS_HOST}",
      "port": ${REDIS_PORT},
      "db": 0
    }
  ]
}
EOF

echo "🗄️  Configured database extensions:"
echo "   MongoDB: localhost:${MONGO_PORT}/depictioDB"
echo "   Redis:   localhost:${REDIS_PORT}"
