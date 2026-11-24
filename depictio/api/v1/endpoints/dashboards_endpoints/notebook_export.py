"""Dashboard → notebook: preflight and export endpoints.

Everything that needs Mongo, Delta or link resolution happens here, in
``build_export_plan``; the plan is then handed to the generator, which only
turns it into cells. The helpers come from ``routes`` — the same ones the
funnel endpoint uses — so the stage counts in the notebook are the counts the
funnel view showed, computed by the same code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from bson import ObjectId
from fastapi import Depends, HTTPException, Response

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.endpoints.dashboards_endpoints import routes
from depictio.api.v1.endpoints.dashboards_endpoints.report_layer_routes import (
    _editable_family,
    _require_report_editor,
)
from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
    dashboards_endpoint_router,
    get_user_or_anonymous,
    oauth2_scheme_optional,
)
from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    MarkdownUnit,
    NotebookBuilder,
    StagePlan,
)
from depictio.api.v1.services.notebook_export.reading_order import filter_icon_id
from depictio.models.models.analysis_state import (
    AnalysisContext,
    AnalysisState,
    NotebookExportRequest,
    NotebookPreflight,
    NotebookRenderStatus,
)
from depictio.models.models.base import PyObjectId, convert_objectid_to_str
from depictio.models.models.report_layer import (
    ReportCoverDefaults,
    ReportLayer,
    ReportOutline,
    ReportOutlineEntry,
    ReportOutlineTab,
    ReportPreviewRequest,
)
from depictio.models.models.users import User
from depictio.notebook.theme import palette_hex

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
        # The report layer (#1457): the export's own intro, conclusion, cover
        # and tile/tab placement, stored on the main tab.
        "report_layer",
    )
}


def _require_enabled() -> None:
    if not settings.notebook_export.enabled:
        raise HTTPException(status_code=404, detail="Notebook export is disabled.")


def _state_of_layer(main_tab: dict[str, Any]) -> AnalysisState | None:
    """The report layer's state: the filters the report is drawn and exported
    at, or ``None`` (the layer holds none, or one that does not validate).

    A pin of that state naming a version retention has since deleted is
    dropped, with a warning: that half reads live data. A stored state must
    never 400 every export of the dashboard, or lock its report editor out
    (the outline sends no state). A pin a caller sends stays a 400.
    """
    layer = main_tab.get("report_layer")
    raw_state = layer.get("state") if isinstance(layer, dict) else None
    if not isinstance(raw_state, dict):
        return None
    try:
        state = AnalysisState.model_validate(raw_state)
    except Exception as exc:
        logger.warning(
            f"Dashboard {main_tab.get('dashboard_id')}: the report layer's state does not "
            f"validate, the export uses the dashboard's defaults ({exc})"
        )
        return None
    return _without_lost_pins(state, main_tab)


def _without_lost_pins(state: AnalysisState, main_tab: dict[str, Any]) -> AnalysisState:
    """``state`` without the version pins that no longer resolve for this family."""
    from depictio.api.v1.endpoints.dashboards_endpoints import data_versions

    drop: dict[str, Any] = {}
    for field_name in ("as_of_version", "definition_version"):
        version_id = getattr(state.pins, field_name)
        if not version_id:
            continue
        try:
            record = data_versions.version_store.get_version(str(version_id))
            data_versions.check_version_family(record, version_id, main_tab)
        except ValueError:
            drop[field_name] = None
    if not drop:
        return state
    logger.warning(
        f"Dashboard {main_tab.get('dashboard_id')}: the report layer pins version(s) "
        f"{sorted(str(getattr(state.pins, f)) for f in drop)} that no longer exist; "
        "the export reads live data for them"
    )
    return state.model_copy(update={"pins": state.pins.model_copy(update=drop)})


def _resolved_request_state(
    dashboard_id: PyObjectId, request: NotebookExportRequest
) -> AnalysisState:
    """The state an export is drawn at: the request's, else the report layer's
    (the state the report is written for), else the dashboard's defaults.

    The preflight, the document and the render must all agree on one state,
    so every route resolves it once, up front — including the checks that run
    before the plan is built.
    """
    if request.state is not None:
        return request.state
    doc = routes.dashboards_collection.find_one(
        {"dashboard_id": ObjectId(str(dashboard_id))}, {"parent_dashboard_id": 1}
    )
    if doc:
        # The projection leaves `dashboard_id` out: with no parent, the doc
        # queried is the family's main tab itself.
        family_id = doc.get("parent_dashboard_id") or dashboard_id
        main_tab = routes.dashboards_collection.find_one(
            {"dashboard_id": ObjectId(str(family_id))},
            {"report_layer": 1, "dashboard_id": 1, "parent_dashboard_id": 1},
        )
        state = _state_of_layer(main_tab or {})
        if state is not None:
            return state
    return AnalysisState(context=AnalysisContext(dashboard_id=str(dashboard_id)))


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
#: A brand logo fetched from an external URL is capped the same way.
_MAX_BRAND_LOGO_BYTES = 1024 * 1024
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
                # An external CDN link goes through the same SSRF gateway as
                # the text-tile logos: allowlist, internal-address refusal,
                # size cap — and the bytes must look like an image.
                from depictio.api.v1.remote_fetch import fetch_validated_bytes

                try:
                    data = fetch_validated_bytes(
                        theme.logo_url, max_bytes=_MAX_BRAND_LOGO_BYTES, timeout=10
                    )
                except Exception as exc:  # refused or unreachable: no logo
                    logger.warning(f"notebook export: brand logo not fetched: {exc}")
                else:
                    mime = _image_mime(data)
                    if mime:
                        logo_data_uri = _data_uri(data, mime)
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
    state: AnalysisState | None,
    current_user: User,
    access_token: str | None,
    theme: str = "paper",
    embed_runtime: bool = False,
    pdf: bool = False,
    pdf_style: str = "colour",
) -> ExportPlan:
    family_id, raw_tabs = routes._resolve_tab_family(dashboard_id, current_user, TAB_PROJECTION)
    tabs = [convert_objectid_to_str(t) for t in raw_tabs]
    if not tabs:
        raise HTTPException(status_code=404, detail=f"Dashboard '{dashboard_id}' not found.")
    if state is None:
        # No state in the request: the report layer's, the filters the report
        # is written for, else the dashboard's defaults.
        state = _state_of_layer(tabs[0]) or AnalysisState(
            context=AnalysisContext(dashboard_id=str(dashboard_id))
        )
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
        report_layer=(main.get("report_layer") or None),
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
        pdf_style=pdf_style,
    )


# ── The report host of the static runtime ─────────────────────────────────────
#
# A report can embed, once, the serverless runtime and producer A's manifest of
# the dashboard (``depictio/serverless/report.py``): its tiles are then drawn by
# the dashboard's own renderers and follow an in-page filter panel, each tile's
# own output staying as its fallback. The manifest carries the data, so it is
# held to the static export's rule (owner on the dashboard's project), and a
# state the runtime cannot reproduce in the page is not embedded at all.


def _owner_refusal(
    dashboard_id: PyObjectId, state: AnalysisState, current_user: User
) -> str | None:
    """Why this caller (or this state) cannot have the dashboard's manifest
    embedded, or ``None``: a state the runtime reproduces, and an owner, as a
    static export needs."""
    from depictio.serverless import report

    reason = report.ineligibility(state)
    if reason:
        return reason
    if not current_user or not getattr(current_user, "id", None):
        return "embedding the dashboard's data needs a signed-in owner"
    # The one export rule, the very check a static export's dispatch makes.
    from depictio.serverless.producer_a import export_denial

    if export_denial(str(dashboard_id), current_user, required="owner"):
        return "embedding the dashboard's data is limited to its owners, as a static export is"
    return None


def _runtime_refusal(
    dashboard_id: PyObjectId, state: AnalysisState, current_user: User
) -> str | None:
    """Why this report cannot embed the runtime, or ``None`` when it can."""
    from depictio.serverless import combined

    if not settings.static_export.enabled:
        return "the static dashboard export is not enabled on this server"
    if not combined.runtime_available():
        return "the static runtime is not built on this deployment"
    return _owner_refusal(dashboard_id, state, current_user)


def _embed_runtime(
    request: NotebookExportRequest,
    dashboard_id: PyObjectId,
    state: AnalysisState,
    current_user: User,
    *,
    default: bool,
) -> bool:
    wanted = default if request.embed_runtime is None else request.embed_runtime
    if not wanted:
        return False
    reason = _runtime_refusal(dashboard_id, state, current_user)
    if reason:
        logger.info(f"Notebook export {dashboard_id}: tiles stay the export's own ({reason})")
        return False
    return True


def _combined_refusal(
    dashboard_id: PyObjectId, state: AnalysisState, current_user: User
) -> str | None:
    """Why this caller cannot have the combined report + dashboard file.

    It is a rendered report with the runtime embedded and its switch on, so it
    needs both: a deployment that renders reports, and the runtime's rules.
    """
    if not settings.notebook_export.render_enabled:
        return "this server does not render reports (Quarto is not enabled)"
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
    state = _resolved_request_state(dashboard_id, request)
    plan = build_export_plan(
        dashboard_id,
        state,
        current_user,
        access_token,
        theme=request.theme,
        pdf=request.pdf,
        pdf_style=request.pdf_style,
    )
    # Whether the *worker* can render is not something the API can see (Quarto
    # lives in the worker image), so this is the operator's switch, not a probe.
    preflight = NotebookBuilder(plan).preflight(
        render_available=settings.notebook_export.render_enabled
    )
    reason = _combined_refusal(dashboard_id, state, current_user)
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
    state = _resolved_request_state(dashboard_id, request)
    plan = build_export_plan(
        dashboard_id,
        state,
        current_user,
        access_token,
        theme=request.theme,
        # Off unless asked: the reader's own render fetches the manifest and the
        # runtime from this API, which only works for an owner with access.
        embed_runtime=_embed_runtime(request, dashboard_id, state, current_user, default=False),
        pdf=request.pdf,
        pdf_style=request.pdf_style,
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


def _require_owner_for_authored_code(plan: ExportPlan, current_user: User) -> None:
    """Only a project owner or editor may render a dashboard that carries
    authored code (#1457).

    The render never runs a code-mode figure's Python itself (``author_code``
    is off for it: the figure is drawn through the API's sandbox, as the
    dashboard draws it). The gate stays as a second line: it rests on the
    *project*'s owners and editors, since anyone with viewer access can own
    a dashboard document (by creating or duplicating one) and so write its
    code — a mere viewer who owns such a copy stays refused.
    """
    authored = [
        m
        for tab in plan.tabs
        for m in tab.get("stored_metadata") or []
        if isinstance(m, dict) and m.get("component_type") == "figure" and m.get("mode") == "code"
    ]
    if not authored or settings.auth.is_single_user_mode:
        return
    project_id = (plan.tabs[0] if plan.tabs else {}).get("project_id")
    if project_id and routes.check_project_permission(project_id, current_user, "editor"):
        return
    titles = ", ".join(sorted({str(m.get("title") or m.get("index")) for m in authored})[:3])
    raise HTTPException(
        status_code=403,
        detail=(
            f"This dashboard has {len(authored)} code-mode figure(s) ({titles}). Rendering it "
            "as a report is limited to the project's owners and editors; download the notebook "
            "and run it yourself instead."
        ),
    )


def _render_job(job_id: str, current_user: User) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """The job's Celery result and payload, and its record, for its owner only.

    A job is bound to the user who started it when it is queued
    (``jobs.record``), so ownership holds in every state: queued, running,
    failed or done. Anyone else is told there is no such job.
    """
    from celery.result import AsyncResult

    from depictio.api.celery_app import celery_app
    from depictio.api.v1.services.notebook_export import jobs

    record = jobs.owned(job_id, str(current_user.id), jobs.RENDER)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No render job '{job_id}'.")
    result = AsyncResult(job_id, app=celery_app)
    payload = result.result if isinstance(result.result, dict) else {}
    if str(payload.get("user_id") or record["user_id"]) != str(current_user.id):
        raise HTTPException(status_code=404, detail=f"No render job '{job_id}'.")
    return result, payload, record


def _require_signed_in(current_user: User) -> None:
    """A report is bound to who asked for it: an anonymous visitor is everyone."""
    if not current_user or not getattr(current_user, "id", None):
        raise HTTPException(status_code=401, detail="Rendering a report needs a signed-in user.")
    if getattr(current_user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise HTTPException(
            status_code=401,
            detail=(
                "Rendering a report needs a signed-in user: anonymous visitors share one "
                "identity. Sign in, or download the notebook and run it yourself."
            ),
        )


@dashboards_endpoint_router.post(
    "/notebook_export/{dashboard_id}/render",
    response_model=NotebookRenderStatus,
    status_code=202,
)
def notebook_export_render(
    dashboard_id: PyObjectId,
    request: NotebookExportRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> NotebookRenderStatus:
    """Start rendering the dashboard's notebook into an HTML report.

    A plain (threadpool) route: building the plan reads Delta tables, Mongo
    and S3, none of which may run on the event loop.
    """
    _require_render_enabled()
    _require_signed_in(current_user)

    from depictio.api.celery_app import render_notebook_report
    from depictio.api.v1.services.notebook_export import jobs, store
    from depictio.serverless.combined import combined_filename
    from depictio.serverless.report import user_payload

    combined = request.output == "combined"
    state = _resolved_request_state(dashboard_id, request)
    if combined:
        # The user asked for the dashboard in the file: a report without it is
        # not what they asked for, so a refusal is an error, not a downgrade.
        refusal = _combined_refusal(dashboard_id, state, current_user)
        if refusal:
            raise HTTPException(
                status_code=409, detail=f"The report + dashboard file is unavailable: {refusal}."
            )
        embed_runtime = True
    else:
        embed_runtime = _embed_runtime(request, dashboard_id, state, current_user, default=True)
    user_id = str(current_user.id)
    limits = settings.notebook_export
    jobs.admit(
        user_id,
        jobs.RENDER,
        max_active=limits.render_max_active_per_user,
        max_per_hour=limits.render_max_per_hour,
        window_s=2 * limits.render_timeout_s + 120 + 3600,
    )
    plan = build_export_plan(
        dashboard_id,
        state,
        current_user,
        access_token,
        theme=request.theme,
        embed_runtime=embed_runtime,
        pdf=request.pdf,
        pdf_style=request.pdf_style,
    )
    _require_owner_for_authored_code(plan, current_user)
    # The server never executes an author's Python itself: code-mode figures
    # come from the API, which runs them in the dashboard's own sandbox.
    plan.author_code = False
    builder = NotebookBuilder(plan)
    qmd = builder.build().encode("utf-8")

    job_id = uuid4().hex
    filename = combined_filename(plan.stem) if combined else f"{plan.stem}.html"
    notebook_key = store.job_key(user_id, job_id, f"{plan.stem}.qmd")
    store.put(notebook_key, qmd, store.QMD_MEDIA_TYPE)
    jobs.record(job_id, user_id, jobs.RENDER, dashboard_id=str(dashboard_id))

    # The notebook runs as the user who asked for it, so the report holds what
    # they can see and nothing more: the worker mints a token of theirs when
    # the render starts, and revokes it when it ends.
    render_notebook_report.apply_async(
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "notebook_key": notebook_key,
            "stem": plan.stem,
            "api_url": settings.fastapi.internal_url,
            # The worker builds the manifest in-process (producer A, as the
            # static export does) and embeds it with the runtime after the
            # render.
            "runtime": (
                {
                    "dashboard_id": str(dashboard_id),
                    # The resolved state: a request may leave it to the layer.
                    "state": state.model_dump(mode="json"),
                    "user": user_payload(current_user),
                    # The look the document's own cell would pass (its brand
                    # primary and type), so both render paths match.
                    "config": builder.runtime_config(),
                }
                if embed_runtime
                else None
            ),
            # The combined file: the same embedding, its switch to the
            # dashboard on.
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


# ── The report editor's backend ──────────────────────────────────────────────
#
# The editor page (`/dashboard-report/{id}`) reads the report's shape from the
# outline and asks for an exact preview of it — the same document, rendered on
# a worker, with the last one of an unchanged report served from the finished
# job instead of run again. Both are editor routes: the report editor's flag
# and the dashboard-editing rule decide who may call them, and everyone else
# is told the dashboard does not exist.


def _cover_defaults_for(plan: ExportPlan) -> ReportCoverDefaults:
    """The cover's fields as the export fills them, ignoring the layer's cover.

    The dashboard's title, the project's name, the project's owners, the day
    of the export — what the editor's cover fields reset to.
    """
    project = plan.project or {}
    owners: list[str] = []
    for owner in (project.get("permissions") or {}).get("owners") or []:
        if not isinstance(owner, dict):
            continue
        name = str(owner.get("username") or owner.get("email") or "").strip()
        if name and name not in owners:
            owners.append(name)
    return ReportCoverDefaults(
        title=plan.title or "Report",
        subtitle=str(project.get("name") or "") or None,
        authors=owners,
        date=plan.exported_at.strftime("%Y-%m-%d"),
    )


_MD_NOISE = re.compile(r"!\[[^\]]*\]\([^)]*\)|\{\{[^}]*\}\}|[#*_`>|\[\]]|\([^)]*\)")


def _text_label(body: object, words: int = 8) -> str:
    """A text tile's name in the editor: its first heading, else its first
    words, without markdown, icons or live values."""
    if not isinstance(body, str):
        return ""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    heading = next((ln for ln in lines if ln.startswith("#")), None)
    text = heading or " ".join(lines)
    out = " ".join(_MD_NOISE.sub(" ", text).replace("- ", " ").split())
    parts = out.split(" ")
    return " ".join(parts[:words]) + (" …" if len(parts) > words else "")


@dashboards_endpoint_router.get(
    "/notebook_export/{dashboard_id}/outline", response_model=ReportOutline
)
def notebook_export_outline(
    dashboard_id: PyObjectId,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> ReportOutline:
    """The report's shape, as the editor page draws it: its tabs, sections and
    tiles in the generator's order, with the cover's defaults.

    Every tile of the family is listed — also the ones the layer left out of
    the report, whose ``in_report`` says so. Built by the same plan and
    builder the export uses, so the outline is exactly what a report of this
    dashboard would hold.
    """
    _require_report_editor()
    _editable_family(dashboard_id, current_user)

    state = _resolved_request_state(dashboard_id, NotebookExportRequest())
    plan = build_export_plan(dashboard_id, state, current_user, access_token)

    # The layer's own settings per tile, from the layer as stored — the
    # outline reports them even where the walk below forces every tile in.
    revision = 0
    tiles: dict[tuple[str, str], Any] = {}
    tab_cfgs: dict[str, Any] = {}
    if plan.report_layer:
        try:
            layer = ReportLayer.model_validate(plan.report_layer)
            revision = layer.revision
            tiles = {(t.tab_id, t.component_id): t for t in layer.tiles}
            tab_cfgs = {t.tab_id: t for t in layer.tabs}
        except Exception:  # the builder says why in its warning; the outline still lists everything
            pass

    # A copy of the layer with every tile forced in, so the excluded ones are
    # walked too: the outline shows the whole report an editor can switch on.
    forced = deepcopy(plan.report_layer)
    if forced:
        for tile in forced.get("tiles") or []:
            if isinstance(tile, dict):
                tile["in_report"] = True
    plan.report_layer = forced

    builder = NotebookBuilder(plan)
    outline_tabs: list[ReportOutlineTab] = []
    current: ReportOutlineTab | None = None
    # The section the next components sit under: every component carries it,
    # or the editor has nothing to group them by.
    current_section: str | None = None
    for entry, _tab_name in builder.entries():
        if isinstance(entry, MarkdownUnit):
            if entry.kind == "tab":
                tab_id = entry.dashboard_id or ""
                cfg = tab_cfgs.get(tab_id)
                # The tab's identity, as the report draws it: the sidebar
                # icon the generator puts on the tab's heading, and the same
                # accent it tints that heading with (the tab's own colour,
                # else its brand's primary; none when neither is set).
                brand = plan.tab_brands.get(tab_id) or plan.brand or {}
                current = ReportOutlineTab(
                    tab_id=tab_id,
                    title=entry.text,
                    placement=cfg.placement if cfg is not None else "body",
                    order=cfg.order if cfg is not None else None,
                    icon=entry.icon,
                    color=palette_hex(entry.color, brand.get("primary") or "") or None,
                    entries=[],
                )
                outline_tabs.append(current)
                current_section = None
            elif current is not None:
                current_section = entry.text
                current.entries.append(
                    ReportOutlineEntry(
                        kind="section",
                        tab_id=current.tab_id,
                        title=entry.text,
                        level=entry.level,
                        icon=entry.icon,
                        color=entry.color,
                        description=entry.description,
                    )
                )
            continue
        if current is None:  # a component before any tab: nothing to attach it to
            continue
        meta = entry.highlight if entry.highlight is not None else entry.unit.meta
        # The layer's settings, by the generator's own key: a highlight is its
        # own tile there, even though it draws a figure of another tab.
        tile = tiles.get(entry.layer_key)
        caption = meta.get("caption")
        current.entries.append(
            ReportOutlineEntry(
                kind="component",
                tab_id=current.tab_id,
                # A highlight without a title of its own reads as the figure it
                # shows, a text tile as its heading or first words.
                title=str(
                    meta.get("title")
                    or entry.unit.meta.get("title")
                    or _text_label(meta.get("body"))
                    or meta.get("index")
                    or ""
                ),
                component_id=str(meta.get("index") or ""),
                component_type=str(meta.get("component_type") or "") or None,
                caption=str(caption) if caption is not None else None,
                in_report=bool(tile.in_report) if tile is not None else True,
                in_pdf=bool(tile.in_pdf) if tile is not None else True,
                orientation=tile.orientation if tile is not None else "auto",
                # The layer's override, else the section the tile sits under.
                section=(tile.section if tile is not None and tile.section else current_section),
                page_break_before=bool(tile.page_break_before) if tile is not None else False,
                order=tile.order if tile is not None else None,
            )
        )

    if settings.notebook_export.render_enabled:
        from depictio.api.v1.services.notebook_export import render as render_service

        if render_service.render_available():
            preview_available, preview_reason = True, None
        else:
            preview_available = False
            preview_reason = render_service.render_unavailable_reason() or (
                "Reports cannot be rendered on this deployment."
            )
    else:
        preview_available, preview_reason = (
            False,
            (
                "Rendered reports are not enabled on this deployment "
                "(DEPICTIO_NOTEBOOK_EXPORT_RENDER_ENABLED)."
            ),
        )
    return ReportOutline(
        dashboard_id=str(dashboard_id),
        title=plan.title,
        revision=revision,
        tabs=outline_tabs,
        cover_defaults=_cover_defaults_for(plan),
        preview_available=preview_available,
        preview_unavailable_reason=preview_reason,
    )


def _report_data_identity(plan: Any) -> str:
    """What the report's data is at now: each collection's latest commit (a
    MultiQC collection's report set), as the reader marks read it. The
    document carries the day, not the data, so without this a re-ingest the
    same day would be answered with the preview of the data before it."""
    from depictio.api.v1.services.changes import baseline

    tabs = list(getattr(plan, "tabs", None) or [])
    project_id = tabs[0].get("project_id") if tabs else None
    try:
        types = baseline.family_dc_types(tabs, project_id)
        tokens = sorted(
            f"{dc_id}={baseline.data_token(baseline.dc_state(dc_id, dc_type)) or '-'}"
            for dc_id, dc_type in types.items()
        )
    except Exception as exc:  # the identity is a cache hint, never a failure
        logger.warning(f"Report preview: the data identity could not be read ({exc})")
        tokens = []
    return hashlib.sha256("\n".join(tokens).encode()).hexdigest()


def _preview_cache_key(qmd: bytes, embed_runtime: bool, data_identity: str = "") -> str:
    """What makes one preview equal to another: the document, the runtime
    embedded in it, and the data it reads (``_report_data_identity``). The
    document carries everything else that changes it: the state, the layer,
    the filters."""
    digest = hashlib.sha256()
    digest.update(qmd)
    digest.update(b"\x00embed=" + (b"1" if embed_runtime else b"0"))
    digest.update(b"\x00data=" + data_identity.encode())
    return digest.hexdigest()


def _ready_preview(job_id: str, current_user: User) -> NotebookRenderStatus | None:
    """The finished job's ready status — or ``None`` when it is not (yet, or
    any more) a finished report of its owner's."""
    try:
        result, payload, _record = _render_job(job_id, current_user)
    except HTTPException:
        return None
    if not result.successful():
        return None
    return NotebookRenderStatus(
        job_id=job_id,
        status="ready",
        filename=payload.get("filename"),
        size=payload.get("size"),
        # A preview job's report, by its capability URL; ``None`` for a
        # download's job (its report is fetched through the download route).
        preview_url=payload.get("preview_url"),
    )


def _cached_preview(
    user_id: str, dashboard_id: str, cache_key: str, current_user: User
) -> NotebookRenderStatus | None:
    """The ready preview this user already has for this dashboard and this
    exact document, or ``None``. Only the newest one answers: a re-render of
    the same document replaces the served preview."""
    from depictio.api.v1.services.notebook_export import jobs

    record = (
        jobs.jobs_collection.find(
            {
                "user_id": user_id,
                "kind": jobs.RENDER,
                "dashboard_id": dashboard_id,
                "preview_key": cache_key,
                "status": "success",
            }
        )
        .sort("created_at", -1)
        .limit(1)
    )
    newest = next(iter(record), None)
    if newest is None:
        return None
    return _ready_preview(str(newest["_id"]), current_user)


#: The script the served report runs first: the editor's live patch (the
#: postMessage protocol that applies the editor's edits in the browser). It
#: lives in the service's assets, is served under this virtual path, and is
#: injected into ``report.html`` only.
PREVIEW_PATCH_SCRIPT = "__depictio_preview_patch.js"
_PREVIEW_PATCH_TAG = f'<script src="{PREVIEW_PATCH_SCRIPT}"></script>'
#: An in-memory ``localStorage``/``sessionStorage`` for the sandboxed frame.
#: Its opaque origin makes the real ones throw on access, and Quarto's own
#: scripts (``quarto.js``, ``tabsets.js``) read them unguarded: without the
#: stand-in every preview page logs a dozen errors and those scripts stop
#: half way. Set before any other script runs, and only where access throws.
PREVIEW_STORAGE_SHIM = (
    "<script>(function(){function mem(){var d={};return{getItem:function(k){"
    "return Object.prototype.hasOwnProperty.call(d,k)?d[k]:null},setItem:function(k,v)"
    "{d[k]=String(v)},removeItem:function(k){delete d[k]},clear:function(){d={}},"
    "key:function(i){return Object.keys(d)[i]||null},get length(){return Object.keys(d)"
    ".length}}}['localStorage','sessionStorage'].forEach(function(n){try{window[n]"
    ".getItem('x')}catch(e){try{Object.defineProperty(window,n,{value:mem(),"
    "configurable:true})}catch(e2){}}})})();</script>"
)
#: Blob workers that report the page's origin, for the sandboxed frame. A
#: worker made from a ``blob:`` URL there has ``location.origin == "null"``
#: while the page keeps the URL's origin, and MapLibre's actor drops every
#: message whose origin differs from its own (``Actor.receive``): its worker
#: never answers, so every map in the preview stays blank, basemap and
#: markers alike. Each classic blob worker is wrapped so its ``location``
#: names the page's origin, then runs the original script. Only where the
#: origin is opaque.
PREVIEW_WORKER_SHIM = (
    "<script>(function(){if(self.origin!=='null'||typeof Worker!=='function')return;"
    "var W=Worker,o=location.origin;function S(u,opts){var s=String(u);"
    "if(s.indexOf('blob:')===0&&!(opts&&opts.type==='module')){u=URL.createObjectURL("
    'new Blob([\'(function(o){var L=self.location;try{Object.defineProperty(self,"location",'
    "{configurable:true,get:function(){return{origin:o,href:L.href,protocol:L.protocol,"
    "host:L.host,hostname:L.hostname,port:L.port,pathname:L.pathname,search:L.search,"
    "hash:L.hash,toString:function(){return L.href}}}})}catch(e){}})('+JSON.stringify(o)"
    "+');importScripts('+JSON.stringify(s)+');'],{type:'text/javascript'}))}"
    "return new W(u,opts)}S.prototype=W.prototype;window.Worker=S})();</script>"
)


def preview_files_csp() -> str:
    """The served preview's policy: an offline report's, in a sandbox.

    ``sandbox allow-scripts`` gives the frame an opaque origin, so the
    report's scripts run but cannot read the app's storage or call the API as
    the reader. The rest is what the report needs and nothing more: its own
    files from this origin (``report_files/``, the patch script), inline
    scripts and styles, ``data:``/``blob:`` assets, no network except the
    basemap CDNs a map draws from.
    """
    from depictio.api.v1.configs.security_headers import BASEMAP_CONNECT_SRC

    return (
        "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
        "default-src 'none'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' data: blob:; "
        "worker-src blob:; "
        "style-src 'self' 'unsafe-inline' data:; "
        f"img-src 'self' data: blob: {BASEMAP_CONNECT_SRC}; "
        "font-src 'self' data:; "
        f"connect-src 'self' data: blob: {BASEMAP_CONNECT_SRC}; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'none'"
    )


_PREVIEW_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def _preview_relpath(token: str, path: str) -> str | None:
    """The path under the job's token prefix a request names, or ``None``.

    The token is the capability, so a well-formed one is all that is checked
    here (an unknown one simply has no file in the store, and 404s); the path
    may not escape the token's prefix: no absolute path, no ``..``, no
    backslash — exactly the relative paths the render uploaded.
    """
    if not _PREVIEW_TOKEN_RE.match(token):
        return None
    if not path or path.startswith("/") or "\\" in path:
        return None
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or any(p in ("", ".") for p in pure.parts):
        return None
    return "/".join(pure.parts)


def _inject_preview_patch(html: bytes) -> bytes:
    """The patch script tag before ``</body>``, once, in the served report, and
    the storage and worker stand-ins at the top of ``<head>``.

    The editor's edits reach the preview through it; the report's own files
    are served untouched.
    """
    idx = html.rfind(b"</body>")
    if idx == -1:
        return html
    html = html[:idx] + _PREVIEW_PATCH_TAG.encode("utf-8") + html[idx:]
    head = re.search(rb"<head[^>]*>", html)
    if head is None:
        return html
    shims = (PREVIEW_STORAGE_SHIM + PREVIEW_WORKER_SHIM).encode("utf-8")
    return html[: head.end()] + shims + html[head.end() :]


def _preview_headers(*, immutable: bool = False) -> dict[str, str]:
    """The headers of every preview file.

    ``Access-Control-Allow-Origin: *``: the frame is sandboxed, so its origin is
    opaque, and Quarto's own scripts (``quarto.js``, ``tabsets.js``) are ES
    modules, which a browser fetches in CORS mode: without the header the
    contents, the tabsets and the code tools never start. It gives nothing
    away: the token in the URL is the only key to these files either way.
    A file under a token never changes, so all but the patched report are
    cached for the session.
    """
    return {
        "Content-Security-Policy": preview_files_csp(),
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "private, max-age=3600, immutable" if immutable else "no-store",
    }


@dashboards_endpoint_router.get("/notebook_export/preview_files/{token}/{path:path}")
def notebook_export_preview_files(token: str, path: str) -> Response:
    """One file of a preview job's rendered report, by the job's token.

    No sign-in: the token is the capability, minted per job and known only to
    the editor that queued it, so an unknown token or path is simply a file
    the store does not have — a 404 either way. The report itself
    (``report.html``) is served with the patch script injected before its
    ``</body>``; the patch script is served from the service's own assets.
    """
    from depictio.api.v1.services.notebook_export import store

    _require_report_editor()
    relpath = _preview_relpath(token, path)
    if relpath is None:
        raise HTTPException(status_code=404, detail="No such preview file.")
    if relpath == PREVIEW_PATCH_SCRIPT:
        from depictio.api.v1.services.notebook_export import resources

        try:
            patch = resources.asset("preview_patch.js")
        except Exception as exc:  # noqa: BLE001 — an absent asset is a missing file
            raise HTTPException(status_code=404, detail="No such preview file.") from exc
        return Response(
            content=patch.encode("utf-8"),
            media_type="text/javascript",
            headers=_preview_headers(),
        )
    try:
        body = store.get(store.preview_key(token, relpath))
    except Exception as exc:  # noqa: BLE001 — no such object is no such file
        raise HTTPException(status_code=404, detail="No such preview file.") from exc
    if relpath == "report.html":
        body = _inject_preview_patch(body)
    return Response(
        content=body,
        media_type=store.preview_content_type(relpath),
        headers=_preview_headers(immutable=relpath != "report.html"),
    )


@dashboards_endpoint_router.post(
    "/notebook_export/{dashboard_id}/preview",
    response_model=NotebookRenderStatus,
    status_code=202,
)
def notebook_export_preview(
    dashboard_id: PyObjectId,
    request: ReportPreviewRequest,
    current_user: User = Depends(get_user_or_anonymous),
    access_token: Annotated[str | None, Depends(oauth2_scheme_optional)] = None,
) -> NotebookRenderStatus:
    """Render the dashboard's report as the editor's exact preview.

    The render route's own path — the same document, the same worker, the
    same quotas and gates — into a job whose report the editor polls and
    shows. A finished job of the same user, dashboard and document answers
    instead of queuing a new one, unless ``force`` asks for a fresh render
    (which also re-executes the cached cells of the preview's workdir).
    """
    _require_report_editor()
    _editable_family(dashboard_id, current_user)
    _require_render_enabled()
    _require_signed_in(current_user)

    from depictio.api.celery_app import render_notebook_report
    from depictio.api.v1.services.notebook_export import jobs, store
    from depictio.serverless.report import user_payload

    state = _resolved_request_state(dashboard_id, NotebookExportRequest())
    user_id = str(current_user.id)
    # The report the reader gets: the runtime embedded when it may be, no
    # PDF (that stays the export's own feature), and the server never runs
    # an author's Python itself.
    embed_runtime = _embed_runtime(
        NotebookExportRequest(), dashboard_id, state, current_user, default=True
    )
    plan = build_export_plan(
        dashboard_id,
        state,
        current_user,
        access_token,
        embed_runtime=embed_runtime,
        pdf=False,
    )
    _require_owner_for_authored_code(plan, current_user)
    plan.author_code = False
    # A preview is built from a NEUTRAL layer: every tile in the report,
    # default order and placement, no caption overrides, no page breaks, the
    # default cover, no intro or conclusion — the editor applies all of that
    # itself, in the browser, the instant it is typed, and Quarto re-renders
    # only when the filter state or the data change. So the built document —
    # and with it the preview cache key below — depends on nothing a text
    # edit changes: the same report previewed after one is served from the
    # finished job instead of run again. The layer's own state stays in
    # charge (``_resolved_request_state`` above), and the real layer still
    # drives every download.
    plan.report_layer = ReportLayer().model_dump(mode="json")
    # The preview's provenance carries the day, not the minute (a cache key
    # must not move with the clock), and Quarto renders it with
    # ``embed-resources: false`` — the editor's iframe loads the report and
    # its files from the API (``preview_files``) rather than one huge file.
    plan.preview = True
    builder = NotebookBuilder(plan)
    qmd = builder.build().encode("utf-8")
    data_identity = _report_data_identity(plan)
    cache_key = _preview_cache_key(qmd, embed_runtime, data_identity)

    if not request.force:
        ready = _cached_preview(user_id, str(dashboard_id), cache_key, current_user)
        if ready is not None:
            return ready

    # After the cache: answering with a finished preview costs no render.
    limits = settings.notebook_export
    jobs.admit(
        user_id,
        jobs.RENDER,
        max_active=limits.render_max_active_per_user,
        max_per_hour=limits.render_max_per_hour,
        window_s=2 * limits.render_timeout_s + 120 + 3600,
    )
    job_id = uuid4().hex
    filename = f"{plan.stem}.html"
    notebook_key = store.job_key(user_id, job_id, f"{plan.stem}.qmd")
    store.put(notebook_key, qmd, store.QMD_MEDIA_TYPE)
    jobs.record(job_id, user_id, jobs.RENDER, dashboard_id=str(dashboard_id), preview_key=cache_key)

    # The preview's workdir on the worker: one per user and dashboard, so its
    # jupyter-cache serves the next preview of the same dashboard (a
    # text-only edit then renders without re-executing the tiles). ``force``
    # asks the worker to re-execute everything and refresh that cache.
    render_notebook_report.apply_async(
        kwargs={
            "job_id": job_id,
            "user_id": user_id,
            "notebook_key": notebook_key,
            "stem": plan.stem,
            "api_url": settings.fastapi.internal_url,
            "runtime": (
                {
                    "dashboard_id": str(dashboard_id),
                    "state": state.model_dump(mode="json"),
                    "user": user_payload(current_user),
                    "config": builder.runtime_config(),
                }
                if embed_runtime
                else None
            ),
            "combined": None,
            "filename": filename,
            "pdf": False,
            "preview": True,
            # One workdir per data identity too: Quarto's cell cache is keyed
            # on the cell source, so it would serve outputs of the old data.
            "preview_cache": f"{user_id}/{dashboard_id}/{data_identity[:16]}",
            "preview_force": bool(request.force),
        },
        task_id=job_id,
    )
    logger.info(f"📄 Report preview {job_id} queued for dashboard {dashboard_id}")
    return NotebookRenderStatus(job_id=job_id, status="queued", filename=filename, phase="queued")


_RENDER_FAILED = "The report could not be rendered (the server log has the details)."


@dashboards_endpoint_router.get(
    "/notebook_export/render/{job_id}", response_model=NotebookRenderStatus
)
def notebook_export_render_status(
    job_id: str,
    current_user: User = Depends(get_user_or_anonymous),
) -> NotebookRenderStatus:
    """Where a render job is: queued, running, ready to download, or failed."""
    _require_render_enabled()
    result, payload, record = _render_job(job_id, current_user)
    if result.successful():
        return NotebookRenderStatus(
            job_id=job_id,
            status="ready",
            filename=payload.get("filename"),
            size=payload.get("size"),
            pdf_filename=payload.get("pdf_filename"),
            pdf_error=payload.get("pdf_error"),
            preview_url=payload.get("preview_url"),
        )
    if result.failed() or record.get("status") == "failed":
        # The worker's own sentence, never the exception's text.
        reason = str(record.get("reason") or _RENDER_FAILED)
        return NotebookRenderStatus(job_id=job_id, status="error", reason=reason)
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

    result, payload, _record = _render_job(job_id, current_user)
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
    key = payload.get("key")
    if not key:
        # A preview job keeps no downloadable report: the editor serves its
        # files through the preview_files route, by the job's token.
        raise HTTPException(
            status_code=404,
            detail=f"Render job '{job_id}' made no downloadable report "
            "(the editor's preview is served, not downloaded).",
        )
    try:
        html = store.get(str(key))
    except Exception as exc:  # noqa: BLE001 — a missing object is a gone report
        raise HTTPException(
            status_code=404, detail=f"Report '{job_id}' is no longer stored."
        ) from exc
    return Response(
        content=html,
        media_type=store.HTML_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
