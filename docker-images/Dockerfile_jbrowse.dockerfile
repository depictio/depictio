
# Use a Node.js base image
FROM node:18

# Install additional dependencies required by JBrowse
RUN apt-get update && apt-get install -y git python3 make gcc libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev

# Create a symlink for Python (if needed)
RUN ln -s /usr/bin/python3 /usr/bin/python

# Set the working directory in the container
WORKDIR /usr/src/app

# Clone the JBrowse components repository
RUN git clone https://github.com/GMOD/jbrowse-components.git
WORKDIR /usr/src/app/jbrowse-components

# Install dependencies using Yarn
RUN yarn

# Expose the port JBrowse runs on
EXPOSE 3000

# Default command to start the JBrowse web application
CMD ["yarn", "workspace", "@jbrowse/web", "start"]
