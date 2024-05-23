# Dockerfile for depictio

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements/depictio-requirements.txt .
RUN pip install --no-cache-dir -r depictio-requirements.txt

COPY . .

# Set the PYTHONPATH to include the depictio directory
ENV PYTHONPATH="${PYTHONPATH}:/app"