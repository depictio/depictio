#!/usr/bin/env python3
"""
Test script for real-time WebSocket events.

Directly updates MongoDB to trigger change streams and WebSocket notifications.
No depictio-cli setup required - just needs MongoDB running.

Usage:
    # Test with a specific data collection ID
    python dev/test_realtime_events.py --dc-id 507f1f77bcf86cd799439011

    # List available data collections first
    python dev/test_realtime_events.py --list

    # Trigger multiple updates with interval
    python dev/test_realtime_events.py --dc-id <id> --count 5 --interval 2

Requirements:
    - MongoDB running (localhost:27018 or MONGODB_URL)
    - DEPICTIO_EVENTS_ENABLED=true on the API server
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from bson import ObjectId
except ImportError:
    print("Error: motor and pymongo required. Install with: pip install motor pymongo")
    sys.exit(1)


# MongoDB connection
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27018")
DATABASE_NAME = os.getenv("DEPICTIO_MONGODB_DATABASE", "depictioDB")


async def get_client():
    """Create MongoDB client."""
    return AsyncIOMotorClient(MONGODB_URL)


async def list_data_collections():
    """List all data collections in the database."""
    client = await get_client()
    db = client[DATABASE_NAME]

    print(f"\nConnecting to: {MONGODB_URL}/{DATABASE_NAME}")
    print("-" * 60)

    cursor = db.data_collections.find({}, {"_id": 1, "data_collection_tag": 1, "description": 1})
    collections = await cursor.to_list(length=100)

    if not collections:
        print("No data collections found.")
        print("\nHint: Run with --create-test to create a test data collection:")
        print("  python dev/test_realtime_events.py --create-test")
        client.close()
        return

    print(f"\nFound {len(collections)} data collection(s):\n")
    for dc in collections:
        tag = dc.get("data_collection_tag", "unknown")
        desc = dc.get("description", "")[:50]
        print(f"  ID: {dc['_id']}")
        print(f"  Tag: {tag}")
        if desc:
            print(f"  Desc: {desc}...")
        print()

    client.close()


async def create_test_data_collection():
    """Create a minimal test data collection for WebSocket testing."""
    client = await get_client()
    db = client[DATABASE_NAME]

    print(f"\nConnecting to: {MONGODB_URL}/{DATABASE_NAME}")
    print("-" * 60)

    # Check if test DC already exists
    existing = await db.data_collections.find_one({"data_collection_tag": "_websocket_test"})
    if existing:
        print(f"Test data collection already exists: {existing['_id']}")
        print(f"\nUse: python dev/test_realtime_events.py --dc-id {existing['_id']}")
        client.close()
        return str(existing['_id'])

    # Create minimal test data collection
    test_dc = {
        "data_collection_tag": "_websocket_test",
        "description": "Test data collection for WebSocket event testing",
        "config": {
            "type": "table",
            "metatype": "test",
            "format": "csv",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.data_collections.insert_one(test_dc)
    dc_id = str(result.inserted_id)

    print(f"Created test data collection: {dc_id}")
    print(f"\nNow test with:")
    print(f"  python dev/test_realtime_events.py --dc-id {dc_id}")
    print(f"  python dev/test_realtime_events.py --dc-id {dc_id} --count 5 --interval 2")

    client.close()
    return dc_id


async def trigger_update(dc_id: str, verbose: bool = False):
    """
    Trigger a MongoDB update on a data collection.

    This will:
    1. Update the 'updated_at' field (or similar metadata)
    2. MongoDB change stream detects the update
    3. WebSocket notification sent to connected dashboards
    """
    client = await get_client()
    db = client[DATABASE_NAME]

    try:
        oid = ObjectId(dc_id)
    except Exception:
        print(f"Error: Invalid ObjectId format: {dc_id}")
        client.close()
        return False

    # Check if document exists
    doc = await db.data_collections.find_one({"_id": oid})
    if not doc:
        print(f"Error: Data collection not found: {dc_id}")
        client.close()
        return False

    tag = doc.get("data_collection_tag", "unknown")

    # Update with timestamp to trigger change stream
    now = datetime.now(timezone.utc).isoformat()
    result = await db.data_collections.update_one(
        {"_id": oid},
        {"$set": {"_realtime_test_trigger": now}}
    )

    if result.modified_count > 0:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Updated '{tag}' (ID: {dc_id})")
        if verbose:
            print(f"  Trigger timestamp: {now}")
        return True
    else:
        print(f"Warning: No changes made to {dc_id}")
        return False

    client.close()


async def run_test(dc_id: str, count: int, interval: float, verbose: bool):
    """Run test loop."""
    print(f"\nTriggering {count} update(s) with {interval}s interval...")
    print("Watch the API logs or browser console for WebSocket messages.\n")

    for i in range(count):
        success = await trigger_update(dc_id, verbose)
        if not success:
            break

        if i < count - 1:
            await asyncio.sleep(interval)

    print(f"\nDone! Triggered {count} update(s).")


def main():
    parser = argparse.ArgumentParser(
        description="Test real-time WebSocket events by triggering MongoDB updates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List available data collections",
    )
    parser.add_argument(
        "--create-test",
        action="store_true",
        help="Create a test data collection for WebSocket testing",
    )
    parser.add_argument(
        "--dc-id",
        type=str,
        help="Data collection ID to update",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of updates to trigger (default: 1)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between updates (default: 2.0)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.list:
        asyncio.run(list_data_collections())
    elif args.create_test:
        asyncio.run(create_test_data_collection())
    elif args.dc_id:
        asyncio.run(run_test(args.dc_id, args.count, args.interval, args.verbose))
    else:
        parser.print_help()
        print("\n\nExamples:")
        print("  # Create test data collection")
        print("  python dev/test_realtime_events.py --create-test")
        print()
        print("  # List data collections")
        print("  python dev/test_realtime_events.py --list")
        print()
        print("  # Trigger single update")
        print("  python dev/test_realtime_events.py --dc-id 507f1f77bcf86cd799439011")
        print()
        print("  # Trigger 5 updates, 2 seconds apart")
        print("  python dev/test_realtime_events.py --dc-id <id> --count 5 --interval 2")


if __name__ == "__main__":
    main()
