#!/bin/bash

# Check if we should run in Docker mode or local mode
if [ "$1" == "--local" ]; then
    # Local mode - don't start Docker containers
    echo "Running in local mode..."
    
    # Set environment variables for test mode
    export DEPICTIO_TEST_MODE=true
    export DEPICTIO_MONGODB_DB_NAME=depictioDB_test
    
    # Run the tests
    echo "Running tests..."
    pytest depictio/tests/dash/test_auth.py -v --headed
else
    # Docker mode - start containers
    echo "Running in Docker mode..."
    
    # Stop any running containers
    echo "Stopping any running containers..."
    docker compose down
    
    # Start the containers in test mode
    echo "Starting containers in test mode..."
    DEPICTIO_TEST_MODE=true DEPICTIO_MONGODB_DB_NAME=depictioDB_test DEV_MODE=true docker compose -f docker-compose/docker-compose.vnc.yaml up --build -d 
    
    # Wait for the containers to be ready
    echo "Waiting for containers to be ready..."
    sleep 10
    
    # Run the tests
    echo "Running tests..."
    pytest depictio/tests/dash/test_auth.py -v --headed
    
    # Optional: Stop the containers after tests
    # echo "Stopping containers..."
    # docker-compose down
fi
