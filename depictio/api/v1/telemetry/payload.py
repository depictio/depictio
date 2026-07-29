"""Builds the heartbeat payload from settings and aggregate database counts.

Two rules govern everything in this module:

* **Counts are bucketed, never exact.** See :mod:`depictio.telemetry.buckets` for
  why. A deployment's exact sizes across eight dimensions is close to a
  fingerprint; the bucket labels answer "roughly how big" without one.
* **A failed count must not lose the whole payload.** Every aggregate is computed
  defensively and degrades to ``unknown``. Knowing an install exists and what
  version it runs matters more than knowing how many dashboards it has, so a
  MongoDB hiccup must not cost the heartbeat entirely.
"""

import uuid
from typing import Any, Final

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.telemetry.identity import get_or_create_instance_id, install_age_days
from depictio.telemetry.buckets import bucket
from depictio.telemetry.env import detect_deployment_kind, platform_info
from depictio.telemetry.k8s_resources import parse_cpu_millicores, parse_memory_mib
from depictio.telemetry.schema import (
    FeatureFlags,
    KubernetesResources,
    ServerHeartbeatProperties,
    UsageBuckets,
)
from depictio.version import get_api_version, get_version

#: Regenerated per process. Lets the collector tell a restart apart from a second
#: installation, and makes a database cloned into another environment visible as
#: one identity reporting from two boots at once.
BOOT_ID: Final[str] = uuid.uuid4().hex

#: How many recent CLI versions to report. A cap, so a long-lived instance talked
#: to by many CLI versions cannot grow the payload without bound.
MAX_CLI_VERSIONS: Final[int] = 10


def _count(collection: Any) -> int | None:
    """Count documents in a collection, or ``None`` if the count fails."""
    try:
        return collection.count_documents({})
    except Exception as exc:
        logger.debug("Telemetry: count failed for %r: %s", getattr(collection, "name", "?"), exc)
        return None


def _component_type_buckets() -> dict[str, str]:
    """Bucketed count of dashboard components per type.

    Answers which component types are actually worth investing in. The keys come
    from Depictio's own ``stored_metadata.component_type`` values — the same field
    the MultiQC prewarm query in ``services/lifespan.py`` filters on — so no
    user-supplied string can appear here.
    """
    from depictio.api.v1.db import dashboards_collection

    try:
        pipeline = [
            {"$unwind": "$stored_metadata"},
            {"$group": {"_id": "$stored_metadata.component_type", "n": {"$sum": 1}}},
        ]
        result: dict[str, str] = {}
        for row in dashboards_collection.aggregate(pipeline):
            component_type = row.get("_id")
            if isinstance(component_type, str) and component_type:
                result[component_type] = bucket(row.get("n"))
        return result
    except Exception as exc:
        logger.debug("Telemetry: component type aggregation failed: %s", exc)
        return {}


def _active_users_7d() -> int | None:
    """Users seen in the last 7 days, or ``None`` when not knowable.

    Depends on the local analytics subsystem's session records, which only exist
    when the operator has enabled it. Returns ``None`` otherwise rather than 0, so
    "not measured" stays distinct from "nobody used it".
    """
    if not settings.analytics.enabled:
        return None

    from datetime import datetime, timedelta, timezone

    from depictio.api.v1.db import db
    from depictio.models.models.analytics import UserSession

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        # Read through the Beanie document's own declared collection name so this
        # cannot drift if the collection is ever renamed.
        sessions = db[UserSession.Settings.name]
        # Distinct on the user identifier, not a session count: one person
        # generates many sessions and would otherwise be counted many times.
        return len(sessions.distinct("user_id", {"last_activity": {"$gte": cutoff}}))
    except Exception as exc:
        logger.debug("Telemetry: active-user count failed: %s", exc)
        return None


def _usage_buckets() -> UsageBuckets:
    """Assemble the bucketed size of this deployment."""
    from depictio.api.v1.db import (
        dashboards_collection,
        data_collections_collection,
        deltatables_collection,
        groups_collection,
        projects_collection,
        runs_collection,
        users_collection,
        workflows_collection,
    )

    return UsageBuckets(
        users=bucket(_count(users_collection)),
        groups=bucket(_count(groups_collection)),
        projects=bucket(_count(projects_collection)),
        dashboards=bucket(_count(dashboards_collection)),
        data_collections=bucket(_count(data_collections_collection)),
        workflows=bucket(_count(workflows_collection)),
        runs=bucket(_count(runs_collection)),
        deltatables=bucket(_count(deltatables_collection)),
        active_users_7d=bucket(_active_users_7d()),
        component_types=_component_type_buckets(),
    )


def _feature_flags() -> FeatureFlags:
    """Which optional subsystems this deployment has switched on."""
    return FeatureFlags(
        auth_single_user_mode=settings.auth.is_single_user_mode,
        auth_public_mode=settings.auth.is_public_mode,
        auth_demo_mode=settings.auth.is_demo_mode,
        analytics_enabled=settings.analytics.enabled,
        google_analytics_enabled=settings.google_analytics.enabled,
        events_enabled=settings.events.enabled,
        monitoring_enabled=settings.monitoring.enabled,
        dashboard_yaml_enabled=settings.dashboard_yaml.enabled,
        jbrowse_enabled=settings.jbrowse.enabled,
        # ``external_service`` is the existing flag for "this service lives outside
        # the compose network", which is exactly the bundled-MinIO-or-not question.
        external_s3=settings.minio.external_service,
    )


def _kubernetes_resources() -> KubernetesResources | None:
    """Configured replica count and resource requests/limits, Helm installs only.

    ``replicas`` is required on the model, so absent that (i.e. outside Helm,
    where nothing sets ``DEPICTIO_TELEMETRY_REPLICAS``) there is nothing to
    build — ``None`` for the whole block, not a block of ``None`` guesses.
    """
    if settings.telemetry.replicas is None:
        return None
    return KubernetesResources(
        replicas=settings.telemetry.replicas,
        cpu_request_millicores=parse_cpu_millicores(settings.telemetry.cpu_request),
        cpu_limit_millicores=parse_cpu_millicores(settings.telemetry.cpu_limit),
        memory_request_mib=parse_memory_mib(settings.telemetry.memory_request),
        memory_limit_mib=parse_memory_mib(settings.telemetry.memory_limit),
    )


def recent_cli_versions() -> list[str]:
    """Distinct ``depictio-cli`` versions that recently talked to this instance.

    Recorded from request headers by
    :func:`depictio.api.v1.telemetry.cli_versions.record_cli_version`. Versions
    only — the CLI also sends a hostname header, which stays in the operator's own
    database and is never forwarded.
    """
    from depictio.api.v1.telemetry.cli_versions import read_cli_versions

    return read_cli_versions(limit=MAX_CLI_VERSIONS)


def build_heartbeat_properties() -> tuple[str, ServerHeartbeatProperties]:
    """Build the full heartbeat payload.

    Used for both ``server_install`` and ``server_heartbeat`` — the events differ
    in when they fire, not in what they carry — and by the admin preview endpoint,
    so what an operator inspects is the payload by construction.

    Returns:
        ``(instance_id, properties)``. The instance ID is the event's
        ``distinct_id`` rather than one of its properties, so it is returned
        alongside instead of being embedded.
    """
    instance_id, created_at = get_or_create_instance_id()

    platform = platform_info()
    override = settings.telemetry.deployment_kind
    deployment_kind = override.strip() if override else detect_deployment_kind()

    properties = ServerHeartbeatProperties(
        depictio_version=get_version(),
        deployment_kind=deployment_kind,
        os=platform["os"],
        arch=platform["arch"],
        python_version=platform["python_version"],
        boot_id=BOOT_ID,
        api_version=get_api_version(),
        install_age_days=install_age_days(created_at),
        workers=settings.fastapi.workers,
        features=_feature_flags(),
        usage=_usage_buckets() if settings.telemetry.include_usage_metrics else None,
        kubernetes=_kubernetes_resources(),
        cli_versions_seen=recent_cli_versions(),
    )
    return instance_id, properties
