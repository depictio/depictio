# Image of the "Try Depictio" codespace (devcontainer.json next to this file): the
# published depictio[local] package, with MongoDB, Redis and SeaweedFS downloaded
# and the Iris and Penguins examples loaded, so a new codespace only runs
# `depictio local up`. .github/workflows/build-try-image.yaml builds it for each
# stable release.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

LABEL org.opencontainers.image.source="https://github.com/depictio/depictio"
LABEL org.opencontainers.image.description="Try Depictio: the depictio[local] package, ready to start"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The release to install. Without it, the latest one on PyPI.
ARG DEPICTIO_VERSION

USER vscode
ENV PATH=/home/vscode/.local/bin:$PATH

# The first `local up` downloads the binaries into ~/.depictio/local/env and loads
# the examples. `local down` stops the services; the data stays. The uv and
# py-rattler caches are not needed afterwards.
RUN uv tool install "depictio[local]${DEPICTIO_VERSION:+==$DEPICTIO_VERSION}" \
 && depictio local up --no-open --port 8058 \
 && depictio local down \
 && rm -rf /home/vscode/.cache
