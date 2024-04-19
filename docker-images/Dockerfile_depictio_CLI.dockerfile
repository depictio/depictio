# Dockerfile_frontend
FROM mambaorg/micromamba:latest

WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio_cli.yaml depictio_cli.yaml

# Install the environment using micromamba
RUN micromamba install -y -n base -f depictio_cli.yaml && \
    micromamba clean --all --yes

    # Set the PYTHONPATH to include the depictio directory
ENV PYTHONPATH="${PYTHONPATH}:/app"
