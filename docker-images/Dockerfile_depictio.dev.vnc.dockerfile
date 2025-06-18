# -----------------------------
# Base Image
# -----------------------------
FROM mambaorg/micromamba:latest

# -----------------------------
# Inherit base configuration from Dockerfile_depictio.dockerfile
# -----------------------------
# Note: This Dockerfile follows the same base configuration
# as Dockerfile_depictio.dockerfile, with additional VNC tools

# -----------------------------
# Set Working Directory
# -----------------------------
WORKDIR /app

# -----------------------------
# Copy Conda Environment File
# -----------------------------
COPY conda_envs/depictio.yaml depictio.yaml

# -----------------------------
# Create Conda Environment
# -----------------------------
RUN micromamba create -n depictio -f depictio.yaml && \
    micromamba clean --all --yes

# -----------------------------
# Environment Configuration
# -----------------------------
ARG MAMBA_DOCKERFILE_ACTIVATE=1

RUN micromamba shell init -s bash && \
    echo "source activate depictio" >> ~/.bashrc && \
    echo "conda list" >> ~/.bashrc

# -----------------------------
# Install Playwright and VNC Dependencies
# -----------------------------
USER root

# Ensure /etc/apt/sources.list exists and configure it
RUN if [ ! -f /etc/apt/sources.list ]; then \
    echo "deb http://deb.debian.org/debian buster main" > /etc/apt/sources.list; \
    fi

# Optionally switch to an alternative Debian mirror
RUN sed -i 's|http://deb.debian.org|http://ftp.us.debian.org|g' /etc/apt/sources.list

# Install dependencies using apt
RUN apt-get update && apt-get install --fix-missing -y \
    xvfb xauth sudo git git-lfs curl \
    xvfb x11vnc fluxbox \
    wget unzip nodejs npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome/Chromium (let package manager handle architecture)
RUN apt-get update && apt-get install -y chromium chromium-driver && \
    ln -s /usr/bin/chromium /usr/bin/google-chrome

# Install Cypress
RUN npm install -g cypress

# Install selenium & webdriver-manager using micromamba env
RUN /opt/conda/envs/depictio/bin/pip install selenium webdriver-manager psutil

# Create a shared directory for Playwright browsers with appropriate permissions
RUN mkdir -p /usr/local/share/playwright-browsers && \
    chmod 777 /usr/local/share/playwright-browsers

# Set environment variable to use the shared location for browser installation
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

# Install Playwright browsers as root
RUN /opt/conda/envs/depictio/bin/playwright install --with-deps chromium && \
    chmod -R 755 /usr/local/share/playwright-browsers

# Switch back to non-root user
USER $MAMBA_USER

# Ensure the environment variable is also available to the non-root user
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright-browsers

# -----------------------------
# Copy Necessary Files
# -----------------------------
COPY ./docker-images/run_dash.sh /app/run_dash.sh
COPY ./docker-images/run_fastapi.sh /app/run_fastapi.sh
COPY ./pyproject.toml /app/pyproject.toml

# -----------------------------
# Environment Variables
# -----------------------------
ENV PATH="/opt/conda/envs/depictio/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/mnt"
ENV DISPLAY=:99

# -----------------------------
# User Management
# -----------------------------
USER appuser  # Switch back if needed

# -----------------------------
# -----------------------------
# CMD ["/bin/bash"]

# -----------------------------
# Optional VNC/Display Commands
# -----------------------------
CMD ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "depictio/api/run.py"]
