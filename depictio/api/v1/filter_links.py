"""
Cross-DC filter link resolution.

Originally part of ``depictio.dash.utils``; relocated here so the React-facing
API endpoints (``bulk_compute_cards``, ``render_figure``, ``render_table``,
``render_map``, ``render_image_paths``) can call it without importing from the
Dash package. The Dash module re-exports these names so existing Dash callbacks
keep working unchanged.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import httpx

from depictio.api.v1.configs.config import API_BASE_URL
from depictio.api.v1.configs.logging_init import logger

# Cache for link resolution results
_link_resolution_cache: Dict[str, Dict[str, Any]] = {}
LINK_RESOLUTION_CACHE_TTL_SECONDS = 300  # 5 minutes


def resolve_link_values(
    project_id: str,
    source_dc_id: str,
    source_column: str,
    filter_values: list,
    target_dc_id: str,
    token: str | None,
    use_cache: bool = True,
) -> Optional[Dict[str, Any]]:
    """Resolve filtered values from source DC to target DC via link."""
    if not token:
        logger.warning("No token provided for link resolution")
        return None

    if not filter_values:
        return None

    cache_key = (
        f"link_{project_id}_{source_dc_id}_{target_dc_id}_"
        f"{hash(tuple(sorted(str(v) for v in filter_values)))}"
    )

    if use_cache and cache_key in _link_resolution_cache:
        cached = _link_resolution_cache[cache_key]
        if time.time() - cached.get("timestamp", 0) < LINK_RESOLUTION_CACHE_TTL_SECONDS:
            return cached.get("data")
        else:
            del _link_resolution_cache[cache_key]

    payload = {
        "source_dc_id": source_dc_id,
        "source_column": source_column,
        "filter_values": filter_values,
        "target_dc_id": target_dc_id,
    }

    try:
        response = httpx.post(
            f"{API_BASE_URL}/depictio/api/v1/links/{project_id}/resolve",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )

        if response.status_code == 200:
            result = response.json()
            if use_cache:
                _link_resolution_cache[cache_key] = {
                    "data": result,
                    "timestamp": time.time(),
                }
            return result

        elif response.status_code == 404:
            return None

        else:
            logger.warning(f"Link resolution failed: {response.status_code} - {response.text}")
            return None

    except httpx.TimeoutException:
        logger.warning(f"Link resolution timed out for {source_dc_id} -> {target_dc_id}")
        return None
    except Exception as e:
        logger.error(f"Link resolution error: {e}")
        return None


def get_multiqc_sample_mappings(
    project_id: str,
    dc_id: str,
    token: str | None,
) -> dict[str, list[str]]:
    """Fetch aggregated sample mappings for a MultiQC data collection."""
    if not token:
        logger.warning("No token provided for fetching sample mappings")
        return {}

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/links/{project_id}/multiqc/{dc_id}/sample-mappings",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(
                f"Failed to fetch sample mappings for {dc_id}: "
                f"{response.status_code} - {response.text[:100]}"
            )
            return {}

    except httpx.TimeoutException:
        logger.warning(f"Sample mappings fetch timed out for {dc_id}")
        return {}
    except Exception as e:
        logger.error(f"Sample mappings fetch error: {e}")
        return {}


def get_links_for_target_dc(
    project_id: str,
    target_dc_id: str,
    token: str | None,
) -> list[Dict[str, Any]]:
    """Get all links where the specified DC is the target."""
    if not token:
        logger.warning("No token provided for fetching links")
        return []

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/links/{project_id}/target/{target_dc_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )

        if response.status_code == 200:
            return response.json()
        else:
            return []

    except Exception as e:
        logger.warning(f"Failed to fetch links for target DC {target_dc_id}: {e}")
        return []


def get_links_for_source_dc(
    project_id: str,
    source_dc_id: str,
    token: str | None,
) -> list[Dict[str, Any]]:
    """Get all links where the specified DC is the source."""
    if not token:
        logger.warning("No token provided for fetching links")
        return []

    try:
        response = httpx.get(
            f"{API_BASE_URL}/depictio/api/v1/links/{project_id}/source/{source_dc_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )

        if response.status_code == 200:
            return response.json()
        else:
            return []

    except Exception as e:
        logger.warning(f"Failed to fetch links for source DC {source_dc_id}: {e}")
        return []


def clear_link_resolution_cache():
    """Clear the link resolution cache."""
    _link_resolution_cache.clear()


def extend_filters_via_links(
    target_dc_id: str,
    filters_by_dc: dict,
    project_metadata: dict | None,
    access_token: str | None,
    component_type: str = "unknown",
) -> list:
    """
    Extend filters using DC links for cross-DC filtering.

    When a filter is on a source DC that has a link to the target DC,
    resolve the filter values through the link. This enables components
    to be filtered by interactive components from linked data collections.

    Args:
        target_dc_id: The target component's data collection ID
        filters_by_dc: Dictionary mapping DC IDs to their filters
        project_metadata: Project metadata containing link definitions
        access_token: Authentication token for API calls
        component_type: Component type for logging (e.g., "figure", "image")

    Returns:
        List of filters to apply (resolved via links)
    """
    link_filters: list = []

    if not project_metadata or not access_token:
        logger.info(
            f"[{component_type}] Link resolution skipped: "
            f"project_metadata={project_metadata is not None}, "
            f"access_token={access_token is not None}"
        )
        return link_filters

    project_data = project_metadata.get("project", {})
    project_id = str(project_data.get("_id", ""))
    project_links = project_data.get("links", [])

    if not project_id or not project_links:
        return link_filters

    for link in project_links:
        if not link.get("enabled", True):
            continue

        link_target_dc = str(link.get("target_dc_id", ""))
        link_source_dc = str(link.get("source_dc_id", ""))

        if link_target_dc != target_dc_id:
            continue

        logger.info(
            f"[{component_type}] Found matching link: {link_source_dc[:8]} -> {link_target_dc[:8]}"
        )

        source_filters = filters_by_dc.get(link_source_dc, [])
        logger.info(
            f"[{component_type}] Source DC {link_source_dc[:8]} has {len(source_filters)} filter(s)"
        )

        active_source_filters = [
            f for f in source_filters if f.get("value") not in [None, [], "", False]
        ]

        logger.info(
            f"[{component_type}] Active source filters: {len(active_source_filters)} "
            f"(types: {[f.get('metadata', {}).get('interactive_component_type') for f in active_source_filters]})"
        )

        if not active_source_filters:
            logger.info(f"[{component_type}] No active source filters, skipping link")
            continue

        for source_filter in active_source_filters:
            filter_value = source_filter.get("value", [])
            source_column = source_filter.get("metadata", {}).get("column_name", "")

            if not filter_value:
                continue

            filter_values = filter_value if isinstance(filter_value, list) else [filter_value]

            resolved = resolve_link_values(
                project_id=project_id,
                source_dc_id=link_source_dc,
                source_column=source_column,
                filter_values=filter_values,
                target_dc_id=target_dc_id,
                token=access_token,
            )

            if resolved and resolved.get("resolved_values"):
                resolved_values = resolved["resolved_values"]
                target_column = resolved.get("target_column") or link.get("link_config", {}).get(
                    "target_field", source_column
                )

                link_filter = {
                    "index": f"link_{link.get('id', 'unknown')}",
                    "value": resolved_values,
                    "metadata": {
                        "dc_id": target_dc_id,
                        "column_name": target_column,
                        "interactive_component_type": "MultiSelect",
                    },
                }
                link_filters.append(link_filter)
                logger.debug(
                    f"[{component_type}] Link resolved: {len(filter_values)} values -> "
                    f"{len(resolved_values)} resolved to column '{target_column}' "
                    f"via {resolved.get('resolver_used', 'unknown')}"
                )

    return link_filters
