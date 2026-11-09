"""
MongoDB database configuration and collection definitions.

Provides synchronous MongoDB client and collection instances for the Depictio API.
"""

import os
import sys

import pymongo

from depictio.api.v1.configs.config import MONGODB_URL, settings
from depictio.api.v1.configs.logging_init import logger

is_testing = os.environ.get("DEPICTIO_DEV_MODE", "false").lower() == "true" or any(
    "pytest" in arg for arg in sys.argv
)

client = pymongo.MongoClient(MONGODB_URL)
db_name = settings.mongodb.db_name
db = client[db_name]


def clean_test_database() -> bool:
    """
    Clean the test database by dropping all collections.

    Only operates in test environments. Returns False if not in test mode.

    Returns:
        True if database was cleaned successfully, False otherwise.
    """
    if not is_testing:
        logger.warning(
            "Attempted to clean test database while not in test mode. Operation aborted."
        )
        return False

    try:
        for collection_name in client[db_name].list_collection_names():
            client[db_name].drop_collection(collection_name)
        return True
    except Exception as e:
        logger.error(f"Error cleaning test database: {e}")
        return False


# Collection instances
data_collections_collection = db[settings.mongodb.collections.data_collection]
workflows_collection = db[settings.mongodb.collections.workflow_collection]
runs_collection = db[settings.mongodb.collections.runs_collection]
files_collection = db[settings.mongodb.collections.files_collection]
users_collection = db[settings.mongodb.collections.users_collection]
tokens_collection = db[settings.mongodb.collections.tokens_collection]
groups_collection = db[settings.mongodb.collections.groups_collection]
deltatables_collection = db[settings.mongodb.collections.deltatables_collection]
jbrowse_collection = db[settings.mongodb.collections.jbrowse_collection]
dashboards_collection = db[settings.mongodb.collections.dashboards_collection]
dashboard_versions_collection = db[settings.mongodb.collections.dashboard_versions_collection]
dashboard_version_counters_collection = db[
    settings.mongodb.collections.dashboard_version_counters_collection
]
initialization_collection = db[settings.mongodb.collections.initialization_collection]
projects_collection = db[settings.mongodb.collections.projects_collection]
multiqc_collection = db[settings.mongodb.collections.multiqc_collection]
multiqc_prerender_collection = db[settings.mongodb.collections.multiqc_prerender_collection]
task_events_collection = db[settings.mongodb.collections.task_events_collection]
ingestion_runs_collection = db[settings.mongodb.collections.ingestion_runs_collection]
project_storage_collection = db[settings.mongodb.collections.project_storage_collection]
app_logs_collection = db[settings.mongodb.collections.app_logs_collection]
instance_settings_collection = db[settings.mongodb.collections.instance_settings_collection]
branding_assets_collection = db[settings.mongodb.collections.branding_assets_collection]
user_avatars_collection = db[settings.mongodb.collections.user_avatars_collection]
telemetry_collection = db[settings.mongodb.collections.telemetry_collection]
comment_threads_collection = db[settings.mongodb.collections.comment_threads_collection]

# Per-user filter state of a dashboard (the viewer's remembered filters).
dashboard_filter_states_collection = db["dashboard_filter_states"]
dashboard_annotations_collection = db["dashboard_annotations"]
cli_agents_collection = db[settings.mongodb.collections.cli_agents_collection]
jobs_collection = db[settings.mongodb.collections.jobs_collection]
migration_requests_collection = db[settings.mongodb.collections.migration_requests_collection]
migration_targets_collection = db[settings.mongodb.collections.migration_targets_collection]
migration_pushes_collection = db[settings.mongodb.collections.migration_pushes_collection]
migration_invites_collection = db[settings.mongodb.collections.migration_invites_collection]
test_collection = db[settings.mongodb.collections.test_collection]


def ensure_project_storage_indexes(collection=None) -> None:
    """Unique index on ``project_id`` for per-project storage configs. Idempotent.

    Writes upsert on ``project_id``, so the index is a guard against a racing
    double-insert, not a lookup optimisation. Runs from ``db_init.initialize_db``
    on a fresh deployment and again from the first storage write in a process,
    so instances upgraded past the first boot pick it up too. Never raises:
    an index failure must not block a boot or a credentials write.

    ``collection`` lets callers (and tests) target a patched collection instead
    of the module-level one.
    """
    target = project_storage_collection if collection is None else collection
    try:
        target.create_index("project_id", unique=True, name="project_id_unique")
    except Exception as exc:
        logger.warning(f"Could not ensure unique project_id index on project storage: {exc}")


def ensure_migration_indexes(requests=None, pushes=None, invites=None) -> None:
    """Indexes for the push queue (#1303). Idempotent and never raises."""
    req = migration_requests_collection if requests is None else requests
    push = migration_pushes_collection if pushes is None else pushes
    inv = migration_invites_collection if invites is None else invites
    try:
        req.create_index([("status", 1), ("created_at", -1)], name="status_created")
        req.create_index([("source_name", 1), ("project_id", 1)], name="source_project")
        push.create_index([("project_id", 1), ("created_at", -1)], name="project_created")
        # One push in flight per project: the flag is set while building/uploading.
        push.create_index(
            [("project_id", 1)],
            name="one_in_flight_per_project",
            unique=True,
            partialFilterExpression={"in_flight": True},
        )
        inv.create_index([("code_sha256", 1)], name="code_sha256_unique", unique=True)
        inv.create_index([("created_at", -1)], name="created")
    except Exception as exc:
        logger.warning(f"Could not ensure migration indexes: {exc}")
