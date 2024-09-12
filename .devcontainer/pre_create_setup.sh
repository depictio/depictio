#!/bin/bash

# Create required directories with proper permissions
mkdir -p depictio-data/ && chmod -R 777 depictio-data/
mkdir -p depictioDB/ && chmod -R 777 depictioDB/
mkdir -p minio_data/ && chmod -R 775 minio_data/
mkdir -p depictio/keys/ && chmod -R 775 depictio/keys/
mkdir -p depictio/.depictio/ && chmod -R 775 depictio/.depictio/

# Set environment variables
# echo 'MINIO_ROOT_USER=minio' >> ~/.bashrc
# echo 'MINIO_ROOT_PASSWORD=minio123' >> ~/.bashrc
if [ $(grep DEPICTIO_BACKEND_DATA_VOLUME_HOST .env) ]; then
    echo "Reusing existing variable for backend data volume..."; 
else
    echo DEPICTIO_BACKEND_DATA_VOLUME_HOST='/app/depictio-data' >> .env
fi

# # Source updated bashrc
# source ~/.bashrc