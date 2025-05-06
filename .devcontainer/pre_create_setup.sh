#!/bin/zsh

# This script is run before the container is created.
git submodule update --init --recursive

# Create required directories with proper permissions
rm -rdf minio_data/
rm -rdf depictio-cli/
rm -rdf depictio-example-data && mkdir -p depictio-example-data/ && chmod -R 777 depictio-example-data/
rm -rdf depictioDB/ && mkdir -p depictioDB/ && chmod -R 777 depictioDB/
rm -rdf minio_data/ && mkdir -p minio_data/ && chmod -R 775 minio_data/
rm -rdf depictio/keys && mkdir -p depictio/keys/ && chmod -R 775 depictio/keys/
rm -rdf depictio/.depictio/ && mkdir -p depictio/.depictio/ && chmod -R 775 depictio/.depictio/

# Set environment variables
# echo 'MINIO_ROOT_USER=minio' >> ~/.bashrc
# echo 'MINIO_ROOT_PASSWORD=minio123' >> ~/.bashrc
if [ $(grep DEPICTIO_BACKEND_EXAMPLE_DATA_VOLUME_HOST .env) ]; then
    echo "Reusing existing variable for backend data volume..."; 
else
    echo DEPICTIO_BACKEND_EXAMPLE_DATA_VOLUME_HOST='/app/depictio-example-data' >> .env
fi

# # Source updated bashrc
# source ~/.bashrc