import logging
import threading
import time

import app  # Ensure app.py is in the same directory as profile_app.py
from memory_profiler import memory_usage, profile

logging.basicConfig(level=logging.INFO)


@profile
def run_app():
    logging.info("Starting Dash app")
    app.app.run_server(debug=True)


def log_memory_usage():
    while True:
        mem_usage = memory_usage(-1, interval=1, timeout=1)
        logging.info(f"Memory usage: {mem_usage[0]} MB")
        time.sleep(5)  # Log memory usage every 5 seconds


if __name__ == "__main__":
    # Start a separate thread to log memory usage
    threading.Thread(target=log_memory_usage, daemon=True).start()

    # Run the Dash app
    run_app()
