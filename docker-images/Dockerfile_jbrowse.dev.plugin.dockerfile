# Use a Node.js base image
FROM node:latest

# Install the JBrowse CLI globally
RUN npm install -g @jbrowse/cli

# Create a directory for JBrowse
WORKDIR /usr/src/jbrowse
RUN jbrowse create jbrowse2
WORKDIR /usr/src/jbrowse/jbrowse2

# Clone and set up the plugin in a separate directory
WORKDIR /usr/src/plugin
RUN git clone https://github.com/depictio/jbrowse-watcher-plugin.git .
RUN npm install --force
# Uncomment if a build step is required for your plugin
# RUN npm run build



# Start JBrowse using npx serve
CMD sh -c 'cd /usr/src/jbrowse/jbrowse2 && npx serve -S . & cd /usr/src/plugin && npm start'
