#!/bin/bash

# Clone the depictio-data repository if it doesn't exist
if [ ! -d "depictio-data" ]; then
  git clone https://github.com/depictio/depictio-data.git
else
  echo "depictio-data repository already exists."
fi

# Set up a virtual environment
python -m venv depictio-cli-venv

# Activate the virtual environment
source depictio-cli-venv/bin/activate

# Install dependencies from requirements file
pip install -r requirements/depictio-cli-requirements.txt

# Add the depictio package to the PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/workspaces/depictio


# Create a directory for the depictioDB and set permissions
mkdir -p ./depictioDB
sudo chmod -R 777 ./depictioDB

# start docker-compose services
docker-compose up -f docker-compose.yml -d