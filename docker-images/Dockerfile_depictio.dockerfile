# -----------------------------
# Base Image
# -----------------------------
FROM mambaorg/micromamba:latest

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

# RUN micromamba shell init -s bash -p /opt/conda/envs/depictio && \
#     echo "source activate depictio" >> ~/.bashrc && \
#     echo "conda list" >> ~/.bashrc
RUN micromamba shell init -s bash && \
    echo "source activate depictio" >> ~/.bashrc && \
    echo "conda list" >> ~/.bashrc

# -----------------------------
# Install Playwright Dependencies
# -----------------------------
USER root
RUN bash -c 'whoami'

# Ensure /etc/apt/sources.list exists and configure it
RUN if [ ! -f /etc/apt/sources.list ]; then \
    echo "deb http://deb.debian.org/debian buster main" > /etc/apt/sources.list; \
    fi

# Optionally switch to an alternative Debian mirror
RUN sed -i 's|http://deb.debian.org|http://ftp.us.debian.org|g' /etc/apt/sources.list

# Install dependencies using apt
RUN apt-get update && apt-get install --fix-missing -y \
    xvfb xauth sudo git git-lfs curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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


RUN bash -c 'whoami'

# -----------------------------
# Environment Variables
# -----------------------------
ENV PATH="/opt/conda/envs/depictio/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/mnt"

# -----------------------------
# Install Playwright
# -----------------------------
# RUN bash -c 'playwright install --with-deps chromium'

# -----------------------------
# Install depictio-cli
# -----------------------------
# WORKDIR /app/depictio-cli
# RUN /opt/conda/envs/depictio/bin/pip install .  

# -----------------------------
# Install depictio-models
# -----------------------------
# COPY ./depictio-models /app/depictio-models
# USER root
# # RUN rm -rf /app/depictio-models/depictio_models.egg-info
# RUN pwd
# RUN ls
# COPY ./depictio-models /app/depictio-models
# RUN pip install -e /app/depictio-models --config-settings "editable_mode=compat"

# COPY ./depictio-cli /app/depictio-cli
# RUN pip install -e /app/depictio-cli --config-settings "editable_mode=compat"



USER appuser  # Switch back if needed
# RUN pip install -e /app/depictio-models --config-settings "editable_mode=compat"

# -----------------------------
# Final Commands
# -----------------------------
CMD ["/bin/bash"]

# -----------------------------
# Use xvfb-run to execute Playwright in a virtual display (if needed)
# -----------------------------
# CMD ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "depictio/api/run.py"]
