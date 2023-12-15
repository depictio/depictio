# Use a Node.js base image
FROM node:latest

# Set the working directory in the container
WORKDIR /usr/src/app

# Install the JBrowse CLI globally
RUN npm install -g @jbrowse/cli

WORKDIR /usr/src/app

# Clone the JBrowse 2 repository (if needed)
# RUN git clone https://github.com/GMOD/jbrowse-components.git jbrowse2
# WORKDIR /usr/src/app/jbrowse2

# Install dependencies and build JBrowse (if needed)
# RUN npm install && npm run build

RUN mkdir -p /var/www/html/jbrowse
RUN mkdir -p /data

RUN jbrowse create jbrowse2

RUN cd jbrowse2 

# Expose the port JBrowse runs on
EXPOSE 3000

# Start JBrowse (if needed)
CMD ["npx", "serve", "-S", "."]
