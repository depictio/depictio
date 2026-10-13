# Image of the "Try Depictio" codespace (devcontainer.json next to this file): the
# published depictio[local] package, with MongoDB, Redis and SeaweedFS downloaded
# and the Iris and Penguins examples loaded, so a new codespace only runs
# `depictio local up`. .github/workflows/build-try-image.yaml builds it for each
# stable release.
# The base image without a Python toolchain: uv installs the Python the tool needs.
# It is about 230 MB smaller (compressed) than devcontainers/python, and every MB
# is pulled when a codespace is created.
FROM mcr.microsoft.com/devcontainers/base:bookworm

LABEL org.opencontainers.image.source="https://github.com/depictio/depictio"
LABEL org.opencontainers.image.description="Try Depictio: the depictio[local] package, ready to start"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The release to install. Without it, the latest one on PyPI.
ARG DEPICTIO_VERSION

USER vscode
ENV PATH=/home/vscode/.local/bin:$PATH

# The first `local up` downloads the binaries into ~/.depictio/local/env and loads
# the examples. `local down` stops the services; the data stays. Then, to keep the
# layer small: the uv and py-rattler caches; mongos and the Redis modules, which
# the local server never starts; and Polars' compat runtime, for CPUs without
# AVX2, which Polars would otherwise pick first over the faster default one.
RUN uv tool install --python 3.12 "depictio[local]${DEPICTIO_VERSION:+==$DEPICTIO_VERSION}" \
 && depictio local up --no-open --port 8058 \
 && depictio local down \
 && rm -rf /home/vscode/.cache /tmp/weed.* \
    /home/vscode/.depictio/local/env/bin/mongos \
    /home/vscode/.depictio/local/env/lib/redis/modules \
    /home/vscode/.local/share/uv/tools/depictio/lib/python3.12/site-packages/_polars_runtime_compat*
