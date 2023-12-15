# Use a Node.js base image
FROM node:latest

# Install the JBrowse CLI globally
RUN npm install -g @jbrowse/cli

# Set a working directory (good practice)
WORKDIR /usr/src/app

# The container does nothing by default, it's just for running JBrowse CLI commands
CMD ["bash"]

