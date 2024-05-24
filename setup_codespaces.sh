#!/bin/bash


# Create a .env file for Docker Compose
cat <<EOF > .env
MINIO_ROOT_USER=${MINIO_ROOT_USER}
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}
MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY}
MINIO_SECRET_KEY=${MINIO_SECRET_KEY}
DEPICTIO_BACKEND_DATA_VOLUME_HOST=${DEPICTIO_BACKEND_DATA_VOLUME_HOST}
AUTH_PRIVATE_KEY="${AUTH_PRIVATE_KEY}"
AUTH_PUBLIC_KEY="${AUTH_PUBLIC_KEY}"
EOF

# Print the contents of the .env file for debugging
cat .env


# Clone the depictio-data repository if it doesn't exist
if [ ! -d "depictio-data" ]; then
  git clone https://github.com/depictio/depictio-data.git
else
  echo "depictio-data repository already exists."
fi

# Create a directory for the depictioDB and set permissions
mkdir -p ./depictioDB
sudo chmod -R 777 ./depictioDB

# start docker-compose services
docker-compose -f docker-compose.yml up -d

# Set up a virtual environment
python -m venv depictio-cli-venv

# Activate the virtual environment
source depictio-cli-venv/bin/activate

# Install dependencies from requirements file
pip install -r requirements/depictio-cli-requirements.txt

# Add the depictio package to the PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/workspaces/depictio

# Run the depictio-cli create-user-and-return-token
python depictio-cli/depictio_cli/depictio_cli.py create-user-and-return-token

TOKEN=$(grep "token" ~/.depictio/config.yaml | sed 's/token: //g')
cat <<EOF >> .env
TOKEN=${TOKEN}
EOF



# start docker-compose services
docker-compose -f docker-compose.yml up -d --force-recreate