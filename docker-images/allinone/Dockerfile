# syntax=docker/dockerfile:1.7
# -----------------------------
# Depictio all-in-one image (DRAFT)
# -----------------------------
# The whole single-user stack of `depictio local up` in one image: MongoDB, Redis
# and SeaweedFS (conda-forge builds, the same ones `local up` downloads), the
# FastAPI API serving the built viewer, and the Celery worker. Its only state is
# the local home mounted at /data, e.g. the depictio/ folder the Nextflow module
# writes:
#
#   docker run --rm -p 8058:8058 -v "$PWD/results/depictio:/data" depictio-allinone
#   apptainer run --containall --bind "$PWD/results/depictio:/data" depictio-allinone.sif
#
# Build from the root of a depictio checkout (see README.md):
#
#   docker build -f docker-images/allinone/Dockerfile -t depictio-allinone .
#
# No Playwright browser: dashboard thumbnails are off (the shipped ones are copied).
# -----------------------------

# Base images pinned by digest, the same as Dockerfile.api / Dockerfile.viewer.
# -----------------------------
# 1. Viewer bundles: arch-independent, so built once on the build machine
# -----------------------------
# Same steps and pins as Dockerfile.viewer (the SPA) and Dockerfile.api (the
# catalog-preview and embed single-file bundles the API injects payloads into).
FROM --platform=$BUILDPLATFORM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS viewer-builder
WORKDIR /build
RUN corepack enable && corepack prepare pnpm@10 --activate
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/depictio-components/package.json ./packages/depictio-components/
COPY packages/depictio-react-core/package.json ./packages/depictio-react-core/
COPY depictio/viewer/package.json ./depictio/viewer/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY packages ./packages/
COPY depictio/viewer ./depictio/viewer/
# The icon-subset step of the build scans these (see VIEWER_SOURCES in local_stack.py).
COPY depictio/models/components/advanced_viz/schemas.py ./depictio/models/components/advanced_viz/schemas.py
COPY depictio/projects ./depictio/projects/
ENV VITE_NO_SOURCEMAP=true NODE_OPTIONS="--max-old-space-size=4096"
RUN pnpm --filter depictio-viewer build \
    && pnpm --filter depictio-viewer build:catalog-preview \
    && pnpm --filter depictio-viewer build:embed

# -----------------------------
# 2. Native services from conda-forge, for the target platform
# -----------------------------
# install_services.py reads CONDA_SPECS from local_stack.py, so this image runs
# the MongoDB series `depictio local up` of the same version runs, and prunes
# what serving a home does not need (~900 MB -> ~550 MB on linux-64).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS services
ARG SERVICES_SPECS=""
WORKDIR /build
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /build/venv && uv pip install --python /build/venv/bin/python py-rattler==0.26.0
COPY depictio/cli/cli/local_stack.py docker-images/allinone/install_services.py ./
RUN --mount=type=cache,target=/root/.cache/rattler \
    SERVICES_SPECS="${SERVICES_SPECS}" \
    /build/venv/bin/python -I install_services.py local_stack.py /opt/depictio-services
# Fail the build, not the first run, if a binary cannot start on this platform.
ENV GLIBC_TUNABLES=glibc.pthread.rseq=1
RUN /opt/depictio-services/bin/mongod --version \
    && /opt/depictio-services/bin/redis-server --version \
    && /opt/depictio-services/bin/weed version

# -----------------------------
# 3. Runtime
# -----------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

ARG VERSION=latest
LABEL org.opencontainers.image.description="Depictio all-in-one: MongoDB, Redis, SeaweedFS, API + viewer and worker on one /data folder."
LABEL org.opencontainers.image.source="https://github.com/depictio/depictio"
LABEL org.opencontainers.image.version="${VERSION:-latest}"
LABEL org.opencontainers.image.licenses="MIT"

# tini: PID 1 that forwards signals to the entrypoint and reaps orphans.
# Unpinned like every apt install in docker-images/: the digest-pinned base fixes
# the Debian release.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install --no-install-recommends -y \
        ca-certificates \
        tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Same layering as Dockerfile.api: dependencies first (keyed on the lockfile),
# then the project. --extra server is the API and the worker; py-rattler
# ([local]) is not needed, the services are baked in. Bytecode is compiled at
# build time: an Apptainer image is read-only, so it could never be cached later.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY packages/plotly-complexheatmap ./packages/plotly-complexheatmap/
COPY packages/plotly-upset ./packages/plotly-upset/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --extra server

COPY VERSION ./
COPY depictio ./depictio/
COPY packages ./packages/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra server

COPY --from=viewer-builder /build/depictio/viewer/dist /app/depictio/viewer/dist
COPY --from=viewer-builder /build/depictio/viewer/dist-catalog-preview/catalog-preview.html \
    /app/depictio/viewer/dist-catalog-preview/catalog-preview.html
COPY --from=viewer-builder /build/depictio/viewer/dist-embed/embed.html \
    /app/depictio/viewer/dist-embed/embed.html
COPY --from=services /opt/depictio-services /opt/depictio-services
COPY docker-images/allinone/entrypoint.py /usr/local/bin/depictio-allinone

# The API mkdir()s these at import: present in the image, they never need a
# write to a read-only filesystem. /data is the mount point (Apptainer binds onto
# an existing directory); world-writable so a fresh anonymous volume works for -u.
# The SPA served from a non-editable layout: no pnpm-workspace.yaml next to the
# package, so nothing ever tries to rebuild the viewer at runtime.
RUN mkdir -p /app/depictio/api/static/dashboard_logos /app/depictio/api/static/branding \
        /app/depictio/api/static/screenshots /data \
    && chmod 1777 /data \
    && chmod 0755 /usr/local/bin/depictio-allinone \
    && /app/.venv/bin/python -m compileall -q /app/depictio \
    && test -f /app/depictio/viewer/dist/index.html \
    && test -d /app/depictio/viewer/dist/assets

# GLIBC_TUNABLES: official mongo images need rseq=1 on Linux 6.19+ (SERVER-121912).
# The conda-forge mongod carries the same startup check; glibc >= 2.35 (bookworm:
# 2.36) owns rseq by default, so this only pins that default against an inherited value.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEPICTIO_LOCAL_HOME=/data \
    DEPICTIO_SERVICES_PREFIX=/opt/depictio-services \
    DEPICTIO_TELEMETRY_DEPLOYMENT_KIND=docker \
    GLIBC_TUNABLES=glibc.pthread.rseq=1

VOLUME ["/data"]
EXPOSE 8058

# The API's own health check; the port comes from /data/state.json.
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "/usr/local/bin/depictio-allinone", "health"]

# Starts as root only to drop to the owner of /data (as the mongo and postgres
# images do), so files stay the user's; `-u UID:GID` and Apptainer skip that.
# hadolint ignore=DL3002
USER root
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "python", "/usr/local/bin/depictio-allinone"]
CMD ["serve"]
