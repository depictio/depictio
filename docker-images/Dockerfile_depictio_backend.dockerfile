# Dockerfile_backend
FROM mambaorg/micromamba:0.15.3

WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio_backend.yaml depictio_backend.yaml

# Install the environment using micromamba
RUN micromamba install -y -n base -f depictio_backend.yaml && \
    micromamba clean --all --yes

# Copy the backend app files into the container
COPY fastapi_backend/ ./fastapi_backend/

CMD ["python", "fastapi_backend/run.py"]
