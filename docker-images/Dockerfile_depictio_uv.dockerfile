# -----------------------------
# Depictio Dockerfile using uv (simplified)
# -----------------------------
# This Dockerfile uses uv for package management instead of conda/mamba
# Benefits: Faster builds, simpler setup, pure Python dependencies
# -----------------------------

# -----------------------------
# Base Image - Python with uv pre-installed
# -----------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

# -----------------------------
# Metadata Labels
# -----------------------------
ARG VERSION=latest
LABEL org.opencontainers.image.description="Depictio - Dashboard generation from workflows outputs."
LABEL org.opencontainers.image.source="https://github.com/depictio/depictio"
LABEL org.opencontainers.image.version="${VERSION:-latest}"
LABEL org.opencontainers.image.authors="Thomas Weber <thomas.weber@embl.de>"
LABEL org.opencontainers.image.licenses="MIT"

# -----------------------------
# Set Working Directory
# -----------------------------
WORKDIR /app

# -----------------------------
# Install System Dependencies
# -----------------------------
# Minimal system dependencies for:
# - xvfb: Virtual framebuffer for headless browser
# - Playwright browser dependencies (installed via playwright install --with-deps)
RUN apt-get update && apt-get install --no-install-recommends -y \
    xvfb \
    xauth \
    curl \
    netcat-openbsd \
    ca-certificates \
    # Playwright chromium dependencies (common ones)
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Create Non-Root User
# -----------------------------
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} depictio && \
    useradd -m -u ${UID} -g ${GID} -s /bin/bash depictio

# -----------------------------
# Copy Project Files
# -----------------------------
COPY --chown=depictio:depictio pyproject.toml uv.lock* VERSION ./
COPY --chown=depictio:depictio packages ./packages/
COPY --chown=depictio:depictio depictio ./depictio/

# -----------------------------
# Install Python Dependencies with uv
# -----------------------------
# Use uv sync for fast, reproducible installs
# --frozen: Use lockfile exactly as-is
# --no-dev: Skip dev dependencies for smaller image
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev || uv sync --no-dev

# -----------------------------
# Install Playwright Browsers
# -----------------------------
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

RUN mkdir -p ${PLAYWRIGHT_BROWSERS_PATH} && \
    chmod 755 ${PLAYWRIGHT_BROWSERS_PATH}

# Install playwright browsers with dependencies
RUN uv run playwright install --with-deps chromium && \
    chmod -R 755 ${PLAYWRIGHT_BROWSERS_PATH}

# -----------------------------
# Copy Scripts
# -----------------------------
COPY --chown=depictio:depictio docker-images/run_dash.sh /app/run_dash.sh
COPY --chown=depictio:depictio docker-images/run_fastapi.sh /app/run_fastapi.sh
COPY --chown=depictio:depictio docker-images/run_celery_worker.sh /app/run_celery_worker.sh

RUN chmod +x /app/run_dash.sh /app/run_fastapi.sh /app/run_celery_worker.sh

# -----------------------------
# Environment Variables
# -----------------------------
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# -----------------------------
# Switch to Non-Root User
# -----------------------------
USER depictio

# -----------------------------
# Expose Ports
# -----------------------------
EXPOSE 5080 8058

# -----------------------------
# Default Command
# -----------------------------
CMD ["/bin/bash"]

# -----------------------------
# Dev-Viewer Stage (Node.js + corepack)
# -----------------------------
# Only the docker-compose `depictio-viewer-dev` service needs Node to run
# Vite/HMR (`pnpm dev`). Keeping it out of `base` keeps the prod backend/
# frontend image ~150MB lighter, which matters on minikube CI where the
# extra layer load was stressing the apiserver enough to break
# `kubectl exec` connectivity tests. Build with `--target dev-viewer`.
FROM base AS dev-viewer
USER root
RUN apt-get update && apt-get install --no-install-recommends -y \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install --no-install-recommends -y nodejs \
    && corepack enable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
# /app is created by WORKDIR in the base stage (root-owned). pnpm writes
# temp files (_tmp_<pid>_*) directly at the workspace root during install,
# so the runtime user (depictio, mapped to host UID/GID by compose) needs
# write access here. Also pre-create the per-workspace node_modules dirs
# with depictio ownership: Docker's named-volume init copies the image's
# directory ownership onto the volume on first mount, so this ensures the
# `*_node_modules` named volumes in docker-compose.dev.yaml don't default
# to root ownership and lock out pnpm install.
RUN chown depictio:depictio /app && \
    mkdir -p /app/node_modules \
             /app/depictio/viewer/node_modules \
             /app/packages/depictio-react-core/node_modules \
             /app/packages/depictio-components/node_modules && \
    chown depictio:depictio /app/node_modules \
                            /app/depictio/viewer/node_modules \
                            /app/packages/depictio-react-core/node_modules \
                            /app/packages/depictio-components/node_modules
# pnpm-workspace.yaml + lockfile aren't copied by the base stage (which
# only handles Python deps). Add them here so we can run pnpm install at
# build time.
COPY --chown=depictio:depictio pnpm-workspace.yaml pnpm-lock.yaml /app/
USER depictio
# Install workspace deps at build time, not at container startup. Doing
# this at runtime OOMs on memory-constrained hosts (Colima default 6 GB
# shared with mongo/minio/redis/backend leaves only ~3 GB for pnpm to
# extract 612 packages). Build time has the full host RAM available.
# The named volumes (`*_node_modules`) in docker-compose.dev.yaml will
# initialize from these populated dirs on first mount, so the runtime
# `pnpm install --frozen-lockfile --prefer-offline` is a fast integrity
# check rather than a full extract.
RUN corepack prepare pnpm@10 --activate && \
    pnpm install --frozen-lockfile --child-concurrency=2 --network-concurrency=4

# -----------------------------
# Viewer-Builder Stage (Node only, discarded from final image)
# -----------------------------
# Produces depictio/viewer/dist/ for the prod runtime image. Kept as its
# own stage so the final image ships zero Node tooling — only the built
# bundle is COPYed forward via --from=viewer-builder. ~30s build cost,
# but no runtime image size impact (intermediate stages are dropped).
FROM node:20-slim AS viewer-builder
WORKDIR /build
# Pinned: pnpm 11+ requires Node 22.13+ (uses node:sqlite builtin). Stay on
# pnpm 10's tip until we bump the base image; `@latest` rolled forward and
# broke the build mid-day on 2026-05-07.
RUN corepack enable && corepack prepare pnpm@10 --activate
COPY pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages ./packages/
COPY depictio/viewer ./depictio/viewer/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
# Two memory knobs to keep the build under typical container memory caps
# (Colima/Docker Desktop default 6 GB):
#   - VITE_NO_SOURCEMAP=true: skip sourcemap emission. Big peak-memory
#     win during chunk rendering; sourcemaps aren't shipped to users
#     anyway. This is the load-bearing fix.
#   - NODE_OPTIONS heap cap at 4 GB: well above sourcemap-off peak
#     (~1–2 GB) but leaves ~2 GB cgroup headroom for stack, native, and
#     Vite's parallel workers — avoids exit 137 from the kernel OOM
#     killer that fires when total RSS exceeds the cgroup limit.
RUN VITE_NO_SOURCEMAP=true NODE_OPTIONS="--max-old-space-size=4096" \
    pnpm --filter depictio-viewer build

# Default target = lean prod (alias of `base` + the viewer dist/). Without
# this, the last stage in the file would be the implicit default and CI
# builds with no `target:` would pick up the wrong stage.
FROM base AS final
COPY --from=viewer-builder --chown=depictio:depictio /build/depictio/viewer/dist /app/depictio/viewer/dist
