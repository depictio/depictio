# -----------------------------
# Base Image
# -----------------------------
FROM mambaorg/micromamba:2.1.1

# -----------------------------
# Metadata Labels
# -----------------------------
ARG VERSION=latest
LABEL org.opencontainers.image.description="Depictio - Dashboard generation from workflows outputs."
LABEL org.opencontainers.image.source="https://github.com/yourusername/depictio"
LABEL org.opencontainers.image.version="${VERSION:-latest}"
LABEL org.opencontainers.image.authors="Thomas Weber <thomas.weber@embl.de>"
LABEL org.opencontainers.image.licenses="MIT"

# -----------------------------
# Set Working Directory
# -----------------------------
WORKDIR /app

# -----------------------------
# Environment Configuration
# -----------------------------
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# -----------------------------
# Copy Conda Environment File and Create Environment
# -----------------------------
COPY conda_envs/depictio.yaml /tmp/depictio.yaml
RUN micromamba create -n depictio -f /tmp/depictio.yaml && \
    micromamba clean --all --yes
# Note: Removed the rm command that was causing permission issues

# Setup shell initialization
RUN micromamba shell init -s bash && \
    echo "source activate depictio" >> ~/.bashrc

# -----------------------------
# Install Playwright Dependencies as root
# -----------------------------
USER root

# Clean up the temporary yaml file (now as root)
RUN rm -f /tmp/depictio.yaml

# Install dependencies more efficiently
RUN apt-get update && apt-get install --no-install-recommends -y \
    xvfb xauth sudo git git-lfs curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a shared directory for Playwright browsers with appropriate permissions
RUN mkdir -p /usr/local/share/playwright-browsers && \
    chmod 777 /usr/local/share/playwright-browsers

# Set environment variable for Playwright browser installation
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

# Install Playwright browsers
RUN /opt/conda/envs/depictio/bin/playwright install --with-deps chromium && \
    chmod -R 755 /usr/local/share/playwright-browsers

# -----------------------------
# Copy scripts and setup permissions
# -----------------------------
COPY ./docker-images/run_dash.sh /app/run_dash.sh
COPY ./docker-images/run_fastapi.sh /app/run_fastapi.sh
COPY ./pyproject.toml /app/pyproject.toml
COPY ./depictio /app/depictio

# Change ownership of the scripts and app directory to the non-root user
RUN chmod +x /app/run_dash.sh /app/run_fastapi.sh && \
    chown -R $MAMBA_USER:$MAMBA_USER /app

# -----------------------------
# Environment Variables (fixed PYTHONPATH definition)
# -----------------------------
ENV PATH="/opt/conda/envs/depictio/bin:${PATH}"
ENV PYTHONPATH="/app"


# COPY --chown=$MAMBA_USER:$MAMBA_USER . /app/depictio

# Switch back to non-root user
USER $MAMBA_USER

# -----------------------------
# Final Commands
# -----------------------------
CMD ["/bin/bash"]