# Use a Node.js base image
FROM node:latest

# Set the working directory in the container

# Install the JBrowse CLI globally
RUN npm install -g @jbrowse/cli

# Clone the JBrowse 2 repository (if needed)
# RUN git clone https://github.com/GMOD/jbrowse-components.git jbrowse2
# WORKDIR /usr/src/app/jbrowse2

# Install dependencies and build JBrowse (if needed)
# RUN npm install && npm run build
WORKDIR /usr/src/app

RUN jbrowse create jbrowse2

WORKDIR /usr/src/app/jbrowse2

# Expose the port JBrowse runs on
EXPOSE 3000

# Start JBrowse (if needed)
CMD ["npx", "serve", "."]
