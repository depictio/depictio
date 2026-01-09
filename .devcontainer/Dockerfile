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
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy install script
COPY .devcontainer/post_create_setup.sh /bin

# Switch to vscode user and install pipenv package manager for creating venvs
USER vscode

# Install uv
# RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# RUN echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && \
#     echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc

CMD ["sleep", "infinity"]
