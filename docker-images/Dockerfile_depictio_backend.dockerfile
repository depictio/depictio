# Dockerfile_backend
FROM mambaorg/micromamba:latest

WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio_backend.yaml depictio_backend.yaml

# Install the environment using micromamba
RUN micromamba install -y -n base -f depictio_backend.yaml && \
    micromamba clean --all --yes

# Set the PYTHONPATH to include the depictio directory
ENV PYTHONPATH="${PYTHONPATH}:/app"

# The command to run the FastAPI application
CMD ["python", "depictio/api/run.py"]