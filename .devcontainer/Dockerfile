FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

ENV PYTHONUNBUFFERED 1

# Update args in docker-compose.yaml to set the UID/GID of the "vscode" user
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN if [ "$USER_GID" != "1000" ] || [ "$USER_UID" != "1000" ]; then \
    groupmod --gid $USER_GID vscode && \
    usermod --uid $USER_UID --gid $USER_GID vscode; \
    fi

# Install git, git-lfs, curl, and development tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        wget \
        vim \
        netcat-openbsd \
        build-essential \
        git-lfs && \
    rm -rf /var/lib/apt/lists/*


# Copy install script
COPY .devcontainer/post_create_setup.sh /bin

# Install Node.js directly in the container
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Switch to vscode user and configure npm for user installation
USER vscode
RUN npm config set prefix ~/.local && \
    npm config set cache ~/.npm && \
    npm config set init-module ~/.npm-init.js

# Install AI tools directly in the container image to ensure they're Linux-compatible
RUN npm install -g @google/gemini-cli @anthropic-ai/claude-code @qwen-code/qwen-code@latest

# Add npm global bin to PATH
ENV PATH="/home/vscode/.local/bin:${PATH}"

# Configure shell to include npm global bin in PATH
RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

# Install uv
# RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && \
#     echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

CMD ["sleep", "infinity"]
