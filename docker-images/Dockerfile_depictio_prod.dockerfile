# -----------------------------
# Depictio Production Dockerfile (multi-stage, optimized)
# -----------------------------
# Uses multi-stage builds for smaller final image
# Based on uv for fast, reproducible builds
# -----------------------------

# =================================
# Stage 1: Build stage
# =================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

WORKDIR /app

# Copy dependency files first (better caching)
COPY pyproject.toml uv.lock* ./

# Install dependencies (without dev dependencies)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project || uv sync --no-dev --no-install-project

# Copy source code
COPY depictio ./depictio/

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev || uv sync --no-dev

# =================================
# Stage 2: Runtime stage
# =================================
FROM python:3.12-slim-bookworm AS runtime

# Metadata
ARG VERSION=latest
LABEL org.opencontainers.image.description="Depictio - Dashboard generation from workflows outputs."
LABEL org.opencontainers.image.version="${VERSION:-latest}"

WORKDIR /app

# Install minimal runtime dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    xvfb \
    xauth \
    curl \
    netcat-openbsd \
    # Playwright chromium runtime dependencies
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

# Create non-root user
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} depictio && \
    useradd -m -u ${UID} -g ${GID} -s /bin/bash depictio

# Copy virtual environment from builder
COPY --from=builder --chown=depictio:depictio /app/.venv /app/.venv

# Copy application code
COPY --chown=depictio:depictio depictio ./depictio/
COPY --chown=depictio:depictio pyproject.toml ./

# Copy scripts
COPY --chown=depictio:depictio docker-images/run_dash.sh /app/run_dash.sh
COPY --chown=depictio:depictio docker-images/run_fastapi.sh /app/run_fastapi.sh
COPY --chown=depictio:depictio docker-images/run_celery_worker.sh /app/run_celery_worker.sh
RUN chmod +x /app/run_*.sh

# Set up Playwright browsers path
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers
RUN mkdir -p ${PLAYWRIGHT_BROWSERS_PATH} && chmod 755 ${PLAYWRIGHT_BROWSERS_PATH}

# Install Playwright browsers
RUN /app/.venv/bin/playwright install --with-deps chromium && \
    chmod -R 755 ${PLAYWRIGHT_BROWSERS_PATH}

# Environment
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# Switch to non-root user
USER depictio

EXPOSE 5080 8058

CMD ["/bin/bash"]
