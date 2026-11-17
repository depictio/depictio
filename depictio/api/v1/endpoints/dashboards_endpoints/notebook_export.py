"""Dashboard → notebook: preflight and export endpoints.

Everything that needs Mongo, Delta or link resolution happens here, in
``build_export_plan``; the plan is then handed to the generator, which only
turns it into cells. The helpers come from ``routes`` — the same ones the
funnel endpoint uses — so the stage counts in the notebook are the counts the
funnel view showed, computed by the same code.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from bson import ObjectId
from fastapi import Depends, HTTPException, Response

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    dashboards_endpoint_router,
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    NotebookBuilder,
    StagePlan,
)
from depictio.api.v1.services.notebook_export.reading_order import filter_icon_id
from depictio.models.models.analysis_state import (
    AnalysisState,
    NotebookExportRequest,
    NotebookPreflight,
    NotebookRenderStatus,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.users import User

STAGE_COMPONENT_TYPES: frozenset[str] = frozenset(
    {"figure", "table", "map", "image", "card", "interactive"}
)

TAB_PROJECTION = {
    k: 1
    for k in (
        "dashboard_id",
        "title",
        "subtitle",
        "tab_order",
        "is_main_tab",
        "main_tab_name",
        "parent_dashboard_id",
        "grid_sections",
        "filter_sections",
        "stored_metadata",
        # Where each tile sits on its tab's grid (``box-<index>``): the
        # document reads a tab in the order the grid draws it.
        "right_panel_layout_data",
        "project_id",
        # The footer links the live dashboard only when a reader can open it.
        "is_public",
        "brand_theme",
        # Sidebar precedence is tab_icon(_color) || icon(_color) — both are
        # needed to replicate a tab's own icon in the export.
        "tab_icon",
        "tab_icon_color",
        "icon",
        "icon_color",
        # The colour per category value code-mode figures read
        # (`depictio_category_colors`).
        "category_colors",
    )
}


def _require_enabled() -> None:
    if not settings.notebook_export.enabled:
        raise HTTPException(status_code=404, detail="Notebook export is disabled.")


def _order_active_filters(
    filters: list[dict[str, Any]], stage_order: list[str]
) -> list[dict[str, Any]]:
    """The funnel modal's reconcile rule: ranked ones first, the rest in their order."""
    by_index = {str(f.get("index")): f for f in filters}
    ranked: list[dict[str, Any]] = []
    for idx in stage_order:
        f = by_index.pop(str(idx), None)
        if f is not None:
            ranked.append(f)
    for f in filters:
        if by_index.pop(str(f.get("index")), None) is not None:
            ranked.append(f)
    return ranked


def _dc_tags(project: dict[str, Any] | None) -> dict[str, str]:
    tags: dict[str, str] = {}
    for wf in (project or {}).get("workflows") or []:
        for dc in wf.get("data_collections") or []:
            dc_id = str(dc.get("_id") or dc.get("id") or "")
            tag = dc.get("data_collection_tag") or dc.get("tag")
            if dc_id and tag:
                tags[dc_id] = str(tag)
    for dc in (project or {}).get("data_collections") or []:
        dc_id = str(dc.get("_id") or dc.get("id") or "")
        tag = dc.get("data_collection_tag") or dc.get("tag")
        if dc_id and tag:
            tags.setdefault(dc_id, str(tag))
    return tags


def _entry_key(entry: dict[str, Any]) -> str:
    return json.dumps(
        [entry.get("index"), entry.get("column_name"), entry.get("value")],
        sort_keys=True,
        default=str,
    )


def _cleaned_with_index(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for f in filters:
        cleaned = routes._build_filter_metadata([f])
        if not cleaned:
            continue
        entry = dict(cleaned[0])
        entry["index"] = str(f.get("index") or "")
        entry["link"] = entry["index"].startswith("link_")
        out.append(entry)
    return out


def _dtypes_for(family_doc: dict[str, Any], dc_id: str, wf_id: str | None) -> dict | None:
    """The DC's Delta schema, or ``None`` when it cannot be read at export time."""
    if not wf_id:
        return None
    try:
        from depictio.api.v1.deltatables_utils import _get_cached_dtypes, open_deltatable_scan

        scan = open_deltatable_scan(
            workflow_id=ObjectId(str(wf_id)),
            data_collection_id=dc_id,
            init_data=routes._funnel_init_data(family_doc, dc_id),
        )
        if scan is None:
            return None
        dtypes = _get_cached_dtypes(scan, str(dc_id), None)
        return dict(dtypes) if dtypes else None
    except Exception as exc:  # the notebook still works: predicates fall back to string casts
        logger.debug(f"notebook export: schema unavailable for {dc_id}: {exc}")
        return None


def _who(current_user: Any) -> str | None:
    for attr in ("email", "username", "name"):
        value = getattr(current_user, attr, None)
        if value:
            return str(value)
    return None


# The default wordmark shipped with the app — what an unbranded ("inherit")
# instance shows in its own chrome, so an unbranded export's header matches it
# rather than looking generic. Read from disk once; nothing here changes at
# runtime, unlike an admin-uploaded logo.
_DEFAULT_LOGO_PATH = (
    Path(__file__).resolve().parents[3] / "static_assets/images/logos/logo_black.svg"
)


def _data_uri(content: bytes, content_type: str | None) -> str:
    mime = content_type or mimetypes.guess_type("x.svg")[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


# The tab icon, which is the app's own and not the brand's: the live SPA ships
# one favicon whatever an instance is branded as, and a reader with the report
# and the dashboard open in two tabs should see the same mark on both.
_FAVICON_PATH = Path(__file__).resolve().parents[3] / "static_assets/images/icons/favicon.png"


@lru_cache(maxsize=1)
def _favicon_data_uri() -> str | None:
    try:
        return _data_uri(_FAVICON_PATH.read_bytes(), "image/png")
    except OSError as exc:  # a missing icon is never worth failing the export over
        logger.debug(f"notebook export: favicon unavailable: {exc}")
        return None


_STATIC_ASSETS = Path(__file__).resolve().parents[3] / "static_assets"
#: A text tile's header logo is inlined up to this size; past it the tile shows its title.
_MAX_TEXT_LOGO_BYTES = 1024 * 1024
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _image_mime(data: bytes) -> str | None:
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic):
            return mime
    if data[:8] == b"RIFF" or data[8:12] == b"WEBP":
        return "image/webp" if data[8:12] == b"WEBP" else None
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "image/svg+xml"
    return None


def _image_data_uri(ref: str | None) -> str | None:
    """An image the app shows by path or URL, as a data URI, or ``None``.

    ``/assets/...`` is one of the app's own static images (the dashboards'
    workflow marks), read from disk; an http(s) URL goes through the SSRF
    gateway, capped and checked to be an image. A data URI is kept. Any
    failure answers ``None``: a logo is never worth failing an export over.
    """
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith("data:image/"):
        return ref
    try:
        if ref.startswith("/assets/"):
            path = (_STATIC_ASSETS / ref[len("/assets/") :]).resolve()
            if _STATIC_ASSETS.resolve() not in path.parents or not path.is_file():
                return None
            data = path.read_bytes()
        elif ref.startswith(("https://", "http://")):
            from depictio.api.v1.remote_fetch import fetch_validated_bytes

            data = fetch_validated_bytes(ref, max_bytes=_MAX_TEXT_LOGO_BYTES, timeout=10)
        else:
            return None
    except Exception as exc:  # unreachable, rejected, too large: no logo
        logger.debug(f"notebook export: image {ref} not inlined: {exc}")
        return None
    mime = _image_mime(data)
    return _data_uri(data, mime) if mime else None


def _resolve_text_logos(tabs: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Every text tile's header logo (``logo`` / ``logo_dark``), inlined."""
    out: dict[str, dict[str, str]] = {}
    for tab in tabs:
        for meta in tab.get("stored_metadata") or []:
            if not isinstance(meta, dict) or meta.get("component_type") != "text":
                continue
            got = {
                kind: uri
                for kind, key in (("light", "logo"), ("dark", "logo_dark"))
                if (uri := _image_data_uri(meta.get(key)))
            }
            if got:
                out[str(meta.get("index") or "")] = got
    return out


@lru_cache(maxsize=1)
def _depictio_mark() -> str | None:
    """The Depictio wordmark the app's "Powered by" shows (``logo_black.svg``)."""
    try:
        return _data_uri(_DEFAULT_LOGO_PATH.read_bytes(), "image/svg+xml")
    except OSError as exc:
        logger.debug(f"notebook export: wordmark unavailable: {exc}")
        return None


@lru_cache(maxsize=1)
def _depictio_version() -> str | None:
    try:
        from depictio.version import get_version

        return get_version()
    except Exception as exc:  # the export is not worth failing over a version string
        logger.debug(f"notebook export: version unavailable: {exc}")
        return None


def _resolve_export_brand(
    dashboard_id: Any, dashboard_brand_theme: dict[str, Any] | None
) -> dict[str, Any]:
    """The header byline: instance identity, with this dashboard's own override on top.

    Mirrors what the live app's chrome shows (``/utils/public-config`` +
    ``useBrandLogoMode``): env defaults, folded with the admin panel's live
    overrides, folded with this dashboard's own ``brand_theme`` — so a
    dashboard branded for e.g. a specific project carries that identity into
    its export too, not just the instance default. The logo is baked in as a
    data URI (base64) rather than linked, matching every other asset in these
    exports: the file is meant to still work months later, off the network
    that served it.
    """
    from depictio.api.v1.services.branding import (
        dashboard_logo_key,
        get_effective_brand_theme,
        instance_logo_key,
        read_logo_asset,
    )
    from depictio.models.models.branding import BrandTheme, merge_brand_themes, resolve_brand_theme

    try:
        instance_theme = get_effective_brand_theme()
        dash_theme = BrandTheme(**(dashboard_brand_theme or {}))
        theme = resolve_brand_theme(merge_brand_themes(instance_theme, dash_theme))
    except Exception as exc:  # a broken theme document should not break the export
        logger.debug(f"notebook export: brand theme unavailable: {exc}")
        theme = None

    brand: dict[str, Any] = {"app_name": (theme.app_name if theme else None) or "Depictio"}
    if theme:
        brand["primary"] = theme.primary
        # The report's Paper theme sets its type from these (the app's own
        # `buildDepictioTheme` does), Inter when the brand names none.
        if theme.font_family:
            brand["font_family"] = theme.font_family
        if theme.headings_font_family:
            brand["headings_font_family"] = theme.headings_font_family

    logo_data_uri: str | None = None
    try:
        if theme and theme.logo_mode == "custom" and theme.logo_url:
            # An upload (dashboard-level or instance-level) lives in Mongo under
            # a predictable key — read the bytes directly rather than looping
            # the export's own HTTP request back through the API. Only a
            # genuinely external `logo_url` (an admin-configured CDN link) ever
            # needs the network.
            stored = read_logo_asset(dashboard_logo_key(dashboard_id)) or read_logo_asset(
                instance_logo_key("light")
            )
            if stored:
                logo_data_uri = _data_uri(*stored)
            elif theme.logo_url.startswith("http"):
                import httpx

                resp = httpx.get(theme.logo_url, timeout=5.0)
                resp.raise_for_status()
                logo_data_uri = _data_uri(resp.content, resp.headers.get("content-type"))
        elif not theme or theme.logo_mode == "inherit":
            content = _DEFAULT_LOGO_PATH.read_bytes()
            logo_data_uri = _data_uri(content, "image/svg+xml")
        # logo_mode == "none": the brand explicitly asks for no logo.
    except Exception as exc:  # a cosmetic byline is never worth failing the export over
        logger.debug(f"notebook export: brand logo unavailable: {exc}")
    if logo_data_uri:
        brand["logo_data_uri"] = logo_data_uri
    return brand


def _resolve_tab_brands(
    tabs: list[dict[str, Any]], *, main_brand: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Every tab's own resolved brand, keyed by its ``dashboard_id``.

    Each tab in a family is its own dashboard document with its own possible
    ``brand_theme`` override (#397), the same as the main tab; ``main_brand``
    is already resolved by the caller and reused here rather than twice.
    """
    out: dict[str, dict[str, Any]] = {}
    for i, tab in enumerate(tabs):
        dash_id = str(tab.get("dashboard_id") or "")
        if not dash_id:
            continue
        out[dash_id] = (
            main_brand if i == 0 else _resolve_export_brand(dash_id, tab.get("brand_theme"))
        )
    return out


def _resolve_tab_icons(tabs: list[dict[str, Any]]) -> dict[str, str]:
    """Every Iconify id a tab or one of its grid sections uses, resolved once.

    From the viewer's bundled icon subset (``icons.py``), so no Iconify call
    happens on the request path for any icon the viewer itself can draw.
    """
    from depictio.api.v1.services.icons import resolve_icons
    from depictio.api.v1.services.notebook_export.generator import (
        FILTERS_ICON,
        FUNNEL_ICON,
        INLINE_ICON_RE,
        METHODS_ICON,
        RESULTS_ICON,
        SUMMARY_ICON,
    )
    from depictio.api.v1.services.notebook_export.provenance import (
        EXPORT_DETAILS_ICON,
        PROVENANCE_ICON,
        RUN_ICON,
    )
    from depictio.api.v1.services.notebook_export.reading_order import tab_icon_id

    # The headings the export writes itself, alongside the dashboard's own.
    icon_ids: set[str] = {
        PROVENANCE_ICON,
        EXPORT_DETAILS_ICON,
        RUN_ICON,
        METHODS_ICON,
        RESULTS_ICON,
        FILTERS_ICON,
        SUMMARY_ICON,
        FUNNEL_ICON,
    }
    for tab in tabs:
        icon_ids.add(tab_icon_id(tab))
        for spec in tab.get("grid_sections") or []:
            if isinstance(spec, dict):
                icon_ids.add(str(spec.get("icon") or ""))
        # Every filter the panel could list, so the export's own summary can
        # show the same icon the panel does.
        for meta in tab.get("stored_metadata") or []:
            if isinstance(meta, dict) and meta.get("component_type") == "interactive":
                icon_ids.add(filter_icon_id(meta))
            # A text tile's inline icons, `![](icon:mdi:flask-outline)`.
            if isinstance(meta, dict) and meta.get("component_type") == "text":
                for field in ("title", "body"):
                    icon_ids.update(INLINE_ICON_RE.findall(str(meta.get(field) or "")))
    return resolve_icons(icon_ids)


def _export_text_values(
    tabs: list[dict[str, Any]],
    filters: list[dict[str, Any]],
    current_user: User,
    access_token: str | None,
    pins: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Every live-value text tile's values under the exported filters, by its index.

    The same call the viewer makes (``bulk_compute_cards`` with the tiles'
    indexes), one per tab. Best effort: a tab whose values cannot be computed
    leaves its tiles printing the values the document computes when it runs.
    """
    out: dict[str, dict[str, Any]] = {}
    pins = pins or {}
    for tab in tabs:
        texts = [
            str(m.get("index"))
            for m in tab.get("stored_metadata") or []
            if isinstance(m, dict)
            and m.get("component_type") == "text"
            and routes._text_has_live_values(m)
        ]
        if not texts:
            continue
        try:
            payload = routes.bulk_compute_cards(
                dashboard_id=PyObjectId(str(tab.get("dashboard_id"))),
                request={"filters": filters, "component_ids": texts, **pins},
                current_user=current_user,
                access_token=access_token,
            )
        except Exception as exc:  # noqa: BLE001 - the document computes them itself
            logger.debug(
                f"notebook export: text values unavailable for {tab.get('dashboard_id')}: {exc}"
            )
            continue
        for idx in texts:
            got = (payload.get("values") or {}).get(idx)
            if isinstance(got, dict):
                out[idx] = got
    return out


def _overlay_definitions(
    tabs: list[dict[str, Any]], version_id: str, project_dc_ids: set[str], warnings: list[str]
) -> list[dict[str, Any]]:
    """The family as ``version_id`` defined its components.

    The other half of a pinned export: each component is taken from the
    version (``_definition_tab``, which 400s for a version of another family
    or one that no longer exists), with the live identity fields kept
    (``_LIVE_IDENTITY_FIELDS``) when it still reads the same collection, as
    ``_component_from_version`` does for a render. A component whose
    collection changed since cannot be drawn from the version (a render
    answers 409), so it is left out with a warning; one deleted since is kept
    when its collection still belongs to the project.
    """
    out = []
    for tab in tabs:
        stored_tab = routes._definition_tab(tab, version_id)
        if stored_tab is None:
            out.append(tab)
            continue
        live = {str(m.get("index")): m for m in tab.get("stored_metadata") or []}
        merged: list[dict[str, Any]] = []
        for m in convert_objectid_to_str(stored_tab.get("stored_metadata") or []):
            idx = str(m.get("index"))
            current = live.get(idx)
            if current is not None:
                if str(current.get("dc_id") or "") != str(m.get("dc_id") or ""):
                    warnings.append(
                        f"{m.get('title') or idx} reads another collection than in version "
                        f"{version_id}, so it is left out of this export."
                    )
                    continue
                m = {
                    **m,
                    **{k: current[k] for k in routes._LIVE_IDENTITY_FIELDS if k in current},
                }
            elif m.get("dc_id") and str(m.get("dc_id")) not in project_dc_ids:
                continue
            merged.append(m)
        out.append({**tab, "stored_metadata": merged})
    return out


def _resolve_export_pins(
    state: AnalysisState, main_tab: dict[str, Any], dc_ids: list[str], warnings: list[str]
) -> dict[str, int]:
    """The Delta commit each exported collection is read at, from the state's pins."""
    if not state.pins.active:
        return {}
    from depictio.api.v1.endpoints.dashboards_endpoints.data_versions import (
        resolve_data_versions,
    )

    try:
        resolved = resolve_data_versions(state.pins.body(), dashboard=main_tab, referenced=dc_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    live = [d for d in dc_ids if resolved.for_dc(d) is None]
    if resolved.pins:
        what = (
            f"dashboard version {state.pins.as_of_version}"
            if state.pins.as_of_version
            else "the pinned commits"
        )
        warnings.append(
            f"This export reads its data as {what} held it ({len(resolved.pins)} collection(s) "
            "pinned). MultiQC reports and advanced visualisations are not versioned on the "
            "server: those tiles show live data."
            + (
                f" {len(live)} collection(s) have no stamp in that version and read live data."
                if live
                else ""
            )
        )
    return dict(resolved.pins)


def build_export_plan(
    dashboard_id: PyObjectId,
    state: AnalysisState,
    current_user: User,
    access_token: str | None,
    theme: str = "paper",
    embed_runtime: bool = False,
    pdf: bool = False,
) -> ExportPlan:
    family_id, raw_tabs = routes._resolve_tab_family(dashboard_id, current_user, TAB_PROJECTION)
    tabs = [convert_objectid_to_str(t) for t in raw_tabs]
    if not tabs:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")
    project_id = tabs[0].get("project_id")
    project_doc = None
    try:
        project_doc = routes.projects_collection.find_one({"_id": ObjectId(str(project_id))})
    except Exception:
        project_doc = None
    project = convert_objectid_to_str(project_doc) if project_doc else None
    dc_tags = _dc_tags(project)
    warnings: list[str] = []
    if state.pins.definition_version:
        tabs = _overlay_definitions(tabs, state.pins.definition_version, set(dc_tags), warnings)

    family_meta: list[dict[str, Any]] = []
    for tab in tabs:
        family_meta.extend(m for m in (tab.get("stored_metadata") or []) if isinstance(m, dict))
    family_doc = {"stored_metadata": family_meta}

    active = [f for f in state.filters_as_payload() if routes._funnel_filter_is_active(f)]
    active = _order_active_filters(active, state.funnel.stage_order)
    if len(active) > routes.FUNNEL_MAX_STAGES:
        warnings.append(
            f"{len(active)} filters were active; only the first {routes.FUNNEL_MAX_STAGES} "
            "become funnel stages (the funnel view has the same limit)."
        )
        active = active[: routes.FUNNEL_MAX_STAGES]

    stage_dc_ids: list[str] = []
    wf_by_dc: dict[str, str | None] = {}
    for m in family_meta:
        if m.get("component_type") not in STAGE_COMPONENT_TYPES:
            continue
        dc_id = str(m.get("dc_id") or "")
        if not dc_id or dc_id in wf_by_dc:
            continue
        if routes._funnel_is_multiqc_dc(family_doc, dc_id):
            continue
        wf_by_dc[dc_id] = str(m.get("wf_id")) if m.get("wf_id") else None
        stage_dc_ids.append(dc_id)

    pinned = _resolve_export_pins(state, tabs[0], stage_dc_ids, warnings)
    if pinned:
        # The funnel endpoint counts live rows; under pins the document counts
        # its own stages when it runs instead of printing numbers of other data.
        initial, stage_rows = {}, []
    else:
        counted = routes._funnel_stage_counts(
            family_doc, project_id, access_token, active, stage_dc_ids
        )
        # ``None`` only answers column mode (a stage column the frame lacks),
        # which the export never asks for.
        initial, stage_rows, _ = counted if counted is not None else ({}, [], None)

    dcs: list[DCPlan] = []
    for dc_id in stage_dc_ids:
        dtypes = _dtypes_for(family_doc, dc_id, wf_by_dc.get(dc_id))
        dcs.append(
            DCPlan(
                dc_id=dc_id,
                tag=dc_tags.get(dc_id) or f"dc_{dc_id[-6:]}",
                wf_id=wf_by_dc.get(dc_id),
                dtypes=dtypes,
                initial_rows=initial.get(dc_id),
                n_cols=len(dtypes) if dtypes else None,
                version=pinned.get(dc_id),
            )
        )

    meta_index = {str(m.get("index")): m for m in family_meta}
    stages: list[StagePlan] = []
    previous: dict[str, set[str]] = {dc: set() for dc in stage_dc_ids}
    for k, f in enumerate(active):
        cumulative = active[: k + 1]
        per_dc: dict[str, list[dict[str, Any]]] = {}
        for dc_id in stage_dc_ids:
            try:
                merged = routes._resolve_link_filters_cached(
                    filters=cumulative,
                    target_dc_id=dc_id,
                    project_id=project_id,
                    access_token=access_token,
                    component_type="funnel",
                )
            except Exception as exc:
                warnings.append(
                    f"Cross-collection links could not be resolved for stage {k + 1} on "
                    f"{dc_tags.get(dc_id, dc_id)}: {exc}"
                )
                merged = list(cumulative)
            mine = [g for g in merged if str((g.get("metadata") or {}).get("dc_id") or "") == dc_id]
            entries = _cleaned_with_index(mine)
            fresh = [e for e in entries if _entry_key(e) not in previous[dc_id]]
            previous[dc_id] |= {_entry_key(e) for e in entries}
            per_dc[dc_id] = fresh
        meta = meta_index.get(str(f.get("index") or "")) or {}
        row = stage_rows[k] if k < len(stage_rows) else {}
        stages.append(
            StagePlan(
                index=str(f.get("index") or ""),
                label=str(
                    meta.get("title")
                    or meta.get("column_name")
                    or f.get("column_name")
                    or f.get("index")
                ),
                column=f.get("column_name") or meta.get("column_name"),
                interactive_component_type=f.get("interactive_component_type")
                or meta.get("interactive_component_type"),
                value=f.get("value"),
                source_dc_id=str((f.get("metadata") or {}).get("dc_id") or meta.get("dc_id") or "")
                or None,
                icon=filter_icon_id(meta),
                # `interactiveAccentRaw`: the control's own colour, whichever
                # of the three fields carries it.
                color=(meta.get("icon_color") or meta.get("color") or meta.get("custom_color")),
                per_dc=per_dc,
                rows_by_dc=dict(row.get("rows_by_dc") or {}),
            )
        )

    api_url = settings.fastapi.external_url
    instance = urlparse(api_url).netloc or api_url
    main = tabs[0]
    brand = _resolve_export_brand(dashboard_id, main.get("brand_theme"))
    return ExportPlan(
        tabs=tabs,
        project=project,
        state=state,
        dcs=dcs,
        stages=stages,
        title=str(main.get("title") or "Dashboard"),
        subtitle=(main.get("subtitle") or None),
        exported_by=_who(current_user),
        exported_at=datetime.now(timezone.utc),
        instance=instance,
        api_url=api_url,
        warnings=warnings,
        favicon_data_uri=_favicon_data_uri(),
        depictio_version=_depictio_version(),
        logos=_resolve_text_logos(tabs),
        # The dashboard's own mark: its management-page icon when that is an
        # image (the nf-core apple), as the dashboards list shows it.
        dashboard_logo=_image_data_uri(str(main.get("icon") or "")),
        depictio_mark=_depictio_mark(),
        dashboard_public=bool(main.get("is_public")),
        brand=brand,
        tab_brands=_resolve_tab_brands(tabs, main_brand=brand),
        icons=_resolve_tab_icons(tabs),
        text_values=_export_text_values(
            tabs, state.filters_as_payload(), current_user, access_token, state.pins.body()
        ),
        theme=theme,
        embed_runtime=embed_runtime,
        pdf=pdf,
    )


# ── The report host of the static runtime ─────────────────────────────────────
#
# A report can embed, once, the serverless runtime and producer A's manifest of
# the dashboard (``depictio/serverless/report.py``): its tiles are then drawn by
# the dashboard's own renderers and follow an in-page filter panel, each tile's
# own output staying as its fallback. The manifest carries the data, so it is
# held to the static export's rule (owner on the dashboard's project), and a
# state the runtime cannot reproduce in the page is not embedded at all.


def _runtime_refusal(
    dashboard_id: PyObjectId, state: AnalysisState, current_user: User
) -> str | None:
    """Why this report cannot embed the runtime, or ``None`` when it can."""
    from depictio.serverless import report

    if not report.runtime_available():
        return "the report runtime is not built on this deployment"
    reason = report.ineligibility(state)
    if reason:
        return reason
    if not current_user or not getattr(current_user, "id", None):
        return "embedding the dashboard's data needs a signed-in owner"
    try:
        doc = routes.dashboards_collection.find_one(
            {"dashboard_id": ObjectId(str(dashboard_id))}, {"project_id": 1}
        )
    except Exception:  # noqa: BLE001 - an unreadable id is no owner
        doc = None
    project_id = (doc or {}).get("project_id")
    if not project_id or not routes.check_project_permission(project_id, current_user, "owner"):
        return "embedding the dashboard's data is limited to its owners, as a static export is"
    return None


def _embed_runtime(
    request: NotebookExportRequest,
    dashboard_id: PyObjectId,
    current_user: User,
    *,
    default: bool,
) -> bool:
    wanted = default if request.embed_runtime is None else request.embed_runtime
    if not wanted:
        return False
    reason = _runtime_refusal(dashboard_id, request.state, current_user)
    if reason:
        logger.info(f"Notebook export {dashboard_id}: tiles stay the export's own ({reason})")
        return False
    return True


def _combined_refusal(
    dashboard_id: PyObjectId, state: AnalysisState, current_user: User
) -> str | None:
    """Why this caller cannot have the combined report + dashboard file.

    It is a rendered report with the dashboard's manifest embedded, so it needs
    both: a deployment that renders reports, and the runtime's rules (a state it
    can reproduce, an owner, as a static export).
    """
    from depictio.serverless import combined

    if not settings.notebook_export.render_enabled:
        return "this server does not render reports (Quarto is not enabled)"
    if not combined.combined_runtime_available():
        return "the combined runtime is not built on this deployment"
    return _runtime_refusal(dashboard_id, state, current_user)


@dashboards_endpoint_router.post(
    "/notebook_export/{dashboard_id}/preflight", response_model=NotebookPreflight
)
def notebook_export_preflight(
    dashboard_id: PyObjectId,
    request: NotebookExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> NotebookPreflight:
    """What the export will contain: one verdict per tile, stage counts, warnings."""
    _require_enabled()
    plan = build_export_plan(
        dashboard_id,
        request.state,
        current_user,
        access_token,
        theme=request.theme,
        pdf=request.pdf,
    )
    # Whether the *worker* can render is not something the API can see (Quarto
    # lives in the worker image), so this is the operator's switch, not a probe.
    preflight = NotebookBuilder(plan).preflight(
        render_available=settings.notebook_export.render_enabled
    )
    reason = _combined_refusal(dashboard_id, request.state, current_user)
    preflight.combined_available = reason is None
    preflight.combined_reason = reason
    return preflight


@dashboards_endpoint_router.post("/notebook_export/{dashboard_id}")
def notebook_export(
    dashboard_id: PyObjectId,
    request: NotebookExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> Response:
    """The dashboard as a Quarto document (``.qmd``).

    Nothing runs on the server: the document is generated text. The rendered
    report is the one thing that does execute, and it is a separate, opt-in
    endpoint below.
    """
    from depictio.api.v1.services.notebook_export import store

    _require_enabled()
    plan = build_export_plan(
        dashboard_id,
        request.state,
        current_user,
        access_token,
        theme=request.theme,
        # Off unless asked: the reader's own render fetches the manifest and the
        # runtime from this API, which only works for an owner with access.
        embed_runtime=_embed_runtime(request, dashboard_id, current_user, default=False),
        pdf=request.pdf,
    )
    source = NotebookBuilder(plan).build()
    return Response(
        content=source.encode("utf-8"),
        media_type=store.QMD_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{plan.stem}.qmd"'},
    )


# ── The rendered report ───────────────────────────────────────────────────────
#
# The one path in the export that executes anything. It is a job and not a
# request: the notebook is run end to end on a worker, and every tile the
# export renders rather than computes costs a browser pass, so a dashboard's
# report is minutes of work. The client starts it, polls the status, then
# downloads.


def combined_filename(stem: str) -> str:
    """The combined file's name: the report's, marked as holding the dashboard."""
    return f"{stem}-report-dashboard.html"


def _require_render_enabled() -> None:
    _require_enabled()
    if not settings.notebook_export.render_enabled:
        raise HTTPException(
            status_code=501,
            detail=(
                "Rendered HTML reports are not enabled on this deployment "
                "(DEPICTIO_NOTEBOOK_EXPORT_RENDER_ENABLED)."
            ),
        )


def _require_owner_for_authored_code(
    dashboard_id: PyObjectId, current_user: User, builder: NotebookBuilder
) -> None:
    """Only an owner may render a dashboard that carries its author's own code.

    A code-mode figure is Python somebody wrote in the chart builder, and this
    is the one path that runs it: on a worker, with a token minted for whoever
    asked for the report. Rendering someone else's dashboard would therefore
    run their code with the reader's rights. An owner can already change that
    code, so for them the render adds nothing they could not do; for everyone
    else the report is refused rather than quietly downgraded — a report
    missing its figures is not the report they asked for.
    """
    authored = [
        c for c in builder.preflight().components if c.status == "code" and c.kind == "code"
    ]
    if not authored or settings.auth.is_single_user_mode:
        return
    from depictio.api.v1.services.screenshot_service import check_dashboard_owner_permission_sync

    if check_dashboard_owner_permission_sync(str(dashboard_id), str(current_user.id)):
        return
    titles = ", ".join(sorted({c.title or c.index for c in authored})[:3])
    raise HTTPException(
        status_code=403,
        detail=(
            f"This dashboard has {len(authored)} code-mode figure(s) ({titles}) whose Python "
            "would run on the server. Rendering a report is limited to the dashboard's owners; "
            "download the notebook and run it yourself instead."
        ),
    )


def _render_job(job_id: str, current_user: User) -> tuple[Any, dict[str, Any]]:
    """The job's Celery result, plus its payload once it has one.

    A job is addressed by an id the server minted, and its artefacts live under
    the prefix of the user who asked for it: a result that names another user
    is not this caller's job to read.
    """
    from celery.result import AsyncResult

    from depictio.api.celery_app import celery_app

    result = AsyncResult(job_id, app=celery_app)
    payload = result.result if isinstance(result.result, dict) else {}
    owner = str(payload.get("user_id") or "")
    if owner and owner != str(current_user.id):
        raise HTTPException(status_code=404, detail=f"No render job '{job_id}'.")
    return result, payload


@dashboards_endpoint_router.post(
    "/notebook_export/{dashboard_id}/render",
    response_model=NotebookRenderStatus,
    status_code=202,
)
async def notebook_export_render(
    dashboard_id: PyObjectId,
    request: NotebookExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> NotebookRenderStatus:
    """Start rendering the dashboard's notebook into an HTML report."""
    _require_render_enabled()
    if not current_user or not getattr(current_user, "id", None):
        raise HTTPException(status_code=401, detail="Rendering a report needs a signed-in user.")

    from depictio.api.celery_app import render_notebook_report
    from depictio.api.v1.endpoints.user_endpoints.core_functions import _add_token
    from depictio.api.v1.services.notebook_export import store
    from depictio.models.models.users import TokenData

    combined = request.output == "combined"
    if combined:
        # The user asked for the dashboard in the file: a report without it is
        # not what they asked for, so a refusal is an error, not a downgrade.
        refusal = _combined_refusal(dashboard_id, request.state, current_user)
        if refusal:
            raise HTTPException(
                status_code=409, detail=f"The report + dashboard file is unavailable: {refusal}."
            )
        embed_runtime = True
    else:
        embed_runtime = _embed_runtime(request, dashboard_id, current_user, default=True)
    plan = build_export_plan(
        dashboard_id,
        request.state,
        current_user,
        access_token,
        theme=request.theme,
        embed_runtime=embed_runtime,
        pdf=request.pdf,
    )
    builder = NotebookBuilder(plan)
    _require_owner_for_authored_code(dashboard_id, current_user, builder)
    qmd = builder.build().encode("utf-8")

    job_id = uuid4().hex
    user_id = str(current_user.id)
    filename = combined_filename(plan.stem) if combined else f"{plan.stem}.html"
    notebook_key = store.job_key(user_id, job_id, f"{plan.stem}.qmd")
    store.put(notebook_key, qmd, store.QMD_MEDIA_TYPE)

    # The notebook runs as the user who asked for it, so the report holds what
    # they can see and nothing more. A token of its own, so the render can be
    # revoked on its own: the caller's session is not handed to a worker.
    token = await _add_token(
        TokenData(
            sub=current_user.id,
            name=f"notebook-report-{job_id}",
            token_lifetime="short-lived",
        )
    )
    render_notebook_report.apply_async(
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "notebook_key": notebook_key,
            "stem": plan.stem,
            "api_url": settings.fastapi.internal_url,
            "token_id": str(token.id),
            # The worker builds the manifest in-process (producer A, as the
            # static export does) and hands the document the composed block.
            "runtime": (
                {
                    "dashboard_id": str(dashboard_id),
                    "state": request.state.model_dump(mode="json"),
                    "user": {
                        "id": user_id,
                        "email": getattr(current_user, "email", "") or "",
                        "is_admin": bool(getattr(current_user, "is_admin", False)),
                        "is_anonymous": bool(getattr(current_user, "is_anonymous", False)),
                    },
                    # The look the document's own cell would pass (its brand
                    # primary and type), so both render paths match.
                    "config": builder.runtime_config(),
                }
                if embed_runtime
                else None
            ),
            # The combined file: the same render, then the report's runtime
            # block swapped for the App runtime the dashboard view shares.
            "combined": {"default_view": request.default_view} if combined else None,
            "filename": filename,
            "pdf": bool(request.pdf),
        },
        task_id=job_id,
    )
    logger.info(
        f"📄 Notebook {'report + dashboard' if combined else 'report'} {job_id} queued "
        f"for dashboard {dashboard_id}"
    )
    return NotebookRenderStatus(job_id=job_id, status="queued", filename=filename, phase="queued")


@dashboards_endpoint_router.get(
    "/notebook_export/render/{job_id}", response_model=NotebookRenderStatus
)
def notebook_export_render_status(
    job_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> NotebookRenderStatus:
    """Where a render job is: queued, running, ready to download, or failed."""
    _require_render_enabled()
    result, payload = _render_job(job_id, current_user)
    if result.successful():
        return NotebookRenderStatus(
            job_id=job_id,
            status="ready",
            filename=payload.get("filename"),
            size=payload.get("size"),
            pdf_filename=payload.get("pdf_filename"),
            pdf_error=payload.get("pdf_error"),
        )
    if result.failed():
        return NotebookRenderStatus(job_id=job_id, status="error", reason=str(result.result))
    return NotebookRenderStatus(
        job_id=job_id,
        status="running" if result.state == "PROGRESS" else "queued",
        phase=str(payload.get("phase") or "").strip() or None,
    )


@dashboards_endpoint_router.get("/notebook_export/render/{job_id}/download")
def notebook_export_render_download(
    job_id: str,
    format: Literal["html", "pdf"] = "html",
    current_user: User = Depends(get_user_or_anonymous),
) -> Response:
    """The rendered report, as a file: the HTML report, or its PDF (``?format=pdf``)."""
    _require_render_enabled()
    from depictio.api.v1.services.notebook_export import store

    result, payload = _render_job(job_id, current_user)
    if not result.successful():
        raise HTTPException(status_code=409, detail=f"Render job '{job_id}' is not ready.")
    if format == "pdf":
        if not payload.get("pdf_key"):
            raise HTTPException(
                status_code=404,
                detail=str(payload.get("pdf_error") or f"Render job '{job_id}' made no PDF."),
            )
        try:
            pdf = store.get(str(payload["pdf_key"]))
        except Exception as exc:  # noqa: BLE001 — a missing object is a gone report
            raise HTTPException(
                status_code=404, detail=f"Report '{job_id}' is no longer stored."
            ) from exc
        return Response(
            content=pdf,
            media_type=store.PDF_MEDIA_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{payload.get("pdf_filename") or "report.pdf"}"'
                )
            },
        )
    filename = str(payload.get("filename") or "report.html")
    try:
        html = store.get(str(payload["key"]))
    except Exception as exc:  # noqa: BLE001 — a missing object is a gone report
        raise HTTPException(
            status_code=404, detail=f"Report '{job_id}' is no longer stored."
        ) from exc
    return Response(
        content=html,
        media_type=store.HTML_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
