FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

ENV PYTHONUNBUFFERED 1

# Update args in docker-compose.yaml to set the UID/GID of the "vscode" user.
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN if [ "$USER_GID" != "1000" ] || [ "$USER_UID" != "1000" ]; then groupmod --gid $USER_GID vscode && usermod --uid $USER_UID --gid $USER_GID vscode; fi

# Copy install script
COPY ./post-create.sh /bin

# Install secondary Python version and uv package manager
USER vscode
RUN <<EOF
curl -sS https://pyenv.run | /bin/sh
INIT_PYENV='
export PYENV_ROOT="$HOME/.pyenv"
[ -d "$PYENV_ROOT/bin" ] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
'
echo "$INIT_PYENV" >> ~/.profile
echo "$INIT_PYENV" >> ~/.bashrc
. ~/.profile
pyenv install --skip-existing 3.9
pyenv global system 3.9

# Install uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.profile
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
EOF

CMD ["sleep", "infinity"]