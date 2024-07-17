FROM mambaorg/micromamba:latest

WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio.yaml depictio.yaml

# Install the environment using micromamba
RUN micromamba install -y -n base -f depictio.yaml && \
    micromamba clean --all --yes

# Set the PYTHONPATH to include the depictio directory
ENV PYTHONPATH="${PYTHONPATH}:/app"