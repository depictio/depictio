#!/bin/bash

# Clone the depictio-data repository if it doesn't exist
if [ ! -d "depictio-data" ]; then
  git clone https://github.com/depictio/depictio-data.git
else
  echo "depictio-data repository already exists."
fi
