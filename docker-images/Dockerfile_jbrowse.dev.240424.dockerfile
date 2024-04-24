# Use a stable Node.js base image
FROM node:16

# Install the JBrowse CLI globally
RUN npm install -g @jbrowse/cli

# Create a directory for JBrowse
WORKDIR /usr/src/jbrowse
RUN jbrowse create jbrowse2
WORKDIR /usr/src/jbrowse/jbrowse2

# Clone and set up the plugin in a separate directory
WORKDIR /usr/src/jbrowse/plugin
RUN git clone https://github.com/depictio/jbrowse-watcher-plugin.git .

# Install all dependencies including npm-run-all
# Remove the yarn.lock if it exists to ensure npm is used for installation
RUN rm -f yarn.lock && npm install --force

# Now run build
RUN npm run build

# Expose the necessary ports
# EXPOSE 3000 9010

# Command to start the service
CMD ["sh", "-c", "cd /usr/src/jbrowse/jbrowse2 && npx serve -S . & cd /usr/src/jbrowse/plugin && npm start"]
