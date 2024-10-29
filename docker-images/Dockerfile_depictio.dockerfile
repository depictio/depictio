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
    xvfb xauth \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


RUN bash -c '/opt/conda/envs/depictio/bin/playwright install --with-deps'


USER $MAMBA_USER
RUN bash -c 'whoami'

# -----------------------------
# Environment Variables
# -----------------------------
ENV PATH="/opt/conda/envs/depictio/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/mnt"

# -----------------------------
# Install Playwright
# -----------------------------
RUN bash -c 'playwright install chromium'

# -----------------------------
# Install depictio-cli
# -----------------------------
# WORKDIR /app/depictio-cli
# RUN /opt/conda/envs/depictio/bin/pip install .

# -----------------------------
# Final Commands
# -----------------------------
CMD ["/bin/bash"]

# -----------------------------
# Use xvfb-run to execute Playwright in a virtual display (if needed)
# -----------------------------
# CMD ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "depictio/api/run.py"]
