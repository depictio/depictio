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
from depictio.api.v1.deltatables_utils import LINK_NO_MATCH
from depictio.models.models.links import resolve_link_tag_refs

# Cache for link resolution results
_link_resolution_cache: Dict[str, Dict[str, Any]] = {}
LINK_RESOLUTION_CACHE_TTL_SECONDS = 300  # 5 minutes

# Resolution now scans lazily with the two needed columns projected, so it is far
# cheaper than the previous eager full-table read — but a translation whose join
# column is near-unique still returns millions of values, and that is a design
# limit, not a slow network. Keep the ceiling low enough that it surfaces as an
# error the user can act on instead of a request nobody ever answers.
LINK_RESOLUTION_TIMEOUT_S = 30.0


# How many links a filter may travel before we stop looking. A chain costs one
# resolution per hop and each hop's output is the next hop's input, so depth is
# multiplicative in both latency and value-list size — this is a safety rail, not
# a modelling limit. Three covers metadata -> samples -> features, which is the
# deepest real topology we ship.
MAX_LINK_HOPS = 3


class LinkResolutionError(RuntimeError):
    """A link could not be resolved — as opposed to resolving to nothing.

    The two must never be conflated. "Resolved to no values" is an answer: the
    filter matches nothing on the target, and the component should show an empty
    result. "Failed to resolve" is the absence of an answer, and the only honest
    responses are to raise or to show nothing — never to drop the filter, which
    renders every row and is indistinguishable from a filter the user didn't set.

    This used to be swallowed: a timeout returned ``None``, the caller read that
    as "no link filters", and the component came back unfiltered with no error
    anywhere.
    """


def _link_target_column(link: dict, resolved: dict | None = None) -> str | None:
    """The column a link's resolved values name on the *target* DC.

    Preference order (each falls through on ``None``, so an explicit ``or``
    chain rather than ``dict.get(key, default)``):

      1. ``resolved.target_column`` — explicit, if the resolver ever returns it.
      2. ``link_config.target_field`` — for resolvers that rename across DCs
         (e.g. MultiQC ``sample_mapping``). Often null for ``direct``.
      3. ``link.source_column`` — the link's join column. For a direct
         table->table link the join column has the same name on both sides.

    Never the user's filter column: that names something the target DC may not
    have, and ``apply_runtime_filters`` drops an unknown column silently — every
    row comes back and the component looks like it never filtered.
    """
    link_config = link.get("link_config") or {}
    return (
        (resolved or {}).get("target_column")
        or link_config.get("target_field")
        or link.get("source_column")
    )


def _link_paths(
    project_links: list[dict],
    origin_dc: str,
    target_dc_id: str,
    max_hops: int = MAX_LINK_HOPS,
) -> list[list[dict]]:
    """Every enabled link path from ``origin_dc`` to ``target_dc_id``.

    Filters do not only travel one hop. With A -> B -> C, a filter on A must
    still narrow a component reading C even though no A -> C link exists; the
    original implementation only matched links whose target *was* the component's
    DC, so anything beyond a direct neighbour silently went unfiltered.

    Breadth-first so the shortest path to a target is found first, and a DC is
    never revisited within a path (cycles in the link graph are legal to declare
    and would otherwise loop forever).
    """
    if origin_dc == target_dc_id:
        return []

    by_source: dict[str, list[dict]] = {}
    for link in project_links:
        if not link.get("enabled", True):
            continue
        by_source.setdefault(str(link.get("source_dc_id", "")), []).append(link)

    paths: list[list[dict]] = []
    # (current DC, path taken, DCs already on that path)
    queue: list[tuple[str, list[dict], set[str]]] = [(origin_dc, [], {origin_dc})]
    while queue:
        dc, path, seen = queue.pop(0)
        if len(path) >= max_hops:
            continue
        for link in by_source.get(dc, []):
            nxt = str(link.get("target_dc_id", ""))
            if not nxt or nxt in seen:
                continue
            if nxt == target_dc_id:
                paths.append(path + [link])
            else:
                queue.append((nxt, path + [link], seen | {nxt}))
    return paths


def _walk_link_path(
    path: list[dict],
    project_id: str,
    origin_column: str,
    origin_values: list,
    access_token: str,
    component_type: str,
) -> tuple[str | None, list]:
    """Resolve a filter along a chain of links, hop by hop.

    Each hop translates the values it receives into the next DC's join column;
    that output becomes the next hop's input.

    Returns ``(target_column, values)``. Three outcomes, and keeping them apart
    is the whole point:

    * **values** — the filter translated successfully.
    * **empty list** — it translated to nothing: the filter is satisfiable on
      the source but matches no row here, so the component must show no rows.
      The caller turns this into a ``LINK_NO_MATCH`` filter, because an empty
      value list would be read downstream as "no filter" and render everything.
    * **``(None, [])``** — the chain is unusable (no target column). Distinct
      from the above; the caller drops it rather than claiming a result.

    A failed resolution does not return at all — ``resolve_link_values`` raises
    ``LinkResolutionError`` so a timeout can never masquerade as "no filter".
    """
    column, values = origin_column, origin_values
    for hop, link in enumerate(path):
        source_dc = str(link.get("source_dc_id", ""))
        next_dc = str(link.get("target_dc_id", ""))
        resolved = resolve_link_values(
            project_id=project_id,
            source_dc_id=source_dc,
            source_column=column,
            filter_values=values,
            target_dc_id=next_dc,
            token=access_token,
        )
        final_column = _link_target_column(path[-1])
        if resolved is None:
            # No link declared for this hop (404). Nothing to translate through.
            logger.info(
                f"[{component_type}] Link chain stopped at hop {hop + 1}/{len(path)} "
                f"({source_dc[:8]} -> {next_dc[:8]}): no link"
            )
            return None, []
        if not resolved.get("resolved_values"):
            # Resolved, to nothing. Every later hop would also be empty, so stop
            # here and report the empty match on the FINAL target column.
            logger.info(
                f"[{component_type}] Link chain matched nothing at hop "
                f"{hop + 1}/{len(path)} ({source_dc[:8]} -> {next_dc[:8]})"
            )
            return final_column, []
        values = resolved["resolved_values"]
        column = _link_target_column(link, resolved)
        if not column:
            logger.warning(
                f"[{component_type}] Skipping link {link.get('id')!r} at hop {hop + 1}: "
                f"could not resolve a target column "
                f"(link.source_column={link.get('source_column')!r}, "
                f"link_config.target_field={(link.get('link_config') or {}).get('target_field')!r})"
            )
            return None, []
    return column, values


def _agg_hash(dc_id: str) -> str:
    """A DC's ``aggregation_hash``, for use as a cache-key salt.

    The hash is derived from the Delta log (table version + active files), so
    it changes whenever the data behind the DC changes — which is what lets a
    cache key expire on *data* change rather than only on elapsed time. The
    ``aggregation_version`` counter would also move on a re-ingest, but it only
    counts writes; the hash describes the state they produced.

    Returns ``"?"`` when it can't be read, so a failed lookup produces a key
    that never collides with a real hash — stale data is the failure mode worth
    avoiding here, an extra resolution is not.
    """
    try:
        from depictio.api.v1.deltatables_utils import _get_aggregation_hash

        return str(_get_aggregation_hash(str(dc_id)) or "none")
    except Exception:
        return "?"


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

    # Salted with both DCs' aggregation_hash: a link resolves which target rows
    # correspond to the filtered source rows, so any update to either side
    # changes the correct answer. Without the salt this cache kept serving the
    # pre-update resolution for its full 5-minute TTL and the affected rows were
    # simply absent from every linked component — with nothing to indicate it.
    versions = f"{_agg_hash(source_dc_id)}_{_agg_hash(target_dc_id)}"
    cache_key = (
        f"link_{project_id}_{source_dc_id}_{target_dc_id}_{versions}_"
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
            timeout=LINK_RESOLUTION_TIMEOUT_S,
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
            # No such link. That is a real answer — there is nothing to resolve
            # — so it stays a quiet ``None``.
            return None

        else:
            raise LinkResolutionError(
                f"Link resolution failed for {source_dc_id} -> {target_dc_id}: "
                f"HTTP {response.status_code} {response.text[:200]}"
            )

    except httpx.TimeoutException as e:
        # Loud. Previously this returned None, the caller read it as "no link
        # filters to add", and the component rendered EVERY row — a wrong answer
        # presented as a normal one. An error the user can see is strictly
        # better than silently unfiltered data.
        raise LinkResolutionError(
            f"Link resolution timed out after {LINK_RESOLUTION_TIMEOUT_S:.0f}s for "
            f"{source_dc_id} -> {target_dc_id}. The source data collection is too "
            f"large to translate this filter through."
        ) from e
    except LinkResolutionError:
        raise
    except Exception as e:
        raise LinkResolutionError(
            f"Link resolution error for {source_dc_id} -> {target_dc_id}: {e}"
        ) from e


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
    # Resolve template-time ``tag:`` link placeholders before walking the
    # graph — see ``resolve_link_tag_refs``.
    resolve_link_tag_refs(project_data)
    project_id = str(project_data.get("_id", ""))
    project_links = project_data.get("links", [])

    if not project_id or not project_links:
        return link_filters

    # Walk the link GRAPH, not just direct neighbours: a filter on A must still
    # reach a component on C when the project declares A -> B -> C. Only links
    # whose target was the component's own DC used to be considered, so anything
    # further than one hop was silently ignored — the component rendered
    # unfiltered with nothing to indicate it.
    for origin_dc, source_filters in filters_by_dc.items():
        if origin_dc == target_dc_id:
            continue  # same DC: the filter already applies natively

        active_source_filters = [
            f for f in source_filters if f.get("value") not in [None, [], "", False]
        ]
        if not active_source_filters:
            continue

        paths = _link_paths(project_links, origin_dc, target_dc_id)
        if not paths:
            continue

        logger.info(
            f"[{component_type}] {origin_dc[:8]} -> {target_dc_id[:8]}: "
            f"{len(paths)} link path(s), depths {sorted({len(p) for p in paths})}"
        )

        for path in paths:
            for source_filter in active_source_filters:
                filter_value = source_filter.get("value", [])
                if not filter_value:
                    continue
                filter_values = filter_value if isinstance(filter_value, list) else [filter_value]
                origin_column = source_filter.get("metadata", {}).get("column_name", "")

                target_column, resolved_values = _walk_link_path(
                    path=path,
                    project_id=project_id,
                    origin_column=origin_column,
                    origin_values=filter_values,
                    access_token=access_token,
                    component_type=component_type,
                )
                if not target_column:
                    continue  # unusable chain — not a result, so claim nothing

                # One synthetic filter per (path, source filter). The path id
                # keeps two routes to the same target from colliding on index.
                path_id = "_".join(str(link.get("id", "?")) for link in path)
                link_filters.append(
                    {
                        "index": f"link_{path_id}",
                        # Empty means "matched nothing", which must survive as a
                        # filter. Tagging it keeps it from being read downstream
                        # as an unset filter and rendering every row.
                        "value": resolved_values,
                        "metadata": {
                            "dc_id": target_dc_id,
                            "column_name": target_column,
                            "interactive_component_type": (
                                "MultiSelect" if resolved_values else LINK_NO_MATCH
                            ),
                        },
                    }
                )
                logger.debug(
                    f"[{component_type}] Link chain resolved over {len(path)} hop(s): "
                    f"{len(filter_values)} values -> {len(resolved_values)} on "
                    f"column '{target_column}'"
                )

    return link_filters
