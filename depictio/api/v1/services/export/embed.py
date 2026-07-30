"""Build a self-contained HTML page rendering one dashboard component offline.

This is the format with near-total coverage. It injects a precomputed payload into
a prebuilt single-file React bundle that runs the viewer's *real*
``ComponentRenderer`` — so component types with no server-side figure (tables,
cards, images, and the advanced-viz kinds whose Plotly spec is built in
TypeScript) render correctly without any Python port.

The payload shape and its keying rules come from
``depictio/viewer/src/offline/mockApi.ts``, the offline API shim the bundle is
built against. Two keying rules matter:

* figure / table / map / image / multiqc are keyed by component ``index``
* interactive / advanced_viz are keyed by ``dc_id``

The second rule is a collision risk on a real dashboard, where two advanced-viz
components can share a data collection. We do what the catalog preview does and
rewrite ``dc_id`` in the *embedded copy* of the metadata to a synthetic
per-component value, so payload keys are unique. Nothing inside the offline bundle
needs the real id.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.export.bundle import (
    OfflineBundleError,
    inject,
    svg_data_uris,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str

#: Placeholder the embed bundle emits for its payload.
EMBED_SENTINEL = "__DEPICTIO_EMBED_PAYLOAD__"

#: Prebuilt single-file bundle (`pnpm --filter depictio-viewer run build:embed`).
_VIEWER_DIR = Path(__file__).resolve().parents[4] / "viewer"
EMBED_TEMPLATE_PATH = _VIEWER_DIR / "dist-embed" / "embed.html"

_BUILD_HINT = "cd depictio/viewer && pnpm run build:embed"


def _synthetic_dc_id(index: str, suffix: str = "") -> str:
    """Per-component data key, replacing the real ``dc_id`` in the embedded copy."""
    return f"embed::{index}{f'::{suffix}' if suffix else ''}"


def _empty_data() -> dict[str, Any]:
    """The ``OfflineData`` shape mockApi.ts expects, with every bucket present."""
    return {
        "figures": {},
        "tables": {},
        "maps": {},
        "images": {},
        "multiqc": {},
        "multiqcGeneralStats": {},
        "cards": {"values": {}, "secondary": {}, "aggregations": {}},
        "unique": {},
        "ranges": {},
        "specs": {},
        "advancedVizData": {},
        "compute": {},
    }


def _logo_data_uris() -> dict[str, str]:
    """Inline the MultiQC logos so they survive going offline."""
    return svg_data_uris(
        _VIEWER_DIR / "public" / "logos",
        {
            f"/dashboard-beta/logos/{name}": name
            for name in ("multiqc_icon_dark.svg", "multiqc_icon_white.svg")
        },
    )


def _script_hashes(html: str) -> list[str]:
    """SHA-256 hashes of every inline ``<script>`` body, for the CSP.

    Preferable to ``'unsafe-inline'``: the bundle's scripts are known at the moment
    we serve them, so they can be pinned exactly.
    """
    import base64
    import re

    hashes: list[str] = []
    for match in re.finditer(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE
    ):
        digest = hashlib.sha256(match.group(1).encode()).digest()
        hashes.append(base64.b64encode(digest).decode())
    return hashes


def build_embed_csp() -> str:
    """CSP for an embed response.

    ``connect-src 'none'`` is the interesting one: the bundle makes no network
    calls at all, so declaring that both hardens the page and proves the claim.
    """
    origins = list(settings.fastapi.embed_allowed_origins)
    frame_ancestors = " ".join(origins) if origins else "'none'"
    if not origins:
        logger.info(
            "export: DEPICTIO_FASTAPI_EMBED_ALLOWED_ORIGINS is empty — embeds render "
            "standalone but cannot be framed by any site."
        )
    return (
        "default-src 'none'; "
        "script-src {script_src}; "
        "style-src 'unsafe-inline'; "
        "img-src data: blob:; "
        "font-src data:; "
        "connect-src 'none'; "
        f"frame-ancestors {frame_ancestors}; "
        "base-uri 'none'; "
        "form-action 'none'"
    )


def _finalise_csp(html: str) -> str:
    """Resolve the ``script-src`` placeholder against the served HTML."""
    template = build_embed_csp()
    if settings.fastapi.embed_csp_unsafe_inline:
        return template.format(script_src="'unsafe-inline'")
    hashes = _script_hashes(html)
    if not hashes:
        # No inline script found — either the bundle changed shape or it loads
        # externally. 'self' is the safe interpretation; the escape hatch exists
        # for when it isn't.
        return template.format(script_src="'self'")
    return template.format(script_src=" ".join(f"'sha256-{h}'" for h in hashes))


# --- per-type payload builders ---------------------------------------------
#
# Each returns nothing and mutates `data` in place, mirroring how mockApi.ts reads
# it. They call the same render handlers the live viewer uses, so an embed and the
# dashboard cannot diverge.


async def _add_figure(data, dashboard_id, component_id, filters, theme, user, token) -> None:
    from fastapi import Response

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_figure_endpoint

    data["figures"][component_id] = await render_figure_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        # The handler only uses this to set an X-Celery-Path diagnostic header,
        # which is meaningless for an embed; a throwaway Response absorbs it.
        response=Response(),
        current_user=user,
        access_token=token,
    )


def _add_map(data, dashboard_id, component_id, filters, theme, user, token) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_map_endpoint

    data["maps"][component_id] = render_map_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        current_user=user,
        access_token=token,
    )


def _add_table(data, dashboard_id, component_id, filters, user, token) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import render_table_endpoint

    # The offline shim slices client-side from one block, so fetch the page the
    # viewer would show rather than the whole table.
    result = render_table_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "start": 0, "limit": 1000},
        current_user=user,
        access_token=token,
    )
    data["tables"][component_id] = {
        "columns": result.get("columns") or [],
        "rows": result.get("rows") or [],
        "total": result.get("total") or 0,
    }


def _add_image(data, dashboard_id, component_id, filters, user, token) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        render_image_paths_endpoint,
    )

    data["images"][component_id] = render_image_paths_endpoint(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters},
        current_user=user,
        access_token=token,
    )


def _add_card(data, dashboard_id, component_id, filters, user, token) -> None:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import bulk_compute_cards

    result = bulk_compute_cards(
        dashboard_id=dashboard_id,
        request={"filters": filters, "component_ids": [component_id]},
        current_user=user,
        access_token=token,
    )
    cards = data["cards"]
    for key, bucket in (
        ("values", "values"),
        ("secondary_values", "secondary"),
        ("aggregations", "aggregations"),
    ):
        value = (result.get(key) or {}).get(component_id)
        if value is not None:
            cards[bucket][component_id] = value


def _add_multiqc(data, dashboard_id, component_id, component, filters, theme, user) -> None:
    from fastapi.responses import JSONResponse

    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _resolve_selected_keys,
        render_multiqc_endpoint,
        render_multiqc_general_stats_endpoint,
    )

    *_, is_general_stats = _resolve_selected_keys(component)
    handler = render_multiqc_general_stats_endpoint if is_general_stats else render_multiqc_endpoint
    result = handler(
        dashboard_id=dashboard_id,
        component_id=component_id,
        request={"filters": filters, "theme": theme},
        current_user=user,
    )
    if isinstance(result, JSONResponse):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "multiqc_cache_warming",
                "message": (
                    "MultiQC figures for this data collection are still being prepared. "
                    "Retry shortly."
                ),
            },
        )
    bucket = "multiqcGeneralStats" if is_general_stats else "multiqc"
    data[bucket][component_id] = result


async def _add_interactive(data, component, synthetic_dc_id, user) -> None:
    """Populate the value universe an interactive control needs to render.

    Keyed by the synthetic dc_id so a dashboard with several controls over the
    same data collection does not collide.
    """
    from depictio.api.v1.endpoints.deltatables_endpoints.routes import specs as fetch_specs

    column = component.get("column_name")
    real_dc_id = component.get("dc_id")

    specs: Any = {}
    try:
        specs = await fetch_specs(data_collection_id=real_dc_id, current_user=user)
    except Exception as exc:
        logger.warning("export: specs lookup failed for dc=%s: %s", real_dc_id, exc)
    data["specs"][synthetic_dc_id] = specs

    if not column:
        return

    # Derive min/max from the specs the same way fetchColumnRange does in api.ts,
    # rather than issuing a second query.
    entry: dict[str, Any] = {}
    if isinstance(specs, list):
        entry = next((e for e in specs if e.get("name") == column), {}) or {}
        entry = entry.get("specs") or {}
    elif isinstance(specs, dict):
        entry = (specs.get(column) or {}) if isinstance(specs.get(column), dict) else {}
    data["ranges"][f"{synthetic_dc_id}::{column}"] = {
        "min": entry.get("min"),
        "max": entry.get("max"),
    }

    try:
        from bson import ObjectId

        from depictio.api.v1.deltatables_utils import load_deltatable_lite
        from depictio.api.v1.services.export.delta_location import init_data_for

        # Without init_data the loader falls back to an authenticated HTTP call it
        # cannot make from here, and the control renders with an empty option list
        # while the response still looks healthy. See delta_location.py.
        init_data = init_data_for(real_dc_id, component.get("dc_config") or {})
        if not init_data:
            raise LookupError(f"data collection {real_dc_id} has no materialised Delta table")

        df = load_deltatable_lite(
            workflow_id=ObjectId(str(component.get("wf_id"))),
            data_collection_id=str(real_dc_id),
            select_columns=[column],
            load_for_options=True,
            init_data=init_data,
        )
        values = [v for v in df.get_column(column).unique().to_list() if v is not None]
        data["unique"][f"{synthetic_dc_id}::{column}"] = sorted(str(v) for v in values)
    except Exception as exc:
        logger.warning(
            "export: unique-values lookup failed for dc=%s col=%s: %s", real_dc_id, column, exc
        )
        data["unique"][f"{synthetic_dc_id}::{column}"] = []


def _add_advanced_viz(data, component, synthetic_dc_id, filters, viz_kind, user) -> None:
    """Precompute whatever the advanced-viz renderer would have fetched.

    Three shapes, matching the three fetch paths in mockApi.ts: ``compute`` for the
    Celery-backed kinds, ``advancedVizData`` for the tidy-data kinds, and a
    ``::newick`` entry for the phylogenetic tree.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import _build_filter_metadata
    from depictio.api.v1.services.advanced_viz.data import load_tidy_columns

    config = component.get("config") or {}
    filter_metadata = _build_filter_metadata(filters)
    wf_id = str(component.get("wf_id"))
    real_dc_id = str(component.get("dc_id"))

    celery_kinds = {
        "complex_heatmap": "compute_complex_heatmap",
        "upset_plot": "compute_upset",
        "sankey": "compute_sankey",
        "embedding": "compute_embedding",
        "coverage_track": "compute_coverage_track",
    }
    if viz_kind in celery_kinds:
        from depictio.api.v1 import celery_tasks

        task = getattr(celery_tasks, celery_kinds[viz_kind])
        data["compute"][synthetic_dc_id] = task.run(
            {**config, "wf_id": wf_id, "dc_id": real_dc_id, "filter_metadata": filter_metadata}
        )
        return

    if viz_kind == "phylogenetic":
        # The tree lives in a *different* DC named inside config, so it needs its
        # own synthetic key — see PhylogeneticRenderer.tsx:134.
        from depictio.api.v1.endpoints.advanced_viz_endpoints.routes import (
            get_phylogeny_newick,
        )

        tree_dc_id = PyObjectId(str(config.get("tree_dc_id") or real_dc_id))
        tree_key = _synthetic_dc_id(str(component.get("index")), "tree")
        try:
            data["advancedVizData"][f"{tree_key}::newick"] = get_phylogeny_newick(
                data_collection_id=tree_dc_id, current_user=user
            )
        except Exception as exc:
            logger.warning("export: newick load failed for dc=%s: %s", tree_dc_id, exc)

    columns = _advanced_viz_columns(config)
    if columns:
        data["advancedVizData"][synthetic_dc_id] = load_tidy_columns(
            wf_id=wf_id,
            dc_id=real_dc_id,
            columns=columns,
            filter_metadata=filter_metadata,
        )


def _advanced_viz_columns(config: dict[str, Any]) -> list[str]:
    """Every column the config binds, without needing a per-kind resolver.

    Advanced-viz configs name their bindings with ``*_col`` / ``*_cols`` keys, so
    collecting those covers any kind — including ones with no Python builder.
    """
    columns: list[str] = []
    for key, value in config.items():
        if not (key.endswith("_col") or key.endswith("_cols")):
            continue
        if isinstance(value, str) and value:
            columns.append(value)
        elif isinstance(value, list):
            columns.extend(v for v in value if isinstance(v, str) and v)
    return list(dict.fromkeys(columns))


async def build_component_embed_payload(
    *,
    dashboard_doc: dict,
    component: dict,
    theme: str,
    filters: list[dict],
    access_token: str | None,
    current_user: Any,
) -> dict[str, Any]:
    """Compute the ``window.__DEPICTIO_EMBED__`` blob for one component."""
    component_id = str(component.get("index"))
    component_type = component.get("component_type") or ""
    dashboard_id = dashboard_doc.get("dashboard_id")

    from depictio.api.v1.services.export.capabilities import resolve_viz_kind

    viz_kind = resolve_viz_kind(component.get("viz_kind"))
    data = _empty_data()

    # The embedded metadata is a copy: dc_id is rewritten to a per-component value
    # so the dc-keyed payload buckets cannot collide.
    embedded = convert_objectid_to_str(dict(component))
    synthetic = _synthetic_dc_id(component_id)
    if component_type in ("interactive", "advanced_viz"):
        embedded["dc_id"] = synthetic
        if component_type == "advanced_viz" and (component.get("config") or {}).get("tree_dc_id"):
            embedded.setdefault("config", {})
            embedded["config"] = {
                **embedded["config"],
                "tree_dc_id": _synthetic_dc_id(component_id, "tree"),
            }

    if component_type == "figure":
        await _add_figure(
            data, dashboard_id, component_id, filters, theme, current_user, access_token
        )
    elif component_type == "map":
        _add_map(data, dashboard_id, component_id, filters, theme, current_user, access_token)
    elif component_type == "table":
        _add_table(data, dashboard_id, component_id, filters, current_user, access_token)
    elif component_type == "image":
        _add_image(data, dashboard_id, component_id, filters, current_user, access_token)
    elif component_type == "card":
        _add_card(data, dashboard_id, component_id, filters, current_user, access_token)
    elif component_type == "multiqc":
        _add_multiqc(data, dashboard_id, component_id, component, filters, theme, current_user)
    elif component_type == "interactive":
        await _add_interactive(data, component, synthetic, current_user)
    elif component_type == "advanced_viz":
        _add_advanced_viz(data, component, synthetic, filters, viz_kind, current_user)
    elif component_type == "text":
        pass  # Renders entirely from metadata.
    else:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_export",
                "message": f"{component_type!r} cannot be embedded.",
                "component_type": component_type,
                "supported_formats": [],
            },
        )

    return {
        "theme": "dark" if theme == "dark" else "light",
        "component": embedded,
        "title": component.get("title") or "",
        "data": data,
    }


async def render_component_embed(
    *,
    dashboard_doc: dict,
    component: dict,
    theme: str,
    filters: list[dict],
    access_token: str | None,
    current_user: Any,
) -> tuple[str, str]:
    """Render the offline HTML page and the CSP header that should accompany it.

    Returns:
        ``(html, content_security_policy)``

    Raises:
        HTTPException: 503 when the embed bundle has not been built.
    """
    payload = await build_component_embed_payload(
        dashboard_doc=dashboard_doc,
        component=component,
        theme=theme,
        filters=filters,
        access_token=access_token,
        current_user=current_user,
    )
    try:
        html = inject(
            EMBED_TEMPLATE_PATH,
            EMBED_SENTINEL,
            payload,
            asset_replacements=_logo_data_uris(),
            build_hint=_BUILD_HINT,
        )
    except OfflineBundleError as exc:
        logger.error("export: embed bundle unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"code": "bundle_unavailable", "message": str(exc)},
        ) from exc

    return html, _finalise_csp(html)
