#!/bin/bash

# Create required directories with proper permissions
mkdir -p depictioDB/ && chmod -R 777 depictioDB/
mkdir -p minio_data/ && chmod -R 775 minio_data/
mkdir -p depictio/keys/ && chown -R vscode:docker depictio/keys/ && chmod -R 775 depictio/keys/
mkdir -p depictio/.depictio/ && chown -R vscode:docker depictio/.depictio/ && chmod -R 775 depictio/.depictio/

# Set environment variables
echo 'MINIO_ROOT_USER=minio' >> ~/.bashrc
echo 'MINIO_ROOT_PASSWORD=minio123' >> ~/.bashrc
echo 'DEPICTIO_BACKEND_DATA_VOLUME_HOST=/workspace/depictio-data' >> ~/.bashrc

# Source updated bashrc
source ~/.bashrc
