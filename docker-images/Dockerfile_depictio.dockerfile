# Use mambaorg/micromamba as the base image
FROM mambaorg/micromamba:latest

# Set the working directory
WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio.yaml depictio.yaml


# Create a new environment using micromamba
RUN micromamba create -n depictio -f depictio.yaml && \
    micromamba clean --all --yes 

ARG MAMBA_DOCKERFILE_ACTIVATE=1  # (otherwise python will not be found)

RUN micromamba shell init -s bash -p /opt/conda/envs/depictio && \
    echo "source activate depictio" >> ~/.bashrc && \
    echo "conda list" >> ~/.bashrc


USER root
RUN bash -c 'whoami'
# List the contents of the environment
RUN bash -c '/opt/conda/envs/depictio/bin/playwright install --with-deps'

# Install necessary tools including xvfb
RUN apt-get update && apt-get install -y \
    xvfb xauth \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER
RUN bash -c 'whoami'

# Set the PATH and PYTHONPATH to include the environment and /mnt directory
ENV PATH="/opt/conda/envs/depictio/bin:${PATH}"
ENV PYTHONPATH="${PYTHONPATH}:/mnt"

RUN bash -c 'playwright install chromium'

# Run the container with bash
CMD ["/bin/bash"]


# Use xvfb-run to execute Playwright in a virtual display
# CMD ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "depictio/api/run.py"]
