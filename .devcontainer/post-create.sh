#!/bin/bash

# Clone the required repositories
git clone https://github.com/depictio/depictio-data.git
git clone -b 19-fixing-pipeline-config-path-parameter-missing-in-dataupload https://github.com/depictio/depictio-cli.git

# Navigate to depictio-cli directory, set up the virtual environment, and install dependencies
cd depictio-cli
python -m venv depictio-cli-venv
depictio-cli-venv/bin/python -m pip install --upgrade pip
depictio-cli-venv/bin/pip install -e .

# Run depictio-cli data setup with configurations
depictio-cli-venv/bin/depictio-cli data setup \
  --agent-config-path ../depictio/.depictio/default_admin_agent.yaml \
  --pipeline-config-path configs/mosaicatcher_pipeline/mosaicatcher_pipeline.yaml \
  --scan-files