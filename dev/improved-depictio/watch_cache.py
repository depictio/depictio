#!/usr/bin/env python3
"""
Simple diskcache watcher for Dash background callbacks
"""

import time
import diskcache
from datetime import datetime

cache = diskcache.Cache("./cache")

print("👀 Watching diskcache for background callbacks")
print(f"Cache dir: {cache.directory}")
print("Press Ctrl+C to stop\n")

seen_keys = set()

try:
    while True:
        current_keys = set(cache.iterkeys())
        new_keys = current_keys - seen_keys
        
        for key in new_keys:
            timestamp = datetime.now().strftime("%H:%M:%S")
            try:
                value = cache[key]
                print(f"[{timestamp}] New callback result:")
                print(f"  Key: {key}")
                print(f"  Type: {type(value)}")
                if isinstance(value, tuple) and len(value) == 2:
                    result, status = value
                    print(f"  Status: {status}")
                    print(f"  Result: {type(result).__name__}")
                print()
            except Exception as e:
                print(f"[{timestamp}] Error reading {key}: {e}")
        
        seen_keys = current_keys
        time.sleep(1)
        
except KeyboardInterrupt:
    print(f"\n👋 Final cache state: {len(cache)} items")