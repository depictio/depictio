#!/bin/bash

WORKSPACE_URL=${GITPOD_WORKSPACE_URL#https://}
WORKSPACE_ID=$(echo "$GITPOD_WORKSPACE_URL" | cut -d'-' -f2- | cut -d'.' -f1)
MINIO_PASSWORD=$(openssl rand -base64 32)

cat >.env <<EOF
# GitPod Dynamic Configuration

## MinIO Configuration
DEPICTIO_MINIO_ROOT_USER=${WORKSPACE_ID}
DEPICTIO_MINIO_ROOT_PASSWORD=${MINIO_PASSWORD}
DEPICTIO_MINIO_PUBLIC_URL=https://9000-${WORKSPACE_URL}

## FastAPI Configuration
DEPICTIO_FASTAPI_PUBLIC_URL=https://8058-${WORKSPACE_URL}
EOF

echo "Created .env with GitPod configuration"
