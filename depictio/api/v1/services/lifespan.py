"""
FastAPI application lifespan management.

Coordinates startup and shutdown tasks including initialization,
background processing, and cleanup.
"""

import os
from contextlib import asynccontextmanager
from typing import cast

from beanie import init_beanie
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.asynchronous.database import AsyncDatabase

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.initialization import run_initialization
from depictio.api.v1.services.background_tasks import delayed_process_data_collections
from depictio.api.v1.services.initialization import (
    check_and_set_initialization,
    cleanup_failed_initialization,
    mark_initialization_complete,
    wait_for_initialization_complete,
)
from depictio.api.v1.services.yaml_sync import (
    initialize_yaml_directory,
    start_yaml_sync_services,
    stop_yaml_sync_services,
)
from depictio.api.v1.tasks.cleanup_tasks import start_cleanup_tasks
from depictio.api.v1.utils import clean_screenshots
from depictio.models.models.analytics import UserActivity, UserSession
from depictio.models.models.projects import ProjectBeanie
from depictio.models.models.users import GroupBeanie, TokenBeanie, UserBeanie

WORKER_ID = os.getpid()


async def init_motor_beanie() -> None:
    """Initialize Motor (async MongoDB client) and Beanie ODM."""
    client = AsyncIOMotorClient(MONGODB_URL)
    await init_beanie(
        database=cast(AsyncDatabase, client[settings.mongodb.db_name]),
        document_models=[
            TokenBeanie,
            GroupBeanie,
            UserBeanie,
            ProjectBeanie,
            UserSession,
            UserActivity,
        ],
    )


async def handle_initialization() -> bool:
    """
    Handle application initialization with worker coordination.

    Returns:
        True if this worker performed initialization, False otherwise
    """
    # If wiping, clear existing initialization markers first
    if settings.mongodb.wipe:
        logger.info(f"Worker {WORKER_ID}: Database wipe requested")
        from depictio.api.v1.db import initialization_collection

        initialization_collection.delete_many({})

    # Check if this worker should perform initialization
    should_initialize = await check_and_set_initialization()

    if should_initialize:
        logger.info(f"Worker {WORKER_ID}: Running initialization...")
        try:
            await run_initialization()
            await mark_initialization_complete()
            await clean_screenshots()
            logger.info(f"Worker {WORKER_ID}: Initialization completed successfully")
        except Exception as e:
            logger.error(f"Worker {WORKER_ID}: Initialization failed: {e}")
            await cleanup_failed_initialization()
            raise
    else:
        await wait_for_initialization_complete()

    return should_initialize


def start_background_services(should_initialize: bool):
    """
    Start background services and tasks.

    Args:
        should_initialize: Whether this worker performed initialization

    Returns:
        Background task that can be cancelled during shutdown (or None)
    """
    background_task = None

    # Only start background data processing on the initializing worker
    if should_initialize:
        logger.info(f"Worker {WORKER_ID}: Starting background data collection processing")
        background_task = delayed_process_data_collections()

    # Start cleanup tasks on every worker
    logger.info(f"Worker {WORKER_ID}: Starting cleanup tasks")
    start_cleanup_tasks()

    return background_task


def start_yaml_services(should_initialize: bool) -> None:
    """
    Initialize and start YAML dashboard services if enabled.

    Args:
        should_initialize: Whether this worker performed initialization
    """
    if not settings.dashboard_yaml.enabled:
        return

    # All workers can initialize the directory
    initialize_yaml_directory()

    # Only the initializing worker runs sync and starts the watcher
    if should_initialize:
        start_yaml_sync_services()


def stop_background_services(background_task, should_initialize: bool) -> None:
    """
    Stop background services and tasks.

    Args:
        background_task: Background task to cancel (if any)
        should_initialize: Whether this worker performed initialization
    """
    if background_task and not background_task.done():
        logger.info(f"Worker {WORKER_ID}: Cancelling background task")
        background_task.cancel()

    if settings.dashboard_yaml.enabled and should_initialize:
        stop_yaml_sync_services()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    FastAPI lifespan context manager.

    Handles startup and shutdown tasks including:
    - Database initialization
    - Worker coordination
    - Background task management
    - YAML synchronization services
    """
    # Startup
    await init_motor_beanie()
    should_initialize = await handle_initialization()
    background_task = start_background_services(should_initialize)
    start_yaml_services(should_initialize)

    yield

    # Shutdown
    stop_background_services(background_task, should_initialize)
