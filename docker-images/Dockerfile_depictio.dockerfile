# Dockerfile_frontend
FROM mambaorg/micromamba:latest

WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio.yaml depictio.yaml

# Install the environment using micromamba
RUN micromamba install -y -n base -f depictio.yaml && \
    micromamba clean --all --yes

# Copy the entire depictio directory into the container
# Make sure your .dockerignore file is set up to exclude unnecessary files
# COPY . /app

# Set the PYTHONPATH to include the depictio directory
ENV PYTHONPATH="${PYTHONPATH}:/app"

# Run the Dash app
# CMD ["python", "depictio/dash/app.py"]
