"""
MongoDB change streams watcher for real-time data collection updates.

Listens to data_collections changes and auto-detects affected dashboards.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.realtime import EventMessage, EventSourceType, EventType

# Type alias for the change callback
ChangeCallback = Callable[[EventMessage, list[str]], Awaitable[None]]


class MongoDBChangeWatcher:
    """
    Watches MongoDB change streams for data_collection updates.

    Auto-detects which dashboards use the changed data collection
    and notifies the EventService to broadcast updates.
    """

    def __init__(self, on_change_callback: ChangeCallback) -> None:
        """
        Initialize the MongoDB change watcher.

        Args:
            on_change_callback: Async function to call when changes are detected.
                               Signature: async def callback(event: EventMessage, dashboard_ids: list[str])
        """
        self._on_change = on_change_callback
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None
        self._watch_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start watching MongoDB change streams."""
        if not settings.events.enabled or not settings.events.mongodb_change_streams_enabled:
            logger.info("MongoDB change streams disabled")
            return

        try:
            self._client = AsyncIOMotorClient(MONGODB_URL)
            self._db = self._client[settings.mongodb.db_name]

            # Verify connection
            await self._client.admin.command("ping")
            logger.info("MongoDB change watcher connected")

            self._running = True
            self._watch_task = asyncio.create_task(self._watch_data_collections())

        except Exception as e:
            logger.error(f"Failed to start MongoDB change watcher: {e}")

    async def stop(self) -> None:
        """Stop watching MongoDB change streams."""
        self._running = False

        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None

        if self._client:
            self._client.close()
            self._client = None
            self._db = None

        logger.info("MongoDB change watcher stopped")

    async def _watch_data_collections(self) -> None:
        """Watch the data_collections collection for changes."""
        if not self._db:
            return

        collection: AsyncIOMotorCollection = self._db[settings.mongodb.collections.data_collection]

        # Pipeline to filter for relevant operations
        pipeline = [
            {
                "$match": {
                    "operationType": {"$in": ["insert", "update", "replace"]},
                }
            }
        ]

        try:
            logger.info("Starting MongoDB change stream on data_collections")

            async with collection.watch(pipeline, full_document="updateLookup") as stream:
                async for change in stream:
                    if not self._running:
                        break

                    await self._process_change(change)

        except asyncio.CancelledError:
            logger.info("MongoDB change stream cancelled")
        except Exception as e:
            logger.error(f"MongoDB change stream error: {e}")
            # Attempt to reconnect after a delay
            if self._running:
                await asyncio.sleep(5)
                self._watch_task = asyncio.create_task(self._watch_data_collections())

    async def _process_change(self, change: dict[str, Any]) -> None:
        """
        Process a change event from the change stream.

        Args:
            change: The change document from MongoDB
        """
        try:
            operation_type = change.get("operationType")
            document_key = change.get("documentKey", {})
            dc_id = document_key.get("_id")

            if not dc_id:
                return

            dc_id_str = str(dc_id)
            full_document = change.get("fullDocument", {})

            # Extract data collection info
            dc_tag = full_document.get("data_collection_tag", "")
            workflow_id = full_document.get("workflow_id")
            project_id = full_document.get("project_id")

            # Map operation type to event type
            if operation_type == "insert":
                event_type = EventType.DATA_COLLECTION_CREATED
            else:
                event_type = EventType.DATA_COLLECTION_UPDATED

            # Find dashboards that use this data collection
            dashboard_ids = await self._find_dashboards_using_dc(dc_id_str)

            if not dashboard_ids:
                logger.debug(f"No dashboards found using DC {dc_id_str}")
                return

            # Create event message
            event = EventMessage(
                event_type=event_type,
                source_type=EventSourceType.MONGODB_CHANGES,
                timestamp=datetime.utcnow(),
                project_id=str(project_id) if project_id else None,
                data_collection_id=dc_id_str,
                payload={
                    "operation": operation_type,
                    "data_collection_tag": dc_tag,
                    "workflow_id": str(workflow_id) if workflow_id else None,
                    "affected_dashboards": dashboard_ids,
                },
            )

            logger.info(
                f"DC change detected: {dc_tag} ({operation_type}), "
                f"notifying {len(dashboard_ids)} dashboards"
            )

            # Call the callback to notify affected dashboards
            await self._on_change(event, dashboard_ids)

        except Exception as e:
            logger.error(f"Error processing change event: {e}")

    async def _find_dashboards_using_dc(self, dc_id: str) -> list[str]:
        """
        Find all dashboards that have components using a specific data collection.

        Args:
            dc_id: The data collection ID

        Returns:
            List of dashboard IDs that use this data collection
        """
        if not self._db:
            return []

        try:
            dashboards_collection = self._db[settings.mongodb.collections.dashboards_collection]

            # Query for dashboards where stored_metadata contains this DC ID
            # The structure is: stored_metadata.{component_id}.data_collection_id
            # We need to check if any component uses this DC

            # Use aggregation to find dashboards with matching DC in stored_metadata
            pipeline = [
                {
                    "$project": {
                        "_id": 1,
                        "stored_metadata_values": {"$objectToArray": "$stored_metadata"},
                    }
                },
                {"$unwind": "$stored_metadata_values"},
                {
                    "$match": {
                        "$or": [
                            {"stored_metadata_values.v.data_collection_id": dc_id},
                            {"stored_metadata_values.v.data_collection_id": ObjectId(dc_id)},
                        ]
                    }
                },
                {"$group": {"_id": "$_id"}},
            ]

            cursor = dashboards_collection.aggregate(pipeline)
            dashboard_ids = [str(doc["_id"]) async for doc in cursor]

            return dashboard_ids

        except Exception as e:
            logger.error(f"Error finding dashboards for DC {dc_id}: {e}")
            return []
