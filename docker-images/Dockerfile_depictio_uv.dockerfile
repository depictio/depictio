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
# Node 22+ required: pnpm 11.x (pinned in docker-compose.dev.yaml) uses
# the `node:sqlite` built-in module, which is only available starting in
# Node 22. Earlier Node 20 base crashed at corepack-prepared pnpm startup.
RUN apt-get update && apt-get install --no-install-recommends -y \
        gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install --no-install-recommends -y nodejs \
    && corepack enable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER depictio

# Default target = lean prod (alias of `base`). Without this, the last
# stage in the file (`dev-viewer`) would be the implicit default and CI
# builds with no `target:` would pick up Node.js again.
FROM base AS final
