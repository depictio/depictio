#!/bin/zsh

# Clone the required repositories
git clone https://github.com/depictio/depictio-data.git
# git clone https://github.com/depictio/depictio-cli.git

# Navigate to depictio-cli directory, set up the virtual environment, and install dependencies
# cd depictio-cli
uv venv depictio-cli-venv
# https://github.com/depictio/depictio-cli.git
depictio-cli-venv/bin/python -m pip install git+https://github.com/depictio/depictio-cli.git

# Run depictio-cli data setup with configurations
depictio-cli-venv/bin/depictio-cli data setup \
  --agent-config-path ../depictio/.depictio/default_test_user_agent.yaml \
  --pipeline-config-path configs/projects/strand-seq/strand-seq_validation.yaml \
  --scan-files
