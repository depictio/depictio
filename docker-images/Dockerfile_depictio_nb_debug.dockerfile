# Use the depictio:dev image as the base
FROM registry.embl.de/tweber/depictio/depictio:latest

# Optionally, if Jupyter Lab is not included in your depictio.yaml,
# you can install it directly using micromamba
RUN micromamba install -y -n base -c conda-forge jupyterlab && \
    micromamba clean --all --yes

# Expose the port Jupyter Lab uses by default
EXPOSE 8888

# Set the default command to run Jupyter Lab
# Note: --ip=0.0.0.0 is used to allow connections from outside the container
# CMD ["jupyter", "lab", "--ip=0.0.0.0", "--allow-root", "--NotebookApp.token=''", "--NotebookApp.password='DEV'"]
