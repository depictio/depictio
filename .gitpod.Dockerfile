FROM gitpod/workspace-full:latest

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
