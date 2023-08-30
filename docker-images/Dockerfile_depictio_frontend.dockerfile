# Dockerfile_frontend
FROM mambaorg/micromamba:0.15.3

WORKDIR /app

# Copy the environment file
COPY conda_envs/depictio_frontend.yaml depictio_frontend.yaml

# Install the environment using micromamba
RUN micromamba install -y -n base -f depictio_frontend.yaml && \
    micromamba clean --all --yes

# Copy the frontend app files into the container
COPY *.py ./

CMD ["python", "app.py"]
