# -----------------------------
# Base Image
# -----------------------------
FROM mambaorg/micromamba:latest

# -----------------------------
# Metadata
# -----------------------------
LABEL maintainer="thomas.weber@embl.de"
LABEL description="Depictio"

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

RUN micromamba shell init -s bash -p /opt/conda/envs/depictio && \
    echo "source activate depictio" >> ~/.bashrc && \
    echo "conda list" >> ~/.bashrc

# -----------------------------
# Install Playwright Dependencies
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
    xvfb xauth \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN /opt/conda/envs/depictio/bin/playwright install --with-deps

USER $MAMBA_USER

# -----------------------------
# Environment Variables
# -----------------------------
ENV PATH="/opt/conda/envs/depictio/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/mnt"

# -----------------------------
# Install Playwright
# -----------------------------
RUN playwright install chromium

# -----------------------------
# Copy Application Code
# -----------------------------
COPY . /app

# -----------------------------
# Expose Ports
# -----------------------------
EXPOSE 8058 5080

# -----------------------------
# Final Command
# -----------------------------
CMD ["/bin/bash"]