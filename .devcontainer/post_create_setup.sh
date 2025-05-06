#!/bin/zsh

# Install depictio-cli from GitHub
uv venv depictio-cli-venv
source depictio-cli-venv/bin/activate
# Install the required packages
uv pip install git+https://github.com/depictio/depictio-models.git git+https://github.com/depictio/depictio-cli.git

# Run depictio-cli - use python -m to run the module
depictio-cli --help
