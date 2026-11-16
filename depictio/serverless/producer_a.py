"""Producer A — export a static dashboard bundle from a RUNNING instance.

RFC §3.3: the full-fidelity producer. Input is a dashboard that lives in Mongo
(with its Delta tables in S3/MinIO); output is one self-contained HTML file
(phase 2: ``single-file`` mode only), sharing the manifest contract and the
emission machinery with producer B (``producer_b.py``).

Everything runs **in-process** — no HTTP round-trips to the API:

- Live tiers (cards / interactive / text, and since phase 4 the advanced_viz
  data-path kinds) bundle their data collections the same way producer B does:
  ``load_deltatable_lite(..., init_data=...)`` →
  prune to the union of consuming components' columns (plus every interactive
  filter column that exists in the schema, mirroring the server's
  ``_effective_projection`` fold) → companion columns / codebooks → re-export
  as fresh snappy Parquet with 250k row groups. The Delta part-files are never
  globbed (RFC §6 / errata: tombstones double-count rows).
- Frozen tiers call the *real* endpoint bodies with the default (empty)
  filter state: ``bulk_compute_cards`` (fallback card payloads),
  ``render_table_endpoint`` (paged to the producer-B row cap),
  ``build_figure_preview`` (the Celery task *function*, called directly — the
  same code path preview and render share), ``fetch_advanced_viz_data`` (the
  phylogenetic kind only — its ``sampling`` block is kept verbatim),
  ``render_multiqc*``, and the map service with the basemap forced to
  ``white-bg`` (zero-network single-file).
- Staleness: each DataRef records the server's ``_get_aggregation_hash`` for
  its DC (RFC errata #8), so a rebuilt bundle can be compared against the
  instance state it was cut from.

Figures are first offered to the bind-and-refill builder (``binding.py``, RFC
§4), exactly like producer B: a component that binds ships a *binding table*
built from the same pruned frame whose Parquet lands in the bundle and goes
``live`` (no frozen payload — the runtime refills from the bundled data). A
component that cannot be bound with certainty falls back to the frozen path
with reason ``binding_miss``.

Code-mode figures join them since phase 6 (RFC §7): their data prologue is
compiled to the JSON IR (``prologue.py``), the figure is built by the *server*
pipeline (``build_figure_preview`` — RestrictedPython, never a local exec), the
IR is replayed here with Polars (``prologue_exec.py``) to rebuild the frame the
code handed to plotly-express, and the binder matches the two. A bound one
ships ``prologues[cid]`` + ``bindings[cid]`` with its DC bundled keep-all; code
the transpiler refuses stays frozen with reason ``code_mode``.

advanced_viz components split three ways since phase 4: the tabular data-path
kinds go ``live`` (their DC is bundled, pruned to the columns their ``config``
binds, and the in-browser engine recomputes ``/advanced_viz/data`` at every
filter state — no frozen payload); ``phylogenetic`` stays frozen, because its
Newick tree DC is a second, non-tabular source one bundled table cannot carry;
and the four Celery-computed kinds (embedding, complex_heatmap, upset, sankey)
are *pre-exported*: the producer calls their task functions in-process and
ships the result as a frozen ``compute`` payload, which the runtime's
dispatch/poll shim hands back as a finished job. They are badged as
computed-at-export — no filter refreshes them — and degrade to ``omitted``
(with the reason) when the compute fails or runs past its budget.
``coverage_track`` dispatches server-side too but left that family in phase 8:
its task is row-wise plus a per-(chromosome, sample) rolling mean, so the
browser recomputes it live from the bundled Parquet like any data-path kind
(see ``CELERY_VIZ_KINDS``).

One bundle carries a whole **tab family** (RFC §3.1 ``BundleManifest.tabs``):
the requested dashboard is the entry tab, its main tab and siblings ride along,
and every component-keyed section merges across them. Data collections are
deduplicated by dc_id over the family, which is where the size goes: six tabs
over the same two tables used to mean six bundles each re-inlining both.
``manifest.provenance`` records who exported it, when, and from which instance.

``--check`` (``export_static(check=True)``) is that same build, run for its
verdicts and stopped before it produces anything: the data collections are
loaded and pruned and every figure goes through the binder, because that is the
only thing that can tell a live figure from a frozen one — but no Parquet is
written, no payload frozen, no Celery compute dispatched and no manifest
emitted. It costs seconds, and no FIGURE comes back ``provisional``; the rows it
does not run (a Celery compute the build's budget may not cover, a frozen
payload that may fail) are still the plan. ``bind=False`` opts back down to the
instant, data-free plan (:func:`classify_stored_component`).

Permissions (RFC §8): ``--check`` needs *viewer* on the dashboard's project —
every row it reads is a row the render endpoints would already serve that
viewer; the build itself needs *owner* — a bundle is bulk data exfiltration.
Both are evaluated for EVERY tab of the family (they share a project in
practice, so it is the same check repeated — but the bundle does not have to
assume that).
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
from bson import ObjectId

from depictio.models.models.base import convert_objectid_to_str
from depictio.models.models.serverless import (
    BindingTable,
    BundleManifest,
    BundleMode,
    ColumnSpec,
    ComponentTier,
    DashboardSection,
    DataRef,
    ExportProvenance,
    FrozenPayload,
    LinksSection,
    LinkTable,
    Producer,
    PrologueOp,
    TabEntry,
    TierEntry,
    TierReason,
)
from depictio.serverless import computes
from depictio.serverless.binding import (
    BindingMiss,
    build_binding_with_reason,
    frozen_miss_detail,
    miss_tier_reason,
    planned_figure_miss,
)
from depictio.serverless.companions import filter_expr_companionable
from depictio.serverless.objects import IMAGE_SNAPSHOT_MAX, IMAGE_THUMB_PX, ObjectBudget
from depictio.serverless.preflight import (
    LINK_TIER_A,
    LINK_TIER_B,
    LINK_TIER_INERT,
    LinkRow,
    PlannedTier,
    TabRow,
    TierRow,
)
from depictio.serverless.producer_b import (
    PARQUET_COMPRESSION,
    PARQUET_ROW_GROUP_SIZE,
    SAMPLE_MAPPING_NO_INLINE_NOTE,
    _companion_targets,
    _depictio_version,
    _runtime_limits,
    render_bundle_html,
    runtime_floor_bytes,
)
from depictio.serverless.prologue import transpile_with_reason
from depictio.serverless.prologue_exec import execute_ops, terminal_px_call
from depictio.serverless.pruning import (
    CELERY_VIZ_KINDS,
    PYTHON_JOB_KEY,
    advanced_viz_capability,
    advanced_viz_columns,
    advanced_viz_companions,
    advanced_viz_kind,
    advanced_viz_roles,
    component_columns,
    link_target_column,
    serves_advanced_viz_live,
    ships_frozen_inputs,
)

# Component types whose data ships in the bundle (live in the static runtime).
# Figures are handled via :func:`_refillable_figure`: their DC is bundled too,
# so the bind-and-refill runtime can refill bound traces from it. advanced_viz
# components go through :func:`serves_advanced_viz_live` for the same reason —
# their data-path kinds are recomputed in the browser since phase 4.
# Tables are here because the runtime reproduces `render_table_endpoint` in full
# (filter → sort → slice, `renderTableLive`), so their DC must ship — unpruned,
# since any column can be sorted or filtered on (pruning.component_columns).
LIVE_DATA_TYPES = frozenset({"card", "interactive", "table"})

logger = logging.getLogger(__name__)


#: Export-time context a code figure's injected names fold against
#: (``context_fold``), set on the component by :func:`annotate_code_context` and
#: stripped from the shipped document (``sanitize_dashboard_doc``).
_FOLD_COLORS_KEY = "__fold_category_colors__"
_FOLD_COLUMNS_KEY = "__fold_columns__"


def figure_code(comp: dict[str, Any]) -> str:
    """The code the transpiler and the binder read: the stored code with the
    injected context (``depictio_group_by`` / ``depictio_group_kwargs`` /
    ``depictio_category_colors``) folded at the export's default state."""
    from depictio.serverless.context_fold import fold_context

    return fold_context(
        comp.get("code_content") or "",
        comp.get(_FOLD_COLORS_KEY) or {},
        comp.get(_FOLD_COLUMNS_KEY),
    )


def annotate_code_context(tabs: list["FamilyTab"]) -> None:
    """Give each code figure the dashboard's category colours and its
    collection's columns, which the fold needs (a ``'x' in df.columns`` guard
    folds only against the real schema)."""
    routes = _routes()
    dtu = _dtu()
    schema_cache: dict[str, list[str] | None] = {}
    for tab in tabs:
        try:
            colors = routes.effective_category_colors(tab.doc) or {}
        except Exception:
            colors = {}
        for comp in tab.components:
            if comp.get("component_type") != "figure" or comp.get("mode") != "code":
                continue
            comp[_FOLD_COLORS_KEY] = colors
            dc_id = str(comp.get("dc_id") or "")
            if dc_id and dc_id not in schema_cache:
                try:
                    init = _dc_init_entry(comp)
                    schema_cache[dc_id] = (
                        list(
                            dtu.schema_deltatable_lite(
                                workflow_id=ObjectId(str(comp.get("wf_id"))),
                                data_collection_id=dc_id,
                                init_data={dc_id: init} if init else None,
                            ).keys()
                        )
                        if comp.get("wf_id")
                        else None
                    )
                except Exception:
                    schema_cache[dc_id] = None
            if schema_cache.get(dc_id) is not None:
                comp[_FOLD_COLUMNS_KEY] = schema_cache[dc_id]


def _code_figure_plan(
    comp: dict[str, Any],
) -> tuple[list[PrologueOp] | None, tuple[str, dict[str, Any]] | None, str | None]:
    """``(prologue ops, terminal px call, refusal)`` for a code-mode figure.

    Both halves must succeed for the figure to be bindable: the ops let the
    runtime re-derive the code's frame, and the ``px`` call names the columns
    the binder forms its hypothesis from. Either refusal returns
    ``(None, None, reason)`` and the figure freezes with ``code_mode``.
    """
    code = figure_code(comp)
    ops, refusal = transpile_with_reason(code)
    if ops is None:
        return None, None, refusal
    call = terminal_px_call(code)
    if call is None:
        return None, None, "figure call not analyzable"
    return ops, call, None


def _refillable_figure(comp: dict[str, Any]) -> bool:
    """True when a figure is offered to the bind-and-refill builder (RFC §4),
    so its DC's frame must be loaded (and, if the figure binds, bundled).

    ui-mode figures always are. A code-mode figure is too when its data
    prologue transpiles and its ``px`` call is readable (RFC §7, phase 6) — its
    DC then ships **keep-all** (``pruning.component_columns`` never projects
    code mode: arbitrary code reads anything, and the runtime re-derives the
    frame from the bundled base columns). Code the transpiler refuses keeps the
    old road: frozen payload, no data bundled for it.
    """
    if comp.get("component_type") != "figure":
        return False
    if comp.get("mode", "ui") != "code":
        return True
    return _code_figure_plan(comp)[1] is not None


def _ships_data(comp: dict[str, Any]) -> bool:
    """True when a component's DC must be bundled for it to work offline.

    The union of the three data paths the static runtime computes itself:
    cards/interactive (re-queried in the browser), the figures offered to
    bind-and-refill, and the advanced_viz kinds the in-browser engine serves
    (phase 4). Everything else is either frozen (payload self-contained) or
    omitted.
    """
    return (
        comp.get("component_type") in LIVE_DATA_TYPES
        or _refillable_figure(comp)
        or serves_advanced_viz_live(comp)
        or ships_frozen_inputs(comp)
        or bool(comp.get(PYTHON_JOB_KEY))
    )


# A table only freezes when its data collection could not be bundled. That
# fallback inlines rows into the manifest, so cap them like the catalog preview
# does — a large DC must not blow the single-file byte budget.
TABLE_FROZEN_MAX_ROWS = 1_000

# render_table_endpoint clamps ``limit`` to 500 per request; page up to the
# producer cap (``TABLE_FROZEN_MAX_ROWS``).
_TABLE_PAGE_LIMIT = 500

# Dashboard-document keys stripped before embedding: Mongo internals, the
# permission ACL (a shared bundle must not carry user identities), and the
# realtime config (errata #5 — omitting ``project_realtime`` keeps
# ``useDataCollectionUpdates`` inert, so the bundle never opens a WebSocket).
_DOC_STRIP_KEYS = frozenset({"_id", "permissions", "project_realtime"})


class ProducerAError(Exception):
    """Raised when a dashboard cannot be exported to a bundle."""


class BundleTooLargeError(ProducerAError):
    """Raised when a bundle crosses ``performance.static_bundle_max_mb``.

    A subclass because it is the one producer-A refusal that is neither a
    permission denial nor a missing document: the dashboard exists and the
    caller may read it, the artifact is simply too big to hand over. The HTTP
    surface maps it to its own status so a preflight of an oversized dashboard
    does not answer "not found" (``serverless_endpoints/routes.py``).
    """


# ---------------------------------------------------------------------------
# Lazy server-module accessors.
#
# Producer A's dependencies (Mongo client, endpoint bodies, the Celery task
# function) live in modules that are heavy to import and need DEPICTIO_CONTEXT
# set; resolving them through their module objects at call time keeps
# ``import depictio.serverless.producer_a`` cheap and lets tests monkeypatch
# the module attributes (``routes.bulk_compute_cards = fake``) without any
# seam of our own.
# ---------------------------------------------------------------------------


def _db():
    from depictio.api.v1 import db

    return db


def _dtu():
    from depictio.api.v1 import deltatables_utils

    return deltatables_utils


def _routes():
    from depictio.api.v1.endpoints.dashboards_endpoints import routes

    return routes


def _dashboards_core():
    """``dashboards_endpoints.core_functions`` — the tab-family helpers.

    Note it binds ``dashboards_collection`` at import time (a ``from ... import``),
    so tests that fake the collection must patch it on THIS module, not on
    ``depictio.api.v1.db``.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints import core_functions

    return core_functions


def _av_routes():
    from depictio.api.v1.endpoints.advanced_viz_endpoints import routes

    return routes


def _celery():
    from depictio.api.v1 import celery_tasks

    return celery_tasks


def _response():
    """A throwaway ``fastapi.Response`` for endpoint bodies that set headers."""
    from fastapi import Response

    return Response()


# ---------------------------------------------------------------------------
# User resolution + permissions
# ---------------------------------------------------------------------------


@dataclass
class ExportUser:
    """The minimal user surface ``check_project_permission`` and the endpoint
    bodies read (``id`` / ``is_admin`` / ``is_anonymous``)."""

    id: Any
    email: str = ""
    is_admin: bool = False
    is_anonymous: bool = False


def resolve_user(user: Any = None) -> ExportUser:
    """Normalise the ``user`` argument into an :class:`ExportUser`.

    Accepts a User-like object (anything with ``id``/``is_admin``), an email
    string (looked up in ``users_collection``), or ``None`` — which falls back
    to the instance's first admin account, matching how operator-run exports
    are expected to be invoked.
    """
    if user is not None and not isinstance(user, str):
        return ExportUser(
            id=getattr(user, "id", None),
            email=getattr(user, "email", "") or "",
            is_admin=bool(getattr(user, "is_admin", False)),
            is_anonymous=bool(getattr(user, "is_anonymous", False)),
        )

    query: dict[str, Any] = {"email": user} if isinstance(user, str) else {"is_admin": True}
    doc = _db().users_collection.find_one(query)
    if not doc:
        target = f"user {user!r}" if isinstance(user, str) else "an admin user"
        raise ProducerAError(f"cannot resolve {target} in users_collection")
    return ExportUser(
        id=doc.get("_id"),
        email=doc.get("email") or "",
        is_admin=bool(doc.get("is_admin", False)),
        is_anonymous=bool(doc.get("is_anonymous", False)),
    )


# ---------------------------------------------------------------------------
# Tab family (RFC §3.1 ``BundleManifest.tabs``)
#
# Server-side a dashboard's tabs are SEPARATE documents: one main tab
# (``is_main_tab``, its ``dashboard_id`` is the family id) plus children
# carrying ``parent_dashboard_id`` + ``tab_order``, switched by routing to
# /dashboard/<id>. A bundle has no routing and no server, so one bundle carries
# the whole family: every tab's document, the component-keyed sections merged
# across them (component ids are uuids), and — the actual size win — ONE copy
# of each data collection however many tabs read it.
# ---------------------------------------------------------------------------


@dataclass
class FamilyTab:
    """One tab of the exported family: its full Mongo document plus its place."""

    doc: dict[str, Any]
    tab_order: int = 0
    is_main_tab: bool = False

    @property
    def id(self) -> str:
        return str(self.doc.get("dashboard_id") or "")

    @property
    def title(self) -> str:
        return self.doc.get("title") or ""

    @property
    def components(self) -> list[dict[str, Any]]:
        return self.doc.get("stored_metadata") or []

    def tab_entry(self) -> TabEntry:
        """The manifest entry for this tab (document sanitised like the entry tab).

        Icons follow the tabs endpoint's inheritance: the tab's own
        ``tab_icon``/``tab_icon_color`` when set, else the dashboard's.
        """
        return TabEntry(
            id=self.id,
            title=self.title,
            tab_order=self.tab_order,
            is_main_tab=self.is_main_tab,
            icon=self.doc.get("tab_icon") or self.doc.get("icon"),
            icon_color=self.doc.get("tab_icon_color") or self.doc.get("icon_color"),
            doc=sanitize_dashboard_doc(self.doc),
        )

    def tab_row(self) -> TabRow:
        """The ``--check`` / preflight-endpoint row for this tab."""
        return TabRow(
            id=self.id,
            title=self.title,
            tab_order=self.tab_order,
            is_main_tab=self.is_main_tab,
        )


def family_from_doc(
    entry_doc: dict[str, Any], single_tab: bool = False
) -> tuple[list[FamilyTab], FamilyTab]:
    """``(tabs, entry_tab)`` around an already-fetched dashboard document.

    Takes the document rather than an id so callers run the permission gate on
    the requested dashboard BEFORE the family is walked — a denied export must
    not read other dashboards first.

    The requested dashboard stays the ENTRY tab (``manifest.dashboard``) even
    when it is a child, so exporting a child opens the bundle on that child.
    Resolution walks UP first (``parent_dashboard_id``) and then collects the
    family through :func:`core_functions.get_child_tabs` — the same helper the
    ``GET /dashboards/tabs/{parent}`` endpoint uses — ordered main tab first,
    then children by ``tab_order`` with the title breaking ties.

    ``single_tab=True`` short-circuits to the requested document alone. A
    dangling ``parent_dashboard_id`` degrades to the same single-tab export
    rather than failing the build: half a family is still a usable bundle.
    """
    entry_tab = FamilyTab(
        doc=entry_doc,
        tab_order=int(entry_doc.get("tab_order") or 0),
        is_main_tab=bool(entry_doc.get("is_main_tab", True)),
    )
    if single_tab:
        return [entry_tab], entry_tab

    entry_id = entry_tab.id
    parent_id = str(entry_doc.get("parent_dashboard_id") or entry_id)
    if parent_id == entry_id:
        main_tab = entry_tab
        main_tab.tab_order = 0
        main_tab.is_main_tab = True
    else:
        try:
            main_tab = FamilyTab(doc=_fetch_dashboard(parent_id), tab_order=0, is_main_tab=True)
        except ProducerAError as exc:
            logger.warning(
                "producer A: dashboard %s points at a missing parent %s (%s) — "
                "exporting it as a single-tab bundle",
                entry_id,
                parent_id,
                exc,
            )
            return [entry_tab], entry_tab

    try:
        children = _dashboards_core().get_child_tabs(ObjectId(parent_id))
    except Exception as exc:  # a family that cannot be listed is not a fatal export
        logger.warning("producer A: could not list child tabs of %s: %s", parent_id, exc)
        children = []

    tabs = [main_tab]
    for child in sorted(
        children, key=lambda c: (int(c.get("tab_order") or 0), str(c.get("title") or ""))
    ):
        child_id = str(child.get("dashboard_id") or "")
        if not child_id or child_id == main_tab.id:
            continue
        doc = entry_doc if child_id == entry_id else _fetch_dashboard(child_id)
        tabs.append(
            FamilyTab(
                doc=doc,
                tab_order=int(child.get("tab_order") or 0),
                is_main_tab=False,
            )
        )

    entry = next((tab for tab in tabs if tab.id == entry_id), entry_tab)
    return tabs, entry


def family_components(tabs: list[FamilyTab]) -> list[tuple[FamilyTab, dict[str, Any], str]]:
    """``(tab, component, component_id)`` over the whole family, tab order first.

    The manifest's component-keyed sections (``tiers``/``frozen``/``bindings``/
    ``prologues``) are flat across the family, which is only sound because
    component ids are uuids. Assert it rather than trust it: a collision would
    silently make one tab's component render another tab's payload.
    """
    out: list[tuple[FamilyTab, dict[str, Any], str]] = []
    seen: dict[str, str] = {}
    for tab in tabs:
        for i, comp in enumerate(tab.components):
            raw = comp.get("index")
            cid = str(raw) if raw else f"{tab.id}-component-{i}"
            if raw and cid in seen:
                raise ProducerAError(
                    f"component id {cid!r} appears on two tabs of the family "
                    f"({seen[cid]} and {tab.id}); component ids must be unique across "
                    "a tab family for the bundle's component-keyed sections to merge"
                )
            seen[cid] = tab.id
            out.append((tab, comp, cid))
    return out


# ---------------------------------------------------------------------------
# Tier classification (stored_metadata components)
# ---------------------------------------------------------------------------


def classify_stored_component(comp: dict[str, Any]) -> PlannedTier:
    """Planned (data-free) tier verdict for one ``stored_metadata`` component.

    Mirrors producer B's ``classify_component`` where the logic transfers,
    diverging where producer A *can* compute a frozen payload with the real
    server code (multiqc, maps, advanced_viz data-path kinds).
    """
    ctype = comp.get("component_type") or ""

    if ctype in ("card", "interactive", "text"):
        expr = comp.get("filter_expr")
        if ctype == "card" and expr and not filter_expr_companionable(expr):
            # A window filter_expr (``.over()``) depends on which rows the
            # window spans, so no build-time ``__fe__`` companion stands for it:
            # the card keeps its server value at the default filter state.
            return PlannedTier(
                ComponentTier.FROZEN,
                TierReason.UNSUPPORTED,
                "the card's filter_expr is a window expression (.over()), which the "
                "browser cannot re-evaluate under filters; frozen at the default state",
            )
        return PlannedTier(ComponentTier.LIVE)

    if ctype == "table":
        # Live (phase 3), like producer B plans it: `renderTableLive` reproduces
        # render_table_endpoint in full — filter → sort → slice — off the
        # bundled Parquet, so a table ships no frozen payload. The build
        # downgrades this only when the table's data collection never landed in
        # the bundle, the same condition `renderTable` tests before taking its
        # live path.
        return PlannedTier(
            ComponentTier.LIVE,
            None,
            "served live from the bundled Parquet: `renderTableLive` reproduces "
            "render_table_endpoint (filter → sort → slice) page by page",
        )

    if ctype == "figure":
        if comp.get("mode", "ui") == "code":
            # The transpiler is data-free, so the planned verdict can already
            # tell a replayable prologue (offered to bind-and-refill, RFC §7)
            # from code that will freeze via the server figure pipeline.
            _, call, refusal = _code_figure_plan(comp)
            if call is None:
                return PlannedTier(
                    ComponentTier.FROZEN,
                    TierReason.CODE_MODE,
                    f"code-mode figure not transpilable: {refusal}; frozen via the "
                    "server figure pipeline (RestrictedPython) at the default filter state",
                )
            # The same two data-free bail-outs, read off the terminal ``px``
            # call rather than off stored_metadata: the code names its own
            # visualisation, so `px.scatter_matrix(...)` is exactly as
            # decidable here as a ui-mode whole-frame visu type. Same prefix
            # :func:`decide_figure` uses, so plan and verdict read alike.
            visu_type, px_kwargs = call
            miss = planned_figure_miss({"visu_type": visu_type, "dict_kwargs": px_kwargs})
            if miss is not None:
                return PlannedTier(
                    ComponentTier.FROZEN,
                    miss_tier_reason(miss),
                    frozen_miss_detail(miss, "code analyzed, but "),
                )
            return PlannedTier(
                ComponentTier.FROZEN,
                TierReason.BINDING_MISS,
                "transpilable prologue; offered to bind-and-refill, upgraded to "
                "live when the binding matches",
                provisional=True,
            )
        # Two of the builder's bail-outs are decidable from stored_metadata
        # alone, so decide them here — in the builder's own words — rather than
        # deferring a verdict the build cannot change (``planned_figure_miss``).
        miss = planned_figure_miss(comp)
        if miss is not None:
            return PlannedTier(
                ComponentTier.FROZEN,
                miss_tier_reason(miss),
                frozen_miss_detail(miss),
            )
        return PlannedTier(
            ComponentTier.FROZEN,
            TierReason.BINDING_MISS,
            "planned frozen fallback; the build offers ui-mode figures to the "
            "bind-and-refill builder (RFC §4) first and upgrades bound ones to live",
            provisional=True,
        )

    if ctype == "multiqc":
        # `render_multiqc` only ever fetched a figure keyed on inputs frozen into
        # stored_metadata and then applied the pure `patch_multiqc_figures`
        # (patching.py:59); the runtime ships the same figure and re-applies the
        # same patch under the current filters, with the sample list resolved
        # through the offline link walk. General Statistics rides the same path —
        # its table rows and violin points are the filtered truth; only the
        # `table_styles` data bars keep the export-time full-cohort scale
        # (regenerating them needs matplotlib colormaps,
        # general_stats_payload.py:630).
        return PlannedTier(ComponentTier.LIVE)
    if ctype == "map":
        return PlannedTier(
            ComponentTier.FROZEN,
            TierReason.MAP_TILES,
            "frozen at the default filter state with the basemap forced to "
            "'white-bg' — network tiles are unavailable in a zero-network "
            "single-file bundle",
        )
    if ctype == "image":
        return PlannedTier(
            ComponentTier.FROZEN,
            TierReason.IMAGE,
            "export-time snapshot: the gallery's images at the default filter state, read "
            "from S3 at export and shipped as thumbnails (up to "
            f"{IMAGE_SNAPSHOT_MAX}, longest side {IMAGE_THUMB_PX} px, within the bundle's "
            "object cap); filters do not reach it",
        )
    if ctype == "jbrowse":
        return PlannedTier(
            ComponentTier.FROZEN,
            TierReason.JBROWSE,
            "the genome browser streams its tracks from the server at view time; the bundle "
            "shows the export-time session instead: assembly, locus and the track table",
        )
    if ctype == "advanced_viz":
        kind = advanced_viz_kind(comp)
        # One explicit per-kind verdict (export/capabilities.SERVERLESS_KINDS),
        # never "live by elimination".
        cap = advanced_viz_capability(comp)
        if cap.path == "celery":
            # The compute is run at export time by calling the task function
            # directly (the way figures call build_figure_preview) and shipped
            # as a frozen 'compute' payload, which the static runtime's
            # finishedJob shim hands back as a finished poll result.
            if celery_compute_request(comp) is not None:
                return PlannedTier(
                    ComponentTier.FROZEN,
                    TierReason.CELERY_COMPUTE,
                    CELERY_FROZEN_DETAIL.format(kind=kind),
                )
            return PlannedTier(
                ComponentTier.OMITTED,
                TierReason.CELERY_COMPUTE,
                f"advanced_viz '{kind}' is a server-side Celery compute and no request "
                "can be derived from its config (missing workflow/data-collection id "
                "or required column bindings)",
            )
        if cap.path == "tree":
            return PlannedTier(
                ComponentTier.FROZEN,
                TierReason.UNSUPPORTED,
                f"advanced_viz '{kind}' also reads a non-tabular tree data collection "
                "(Newick), which one bundled table cannot carry — it stays frozen at "
                "the default filter state (tree merged in) while the other data-path "
                "kinds went live in phase 4",
            )
        if cap.tier == "omitted":
            return PlannedTier(
                ComponentTier.OMITTED,
                TierReason.CELERY_COMPUTE
                if cap.path == "per_interaction"
                else TierReason.UNSUPPORTED,
                f"advanced_viz '{kind or '?'}': {cap.reason}",
            )
        if not serves_advanced_viz_live(comp) or advanced_viz_request(comp) is None:
            return PlannedTier(
                ComponentTier.OMITTED,
                TierReason.UNSUPPORTED,
                f"advanced_viz '{kind or '?'}' has no derivable request: its config "
                "binds no column, or the component carries no workflow/data-collection id",
            )
        # Live since phase 4: the in-browser advanced_viz engine recomputes the
        # /advanced_viz/data payload — projection, tail-preserving sampling, the
        # kind's own reduction — from the bundled Parquet at every filter state,
        # so the component ships NO frozen payload (same rule as a bound figure).
        return PlannedTier(
            ComponentTier.LIVE,
            None,
            f"advanced_viz '{kind}' data path served by the in-browser engine "
            "from the bundled Parquet",
        )

    if ctype == "highlight":
        # Another tab's figure / advanced viz shown again here: it takes its
        # source's tier once the family is classified (resolve_highlight_tiers).
        return PlannedTier(
            ComponentTier.OMITTED,
            TierReason.UNSUPPORTED,
            "the highlighted component is not in this export",
            provisional=True,
        )

    return PlannedTier(
        ComponentTier.OMITTED,
        TierReason.UNSUPPORTED,
        f"component type '{ctype or '?'}' is not supported by producer A",
    )


def classify_stored_metadata(
    stored_metadata: list[dict[str, Any]], tab_id: str | None = None
) -> list[TierRow]:
    """The planned tier table for a dashboard document, in component order.

    ``tab_id`` stamps every row with the tab it came from (family exports) and
    scopes the positional fallback id, so two tabs whose components lack an
    ``index`` cannot collide.
    """
    rows: list[TierRow] = []
    for i, comp in enumerate(stored_metadata):
        plan = classify_stored_component(comp)
        fallback = f"{tab_id}-component-{i}" if tab_id else f"component-{i}"
        rows.append(
            TierRow(
                component_id=str(comp.get("index") or fallback),
                title=comp.get("title") or "",
                component_type=comp.get("component_type") or "?",
                tier=plan.tier,
                reason=plan.reason,
                detail=plan.detail,
                tab_id=tab_id,
                provisional=plan.provisional,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Dashboard document + data references
# ---------------------------------------------------------------------------


#: A text tile's header logo is fetched at most this large; past it the URL stays.
MAX_INLINE_LOGO_BYTES = 1024 * 1024

_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
)


def _image_mime(data: bytes) -> str | None:
    for magic, mime in _IMAGE_MAGIC:
        if data.startswith(magic) and (mime != "image/webp" or data[8:12] == b"WEBP"):
            return mime
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "image/svg+xml"
    return None


def inline_text_logos(comp: dict[str, Any]) -> None:
    """Replace a text tile's remote ``logo`` / ``logo_dark`` with a data URI.

    A bundle opens without a network, and a header logo on
    raw.githubusercontent.com (the nf-core templates') was the one request it
    still made, drawn as a broken image. The fetch goes through the SSRF
    gateway (``remote_fetch``), is capped at ``MAX_INLINE_LOGO_BYTES`` and
    must be an image; any failure keeps the URL, so an export never fails over
    a logo.
    """
    import base64

    for key in ("logo", "logo_dark"):
        url = comp.get(key)
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            continue
        try:
            from depictio.api.v1.remote_fetch import fetch_validated_bytes

            data = fetch_validated_bytes(url, max_bytes=MAX_INLINE_LOGO_BYTES, timeout=10)
        except Exception as exc:  # rejected, unreachable, too large: keep the URL
            logger.info("producer A: text logo %s left remote (%s)", url, exc)
            continue
        mime = _image_mime(data)
        if mime is None:
            logger.info("producer A: text logo %s is not an image; left remote", url)
            continue
        comp[key] = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def sanitize_dashboard_doc(dashboard_data: dict[str, Any]) -> dict[str, Any]:
    """The dashboard document the static runtime mounts.

    The real Mongo document, JSON-ready (ObjectId/datetime → str via the same
    ``convert_objectid_to_str`` the API responses use) with Mongo internals,
    the permission ACL and the realtime config stripped (see
    ``_DOC_STRIP_KEYS``). NaN/Infinity safety is the injector's concern
    (``inject.json_safe``).
    """
    doc = {k: v for k, v in dashboard_data.items() if k not in _DOC_STRIP_KEYS}
    if isinstance(doc.get("stored_metadata"), list):
        doc["stored_metadata"] = [
            {
                k: v
                for k, v in m.items()
                if k not in (_FOLD_COLORS_KEY, _FOLD_COLUMNS_KEY, PYTHON_JOB_KEY)
            }
            if isinstance(m, dict)
            else m
            for m in doc["stored_metadata"]
        ]
    return convert_objectid_to_str(doc)


def _dc_init_entry(comp: dict[str, Any]) -> dict[str, Any] | None:
    """One ``init_data`` entry for a component's DC — ``dc_config`` first, the
    ``deltatables_collection`` lookup as fallback (the exact pattern of every
    render endpoint)."""
    dc_id = comp.get("dc_id")
    if not dc_id:
        return None
    dc_config = comp.get("dc_config") or {}
    delta_loc = dc_config.get("delta_location")
    if not delta_loc:
        dt = _db().deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
        if dt:
            delta_loc = dt.get("delta_table_location")
    if not delta_loc:
        return None
    return {
        "delta_location": delta_loc,
        "dc_type": dc_config.get("type") or "table",
        "size_bytes": dc_config.get("size_bytes", 0),
    }


def text_value_cards(stored_metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A text tile's live values (``{{name}}``) as the cards the server computes
    them with (``routes._text_value_cards``): indexed ``<text index>::<name>``,
    so their data collections ship like a card's and the browser computes them
    on the card path (filters, links, filter_expr)."""
    out: list[dict[str, Any]] = []
    for comp in stored_metadata:
        if comp.get("component_type") != "text" or not comp.get("values"):
            continue
        out.extend(_routes()._text_value_cards(comp))
    return out


def text_run_params(
    project_doc: dict[str, Any] | None, text: dict[str, Any]
) -> dict[str, str | None]:
    """The ``{{param:KEY}}`` values a text tile prints, read the way
    ``_project_run_params`` reads them (pipeline params first, unset → None).
    Run constants: the same under every filter, so the bundle carries them."""
    routes = _routes()
    keys = routes._text_params(text)
    if not keys:
        return {}
    entries = ((project_doc or {}).get("template_origin") or {}).get("run_provenance") or []
    params: dict[str, str | None] = {}
    for entry in sorted(entries, key=lambda e: e.get("source") != "params"):
        key = entry.get("key")
        if not key or key in params:
            continue
        value = entry.get("value")
        params[str(key)] = None if value in (None, "", "null") else str(value)
    return {k: params.get(k) for k in keys}


def live_column_sets(stored_metadata: list[dict[str, Any]]) -> dict[str, set[str] | None]:
    """Per-DC column sets for the components whose data ships in the bundle
    (cards + interactive, the figures offered to bind-and-refill, and the
    live advanced_viz kinds).

    Thin translation of ``pruning.compute_column_sets`` onto stored_metadata:
    the components ARE dicts of the shape ``component_columns`` reads
    (``column_name`` / ``breakdown_col`` / ``filter_expr`` / ``dict_kwargs``),
    but producer A keys DCs by their real Mongo ``dc_id`` and only bundles DCs
    that a bundled-data component consumes (frozen payloads carry their own
    data). ui-mode figures contribute ``referenced_columns`` via
    ``component_columns`` — so every column a binding could reference survives
    pruning (``None`` for whole-frame visus widens to a full keep); a
    transpilable code-mode figure contributes ``None`` too, since its code may
    read any column and the runtime re-derives the frame from all of them.
    A live advanced_viz contributes the columns its config binds (the same
    ``pruning.advanced_viz_columns`` the request derivation uses), so the
    in-browser engine finds every projected column in the bundled Parquet.

    Every interactive filter column that exists in a DC's schema is folded in
    later (see :func:`_bundle_data_refs`) to mirror the server's
    ``_effective_projection`` — cross-DC filters bind by column *name*.
    """
    sets: dict[str, set[str] | None] = {}
    for comp in stored_metadata:
        if not _ships_data(comp):
            continue
        dc_id = comp.get("dc_id")
        if not dc_id:
            continue
        key = str(dc_id)
        cols = component_columns(comp)
        # A live advanced_viz's companion tables (hits, domains, variants,
        # family rows, the MA table…) ship too, under their real ids
        # (``pruning.advanced_viz_companions``).
        for companion, (_wf, ccols) in advanced_viz_companions(comp).items():
            if sets.get(companion, set()) is not None:
                sets[companion] = (sets.get(companion) or set()) | ccols
        if key in sets and sets[key] is None:
            continue
        if cols is None:
            sets[key] = None
        else:
            sets[key] = (sets.get(key) or set()) | cols
    return sets


def companion_components(stored_metadata: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``{companion dc_id: pseudo component}`` for every live advanced_viz's
    companion table that is a ``table`` collection (an ``indexed_file`` holds
    objects, not rows). The pseudo component carries what the DC loader reads
    (``dc_id`` + ``wf_id``)."""
    from depictio.api.v1.services.export.embed import _is_table_dc

    out: dict[str, dict[str, Any]] = {}
    for comp in stored_metadata:
        for dc_id, (wf_id, _cols) in advanced_viz_companions(comp).items():
            if dc_id in out:
                continue
            try:
                if not _is_table_dc(dc_id):
                    continue
            except Exception:
                continue
            out[dc_id] = {
                "component_type": "advanced_viz_companion",
                "dc_id": dc_id,
                "wf_id": wf_id or comp.get("wf_id"),
                "companion_of": comp.get("index"),
            }
    return out


def interactive_filter_columns(stored_metadata: list[dict[str, Any]]) -> set[str]:
    """Column names any interactive component filters on (cross-DC candidates).

    Includes the columns of each interactive ``filter_expr``: the scope travels
    with the filter to every DC carrying its column, and its ``__fe__``
    companion can only be evaluated where the expression's columns survived.
    """
    from depictio.serverless.pruning import filter_expr_columns

    out: set[str] = set()
    for comp in stored_metadata:
        if comp.get("component_type") != "interactive":
            continue
        if comp.get("column_name"):
            out.add(comp["column_name"])
        out |= filter_expr_columns(comp.get("filter_expr"))
    return out


# ---------------------------------------------------------------------------
# Frozen payload builders (in-process endpoint bodies, empty filter state)
# ---------------------------------------------------------------------------


def split_bulk_cards(bulk: dict[str, Any], card_indexes: list[str]) -> dict[str, dict[str, Any]]:
    """Per-component slices of a ``bulk_compute_cards`` response.

    The static runtime's ``bulkComputeCards`` shim merges every frozen
    card-kind payload into one response, so each slice keeps the bulk shape.
    """
    out: dict[str, dict[str, Any]] = {}
    values = bulk.get("values") or {}
    secondary = bulk.get("secondary_values") or {}
    aggregations = bulk.get("aggregations") or {}
    for idx in card_indexes:
        if idx not in values:
            continue
        payload: dict[str, Any] = {
            "values": {idx: values[idx]},
            "filter_applied": False,
            "filter_count": 0,
        }
        if idx in secondary:
            payload["secondary_values"] = {idx: secondary[idx]}
        if idx in aggregations:
            payload["aggregations"] = {idx: aggregations[idx]}
        out[idx] = payload
    return out


def _freeze_cards(
    dashboard_oid: ObjectId, cards: list[dict[str, Any]], user: ExportUser
) -> dict[str, dict[str, Any]]:
    """Fallback card payloads (bulk response shape) at the default filter state.

    Cards are live in the bundle; the frozen snapshot is the value the shim
    shows if the in-browser computation fails (live results win on merge).
    """
    indexes = [str(c.get("index")) for c in cards]
    bulk = _routes().bulk_compute_cards(
        dashboard_oid,
        {"filters": [], "component_ids": indexes},
        current_user=user,
        access_token=None,
    )
    return split_bulk_cards(bulk, indexes)


def _freeze_table(
    dashboard_oid: ObjectId,
    component_id: str,
    user: ExportUser,
    max_rows: int = TABLE_FROZEN_MAX_ROWS,
) -> dict[str, Any]:
    """The renderTable response shape, paged up to the shared row cap."""
    routes = _routes()
    rows: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    total = 0
    start = 0
    while start < max_rows:
        limit = min(_TABLE_PAGE_LIMIT, max_rows - start)
        page = routes.render_table_endpoint(
            dashboard_oid,
            component_id,
            {"filters": [], "start": start, "limit": limit},
            _response(),
            current_user=user,
            access_token=None,
        )
        if start == 0:
            columns = page.get("columns") or []
            total = int(page.get("total") or 0)
        page_rows = page.get("rows") or []
        rows.extend(page_rows)
        start += limit
        if not page_rows or len(rows) >= total:
            break
    return {"columns": columns, "rows": rows[:max_rows], "total": total}


def _freeze_figure(comp: dict[str, Any], full_load: bool = False) -> tuple[dict[str, Any], bool]:
    """Build a figure by calling the Celery task *function* directly.

    ``build_figure_preview`` is the single worker code path preview and render
    share (RFC errata #4); calling the function (not ``.delay()``) runs it
    in-process. The payload mirrors ``render_figure_endpoint``'s task payload
    with the default (empty) filter state.

    ui-mode figures reach this only when ``build_binding`` refused them
    (bind-and-refill, RFC §4) — a bound figure ships a binding table and no
    frozen payload. Code-mode figures always come through here, because this is
    also the only sanctioned way to *run* their Python (RestrictedPython, in the
    same sandbox the server uses): the resulting figure is either the frozen
    payload or the binding's scaffold.

    ``full_load=True`` disables the code-mode row cap
    (``_load_uniform_sample``): a figure that is about to be bound must be built
    from the *whole* frame, since the runtime refills it from the whole bundled
    table. Sampling there would produce a scaffold whose traces no filtered view
    can reproduce.

    Returns ``(payload, was_sampled)``.
    """
    payload = {
        "metadata": {
            "wf_id": str(comp.get("wf_id")),
            "dc_id": str(comp.get("dc_id")),
            "dc_config": convert_objectid_to_str(comp.get("dc_config") or {}),
            "visu_type": comp.get("visu_type", "scatter"),
            "dict_kwargs": comp.get("dict_kwargs") or {},
            "mode": comp.get("mode", "ui"),
            "code_content": comp.get("code_content", ""),
            "selection_enabled": bool(comp.get("selection_enabled", False)),
            "selection_column": comp.get("selection_column"),
            "max_points": comp.get("max_points"),
        },
        "filter_metadata": [],
        "theme": "light",
        "full_load": full_load,
    }
    result = _celery().build_figure_preview(payload)
    meta = result.get("metadata") or {}
    if meta.get("error"):
        raise ProducerAError(f"figure code failed: {meta['error']}")
    return result, bool(meta.get("was_sampled", False))


def advanced_viz_request(comp: dict[str, Any]) -> dict[str, Any] | None:
    """The ``/advanced_viz/data`` request an advanced_viz component implies.

    Columns and roles are derived from the component's persisted ``config``
    blob (``<role>_col`` scalars plus sunburst's ``rank_cols`` list) — the
    same convention ``buildAdvancedVizConfigBlob`` writes and the catalog
    preview reads. The derivation itself lives in ``pruning`` so producer B's
    column pruning bundles exactly the columns this request would ask for.
    Returns ``None`` when no columns can be derived.
    """
    if not comp.get("wf_id") or not comp.get("dc_id"):
        return None
    columns = advanced_viz_columns(comp)
    if not columns:
        return None
    return {
        "wf_id": str(comp["wf_id"]),
        "dc_id": str(comp["dc_id"]),
        "columns": columns,
        "filter_metadata": [],
        "viz_kind": advanced_viz_kind(comp) or None,
        "roles": advanced_viz_roles(comp),
    }


def _freeze_advanced_viz(comp: dict[str, Any], user: ExportUser) -> dict[str, Any]:
    """Freeze a data-path advanced_viz via the real ``/advanced_viz/data`` body.

    The response's ``sampling`` block is kept verbatim — it is what the
    renderer's badge reads, and pinning it is what makes a reduced frozen
    frame honest about being reduced.

    A phylogenetic tile is the one asymmetric case: its tree is the
    visualisation and its tip metadata is decoration, so a failed tabular fetch
    only costs the colours while a missing or unreadable tree is fatal
    (:class:`ProducerAError` here, ``omitted`` with the reason in the manifest).
    """
    request = advanced_viz_request(comp)
    if request is None:
        raise ProducerAError(
            "advanced_viz component has no derivable columns (config carries no '*_col' bindings)"
        )
    config = comp.get("config") or {}
    # A phylogenetic tile reads TWO collections, and its own `dc_id` is the tree
    # rather than the table: a `type: phylogeny` DC is a Newick file and has no
    # Delta table at all, so asking `/advanced_viz/data` for it 404s with
    # "no materialised Delta table" and the whole component drops to omitted.
    # `PhylogeneticRenderer` reads the tip metadata from `metadata_wf_id` /
    # `metadata_dc_id` instead (its data-fetching effect) — do the same.
    # The runtime resolves either id back to this component (apiShim.ts,
    # `advancedVizIndexFor`), so one frozen payload still answers both lookups.
    is_phylo = advanced_viz_kind(comp) == "phylogenetic"
    if is_phylo and config.get("metadata_dc_id"):
        request = {
            **request,
            "wf_id": str(config.get("metadata_wf_id") or request["wf_id"]),
            "dc_id": str(config["metadata_dc_id"]),
        }
    av = _av_routes()
    try:
        payload = av.fetch_advanced_viz_data(
            _response(), payload=request, current_user=user, access_token=None
        )
    except Exception as exc:
        # For every other kind the table IS the visualisation, so a failure here
        # is fatal. A phylogenetic tile is drawn from its tree; the tip metadata
        # only colours and labels it, and `PhylogeneticRenderer` already treats
        # it as optional (`metadata_dc_id` absent -> `Promise.resolve(null)` in
        # its data-fetching effect). Losing the table must therefore cost the
        # colours, not the tree: an unmaterialised metadata collection used to
        # omit the whole component.
        if not is_phylo:
            raise
        logger.warning(
            "phylogenetic tile %s: tip metadata unavailable (%s) — shipping the tree alone",
            comp.get("index"),
            exc,
        )
        payload = {
            "columns": [],
            "rows": {},
            "row_count": 0,
            "total_rows": 0,
            "sampled": False,
            "sampling": {"policy": "none", "exact": True, "degraded": False},
            "filter_applied": False,
        }
    # Phylogenetic kind: its renderer also needs the tree; merge the Newick in
    # (frozen payloads are one slot per component — the shim reads the same
    # payload object for both lookups).
    #
    # `config.tree_dc_id` and nothing else: `PhylogeneticRenderer` bails with
    # "missing tree DC binding" before it ever calls `fetchPhylogenyNewick` when
    # that key is unset, so a Newick fetched off the component's own `dc_id`
    # would be a payload the runtime never reads.
    tree_dc_id = config.get("tree_dc_id")
    if tree_dc_id:
        try:
            payload["newick"] = av.get_phylogeny_newick(ObjectId(str(tree_dc_id)), user)
        except Exception as exc:
            # For a phylogenetic tile the TREE is the visualisation and the tip
            # metadata only colours it, so no tree is fatal whatever the table
            # did: the runtime reads a missing `newick` as `''`, the renderer
            # returns null on an empty tree, and the reader gets a titled empty
            # box with no message. Omitting says what happened instead.
            if is_phylo:
                raise ProducerAError(f"phylogeny tree could not be read: {exc}") from exc
            logger.warning("phylogeny newick unavailable for %s: %s", comp.get("index"), exc)
    elif is_phylo:
        raise ProducerAError(
            "phylogenetic tile has no tree data collection bound (config.tree_dc_id): "
            "the renderer refuses it for the same reason"
        )
    return payload


# ---------------------------------------------------------------------------
# Celery-computed advanced_viz kinds — pre-exported at build time
#
# These five kinds have no in-browser equivalent: the server runs them as a
# Celery task and the renderer dispatch/polls for the result. A bundle cannot
# dispatch anything, so the producer runs the compute ITSELF at export time
# (calling the task *function*, like ``build_figure_preview``) and ships the
# result as a frozen payload. The runtime's ``finishedJob`` shim answers both
# dispatch and poll with it, so the renderers are unchanged — which is why the
# payload must be exactly ``{"result": <task return value>}``, the ``result``
# field of the poll endpoint's ``{job_id, status: 'done', result}`` response.
#
# The view is the one a reader would have seen on first paint: every request is
# built from the persisted ``config`` with the renderer's own control defaults,
# at the default (empty) filter state. Filters cannot refresh it — the badge
# says so.
# ---------------------------------------------------------------------------

CELERY_FROZEN_DETAIL = (
    "advanced_viz '{kind}' is a server-side Celery compute: computed at export time — "
    "filters do not refresh this view"
)

# Wall-clock guards. A family can carry a dozen of these and each one can be a
# clustering over a wide matrix, while the export task itself
# (``depictio.serverless.export_static``) is killed at 900 s (soft 600 s). The
# defaults keep every compute bounded and the whole set well inside the soft
# limit, leaving room for the data bundling and figure freezes around them.
DEFAULT_COMPUTE_BUDGET_S = 120.0
DEFAULT_COMPUTE_TOTAL_BUDGET_S = 300.0
COMPUTE_BUDGET_ENV = "DEPICTIO_SERVERLESS_COMPUTE_BUDGET_S"
COMPUTE_TOTAL_BUDGET_ENV = "DEPICTIO_SERVERLESS_COMPUTE_TOTAL_BUDGET_S"


def _env_seconds(name: str, default: float) -> float:
    """A positive float from the environment, or ``default`` (never fatal)."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("producer A: ignoring non-numeric %s=%r", name, raw)
        return default
    return value if value > 0 else default


@dataclass
class ComputeBudget:
    """Time the export may spend running Celery computes in-process."""

    per_component: float = DEFAULT_COMPUTE_BUDGET_S
    total: float = DEFAULT_COMPUTE_TOTAL_BUDGET_S
    spent: float = 0.0

    @classmethod
    def from_env(cls) -> ComputeBudget:
        return cls(
            per_component=_env_seconds(COMPUTE_BUDGET_ENV, DEFAULT_COMPUTE_BUDGET_S),
            total=_env_seconds(COMPUTE_TOTAL_BUDGET_ENV, DEFAULT_COMPUTE_TOTAL_BUDGET_S),
        )

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.spent)

    def slice(self) -> float:
        """Seconds the next compute may take: its own cap, clipped to what is left."""
        return min(self.per_component, self.remaining)

    def charge(self, elapsed: float) -> None:
        self.spent += max(0.0, elapsed)


def _run_with_timeout(func: Any, payload: dict[str, Any], timeout: float) -> Any:
    """Run ``func(payload)`` on a daemon thread, giving up after ``timeout``.

    A Celery task function is a plain call with no cancellation point, and the
    export runs inside a Celery worker whose own soft limit already owns
    SIGALRM — so the only way to bound one compute without stealing that signal
    is to wait on a thread and walk away. The abandoned thread finishes into the
    void (daemon, so it never holds the process open); what matters is that the
    export moves on and the component degrades to omitted.
    """
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = func(payload)
        except BaseException as exc:  # re-raised on the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=_run, name="serverless-compute", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"compute exceeded its {timeout:.0f}s export budget")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def celery_compute_request(comp: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """``(task function name, payload)`` for a Celery-computed advanced_viz.

    Mirrors the payload the component's renderer POSTs on first paint: the
    persisted ``config`` with every interactive control at the default the
    renderer seeds it with, and an empty ``filter_metadata``. ``None`` when the
    component implies no compute at all — an ``embedding`` without
    ``compute_method`` (its renderer reads coordinates from the table instead),
    or a config missing what its task requires.
    """
    kind = advanced_viz_kind(comp)
    if kind not in CELERY_VIZ_KINDS and kind != "embedding":
        return None
    wf_id, dc_id = comp.get("wf_id"), comp.get("dc_id")
    if not wf_id or not dc_id:
        return None
    config = comp.get("config") or {}
    base: dict[str, Any] = {"wf_id": str(wf_id), "dc_id": str(dc_id), "filter_metadata": []}

    if kind == "embedding":
        method = str(config.get("compute_method") or "").lower()
        if method not in {"pca", "umap", "tsne", "pcoa"}:
            return None  # table-driven embedding: no dispatch, no compute
        params: dict[str, Any] = {"n_components": 2}  # renderer starts in 2D
        if method == "umap":
            params["n_neighbors"] = config.get("umap_n_neighbors", 15)
            params["min_dist"] = config.get("umap_min_dist", 0.1)
        elif method == "tsne":
            params["perplexity"] = config.get("tsne_perplexity", 30)
            params["n_iter"] = config.get("tsne_n_iter", 1000)
        elif method == "pcoa":
            params["distance"] = config.get("pcoa_distance") or "bray_curtis"
        extra_cols = [c for c in (config.get("cluster_col"), config.get("color_col")) if c]
        return "compute_embedding", {
            **base,
            "feature_id_col": config.get("sample_id_col") or "sample_id",
            "method": method,
            "params": params,
            "extra_cols": list(dict.fromkeys(extra_cols)),
        }

    if kind == "complex_heatmap":
        return "compute_complex_heatmap", {
            **base,
            "index_column": config.get("index_column") or "sample_id",
            "value_columns": config.get("value_columns") or None,
            "row_annotation_cols": list(config.get("row_annotation_cols") or []),
            "col_annotations": config.get("col_annotations") or None,
            "col_annotation_colors": config.get("col_annotation_colors") or None,
            "cluster_rows": bool(config.get("cluster_rows", True)),
            "cluster_cols": bool(config.get("cluster_cols", True)),
            "cluster_method": config.get("cluster_method") or "ward",
            "cluster_metric": config.get("cluster_metric") or "euclidean",
            "normalize": config.get("normalize") or "none",
            "colorscale": config.get("colorscale") or None,
        }

    if kind in ("upset", "upset_plot"):
        min_size = config.get("min_size")
        return "compute_upset", {
            **base,
            "set_columns": config.get("set_columns") or None,
            "set_colors": config.get("set_colors") or None,
            "annotation_cols": list(config.get("default_annotation_cols") or []) or None,
            "sort_by": config.get("sort_by") or "cardinality",
            "sort_order": config.get("sort_order") or "descending",
            "min_size": 1 if min_size is None else int(min_size),
            "max_degree": config.get("max_degree"),
            "show_set_sizes": bool(config.get("show_set_sizes", True)),
            "show_values": False,  # renderer's own default, never persisted
            "color_intersections_by": config.get("color_intersections_by") or "none",
        }

    if kind == "group_compare":
        # The renderer's opening request (GroupCompareRenderer `compare`): the
        # persisted controls at their seeded defaults. The pair itself is
        # resolved from the data at freeze time (``_group_compare_opening``),
        # because with no configured defaults it is the first two values of
        # ``group_col`` — a fact about the table, not the config.
        group_col = config.get("group_col")
        if not group_col:
            return None
        return "group_compare_opening", {
            **base,
            **computes.group_compare_settings(config),
            "group_col": str(group_col),
            "default_group_a": config.get("default_group_a"),
            "default_group_b": config.get("default_group_b"),
        }

    if kind == "sankey":
        available = config.get("available_step_cols") or []
        step_cols = list(config.get("step_cols") or [])
        all_steps = list(available) if len(available) >= 2 else step_cols
        # The renderer's depth slider starts at the configured step count (or 3),
        # clipped to the universe it can offer.
        depth = max(2, min(len(all_steps), len(step_cols) or 3))
        selected = all_steps[:depth]
        if len(selected) < 2 or len(set(selected)) != len(selected):
            return None  # compute_sankey rejects <2 or duplicate steps
        return "compute_sankey", {
            **base,
            "step_cols": selected,
            "value_col": config.get("value_col") or None,
            "sort_mode": config.get("sort_mode") or "total_flow",
            "min_link_value": float(config.get("min_link_value") or 0.0),
            "step_filters": {},
        }

    return None


def _group_compare_opening(request: dict[str, Any]) -> dict[str, Any]:
    """Resolve the opening pair from the table, then run ``compute_group_compare``."""
    group_col = request["group_col"]
    frame = _dtu().load_deltatable_lite(
        workflow_id=ObjectId(request["wf_id"]),
        data_collection_id=request["dc_id"],
        select_columns=[group_col],
    )
    labels = sorted({str(v) for v in frame.get_column(group_col).to_list() if v is not None})
    pair = computes.group_compare_opening_pair(
        labels, request.get("default_group_a"), request.get("default_group_b")
    )
    if pair is None:
        raise ValueError(f"group_col '{group_col}' has fewer than two values")
    payload = {
        k: v
        for k, v in request.items()
        if k not in ("group_col", "default_group_a", "default_group_b")
    }
    payload.update(computes.selectors(group_col, pair))
    result = _celery().compute_group_compare(payload)
    return {"__request__": payload, **result} if isinstance(result, dict) else result


#: Export-side tasks that wrap a Celery compute (resolve what the renderer
#: would resolve in the browser first). Looked up before the Celery module.
_LOCAL_TASKS: dict[str, Any] = {"group_compare_opening": _group_compare_opening}


def freeze_celery_compute(
    comp: dict[str, Any], budget: ComputeBudget
) -> tuple[dict[str, Any] | None, str]:
    """Run one advanced_viz Celery compute in-process. ``(payload, detail)``.

    ``payload`` is ``None`` when the component could not be computed — budget
    exhausted, timed out, or the task raised — and ``detail`` then says why, so
    the caller can degrade it to ``omitted`` instead of aborting the export. A
    successful compute returns the frozen payload the runtime's shim serves.
    """
    kind = advanced_viz_kind(comp) or "?"
    plan = celery_compute_request(comp)
    if plan is None:
        return None, f"advanced_viz '{kind}' compute request cannot be derived from its config"
    task_name, request = plan

    allowance = budget.slice()
    if allowance <= 0:
        detail = (
            f"advanced_viz '{kind}' skipped: the export's total compute budget "
            f"({budget.total:.0f}s) was already spent"
        )
        logger.warning("producer A: %s", detail)
        return None, detail

    func = _LOCAL_TASKS.get(task_name) or getattr(_celery(), task_name, None)
    if func is None:
        return None, f"advanced_viz '{kind}' compute task {task_name!r} is unavailable"

    started = time.monotonic()
    try:
        result = _run_with_timeout(func, request, allowance)
    except TimeoutError as exc:
        budget.charge(time.monotonic() - started)
        detail = f"advanced_viz '{kind}' compute abandoned: {exc}"
        logger.warning("producer A: %s", detail)
        return None, detail
    except Exception as exc:
        budget.charge(time.monotonic() - started)
        detail = f"advanced_viz '{kind}' compute failed: {exc}"
        logger.warning("producer A: %s", detail)
        return None, detail

    elapsed = time.monotonic() - started
    budget.charge(elapsed)
    if not isinstance(result, dict):
        return None, f"advanced_viz '{kind}' compute returned no payload"
    logger.info(
        "producer A: froze advanced_viz '%s' via %s in %.1fs (%.0fs of %.0fs budget left)",
        kind,
        task_name,
        elapsed,
        budget.remaining,
        budget.total,
    )
    frozen: dict[str, Any] = {"result": result}
    if "__request__" in result:
        # The request the result answers, so the runtime can tell the opening
        # pair from another one instead of passing this result off for it.
        frozen["request"] = result.pop("__request__")
        computes.open_on_frozen_request(comp.setdefault("config", {}), frozen["request"])
        return frozen, computes.frozen_detail(kind, frozen["request"])
    return frozen, CELERY_FROZEN_DETAIL.format(kind=kind)


def _freeze_multiqc(
    dashboard_oid: ObjectId, comp: dict[str, Any], user: ExportUser
) -> tuple[str, dict[str, Any]]:
    """Freeze a MultiQC component via the endpoint its renderer would call.

    Returns ``(kind, payload)`` — General Stats components render through
    ``render_multiqc_general_stats``, everything else through
    ``render_multiqc`` (one of the two per component, mirroring
    ``MultiQCDispatch``).
    """
    routes = _routes()
    component_id = str(comp.get("index"))
    request = {"filters": [], "theme": "light"}
    _, _, _, is_gs = routes._resolve_selected_keys(comp)
    if is_gs:
        payload = routes.render_multiqc_general_stats_endpoint(
            dashboard_oid, component_id, request, current_user=user
        )
        out = _multiqc_payload(payload, component_id)
        expansion = multiqc_sample_expansion(str(comp.get("dc_id") or ""))
        if expansion:
            out = {**out, "sample_expansion": expansion}
        return "multiqc-general-stats", out
    payload = routes.render_multiqc_endpoint(
        dashboard_oid, component_id, request, current_user=user
    )
    out = _multiqc_payload(payload, component_id)
    expansion = multiqc_sample_expansion(str(comp.get("dc_id") or ""))
    if expansion:
        out = {**out, "sample_expansion": expansion}
    return "multiqc", out


def multiqc_sample_expansion(dc_id: str) -> dict[str, list[str]]:
    """``{sample id: report variants}`` for a MultiQC collection, precomputed.

    The server expands every sample constraint (a canonical ``SRR10070130``
    picked in a filter, or a metadata collection's link values) to the variant
    names the traces carry (``SRR10070130_1``) with the reports'
    ``sample_mappings`` (``expand_canonical_samples_to_variants`` +
    ``remap_mappings_to_hub``). The bundle has no report store, so the answer
    is baked per id the mappings know; the runtime unions it over a
    constraint's values before intersecting.
    """
    if not dc_id:
        return {}
    try:
        mappings: dict[str, list[str]] = {}
        for rep in _db().multiqc_collection.find(
            {"data_collection_id": dc_id}, {"metadata.sample_mappings": 1}
        ):
            for key, variants in ((rep.get("metadata") or {}).get("sample_mappings") or {}).items():
                bucket = mappings.setdefault(str(key), [])
                for v in variants or []:
                    if str(v) not in bucket:
                        bucket.append(str(v))
        return expansion_from_mappings(mappings)
    except Exception as exc:
        # Celery's soft time limit is an Exception too: swallowing it here let
        # an export run on past it and ship without its sample expansion.
        if type(exc).__name__ == "SoftTimeLimitExceeded":
            raise
        logger.warning("producer A: MultiQC sample expansion for %s failed: %s", dc_id, exc)
        return {}


#: Characters a sample id can follow inside a MultiQC name and still be
#: matched to it: ``canonicalize_to_hub``'s token boundaries, plus the path
#: separators ``strip_stage_suffixes`` cuts at.
_EXPANSION_BOUNDARY = frozenset("._- /\\")


def expansion_from_mappings(mappings: dict[str, list[str]]) -> dict[str, list[str]]:
    """``{id: variants}`` for every key and variant of ``mappings``.

    For each id this is ``expand_canonical_samples_to_variants([id],
    remap_mappings_to_hub(mappings, [id]))``, the server's own expansion, but
    each id is computed on the mapping entries that can bear on it rather than
    on all of them. Doing it on all of them is quadratic: a viralrecon report
    holds ~21k ids, which took ten minutes and ran past the task's time limit.

    An entry can bear on an id only if one of its names holds the id (case
    folded, suffix-stripped) at its start or after a boundary character: every
    rule of ``canonicalize_to_hub`` and of ``SampleLookup.match`` needs that.
    The remaining entries keep their own keys under the remap and are never
    looked up, so leaving them out changes nothing.
    """
    from bisect import bisect_left

    from depictio.api.v1.services.multiqc.patching import (
        expand_canonical_samples_to_variants,
    )
    from depictio.api.v1.services.multiqc.sample_matching import strip_sample_suffix
    from depictio.cli.cli.utils.sample_mapping import remap_mappings_to_hub

    if not mappings:
        return {}
    entries = list(mappings.items())
    # Every token-start suffix of every name, lowercased: a prefix search on
    # this sorted list finds the names holding an id at a boundary.
    suffixes: list[tuple[str, int]] = []
    for idx, (key, variants) in enumerate(entries):
        for name in {str(key), *(str(v) for v in variants or [])}:
            low = name.strip().lower()
            for pos, ch in enumerate(low):
                if pos == 0 or low[pos - 1] in _EXPANSION_BOUNDARY:
                    suffixes.append((low[pos:], idx))
    suffixes.sort()
    heads = [s for s, _ in suffixes]

    ids = {k for k in mappings} | {v for vs in mappings.values() for v in vs}
    out: dict[str, list[str]] = {}
    for sample in sorted(ids):
        probe = strip_sample_suffix(str(sample).strip()).lower()
        relevant: set[int] = set()
        i = bisect_left(heads, probe)
        while i < len(heads) and heads[i].startswith(probe):
            relevant.add(suffixes[i][1])
            i += 1
        subset = {entries[j][0]: entries[j][1] for j in sorted(relevant)}
        variants = expand_canonical_samples_to_variants(
            [sample], remap_mappings_to_hub(subset, [sample])
        )
        extra = [str(v) for v in variants if str(v) != sample]
        if extra:
            out[sample] = extra
    return out


def _multiqc_payload(payload: Any, component_id: str) -> dict[str, Any]:
    """The endpoint's dict, or a readable refusal when it answered otherwise.

    ``render_multiqc_endpoint`` returns a ``JSONResponse`` rather than a dict
    when the pre-render for that collection is not warm yet — the figures are
    built by a Celery task on first use, and an export that lands in that
    window gets a status body instead of a figure. Pydantic then rejects it
    while validating ``FrozenPayload`` and the component is omitted with a
    `dict_type` validation error in its detail, which tells a reader nothing.
    Name the actual condition instead: it is transient, and re-exporting once
    the pre-render has finished is the fix.
    """
    if isinstance(payload, dict):
        return payload
    raise ProducerAError(
        f"MultiQC component {component_id}: the endpoint returned no figure "
        f"({type(payload).__name__}), which is what it does while the pre-render for this "
        "data collection is still being built. Re-export once it has finished."
    )


def _freeze_map(
    comp: dict[str, Any], user: ExportUser, category_colors: dict | None = None
) -> dict[str, Any]:
    """Freeze a map at the default filter state with a zero-network basemap.

    Mirrors ``render_map_endpoint``'s body, but forces ``map_style`` to
    ``white-bg``: MapLibre tile styles fetch from the network, which a
    single-file bundle must never do (RFC §2.4). The endpoint itself cannot be
    reused verbatim because it reads the component from Mongo — the style
    override has to reach ``render_map``'s ``trigger_data``.
    """
    import json as _json

    from depictio.api.v1.services.figure.mantine_templates import ensure_mantine_templates
    from depictio.api.v1.services.map.render import render_map

    init_entry = _dc_init_entry(comp)
    if init_entry is None:
        raise ProducerAError("map component's DC has no materialised Delta table")
    dc_id = str(comp["dc_id"])
    df = _dtu().load_deltatable_lite(
        workflow_id=ObjectId(str(comp["wf_id"])),
        data_collection_id=dc_id,
        metadata=None,
        init_data={dc_id: init_entry},
    )
    ensure_mantine_templates()
    trigger_data = {**comp, "map_style": "white-bg"}
    fig, data_info = render_map(
        df=df,
        trigger_data=trigger_data,
        theme="light",
        existing_metadata=None,
        access_token=None,
        category_colors=category_colors,
    )
    fig_dict = _json.loads(fig.to_json()) if hasattr(fig, "to_json") else fig
    if isinstance(fig_dict, dict) and "layout" in fig_dict:
        fig_dict["layout"].setdefault("uirevision", "persistent")
    return {
        "figure": fig_dict,
        "metadata": {
            "map_type": comp.get("map_type", "scatter_map"),
            "filter_applied": False,
            "displayed_count": data_info.get("displayed_count"),
            "total_count": data_info.get("total_count"),
        },
    }


# ---------------------------------------------------------------------------
# Bundle size (RFC §8.1)
#
# A `single-file` bundle is one HTML document with every bundled data collection
# base64'd inside it, so its size is producer-side state that has to be capped
# BEFORE the bytes exist — nothing else stops one dashboard from base64-ing
# hundreds of MB into a single string.
# ---------------------------------------------------------------------------

BYTES_PER_MB = 1024 * 1024

# RFC §8.1: bundled data costs ~2 bytes per cell as snappy Parquet once the
# columns are pruned and the categoricals are codebooked, and base64 inflates
# that by 4/3. This is the only number available before anything is serialised
# — the binding preflight loads and prunes every frame but never encodes one —
# so it is what the preflight reports. It is an order-of-magnitude figure, not a
# prediction: the density is entirely a function of how compressible the data
# is, and small frames are dominated by Parquet's fixed footer rather than by
# their cells. On a compressible frame it runs a factor of ~2 high, which is the
# safe direction for a warning; against the exact runtime floor the *total* is
# far closer than the data part alone.
_ESTIMATED_PARQUET_BYTES_PER_CELL = 2
_BASE64_INFLATION = 4 / 3

# Preflight size verdicts, so a caller does not have to re-derive the ceilings
# it was just handed.
SIZE_OK = "ok"
SIZE_OVER_SOFT_LIMIT = "over_soft_limit"
SIZE_WOULD_BE_REFUSED = "would_be_refused"


def estimated_blob_bytes(rows: int, columns: int) -> int:
    """Base64 bytes a frame's Parquet blob is expected to add to the bundle."""
    return int(rows * columns * _ESTIMATED_PARQUET_BYTES_PER_CELL * _BASE64_INFLATION)


def _base64_length(raw_bytes: int) -> int:
    """Length of the base64 encoding of ``raw_bytes`` bytes, without encoding them.

    The running total is checked against this rather than against
    ``len(b64encode(...))`` so the blob that breaches the ceiling is never
    materialised — the whole point of failing fast.
    """
    return 4 * ((raw_bytes + 2) // 3)


def _bundle_size_limits() -> tuple[int, int]:
    """``(soft, hard)`` bundle ceilings in bytes; 0 means "that check is off".

    Read defensively for the same reason :func:`_runtime_limits` is: producer A
    also runs from the CLI, where server settings may not load at all. The
    fallbacks restate ``PerformanceConfig``'s own defaults so a build without
    loadable settings still enforces the documented behaviour instead of no
    behaviour.
    """
    soft_mb, hard_mb = 25, 100
    try:
        from depictio.api.v1.configs.config import settings

        soft_mb = settings.performance.static_bundle_warn_mb
        hard_mb = settings.performance.static_bundle_max_mb
    except Exception:
        # WARNING, not debug: the fallbacks are the documented *defaults*, not
        # the deployment's configured ceilings, so a settings failure silently
        # enforces different numbers than the operator asked for. That has to be
        # visible at the level a server actually logs at.
        logger.warning(
            "producer A: server settings unavailable; falling back to the default bundle "
            "ceilings (%d MB soft / %d MB hard), which may differ from this deployment's "
            "configured performance.static_bundle_warn_mb / static_bundle_max_mb",
            soft_mb,
            hard_mb,
            exc_info=True,
        )
    return max(int(soft_mb), 0) * BYTES_PER_MB, max(int(hard_mb), 0) * BYTES_PER_MB


def size_verdict(total_bytes: int, soft_limit: int, hard_limit: int) -> str:
    """Which of the three buckets a bundle size falls into (0 = limit disabled)."""
    if hard_limit and total_bytes > hard_limit:
        return SIZE_WOULD_BE_REFUSED
    if soft_limit and total_bytes > soft_limit:
        return SIZE_OVER_SOFT_LIMIT
    return SIZE_OK


@dataclass(frozen=True)
class BundleSize:
    """How big a bundle is, or would be, against the ceilings in force.

    ``runtime_bytes`` is never an estimate: it is the built static runtime's
    real size, and on a small dashboard it is most of the total. ``data_bytes``
    is measured on a build and estimated on a preflight (``estimated`` says
    which) — the preflight prunes every frame but never serialises one, so exact
    bytes do not exist on that path.

    Frozen payloads are counted by neither. On the preflight path none have been
    built, which is most of what makes it cheap; on any dashboard large enough
    to approach a ceiling the live data dominates them anyway. On the reference
    families they are worth 0.01–1.4 MB (RFC §8.1), so a total is optimistic by
    about that much — and a full-load code-mode payload that then fails to bind
    can be worth much more. That is why the ceiling is enforced a last time on
    the rendered HTML (:func:`_refuse_oversized_render`), which is the only
    measurement that counts everything the file contains.
    """

    runtime_bytes: int
    data_bytes: int
    total_bytes: int
    soft_limit_bytes: int
    hard_limit_bytes: int
    verdict: str
    estimated: bool


def _bundle_size(data_bytes: int, estimated: bool) -> BundleSize:
    soft_limit, hard_limit = _bundle_size_limits()
    runtime = runtime_floor_bytes()
    total = runtime + data_bytes
    return BundleSize(
        runtime_bytes=runtime,
        data_bytes=data_bytes,
        total_bytes=total,
        soft_limit_bytes=soft_limit,
        hard_limit_bytes=hard_limit,
        verdict=size_verdict(total, soft_limit, hard_limit),
        estimated=estimated,
    )


def estimate_bundle_size(data_refs: dict[str, DataRef]) -> BundleSize:
    """Predicted bundle size from a set of DataRefs, nothing serialised.

    Give it the FINAL refs — the ones a bundle would really carry, after the
    DCs loaded speculatively for figures that then failed to bind have been
    dropped — so it predicts the file the user would receive rather than the
    work the producer did.
    """
    return _bundle_size(
        sum(estimated_blob_bytes(ref.rows, len(ref.columns)) for ref in data_refs.values()),
        estimated=True,
    )


def measured_bundle_size(inline_blobs: dict[str, str]) -> BundleSize:
    """Actual bundle size from the base64 blobs a build produced."""
    return _bundle_size(sum(len(blob) for blob in inline_blobs.values()), estimated=False)


def report_bundle_size(size: BundleSize, dc_count: int) -> None:
    """Log an oversized bundle once, past either ceiling.

    Past the SOFT ceiling the bundle still builds and still works — it just
    stops travelling well — so this reports rather than refuses. That is the
    case this function exists for.

    The HARD branch is a backstop rather than the normal road: both paths now
    charge a running total while they walk their data collections
    (:meth:`_RunningBundleSize.refuse_if_over_hard_limit`), and that total is
    taken over every DC *loaded* while this one is taken over the DCs that
    survived the ``used_dc_ids`` drop — so anything this could refuse has
    already raised. It stays because the two are computed from different
    quantities (a rendered bundle is measured once more in
    :func:`export_static`) and a verdict that says "refused" must never be
    logged as "still travels badly".
    """
    if size.verdict == SIZE_OK:
        return
    if size.verdict == SIZE_WOULD_BE_REFUSED:
        consequence = (
            f"past the {_mb(size.hard_limit_bytes)} hard ceiling "
            "(performance.static_bundle_max_mb) — a build of this dashboard would be refused"
        )
    else:
        consequence = (
            f"past the {_mb(size.soft_limit_bytes)} soft ceiling "
            "(performance.static_bundle_warn_mb) — it still builds, but it will not travel "
            "well: mail attachments cap near 25 MB, and nothing renders until the whole "
            "document is parsed"
        )
    logger.warning(
        "producer A: static bundle %s %s (%s static runtime + %s of base64 Parquet over "
        "%d data collection(s)), %s",
        "is estimated at" if size.estimated else "is",
        _mb(size.total_bytes),
        _mb(size.runtime_bytes),
        _mb(size.data_bytes),
        dc_count,
        consequence,
    )


def _mb(byte_count: float) -> str:
    return f"{byte_count / BYTES_PER_MB:.1f} MB"


@dataclass
class _RunningBundleSize:
    """The data total accumulated while ``_bundle_data_refs`` walks its DCs.

    Exists so the hard ceiling can be enforced *during* the walk rather than
    after it: the export is refused on the data collection that crosses the
    line, and the ones behind it are never read. It keeps the per-DC
    contributions because "your bundle is 140 MB" is not actionable without
    "and these two data collections are 130 MB of it".

    ``estimated`` says which number is being accumulated, because both paths
    charge and both refuse. A serialising build charges the base64 length of
    the Parquet it just wrote (a measurement); a preflight writes no Parquet
    and charges :func:`estimated_blob_bytes` instead — the same RFC §8.1
    density it reports. The preflight is the *open* path (viewer-gated, and
    anonymous in public mode) and its peak memory is the larger of the two —
    uncompressed Polars frames, retained for the binder — so leaving it
    uncapped would mean the cheapest request to make is the one nothing bounds.
    """

    runtime_bytes: int
    hard_limit: int
    estimated: bool = False
    # (dc_id, charged bytes, rows, columns), in the order they were charged.
    blobs: list[tuple[str, int, int, int]] = field(default_factory=list)

    @property
    def data_bytes(self) -> int:
        return sum(size for _dc, size, _rows, _cols in self.blobs)

    @property
    def total_bytes(self) -> int:
        return self.runtime_bytes + self.data_bytes

    def add(self, dc_id: str, blob_bytes: int, rows: int, columns: int) -> None:
        self.blobs.append((dc_id, blob_bytes, rows, columns))

    def _dominant(self) -> str:
        """The three heaviest DCs so far, named for the refusal message."""
        top = sorted(self.blobs, key=lambda blob: blob[1], reverse=True)[:3]
        return ", ".join(
            f"{dc_id} ({_mb(size)}, {rows} rows × {cols} columns)"
            for dc_id, size, rows, cols in top
        )

    def refuse_if_over_hard_limit(self, total_dcs: int) -> None:
        """Raise :class:`BundleTooLargeError` as soon as the hard ceiling is crossed.

        Called once each DC has been charged and *before* its base64 is written,
        so the blob that breaches the ceiling is the last one this process
        touches. The total is over the DCs loaded so far, which includes any
        loaded speculatively for a figure that may yet fail to bind — those
        bytes were really produced, so charging them is right for a memory
        ceiling even though the finished bundle would have dropped them.

        The message names the path it came from: the two totals differ in kind
        (measured base64 vs the §8.1 density), and a preflight's estimate runs
        ~2x high on compressible frames, so a refusal there does not prove a
        build would be refused as well.
        """
        if not self.hard_limit or self.total_bytes <= self.hard_limit:
            return
        if self.estimated:
            data = (
                f"{_mb(self.data_bytes)} of Parquet ESTIMATED at the RFC §8.1 density "
                "(rows × columns × 2 bytes × 4/3)"
            )
            stopped = (
                "so the preflight was refused before the remaining data collections were "
                "loaded. That estimate runs high on compressible data, so a build may still "
                "fit under the ceiling where this report did not"
            )
        else:
            data = f"{_mb(self.data_bytes)} of base64 Parquet"
            stopped = "so the export was refused before the remaining data was encoded"
        raise BundleTooLargeError(
            f"static bundle too large: {_mb(self.total_bytes)} after "
            f"{len(self.blobs)} of {total_dcs} data collection(s) "
            f"({_mb(self.runtime_bytes)} static runtime + {data}) exceeds the "
            f"{_mb(self.hard_limit)} ceiling, {stopped}. Largest so far: {self._dominant()}. "
            "Raise performance.static_bundle_max_mb "
            "(DEPICTIO_PERFORMANCE_STATIC_BUNDLE_MAX_MB; 0 disables the check), or export "
            "fewer/narrower components so less data has to be bundled."
        )


# ---------------------------------------------------------------------------
# Data refs (live tier)
# ---------------------------------------------------------------------------


def _bundle_data_refs(
    stored_metadata: list[dict[str, Any]],
    links: list[dict[str, Any]] | None = None,
    serialize: bool = True,
) -> tuple[dict[str, DataRef], dict[str, str], dict[str, str], dict[str, pl.DataFrame]]:
    """Bundle every DC a live component, a ui-mode figure or a live
    advanced_viz consumes (:func:`_ships_data`).

    ``links`` are the emitted cross-DC link configs; their join columns are
    folded into the per-DC keep sets (:func:`link_join_column_sets`) so a
    bundled link always finds the column it resolves against.

    ``serialize=False`` is the binding preflight's path (``export_manifest(...,
    decide_only=True)``): the frames are loaded, pruned and given their
    companions exactly as a real build would — the binder has to be handed the
    frame the bundle *would* carry, or its verdict is about a different table —
    but no Parquet is written and nothing is base64'd. ``inline_blobs`` then
    stays empty and every ``DataRef`` reports ``size_bytes=0``; nothing on that
    path reads the bytes, and encoding them is the largest cost of a verdict
    that ships no bundle.

    **Size ceilings (RFC §8.1).** BOTH runs keep a running total and are refused
    the moment it crosses ``performance.static_bundle_max_mb``, so the loop
    stops at the data collection that broke it either way and a 200 MB bundle is
    never materialised. What they charge differs: a serialising run charges the
    base64 length of the Parquet it just wrote, a preflight charges
    :func:`estimated_blob_bytes` — it writes none. Charging on both paths is
    what bounds the preflight at all: it is the *viewer*-gated one (anonymous in
    public/demo mode), it loads every DC uncapped and holds each pruned frame
    for the binder, and uncompressed Polars frames peak higher than the base64
    a build accumulates.

    The report is a separate number from the refusal, on both paths: it is taken
    by the caller over the refs that SURVIVE the ``used_dc_ids`` drop, i.e. the
    bytes a user would receive rather than the bytes the producer touched.

    Returns ``(data_refs, inline_blobs, failures, pruned_frames)``.
    ``failures`` maps ``dc_id`` → error string for DCs that could not be loaded
    (their live components are downgraded by the caller). ``pruned_frames``
    maps ``dc_id`` → the exact companion-bearing frame whose Parquet was
    inlined — the frame the bind-and-refill builder must be handed, so a
    binding's column references always exist in the bundled data.
    """
    dtu = _dtu()
    # Text live values compute like cards, so their collections ship like cards'.
    stored_metadata = [*stored_metadata, *text_value_cards(stored_metadata)]
    column_sets = live_column_sets(stored_metadata)
    filter_cols = interactive_filter_columns(stored_metadata)
    join_cols = link_join_column_sets(links or [])
    interactive_comps = [c for c in stored_metadata if c.get("component_type") == "interactive"]
    live_comps_by_dc: dict[str, list[dict[str, Any]]] = {}
    for comp in stored_metadata:
        if not comp.get("dc_id"):
            continue
        if _ships_data(comp):
            live_comps_by_dc.setdefault(str(comp["dc_id"]), []).append(comp)
    companions = companion_components(stored_metadata)
    for dc_id, pseudo in companions.items():
        live_comps_by_dc.setdefault(dc_id, []).append(pseudo)
    # A table bundled only as a companion: keep it whole when none of the
    # over-collected columns are in its schema (its own ``*_col`` names live
    # on the component that reads it).
    companion_only = {
        d for d, comps in live_comps_by_dc.items() if all(c.get("companion_of") for c in comps)
    }

    data_refs: dict[str, DataRef] = {}
    inline_blobs: dict[str, str] = {}
    failures: dict[str, str] = {}
    pruned_frames: dict[str, pl.DataFrame] = {}

    size = _RunningBundleSize(
        runtime_bytes=runtime_floor_bytes(),
        hard_limit=_bundle_size_limits()[1],
        estimated=not serialize,
    )

    for dc_id, comps in live_comps_by_dc.items():
        rep = comps[0]
        wf_id = rep.get("wf_id")
        init_entry = _dc_init_entry(rep)
        if not wf_id or init_entry is None:
            failures[dc_id] = "no materialised Delta table (missing delta_location)"
            continue

        cols = column_sets.get(dc_id)
        try:
            schema = dtu.schema_deltatable_lite(
                workflow_id=ObjectId(str(wf_id)),
                data_collection_id=dc_id,
                init_data={dc_id: init_entry},
            )
            available = list(schema.keys())
            if cols is None:
                select: list[str] | None = None
            else:
                # Fold every interactive filter column that exists in this DC's
                # schema (cross-DC name binding — RFC §5) and every cross-DC
                # link join column (RFC §8) before intersecting — the schema
                # intersection below is the guard that keeps a column absent
                # from this DC out of ``select`` (mirroring ``_project_scan``).
                wanted = cols | filter_cols | join_cols.get(dc_id, set())
                select = [c for c in available if c in wanted]
                if dc_id in companion_only and not (cols & set(available)):
                    select = None
            df = dtu.load_deltatable_lite(
                workflow_id=ObjectId(str(wf_id)),
                data_collection_id=dc_id,
                metadata=None,
                select_columns=select,
                init_data={dc_id: init_entry},
            )
        except Exception as exc:
            failures[dc_id] = f"Delta load failed: {exc}"
            continue

        if "depictio_aggregation_time" in df.columns:
            df = df.drop("depictio_aggregation_time")

        # Companion columns for every interactive filter column present in this
        # frame — including cross-DC ones, which is why *all* interactive
        # components are passed (``_companion_targets`` schema-guards).
        categorical_cols, datetime_cols = _companion_targets(interactive_comps, df)
        from depictio.serverless.companions import build_companions, filter_expr_targets

        # Component-static filter_exprs: this DC's own components (a card's row
        # scoping) plus every interactive scope, which travels with its filter
        # to any DC carrying the column (``__fe__`` companions, RFC §5).
        result = build_companions(
            df,
            categorical_cols,
            datetime_cols,
            filter_expr_targets([*comps, *interactive_comps]),
        )
        pruned_frames[dc_id] = result.df

        blob_key = f"dc_{dc_id}"
        parquet_bytes = b""
        if serialize:
            buf = io.BytesIO()
            result.df.write_parquet(
                buf, compression=PARQUET_COMPRESSION, row_group_size=PARQUET_ROW_GROUP_SIZE
            )
            parquet_bytes = buf.getvalue()
            charged = _base64_length(len(parquet_bytes))
        else:
            # No bytes exist on this path, so charge the number the preflight
            # would REPORT for this frame — same density, same ceiling. Anything
            # else would leave the open path capped by a different rule than the
            # one it tells the caller about.
            charged = estimated_blob_bytes(result.df.height, result.df.width)
        # Charge the frame and check the ceiling BEFORE the base64 is written:
        # over the ceiling nothing below this line runs, so the bundle stops
        # growing at the DC that broke it instead of at the end of the loop.
        size.add(dc_id, charged, result.df.height, result.df.width)
        size.refuse_if_over_hard_limit(len(live_comps_by_dc))
        if serialize:
            inline_blobs[blob_key] = base64.b64encode(parquet_bytes).decode("ascii")
        data_refs[dc_id] = DataRef(
            uri=f"inline:{blob_key}",
            rows=result.df.height,
            size_bytes=len(parquet_bytes),
            columns=[
                ColumnSpec(name=name, dtype=str(dtype)) for name, dtype in result.df.schema.items()
            ],
            companions=result.companions,
            codebooks=result.codebooks,
            # The content hash is a fallback for a DC whose server-side
            # aggregation hash is missing; with no bytes to hash there is
            # nothing honest to put there.
            aggregation_hash=dtu._get_aggregation_hash(dc_id)
            or (hashlib.sha256(parquet_bytes).hexdigest() if serialize else None),
        )

    return data_refs, inline_blobs, failures, pruned_frames


def _base_frame(
    dc_id: str, data_refs: dict[str, DataRef], pruned_frames: dict[str, pl.DataFrame]
) -> pl.DataFrame | None:
    """The bundled frame WITHOUT its build-time companion columns.

    This is the frame a code-mode prologue is replayed on, and it must be the
    same one the runtime rebuilds (``liveData.renderPrologueFigureLive``): the
    DataRef's columns minus the companion map's keys and the reserved
    ``__code__`` / ``__ts__`` / ``__fe__`` prefixes. The user's Python saw the
    Delta frame, which never carries them, so leaving them in could change an
    ``unpivot`` or collide with an alias.
    """
    df = pruned_frames.get(dc_id)
    if df is None:
        return None
    ref = data_refs.get(dc_id)
    companions = set(ref.companions) if ref is not None else set()
    drop = [
        c for c in df.columns if c in companions or c.startswith(("__code__", "__ts__", "__fe__"))
    ]
    return df.drop(drop) if drop else df


def apply_dc_outcomes(
    items: list[tuple[FamilyTab, dict[str, Any], str]],
    tier_by_id: dict[str, TierRow],
    data_refs: dict[str, DataRef],
    dc_failures: dict[str, str],
) -> None:
    """Fold the outcome of the DC load back into the tier rows, in place.

    Components with no data of their own (frozen figures & co.) survive a failed
    DC — their payload is self-contained. The ones the runtime computes itself
    cannot, so an unloadable DC omits them.
    """
    for _tab, comp, component_id in items:
        if comp.get("component_type") not in LIVE_DATA_TYPES and not serves_advanced_viz_live(comp):
            continue
        dc_id = str(comp.get("dc_id") or "")
        row = tier_by_id[component_id]
        if dc_id in dc_failures:
            row.tier = ComponentTier.OMITTED
            row.reason = TierReason.UNSUPPORTED
            row.detail = f"data collection {dc_id} not bundled: {dc_failures[dc_id]}"
        elif comp.get("component_type") == "table" and dc_id not in data_refs:
            # Planned live, but no Parquet to serve pages from — a table whose
            # component carries no resolvable dc_id never even reached
            # `_bundle_data_refs`, so it is neither bundled nor a failure. That
            # is the one case where `renderTable` falls back to a server-rendered
            # snapshot, so the freeze loop has to emit one.
            row.tier = ComponentTier.FROZEN
            row.reason = TierReason.UNSUPPORTED
            row.detail = (
                "table references no bundled data collection; frozen at the default filter state"
            )


def used_dc_ids(
    items: list[tuple[FamilyTab, dict[str, Any], str]],
    tier_by_id: dict[str, TierRow],
    bindings: dict[str, BindingTable],
    python_ids: frozenset[str] | set[str] = frozenset(),
) -> set[str]:
    """The DCs whose bytes the bundle actually needs.

    A DC bundled only for figures that failed to bind carries data the runtime
    never reads (their frozen payloads are self-contained), so an unbindable
    figure must not double the bundle's bytes. Code-mode figures ride the same
    rule: a transpilable one had its DC bundled speculatively (keep-all), and
    only a *bound* one keeps it. A live advanced_viz keeps its DC — the
    in-browser engine reads it at every filter state — unless the build
    downgraded it (unloadable DC).
    """
    used = {
        str(c["dc_id"])
        for _tab, c, cid in items
        if c.get("dc_id")
        and (
            c.get("component_type") in LIVE_DATA_TYPES
            or cid in bindings
            or (serves_advanced_viz_live(c) and tier_by_id[cid].tier is ComponentTier.LIVE)
            or (ships_frozen_inputs(c) and tier_by_id[cid].tier is ComponentTier.FROZEN)
            or (cid in python_ids)
        )
    }
    # ...the collections a live text tile's values read...
    for _tab, c, cid in items:
        if c.get("component_type") == "text" and tier_by_id[cid].tier is ComponentTier.LIVE:
            used |= {str(v["dc_id"]) for v in text_value_cards([c]) if v.get("dc_id")}
    # ...and the companion tables of every live advanced_viz.
    for _tab, c, cid in items:
        if serves_advanced_viz_live(c) and tier_by_id[cid].tier is ComponentTier.LIVE:
            used |= set(advanced_viz_companions(c))
    return used


# ---------------------------------------------------------------------------
# The figure verdict (bind-and-refill, RFC §4 / §7)
# ---------------------------------------------------------------------------


@dataclass
class FigureDecision:
    """What one figure turned out to be, and what deciding it produced.

    :func:`decide_figure` is the only place a figure's tier is decided. The
    build applies the whole thing (shipping ``binding`` / ``prologue``, or the
    frozen ``payload``); the binding preflight applies the tier half and drops
    the payload. Neither re-derives a verdict, so the report and the bundle
    cannot disagree about a figure — which is the entire point of the seam.
    """

    tier: ComponentTier
    reason: TierReason | None = None
    detail: str | None = None
    binding: BindingTable | None = None
    prologue: list[PrologueOp] | None = None
    payload: dict[str, Any] | None = None


def decide_figure(
    comp: dict[str, Any],
    data_refs: dict[str, DataRef],
    pruned_frames: dict[str, pl.DataFrame],
) -> FigureDecision:
    """Offer a figure to the bind-and-refill builder and read off its tier.

    A bound figure re-renders live in the browser at every filter state —
    including the default, empty one — so it ships NO frozen payload: the
    scaffold already carries the authentic layout and the runtime refills the
    arrays from the bundled Parquet, so a frozen snapshot would only be a second
    copy of data the bundle already has.

    Code-mode figures (phase 6, RFC §7) take the long way round: the figure
    itself must come from the server pipeline — that is where the user's Python
    runs under RestrictedPython, producer A never execs it here — and its
    transpiled ops are replayed on the bundled base frame to rebuild the frame
    the code handed to plotly-express, which the binder matches against the real
    figure.

    ``_freeze_figure`` runs on the non-binding path even when the caller throws
    the payload away: the build-time ``was_sampled`` flag it returns is what
    separates ``frozen`` from ``partial``, and there is no cheaper way to learn
    it than to build the figure the server would have built.
    """
    binding: BindingTable | None = None
    miss: BindingMiss | None = None
    ops: list[PrologueOp] | None = None
    payload: dict[str, Any] | None = None
    sampled = False
    code_mode = comp.get("mode", "ui") == "code"
    refusal: str | None = None
    # Set when the binder (or the prologue replay feeding it) *crashed*. A crash
    # and a clean refusal both freeze the figure, but they are not the same
    # verdict and must not read as one: a refusal is analysis, a crash is a bug
    # in ours. It is logged where it happens and named in the detail below.
    binder_error: str | None = None

    if code_mode:
        ops, call, refusal = _code_figure_plan(comp)
        payload, sampled = _freeze_figure(comp, full_load=call is not None)
        if call is not None and ops is not None:
            df = _base_frame(str(comp.get("dc_id") or ""), data_refs, pruned_frames)
            if df is not None:
                try:
                    import plotly.graph_objects as go

                    binding, miss = build_binding_with_reason(
                        {"visu_type": call[0], "dict_kwargs": call[1]},
                        execute_ops(ops, df),
                        fig=go.Figure(payload["figure"]),
                    )
                except Exception as exc:
                    # any replay/builder crash freezes
                    binding, miss = None, None
                    binder_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "producer A: prologue replay / bind-and-refill crashed for code-mode "
                        "figure %s — freezing it: %s",
                        comp.get("index"),
                        exc,
                        exc_info=True,
                    )
    else:
        df = pruned_frames.get(str(comp.get("dc_id") or ""))
        if df is not None:
            try:
                binding, miss = build_binding_with_reason(comp, df)
            except Exception as exc:
                binding, miss = None, None  # any builder crash freezes below
                binder_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "producer A: bind-and-refill crashed for figure %s — freezing it: %s",
                    comp.get("index"),
                    exc,
                    exc_info=True,
                )

    if binding is not None:
        # An empty op list means the code needed no reshape: it binds to the
        # base table, and the contract omits empty lists from
        # ``manifest.prologues``.
        prologue = ops or None
        if binding.sampled:
            return FigureDecision(
                ComponentTier.PARTIAL,
                TierReason.MAX_POINTS,
                "the server samples above FIGURE_MAX_POINTS after filtering; "
                "the bound figure refills every selected row instead — exact, "
                "but heavier than the server's default view",
                binding=binding,
                prologue=prologue,
            )
        return FigureDecision(ComponentTier.LIVE, binding=binding, prologue=prologue)

    if payload is None:
        payload, sampled = _freeze_figure(comp)
    if binder_error is not None:
        # Distinguishable from a real binding miss on purpose: the binder never
        # reached a verdict here, so reporting its "no unambiguous binding"
        # wording would present our own crash as this figure's analysis.
        reason = TierReason.BINDING_MISS
        detail = (
            f"the bind-and-refill builder failed with an error rather than a verdict "
            f"({binder_error}); frozen at the default filter state — this one is a bug to "
            "report, not a property of the chart"
        )
    elif code_mode and refusal is not None:
        reason = TierReason.CODE_MODE
        detail = f"code-mode figure not transpilable: {refusal}"
    else:
        # The binder names which of its bail-outs fired, and that sentence is
        # what the badge tooltip shows — "computed over the whole table at once"
        # is not "no unambiguous binding". Code mode says how far it got first.
        reason = miss_tier_reason(miss)
        detail = frozen_miss_detail(miss, "code analyzed, but " if code_mode else "")
    if sampled:
        return FigureDecision(
            ComponentTier.PARTIAL,
            TierReason.MAX_POINTS,
            "build-time sampling before filtering (FIGURE_MAX_POINTS); "
            "the frozen figure shows a downsampled default view",
            payload=payload,
        )
    return FigureDecision(ComponentTier.FROZEN, reason, detail, payload=payload)


# ---------------------------------------------------------------------------
# Cross-DC links (RFC §8, phase 7)
# ---------------------------------------------------------------------------

# Ceiling on a precomputed translation table, counted in (source value, target
# value) PAIRS — the thing that actually lands in the manifest JSON. A link
# whose join column is near-unique on a large source DC would otherwise inline
# millions of strings into a single-file bundle and dwarf the data it is meant
# to filter.
#
# Over the cap the table is simply left out. That is deliberate and safe: with
# no table the hop has no way to translate, the runtime's walk reports an
# unusable chain, and the filter does not propagate — precisely what happens
# against a server whose link resolution 404s (``filter_links.py:273``, and
# ``_walk_link_path``'s ``(None, [])`` outcome). Fewer filters applied, never
# wrong rows. The ``--check`` output says so out loud.
LINK_TABLE_MAX_PAIRS = 50_000


def _fetch_project(project_id: Any) -> dict[str, Any] | None:
    """The dashboard's project document — where ``links`` live (projects.py:33).

    Best-effort: a bundle whose project cannot be read still builds, it just
    carries no links (and the check output shows none).
    """
    if not project_id:
        return None
    try:
        return _db().projects_collection.find_one({"_id": ObjectId(str(project_id))})
    except Exception:
        return None


def project_links(project_doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The project's ``links`` list, as stored (list of ``DCLink`` dicts)."""
    links = (project_doc or {}).get("links") or []
    return [link for link in links if isinstance(link, dict)]


def workflow_ids_by_dc(project_doc: dict[str, Any] | None) -> dict[str, str]:
    """``dc_id -> workflow_id`` over the project's workflows.

    ``load_deltatable_lite`` wants a workflow id even when ``init_data`` spares
    it every lookup (it salts the cache key), and a link's source DC need not be
    read by any component — so its workflow cannot be taken from a component.
    """
    out: dict[str, str] = {}
    for workflow in (project_doc or {}).get("workflows") or []:
        if not isinstance(workflow, dict):
            continue
        wf_id = workflow.get("_id") or workflow.get("id")
        if not wf_id:
            continue
        for dc in workflow.get("data_collections") or []:
            if not isinstance(dc, dict):
                continue
            dc_id = dc.get("_id") or dc.get("id")
            if dc_id:
                out[str(dc_id)] = str(wf_id)
    for dc in (project_doc or {}).get("data_collections") or []:
        if isinstance(dc, dict) and (dc.get("_id") or dc.get("id")):
            out.setdefault(str(dc.get("_id") or dc.get("id")), "")
    return out


def dashboard_dc_ids(stored_metadata: list[dict[str, Any]]) -> set[str]:
    """Every data collection any component of this dashboard reads (a text
    tile's live values included)."""
    comps = [*stored_metadata, *text_value_cards(stored_metadata)]
    return {str(comp["dc_id"]) for comp in comps if comp.get("dc_id")}


def _link_config_json(link: dict[str, Any]) -> dict[str, Any]:
    """One Mongo link document, JSON-ready and verbatim otherwise.

    ObjectIds are stringified (``id``/``_id`` and both endpoint ids) because the
    browser core compares them as strings, and Mongo's ``_id`` spelling is
    normalised to ``id`` — the same rename ``DCLink.convert_id_field`` does.
    Nothing else is touched: the runtime reads these dicts with ``.get(...)``,
    exactly like the server code they mirror, so an unknown field is harmless
    and a dropped one is not.
    """
    config = convert_objectid_to_str(dict(link))
    if "_id" in config:
        config["id"] = config.pop("_id")
    for key in ("id", "source_dc_id", "target_dc_id"):
        if config.get(key) is not None:
            config[key] = str(config[key])

    # `sample_mapping` links store ``mappings: null`` in Mongo — the server
    # auto-fetches them from multiqc_collection at resolve time
    # (links_endpoints/routes.py:716-737), which a bundle cannot do. Bake them in
    # so the offline resolver expands canonical ids into the report variants
    # MultiQC actually keys its traces by ("SRR10070130" → "SRR10070130_1",
    # "SRR10070130 - First read: Adapter 1"). Merge shape mirrors render_multiqc's
    # own fetch. Costs ~2.5 KB on a 12-sample report.
    link_config = config.get("link_config") or {}
    if (
        config.get("target_type") == "multiqc"
        and link_config.get("resolver") == "sample_mapping"
        and not link_config.get("mappings")
    ):
        from depictio.api.v1.db import multiqc_collection

        mappings: dict[str, list[str]] = {}
        try:
            for report in multiqc_collection.find(
                {"data_collection_id": str(config.get("target_dc_id") or "")},
                {"metadata.sample_mappings": 1},
            ):
                for key, variants in (
                    (report.get("metadata") or {}).get("sample_mappings") or {}
                ).items():
                    bucket = mappings.setdefault(str(key), [])
                    for variant in variants:
                        if str(variant) not in bucket:
                            bucket.append(str(variant))
        except Exception as exc:  # noqa: BLE001 - a link without mappings still resolves
            logger.warning("producer A: multiqc sample_mappings fetch failed: %s", exc)
        if mappings:
            config["link_config"] = {**link_config, "mappings": mappings}
    return config


def emit_link_configs(links: list[dict[str, Any]], dc_ids: set[str]) -> list[dict[str, Any]]:
    """The subset of a project's links worth shipping with this dashboard.

    Keep-rule: **the link's TARGET DC is one this dashboard's components read.**
    A link that cannot land a filter on anything rendered here is dead weight in
    the bundle. The source side is deliberately NOT required to be a dashboard
    DC: it may be an intermediate hop of a chain (A → B → C with no component on
    B), or an unbundled DC whose translation is precomputed into a tier-B table.
    The runtime's breadth-first walk ignores whatever it cannot use anyway, so
    the rule errs toward keeping — an over-kept link costs a few hundred bytes,
    a dropped one silently kills a cross-DC filter.

    Disabled links are kept too (``enabled: false`` is skipped by the walk
    itself, and keeping them makes the bundle a faithful copy of the project).
    """
    return [
        _link_config_json(link) for link in links if str(link.get("target_dc_id") or "") in dc_ids
    ]


def link_join_column_sets(links: list[dict[str, Any]]) -> dict[str, set[str]]:
    """``dc_id -> join columns`` pinned by a set of emitted links.

    ``source_column`` on the source DC, ``target_field or source_column`` on the
    target (the server's ``_link_target_column`` precedence). Folding these into
    the bundled column sets is what keeps a cross-DC filter working offline —
    the join column is typically not one any component plots. Mirrors the
    server's ``_effective_projection`` fold; columns absent from a DC's real
    schema are dropped by the caller's schema intersection, never selected.
    """
    out: dict[str, set[str]] = {}
    for link in links:
        source_id = str(link.get("source_dc_id") or "")
        target_id = str(link.get("target_dc_id") or "")
        source_column = link.get("source_column")
        target_column = link_target_column(link)
        if source_id and source_column:
            out.setdefault(source_id, set()).add(str(source_column))
        if target_id and target_column:
            out.setdefault(target_id, set()).add(str(target_column))
    return out


def _link_source_column_values(dc_id: str, wf_id: str, column: str) -> list[Any] | None:
    """Distinct values of a link's join column on an UNBUNDLED source DC.

    ``None`` when the Delta table cannot be located or the column is not in its
    schema — either way there is nothing to precompute and the caller leaves the
    link without a table.
    """
    try:
        dt = _db().deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    except Exception:
        dt = None
    delta_location = (dt or {}).get("delta_table_location")
    if not delta_location:
        return None
    try:
        df = _dtu().load_deltatable_lite(
            workflow_id=ObjectId(str(wf_id)) if wf_id else ObjectId(),
            data_collection_id=str(dc_id),
            metadata=None,
            select_columns=[column],
            init_data={
                str(dc_id): {
                    "delta_location": delta_location,
                    "dc_type": "table",
                    "size_bytes": 0,
                }
            },
        )
    except Exception:
        return None
    if column not in df.columns:
        return None
    return [v for v in df[column].unique().to_list() if v is not None]


def build_link_table(
    link: dict[str, Any], source_values: list[Any]
) -> tuple[LinkTable | None, int]:
    """Precompute one link's source value → target values mapping (tier B).

    The resolver is the REAL server one (``links_endpoints.resolvers``), called
    per source value exactly the way ``resolve_link`` calls it — including
    ``target_known_values=None``, which is what makes ``regex``/``wildcard``
    behave as pass-throughs server-side. Anything else would make the bundle
    disagree with the instance it was cut from.

    Returns ``(table, pair_count)``; ``(None, pairs)`` when the table would
    exceed :data:`LINK_TABLE_MAX_PAIRS` pairs, or when the resolver/config
    cannot be built at all.
    """
    from depictio.api.v1.endpoints.links_endpoints.resolvers import get_resolver
    from depictio.models.models.links import LinkConfig

    try:
        link_config = LinkConfig.model_validate(link.get("link_config") or {})
        resolver = get_resolver(link_config.resolver)
    except Exception:
        return None, 0

    values: dict[str, list[str]] = {}
    pairs = 0
    for value in source_values:
        key = str(value)
        if key in values:
            continue
        resolved, _unmapped = resolver.resolve(
            source_values=[value],
            link_config=link_config,
            target_known_values=None,  # what routes.py:743 passes
        )
        values[key] = list(resolved)
        pairs += len(resolved)
        if pairs > LINK_TABLE_MAX_PAIRS:
            return None, pairs
    return LinkTable(values=values), pairs


def build_links_section(
    links: list[dict[str, Any]],
    dc_ids: set[str],
    bundled_dc_ids: set[str],
    wf_by_dc: dict[str, str] | None = None,
    precompute: bool = True,
) -> tuple[LinksSection, list[LinkRow]]:
    """``manifest.links`` plus the rows the ``--check`` links summary prints.

    Tier per emitted link:

    * **tier A** — the source DC is bundled. The browser reruns the server's own
      translation query against the bundled Parquet and applies the resolver; no
      table is needed, and every filter state stays exact.
    * **tier B** — the source DC is NOT bundled, so its whole join-column →
      resolved-values mapping is precomputed here (:func:`build_link_table`).
    * **inert** — tier B was impossible: the source Delta table is unreadable
      from the producer, or the table would blow :data:`LINK_TABLE_MAX_PAIRS`.
      The link ships (the config is still true) but resolves to nothing in the
      bundle, which the runtime reports as an unusable chain — the filter does
      not propagate rather than propagating wrongly.

    ``precompute=False`` is the ``--check`` path: tiers are predicted from
    bundling alone and no Delta table is read.
    """
    configs = emit_link_configs(links, dc_ids)
    tables: dict[str, LinkTable] = {}
    rows: list[LinkRow] = []
    wf_by_dc = wf_by_dc or {}

    for config in configs:
        link_id = str(config.get("id") or "")
        source_id = str(config.get("source_dc_id") or "")
        target_id = str(config.get("target_dc_id") or "")
        link_config = config.get("link_config") or {}
        resolver = str(link_config.get("resolver") or "direct")
        enabled = bool(config.get("enabled", True))
        note = None
        if resolver == "sample_mapping" and not link_config.get("mappings"):
            note = SAMPLE_MAPPING_NO_INLINE_NOTE

        row = LinkRow(
            link_id=link_id or "?",
            source=source_id[:8] or "?",
            target=target_id[:8] or "?",
            resolver=resolver,
            tier=LINK_TIER_A,
            enabled=enabled,
            note=note,
        )
        rows.append(row)

        if source_id in bundled_dc_ids:
            continue  # tier A — nothing to precompute

        row.tier = LINK_TIER_B
        if not enabled:
            # A disabled link never resolves, so its table would be dead
            # weight — the config alone documents the project's intent.
            row.tier = LINK_TIER_INERT
            row.note = _join_notes(note, "disabled; no table precomputed")
            continue
        if not precompute:
            continue
        column = str(config.get("source_column") or "")
        source_values = (
            _link_source_column_values(source_id, wf_by_dc.get(source_id, ""), column)
            if column
            else None
        )
        if source_values is None:
            row.tier = LINK_TIER_INERT
            row.note = _join_notes(
                note,
                f"source data collection {source_id[:8]} is neither bundled nor readable "
                f"(column {column!r}); link inert in bundle",
            )
            continue
        table, pairs = build_link_table(config, source_values)
        if table is None:
            row.tier = LINK_TIER_INERT
            row.note = _join_notes(
                note,
                f"translation table too big (>{LINK_TABLE_MAX_PAIRS} pairs); link inert in bundle",
            )
            continue
        tables[link_id] = table
        row.entries = len(table.values)
        row.note = _join_notes(note, f"{pairs} pair(s) precomputed")

    return LinksSection(configs=configs, tables=tables), rows


def _join_notes(*notes: str | None) -> str | None:
    """Join the non-empty notes of one link row into a single sentence."""
    parts = [n for n in notes if n]
    return "; ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@dataclass
class ExportResult:
    """A validated manifest plus the tier table that produced it.

    ``manifest`` is ``None`` for ``check=True`` (preflight writes nothing).
    ``tabs`` always lists the resolved family — one entry for a single-tab
    dashboard — while ``manifest.tabs`` stays empty in that case, per the
    contract ("empty = single-tab bundle"). Every tier row carries the
    ``tab_id`` it belongs to.

    ``size`` is how big the bundle is or would be, against the ceilings in
    force — estimated on the binding preflight, measured on a build. It stays
    ``None`` only on the data-free plan (``check=True, bind=False``), which
    reads no data collection and so has nothing to size.
    """

    manifest: BundleManifest | None
    tier_rows: list[TierRow]
    link_rows: list[LinkRow] = field(default_factory=list)
    tabs: list[TabRow] = field(default_factory=list)
    size: BundleSize | None = None
    #: The Python runtime plan: ``{"mode", "embedded", "components", "bytes",
    #: "version"}`` — what the export modal states before the build.
    python: dict[str, Any] | None = None


def _fetch_dashboard(dashboard_id: str) -> dict[str, Any]:
    try:
        oid = ObjectId(str(dashboard_id))
    except Exception as exc:
        raise ProducerAError(f"invalid dashboard id {dashboard_id!r}: {exc}") from exc
    doc = _db().dashboards_collection.find_one({"dashboard_id": oid})
    if not doc:
        raise ProducerAError(f"dashboard '{dashboard_id}' not found")
    return doc


def _check_permission(dashboard_data: dict[str, Any], user: ExportUser, required: str) -> None:
    project_id = dashboard_data.get("project_id")
    if not project_id or not _routes().check_project_permission(project_id, user, required):
        raise ProducerAError(
            f"permission denied: exporting needs '{required}' on the dashboard's project "
            "(RFC §8 — a bundle is bulk data exfiltration)"
        )


def _public_base_url() -> str | None:
    """A browser-reachable base URL for this instance, or ``None``.

    ``ServiceConfig.url`` resolves to the compose-internal hostname in server
    context (``http://depictio-backend:8058``), which is worse than useless in a
    bundle that outlives the network it was cut from — it *looks* like a link.
    Only an explicitly declared ``public_url`` (viewer first, then the API,
    which also serves the SPA) is trusted; anything else stays ``None``.
    """
    try:
        from depictio.api.v1.configs.config import settings
    except Exception:  # settings unavailable (bare CLI box) — no URL to claim
        return None
    for section in ("viewer", "fastapi"):
        config = getattr(settings, section, None)
        url = getattr(config, "public_url", None) if config is not None else None
        if url:
            return str(url).rstrip("/")
    return None


def build_provenance(
    user: ExportUser,
    built_at: str,
    project_doc: dict[str, Any] | None,
    entry_tab: FamilyTab,
) -> ExportProvenance:
    """Who exported the bundle, when, and from where (shown in the bundle's rail)."""
    base = _public_base_url()
    return ExportProvenance(
        exported_by=user.email or None,
        exported_at=built_at,
        source=base,
        project_name=(project_doc or {}).get("name") or None,
        dashboard_url=f"{base}/dashboard/{entry_tab.id}" if base and entry_tab.id else None,
    )


_OBJECT_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.I)
_HIGHLIGHTABLE_TYPES = frozenset({"figure", "advanced_viz"})


def _tab_key(name: str) -> str:
    """``tabLinkKey``: trimmed, lower-cased, inner whitespace collapsed."""
    return re.sub(r"\s+", " ", name.strip().lower())


def highlight_source(
    comp: dict[str, Any], tabs: list[FamilyTab]
) -> tuple[FamilyTab, dict[str, Any]] | None:
    """The (tab, component) a highlight shows, resolved inside the exported family.

    Mirrors ``resolveHighlightTab`` + ``findHighlightSource``
    (``highlightTile.ts``): the tab by id first, then by name (an id written in
    ``source_tab`` counts); the component by index, else by title (case and
    spacing ignored), preferring a highlightable one. ``None`` when the source
    is not in the family or is not a figure / advanced viz.
    """
    tab_id = str(comp.get("source_dashboard_id") or "").strip()
    tab_name = str(comp.get("source_tab") or "").strip()
    by_id = {t.id: t for t in tabs}
    tab = by_id.get(tab_id) if tab_id else None
    if tab is None and tab_name:
        tab = next((t for t in tabs if _tab_key(t.title) == _tab_key(tab_name)), None)
        if tab is None and _OBJECT_ID_RE.match(tab_name):
            tab = by_id.get(tab_name)
    if tab is None:
        return None
    wanted = str(comp.get("source_component") or "").strip()
    if not wanted:
        return None
    metas = tab.components
    key = _tab_key(wanted)
    found = next((m for m in metas if str(m.get("index")) == wanted), None)
    found = found or next(
        (
            m
            for m in metas
            if m.get("component_type") in _HIGHLIGHTABLE_TYPES
            and _tab_key(str(m.get("title") or "")) == key
        ),
        None,
    )
    if found is None or found.get("component_type") not in _HIGHLIGHTABLE_TYPES:
        return None
    return tab, found


def resolve_highlight_tiers(
    items: list[tuple[FamilyTab, dict[str, Any], str]],
    tabs: list[FamilyTab],
    tier_by_id: dict[str, TierRow],
) -> None:
    """A highlight takes its source's settled tier (the runtime draws the
    source's own payload / binding / data under the highlight's index)."""
    for _tab, comp, cid in items:
        if comp.get("component_type") != "highlight":
            continue
        row = tier_by_id[cid]
        found = highlight_source(comp, tabs)
        if found is None:
            row.tier = ComponentTier.OMITTED
            row.reason = TierReason.UNSUPPORTED
            row.detail = (
                "the highlighted component is not a figure or advanced viz of a tab in this export"
            )
            row.provisional = False
            continue
        source = tier_by_id.get(str(found[1].get("index")))
        if source is None:
            continue
        row.tier = source.tier
        row.reason = source.reason
        row.detail = f"shows {found[1].get('title') or found[1].get('index')!r} from "
        row.detail += f"{found[0].title!r}" + (f": {source.detail}" if source.detail else "")
        row.provisional = False


def export_manifest(
    dashboard_id: str,
    user: ExportUser,
    single_tab: bool = False,
    budget: ComputeBudget | None = None,
    decide_only: bool = False,
    python_runtime: str = "off",
) -> ExportResult:
    """Assemble and validate the full ``BundleManifest`` for a dashboard family.

    ``dashboard_id`` may name any tab: it stays the bundle's entry tab, and the
    rest of its family rides along (``single_tab=True`` opts out). Everything
    component-keyed merges across the family; data collections are bundled ONCE
    however many tabs read them, which is the whole point — six tabs over the
    same two tables used to mean six bundles each re-inlining both.

    ``decide_only=True`` is the binding preflight (``export_static(check=True)``):
    the same body, run for its verdicts and stopped before it builds anything.
    It loads and prunes the data collections and decides every FIGURE through
    :func:`decide_figure` — that is the only way to know a figure's real tier —
    but writes no Parquet, freezes no payload, runs no Celery compute and emits
    no manifest. It is a *viewer*-gated read, not an export. Sharing one body
    (rather than a second copy of the plumbing) is the point: a report that can
    disagree with the bundle it predicts is worse than no report.

    Only the figure rows are settled by it, though. Every other component keeps
    its planned tier, and the build can still move one — a frozen payload that
    fails, or a Celery compute the wall-clock budget cannot cover, both end up
    ``omitted``. It also loads the same data collections a build would and is
    refused at the same ceiling (``_bundle_data_refs``), because it is the more
    open of the two paths.
    """
    # Permission gate on the REQUESTED dashboard first, before any other document
    # is read: a denied export must not walk someone else's family. Then per tab —
    # all tabs of a family share a project (the tab-creation route copies
    # project_id from the parent, and sync_tab_family_permissions keeps the ACLs
    # equal), so it is the same check repeated, but checking each tab's OWN
    # project makes that an observation rather than an assumption.
    #
    # Building needs *owner* (RFC §8 — a bundle is bulk data exfiltration);
    # deciding needs *viewer*, since every row it reads is a row the normal
    # render endpoints would already hand that viewer.
    required = "viewer" if decide_only else "owner"
    entry_doc = _fetch_dashboard(dashboard_id)
    _check_permission(entry_doc, user, required)
    tabs, entry_tab = family_from_doc(entry_doc, single_tab=single_tab)
    for tab in tabs:
        _check_permission(tab.doc, user, required)
    project_ids = {str(tab.doc.get("project_id") or "") for tab in tabs}
    if len(project_ids) > 1:
        logger.warning(
            "producer A: tab family %s spans %d projects (%s) — every one was permission-checked",
            entry_tab.id,
            len(project_ids),
            ", ".join(sorted(project_ids)),
        )
    budget = budget or ComputeBudget.from_env()

    items = family_components(tabs)
    annotate_code_context(tabs)
    tier_rows: list[TierRow] = []
    for tab in tabs:
        tier_rows.extend(classify_stored_metadata(tab.components, tab_id=tab.id))
    tier_by_id = {row.component_id: row for row in tier_rows}
    stored_metadata: list[dict[str, Any]] = [comp for _tab, comp, _cid in items]

    # Cross-DC links (RFC §8): read from the PROJECT, filtered to the ones that
    # can land a filter on this dashboard, and folded into the column sets
    # before anything is bundled — a join column pruned away is a dead filter.
    project_doc = _fetch_project(entry_tab.doc.get("project_id"))
    # `{{param:KEY}}` in a text tile reads the run's recorded parameters —
    # constants, so the bundle carries them on the tile itself (the runtime
    # folds them in beside the computed values, as bulk_compute_cards does).
    for _tab, comp, _cid in items:
        if comp.get("component_type") == "text":
            params = text_run_params(project_doc, comp)
            if params:
                comp["run_params"] = params
            inline_text_logos(comp)
    dc_ids = dashboard_dc_ids(stored_metadata)
    emitted_links = emit_link_configs(project_links(project_doc), dc_ids)

    # Python-runtime candidates (RFC §13.6) ship their whole table: the build
    # below decides which of them the runtime really serves.
    python_candidates = mark_python_candidates(items, python_runtime)

    # Live tier: bundle the DCs cards/interactive (and ui-mode figures, and the
    # live advanced_viz kinds) read — keyed by dc_id, so a DC read on three tabs
    # is loaded, pruned and inlined exactly once.
    data_refs, inline_blobs, dc_failures, pruned_frames = _bundle_data_refs(
        stored_metadata, emitted_links, serialize=not decide_only
    )
    apply_dc_outcomes(items, tier_by_id, data_refs, dc_failures)

    # Frozen tier: real endpoint bodies, default (empty) filter state.
    # Bindings (bind-and-refill, RFC §4) — and, for code-mode figures, the
    # prologue IR the runtime replays first (RFC §7) — are filled per figure
    # below.
    frozen: dict[str, FrozenPayload] = {}
    bindings: dict[str, BindingTable] = {}
    prologues: dict[str, list[PrologueOp]] = {}
    # One object budget for every file the bundle ships: structures, PAE
    # matrices and gallery thumbnails alike.
    object_budget = ObjectBudget()
    computes_frozen = 0
    computes_skipped = 0

    # Cards freeze per tab: bulk_compute_cards resolves component ids against
    # ONE dashboard document, so a family needs one call per tab. A card's tier
    # is already settled by now (live, or omitted with its DC), so the preflight
    # skips the fallback payload entirely.
    if not decide_only:
        for tab in tabs:
            cards = [
                comp
                for t, comp, cid in items
                if t is tab
                and comp.get("component_type") == "card"
                and tier_by_id[cid].tier is ComponentTier.LIVE
            ]
            if not cards:
                continue
            try:
                for idx, payload in _freeze_cards(ObjectId(tab.id), cards, user).items():
                    frozen[idx] = FrozenPayload(kind="card", payload=payload)
            except Exception as exc:
                # Fallback payloads only — cards stay live off the bundled data.
                logger.warning(
                    "producer A: frozen card fallback failed for tab %s: %s", tab.id, exc
                )

    for tab, comp, component_id in items:
        row = tier_by_id[component_id]
        ctype = comp.get("component_type")
        # A live MultiQC still ships a payload: the runtime re-slices that figure
        # under the current filters, it cannot rebuild it. The payload is its
        # data source, not a snapshot of a dead tile.
        if row.tier is not ComponentTier.FROZEN and ctype != "multiqc":
            continue
        if decide_only and ctype != "figure":
            # A figure is the only tier this loop can still SETTLE cheaply, so
            # it is the only one it runs. The rest keep their planned verdict,
            # which the build can still move: a frozen payload that fails drops
            # the component to omitted, and a Celery compute the budget cannot
            # cover is omitted by policy rather than by failure
            # (:func:`freeze_celery_compute` returning ``None``). So on a
            # dashboard with more computes than the budget covers, this reports
            # `frozen` where the build will ship `omitted`. Running them here to
            # find out would cost the bulk of an export's wall clock, which is
            # not what a preflight is for.
            continue
        dashboard_oid = ObjectId(tab.id)
        try:
            if ctype == "table":
                frozen[component_id] = FrozenPayload(
                    kind="table",
                    payload=_freeze_table(dashboard_oid, component_id, user),
                )
            elif ctype == "figure":
                decision = decide_figure(comp, data_refs, pruned_frames)
                row.tier = decision.tier
                row.reason = decision.reason
                row.detail = decision.detail
                row.provisional = False  # the binder ran; this IS the verdict
                if decision.binding is not None:
                    bindings[component_id] = decision.binding
                    if decision.prologue:
                        prologues[component_id] = decision.prologue
                elif decision.payload is not None and not decide_only:
                    frozen[component_id] = FrozenPayload(kind="figure", payload=decision.payload)
            elif ctype == "advanced_viz":
                if celery_compute_request(comp) is not None:
                    # Server-side Celery kind: run the compute here and ship the
                    # result the poll endpoint would have returned. A failure
                    # degrades this one component to omitted (with the error in
                    # its detail) and never aborts the export.
                    compute_payload, detail = freeze_celery_compute(comp, budget)
                    row.reason = TierReason.CELERY_COMPUTE
                    row.detail = detail
                    if compute_payload is None:
                        row.tier = ComponentTier.OMITTED
                        computes_skipped += 1
                    else:
                        frozen[component_id] = FrozenPayload(
                            kind="compute", payload=compute_payload
                        )
                        computes_frozen += 1
                else:
                    frozen[component_id] = FrozenPayload(
                        kind="advanced-viz-data",
                        payload=_freeze_advanced_viz(comp, user),
                    )
            elif ctype == "multiqc":
                kind, payload = _freeze_multiqc(dashboard_oid, comp, user)
                frozen[component_id] = FrozenPayload(kind=kind, payload=payload)
            elif ctype == "map":
                try:
                    map_colors = _routes().effective_category_colors(tab.doc)
                except Exception:
                    map_colors = None
                frozen[component_id] = FrozenPayload(
                    kind="map", payload=_freeze_map(comp, user, map_colors)
                )
            elif ctype == "image":
                payload, note = _freeze_image(
                    dashboard_oid, comp, component_id, user, object_budget, inline_blobs
                )
                frozen[component_id] = FrozenPayload(kind="image", payload=payload)
                if note:
                    row.detail = f"{row.detail}; {note}"
            elif ctype == "jbrowse":
                frozen[component_id] = FrozenPayload(
                    kind="jbrowse", payload=_freeze_jbrowse(dashboard_oid, component_id, user)
                )
        except Exception as exc:
            row.tier = ComponentTier.OMITTED
            row.reason = row.reason or TierReason.UNSUPPORTED
            row.detail = f"frozen payload could not be computed: {exc}"

    python_components, python_info = settle_python_jobs(
        items, tier_by_id, bindings, data_refs, python_candidates, python_runtime, decide_only
    )
    if python_components and not decide_only:
        from depictio.serverless.pyodide.plan import ipc_blob, user_frame

        for job in python_components.values():
            key = f"ipc_{job.dc_id}"
            if key not in inline_blobs and job.dc_id in pruned_frames:
                inline_blobs[key] = ipc_blob(
                    user_frame(pruned_frames[job.dc_id], data_refs[job.dc_id].companions)
                )

    resolve_highlight_tiers(items, tabs, tier_by_id)

    dcs_loaded = len(data_refs)
    used_dcs = used_dc_ids(items, tier_by_id, bindings, set(python_components))
    for dc_id in [d for d in data_refs if d not in used_dcs]:
        del data_refs[dc_id]
        inline_blobs.pop(f"dc_{dc_id}", None)

    # Size the bundle only now: the drop above is what makes the difference
    # between the bytes the producer touched and the bytes the user receives,
    # and both the warning and the preflight's verdict are about the latter.
    bundle_size = (
        estimate_bundle_size(data_refs) if decide_only else measured_bundle_size(inline_blobs)
    )
    report_bundle_size(bundle_size, len(data_refs))

    if decide_only:
        # Link tiers off the same surviving DC set the build would ship, but
        # without precomputing any tier-B translation table — that reads a whole
        # source column out of Delta to produce a mapping this call never emits.
        _, link_rows = build_links_section(
            project_links(project_doc), dc_ids, set(data_refs), precompute=False
        )
        logger.info(
            "producer A: preflighted %s (%d tab(s), %d component(s), %d data collection(s) "
            "loaded / %d a bundle would keep, %d figure(s) bound)",
            entry_tab.id,
            len(tabs),
            len(tier_rows),
            dcs_loaded,
            len(data_refs),
            len(bindings),
        )
        return ExportResult(
            manifest=None,
            tier_rows=tier_rows,
            link_rows=link_rows,
            tabs=[tab.tab_row() for tab in tabs],
            size=bundle_size,
            python=python_info,
        )

    # Links last: a link's tier depends on whether its SOURCE DC survived the
    # drop above, so this cannot run before the final data_refs are known.
    links_section, link_rows = build_links_section(
        project_links(project_doc),
        dc_ids,
        set(data_refs),
        workflow_ids_by_dc(project_doc),
    )

    objects, resolved_structures, addons = collect_objects_a(
        items, tier_by_id, pruned_frames, inline_blobs, user, object_budget
    )
    if python_info.get("embedded"):
        addons.append(python_info["addon"])

    built_at = datetime.now(timezone.utc).isoformat()
    manifest = BundleManifest(
        mode=BundleMode.SINGLE_FILE,
        producer=Producer.EXPORT_FROM_INSTANCE,
        built_at=built_at,
        depictio_version=_depictio_version(),
        dashboard=DashboardSection(
            id=entry_tab.id,
            title=entry_tab.title,
            doc=sanitize_dashboard_doc(entry_tab.doc),
        ),
        # A one-tab family is a plain single-tab bundle: the contract says
        # ``tabs`` is empty there and ``dashboard`` is the whole story.
        tabs=[tab.tab_entry() for tab in tabs] if len(tabs) > 1 else [],
        provenance=build_provenance(user, built_at, project_doc, entry_tab),
        data_refs=data_refs,
        tiers={
            row.component_id: TierEntry(tier=row.tier, reason=row.reason, detail=row.detail)
            for row in tier_rows
        },
        frozen=frozen,
        bindings=bindings,
        prologues=prologues,
        links=links_section,
        limits=_runtime_limits(),
        inline_blobs=inline_blobs,
        objects=objects,
        resolved_structures=resolved_structures,
        addons=addons,
        python_components=python_components,
    )
    logger.info(
        "producer A: exported %s (%d tab(s), %d component(s), %d data collection(s), "
        "%s of bundled data, %d Celery compute(s) frozen, %d omitted, "
        "%.0fs of %.0fs compute budget spent)",
        entry_tab.id,
        len(tabs),
        len(tier_rows),
        len(data_refs),
        _mb(bundle_size.data_bytes),
        computes_frozen,
        computes_skipped,
        budget.spent,
        budget.total,
    )
    return ExportResult(
        manifest=manifest,
        tier_rows=tier_rows,
        link_rows=link_rows,
        tabs=[tab.tab_row() for tab in tabs],
        size=bundle_size,
        python={k: v for k, v in python_info.items() if k != "addon"},
    )


def _freeze_image(
    dashboard_oid: ObjectId,
    comp: dict[str, Any],
    component_id: str,
    user: ExportUser,
    budget: ObjectBudget,
    inline_blobs: dict[str, str],
) -> tuple[dict[str, Any], str | None]:
    """A gallery's export-time snapshot: its default rows, images as thumbnails.

    The rows come from ``render_image_paths_endpoint`` (the gallery's own
    order and cap); each image is read from the instance's bucket, downsampled
    (:func:`objects.thumbnail`) and shipped under the bundle's object budget.
    The row's image value becomes the ``inline:`` key; the runtime turns it
    into a ``blob:`` URL. Rows whose image did not fit are left out, and the
    tier detail says how many.
    """
    from depictio.api.v1.s3 import s3_client
    from depictio.serverless.objects import image_s3_path, pack_object, thumbnail

    routes = _routes()
    cap = min(int(comp.get("max_images") or IMAGE_SNAPSHOT_MAX), IMAGE_SNAPSHOT_MAX)
    payload = routes.render_image_paths_endpoint(
        dashboard_oid,
        component_id,
        {"filters": [], "max": cap},
        current_user=user,
        access_token=None,
    )
    image_column = payload.get("image_column") or comp.get("image_column")
    base = str(comp.get("s3_base_folder") or "")
    from depictio.api.v1.configs.config import settings

    kept: list[dict[str, Any]] = []
    rows = [r for r in payload.get("rows") or [] if r.get(image_column)]
    for row in rows:
        rel = row.get(image_column)
        path = image_s3_path(base, str(rel))
        bucket, _, key = path.removeprefix("s3://").partition("/")
        if bucket != settings.s3.bucket or not key:
            continue
        try:
            data = thumbnail(s3_client.get_object(Bucket=bucket, Key=key)["Body"].read())
        except Exception as exc:
            logger.warning("producer A: gallery image %s unreadable: %s", path, exc)
            continue
        if not budget.admits(len(data)):
            continue
        blob_key, b64, _ = pack_object(data, compress=False)
        if blob_key not in budget.seen:
            budget.seen.add(blob_key)
            budget.used += len(data)
            inline_blobs[blob_key] = b64
        kept.append({**row, image_column: f"inline:{blob_key}"})
    payload = {
        **payload,
        "rows": kept,
        "paths": [r[image_column] for r in kept],
        "filter_applied": False,
    }
    note = None
    if len(kept) < len(rows):
        note = (
            f"{len(kept)} of {len(rows)} images shipped (the rest did not fit or were unreadable)"
        )
    return payload, note


def _freeze_jbrowse(dashboard_oid: ObjectId, component_id: str, user: ExportUser) -> dict[str, Any]:
    """The genome browser's session at the default filter state (its track table)."""
    return _routes().render_jbrowse_endpoint(
        dashboard_oid,
        component_id,
        {"filters": []},
        current_user=user,
        access_token=None,
    )


def _indexed_file_sources(dc_id: str) -> tuple[str, list[Any]]:
    """``(format, [ObjectSource])`` of one indexed_file collection, from Mongo + S3.

    The same documents ``GET /files/indexed/{dc_id}`` lists, read here with the
    backend's own S3 client rather than through presigned URLs: the export runs
    next to the store, and a presigned URL is signed for the browser's endpoint.
    """
    from depictio.api.v1.endpoints.files_endpoints import routes as files_routes
    from depictio.api.v1.s3 import s3_client
    from depictio.serverless.objects import ObjectSource

    dc_oid = ObjectId(dc_id)
    properties = files_routes._indexed_file_dc_properties(dc_oid)
    if not properties:
        return "", []
    docs = files_routes.files_collection.find(
        {"data_collection_id": dc_oid, "s3_key": {"$ne": None}},
        {"sample": 1, "filename": 1, "filesize": 1, "s3_key": 1},
    )
    bucket = files_routes.settings.minio.bucket

    def loader(key: str):
        def load() -> bytes:
            return s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()

        return load

    sources = []
    for doc in docs:
        key = doc.get("s3_key")
        if not key:
            continue
        sources.append(
            ObjectSource(
                sample=str(doc.get("sample") or ""),
                name=str(doc.get("filename") or str(key).rsplit("/", 1)[-1]),
                size_bytes=doc.get("filesize"),
                load=loader(str(key)),
            )
        )
    return str(properties.get("format", "")).lower(), sources


def _entity_values(comp: dict[str, Any], pruned_frames: dict[str, Any]) -> list[str]:
    """The entities the component's bound table names, most rows first."""
    column = (comp.get("config") or {}).get("entity_col")
    frame = pruned_frames.get(str(comp.get("dc_id") or ""))
    if not column or frame is None or column not in getattr(frame, "columns", ()):
        return []
    try:
        counts = frame.group_by(column).len().sort("len", descending=True)
        return [str(v) for v in counts[column].to_list() if v is not None]
    except Exception:
        return []


def _resolve_structures_a(
    comp: dict[str, Any],
    pruned_frames: dict[str, Any],
    user: ExportUser,
    budget: Any,
    inline_blobs: dict[str, str],
) -> tuple[list[Any], str | None]:
    """Freeze the structure resolver's answers for a resolve-mode tile's entities.

    One resolver call per entity of the bundled table (capped), through the
    route's own function, so the bundle carries the model the live tile would
    have drawn; the model is read from the resolver's bucket cache. A disabled
    resolver leaves the tile with its own "resolver disabled" message.
    """
    from depictio.api.v1.endpoints.advanced_viz_endpoints import structure_resolver as sr
    from depictio.models.models.serverless import ResolvedStructure
    from depictio.serverless.objects import RESOLVE_MAX_ENTITIES, pack_object

    cfg = sr.settings.structure_resolver
    if not cfg.enabled:
        return [], "the structure resolver is disabled on the exporting instance"
    config = comp.get("config") or {}
    frame = pruned_frames.get(str(comp.get("dc_id") or ""))
    if frame is None:
        return [], "the residue table is not bundled"
    entity_col = config.get("entity_col")
    cols = {k: config.get(f"{k}_col") for k in ("uniprot", "gene", "sequence")}
    taxon = int(config.get("taxon") or 9606)
    out: list[Any] = []
    entities = _entity_values(comp, pruned_frames)[:RESOLVE_MAX_ENTITIES] or [None]
    for entity in entities:
        rows = frame if entity is None else frame.filter(frame[entity_col].cast(str) == entity)
        ask: dict[str, Any] = {}
        for key, col in cols.items():
            if col and col in rows.columns:
                vals = [v for v in rows[col].to_list() if v not in (None, "")]
                ask[key] = str(vals[0]) if vals else None
        if not any(ask.values()):
            continue
        try:
            payload = sr.StructureResolveRequest(taxon=taxon, **ask)
            answer = sr.resolve_structure(payload, current_user=user)
            digest = sr._normalise(payload, cfg).cache_key()
            key, _ = sr._keys(cfg, digest)
            data = sr._s3_client().get_object(Bucket=sr.settings.s3.bucket, Key=key)["Body"].read()
        except Exception as exc:
            logger.warning("producer A: structure resolve failed for %s: %s", ask, exc)
            continue
        if not budget.admits(len(data)):
            continue
        blob_key, b64, _gz = pack_object(data)
        if blob_key not in budget.seen:
            budget.seen.add(blob_key)
            budget.used += len(data)
            inline_blobs[blob_key] = b64
        out.append(
            ResolvedStructure(
                uniprot=ask.get("uniprot"),
                gene=ask.get("gene"),
                sequence=ask.get("sequence"),
                taxon=taxon,
                uri=f"inline:{blob_key}",
                origin=answer.get("origin"),
                accession=answer.get("accession"),
                model_sequence=str(answer.get("sequence") or ""),
            )
        )
    return out, None if out else "no structure could be resolved at export"


def collect_objects_a(
    items: list[tuple[FamilyTab, dict[str, Any], str]],
    tier_by_id: dict[str, TierRow],
    pruned_frames: dict[str, Any],
    inline_blobs: dict[str, str],
    user: ExportUser,
    budget: Any = None,
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    """Ship the object files the live protein tiles read (``objects`` path).

    Returns ``(objects, resolved_structures, addons)``. A tile whose files could
    not be shipped (none found, or none under the cap) drops to ``partial`` with
    the reason: its residue-table half still draws, its structure half says the
    file is not in the bundle.
    """
    from depictio.serverless.addons import addon_entry
    from depictio.serverless.objects import (
        THREE_DMOL_KINDS,
        build_collection,
        collection_detail,
        object_dc_refs,
        object_kind,
        resolve_mode,
    )

    budget = budget or ObjectBudget()
    objects: dict[str, Any] = {}
    resolved: list[Any] = []
    three_dmol: list[str] = []
    for _tab, comp, cid in items:
        row = tier_by_id[cid]
        if comp.get("component_type") != "advanced_viz" or row.tier is ComponentTier.OMITTED:
            continue
        kind = object_kind(comp)
        refs = object_dc_refs(comp)
        if not refs and not resolve_mode(comp):
            continue
        notes: list[str] = []
        shipped = False
        for _base, dc_id in refs:
            if dc_id not in objects:
                try:
                    fmt, sources = _indexed_file_sources(dc_id)
                except Exception as exc:
                    logger.warning("producer A: objects of %s unreadable: %s", dc_id, exc)
                    fmt, sources = "", []
                objects[dc_id] = build_collection(
                    sources, fmt, budget, inline_blobs, _entity_values(comp, pruned_frames)
                )
            collection = objects[dc_id]
            shipped = shipped or bool(collection.files)
            note = collection_detail(collection)
            if note:
                notes.append(note)
            if not collection.total:
                notes.append(f"the file collection {dc_id} holds no readable object")
        if resolve_mode(comp):
            answers, note = _resolve_structures_a(comp, pruned_frames, user, budget, inline_blobs)
            resolved.extend(answers)
            shipped = shipped or bool(answers)
            if note:
                notes.append(note)
        if kind in THREE_DMOL_KINDS and shipped:
            three_dmol.append(str(comp.get("title") or cid))
        if not shipped:
            row.tier = ComponentTier.PARTIAL
            row.reason = TierReason.UNSUPPORTED
            row.detail = (
                f"advanced_viz '{kind}': the residue table is live, but no file it draws "
                f"from could be shipped ({'; '.join(notes) or 'none found'})"
            )
        elif notes:
            row.detail = f"advanced_viz '{kind}': live; " + "; ".join(notes)
    addons = []
    if three_dmol:
        entry = addon_entry("3dmol", "3D structure tiles: " + ", ".join(three_dmol))
        if entry is None:
            logger.warning("producer A: the 3dmol add-on is not built; 3D tiles show the stub")
        else:
            addons.append(entry)
    return objects, resolved, addons


def mark_python_candidates(
    items: list[tuple[FamilyTab, dict[str, Any], str]], mode: str
) -> dict[str, tuple[str, set[str]]]:
    """Mark the Python-runtime candidates (``pyodide/plan.py``) before bundling.

    Marked components ship their whole table. ``off`` marks nothing.
    """
    from depictio.serverless.pyodide.plan import candidate

    if mode == "off":
        return {}
    out: dict[str, tuple[str, set[str]]] = {}
    for _tab, comp, cid in items:
        plan = candidate(comp)
        if plan is None:
            continue
        comp[PYTHON_JOB_KEY] = plan[0]
        out[cid] = plan
    return out


def settle_python_jobs(
    items: list[tuple[FamilyTab, dict[str, Any], str]],
    tier_by_id: dict[str, TierRow],
    bindings: dict[str, BindingTable],
    data_refs: dict[str, DataRef],
    candidates: dict[str, tuple[str, set[str]]],
    mode: str,
    decide_only: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Which candidates the embedded Python runtime serves, after the build.

    A code figure that bound is live in TypeScript and needs no Python; a
    candidate whose table did not make it into the bundle cannot run. The rest
    become ``live`` with the job named in their detail — their frozen payload,
    computed by the loop above, stays as the fallback. ``auto`` embeds the
    runtime only when one job survives; ``on`` embeds it regardless.
    """
    from depictio.models.models.serverless import PythonComponent, RuntimeAddon
    from depictio.serverless.pyodide import plan
    from depictio.serverless.pyodide.assets import estimate_bytes, version

    jobs: dict[str, Any] = {}
    job_features: dict[str, set[str]] = {}
    features: set[str] = set()
    for _tab, comp, cid in items:
        comp.pop(PYTHON_JOB_KEY, None)
        if cid not in candidates:
            continue
        job, feats = candidates[cid]
        row = tier_by_id[cid]
        dc_id = str(comp.get("dc_id") or "")
        if cid in bindings or row.tier is ComponentTier.OMITTED or dc_id not in data_refs:
            continue
        spec: dict[str, Any] = {}
        if job == "code_figure":
            spec = {
                "code": comp.get("code_content") or "",
                "category_colors": comp.get(_FOLD_COLORS_KEY) or {},
            }
        jobs[cid] = PythonComponent(
            job=job,  # type: ignore[arg-type]
            dc_id=dc_id,
            spec=spec,
            max_rows=plan.max_rows(job, feats),
            table_uri=f"inline:ipc_{dc_id}",
        )
        job_features[cid] = feats
        features |= feats
    embedded = bool(jobs) if mode == "auto" else mode == "on"
    if mode == "on" and not features:
        features = {"code_figure"}
    info: dict[str, Any] = {
        "mode": mode,
        "embedded": embedded,
        "version": version(),
        "components": sorted(jobs) if embedded else [],
        "candidates": sorted(jobs),
        "bytes": estimate_bytes(features) if embedded else 0,
        "bytes_if_embedded": estimate_bytes(features or {"code_figure"}),
    }
    if embedded and not decide_only:
        missing = plan.unavailable_reason(features)
        if missing and mode == "on":
            raise ProducerAError(f"the Python runtime could not be embedded: {missing}")
        if missing:
            logger.warning(
                "producer A: Python runtime left out (%s); its tiles stay frozen", missing
            )
            info.update(embedded=False, components=[], bytes=0, unavailable=missing)
            embedded = False
    # What each candidate shows without the runtime, so a preflight read with
    # the runtime switched off can say so instead of promising a live tile.
    info["without"] = {
        cid: {
            "tier": tier_by_id[cid].tier.value,
            "reason": tier_by_id[cid].reason.value if tier_by_id[cid].reason else None,
            "detail": tier_by_id[cid].detail,
        }
        for cid in jobs
    }
    if not embedded:
        return {}, info
    for cid, job in jobs.items():
        row = tier_by_id[cid]
        row.tier = ComponentTier.LIVE
        row.detail = plan.live_detail(job.job, job_features[cid])
    info["addon"] = RuntimeAddon(
        name="pyodide",
        version=version(),
        packages=plan.addon_packages(features),
        bytes=info["bytes"],
        reason="Python-live tiles: " + ", ".join(sorted(jobs)),
    )
    return {cid: job for cid, job in jobs.items()}, info


def _refuse_oversized_render(html: str, size: BundleSize | None) -> None:
    """Refuse a rendered bundle past the hard ceiling, before it is written.

    The running total during ``_bundle_data_refs`` only ever sees base64
    Parquet, and ``measured_bundle_size`` only ever sees the same blobs — so
    everything else the file carries is unbounded by them: the frozen payloads,
    and in particular a code-mode figure built with ``full_load=True`` whose
    binding then missed, which embeds every point in the manifest JSON. The
    documented meaning of ``static_bundle_max_mb`` is "the size above which an
    export is refused", so it is checked one last time on the thing that
    actually has a size — the HTML about to be written.

    Named separately from the earlier refusals because the numbers are not
    comparable: this one is the file, they are its data.
    """
    _, hard_limit = _bundle_size_limits()
    rendered = len(html.encode("utf-8"))
    if not hard_limit or rendered <= hard_limit:
        return
    data = f"{_mb(size.data_bytes)} of it is bundled data" if size else "size unavailable"
    raise BundleTooLargeError(
        f"static bundle too large: the rendered bundle is {_mb(rendered)}, past the "
        f"{_mb(hard_limit)} ceiling (performance.static_bundle_max_mb), so it was not "
        f"written. {data}; the rest is the static runtime and the frozen payloads (a "
        "figure that could not be bound ships every point it draws), which the running "
        "total during serialisation does not count. Raise "
        "performance.static_bundle_max_mb (DEPICTIO_PERFORMANCE_STATIC_BUNDLE_MAX_MB; "
        "0 disables the check), or export fewer/narrower components."
    )


def export_static(
    dashboard_id: str,
    out_path: str | Path | None = None,
    mode: BundleMode | str = BundleMode.SINGLE_FILE,
    check: bool = False,
    user: Any = None,
    single_tab: bool = False,
    bind: bool = True,
    python_runtime: str = "off",
) -> ExportResult:
    """End-to-end: dashboard in Mongo → self-contained HTML at ``out_path``.

    Args:
        dashboard_id: Any tab's real Mongo ObjectId string. Its whole tab
            family is exported into one bundle, with this tab as the entry.
        out_path: Where to write the bundle (ignored with ``check=True``;
            required otherwise).
        mode: Bundle delivery mode — phase 2 supports ``single-file`` only.
        check: Preflight — report the tier table (viewer permission), write
            nothing. By default the report is the REAL one: see ``bind``.
        user: A User-like object, an email string, or ``None`` (falls back to
            the instance's admin account). Building needs *owner* on the
            dashboard's project; ``--check`` needs viewer.
        single_tab: Export only the requested tab (no family).
        bind: ``check`` only. True (the default) runs the binding preflight —
            the export's own body, stopped before it builds anything: data
            collections are loaded and pruned and every figure goes through the
            binder, so each *figure* row is the tier the bundle would really get
            and comes back non-``provisional``. It costs seconds, mostly in the
            figure pipeline; it still skips the Celery computes, the frozen
            payloads and the Parquet, so it stays well under a full export.
            False gives the instant data-free plan
            (:func:`classify_stored_component`), where every ui-mode figure is
            an undecided ``binding_miss``.

            Nothing in production passes ``bind=False``: the HTTP preflight and
            the CLI both take the real road. It is an internal escape hatch —
            for the tests, and for anyone debugging a dashboard whose data
            cannot be read (an unreachable S3, a Delta table mid-rewrite) who
            still wants the component inventory. Not public CLI surface.
        python_runtime: ``off`` (the CLI's and the export API's default) leaves the
            optional Python runtime out; ``auto`` embeds it
            (Pyodide) when a tile it can make live survives the build — a code
            figure that did not bind, a group comparison, a PCA / PCoA / t-SNE
            embedding — ``on`` forces it, ``off`` leaves it out (those tiles
            stay frozen). See ``serverless/pyodide/plan.py``. The library
            default is ``off``, so nothing downloads unless a caller asks.
    """
    if python_runtime not in ("auto", "on", "off"):
        raise ProducerAError(f"python_runtime must be auto, on or off, got {python_runtime!r}")
    bundle_mode = BundleMode(mode) if not isinstance(mode, BundleMode) else mode
    if bundle_mode is not BundleMode.SINGLE_FILE:
        raise ProducerAError(f"phase 2 supports only single-file mode, got {bundle_mode.value!r}")

    export_user = resolve_user(user)

    if check and bind:
        return export_manifest(
            dashboard_id,
            export_user,
            single_tab=single_tab,
            decide_only=True,
            python_runtime=python_runtime,
        )

    if check:
        entry_doc = _fetch_dashboard(dashboard_id)
        _check_permission(entry_doc, export_user, "viewer")
        tabs, entry_tab = family_from_doc(entry_doc, single_tab=single_tab)
        for tab in tabs:
            _check_permission(tab.doc, export_user, "viewer")
        tier_rows: list[TierRow] = []
        for tab in tabs:
            tier_rows.extend(classify_stored_metadata(tab.components, tab_id=tab.id))
        stored_metadata = [comp for tab in tabs for comp in tab.components]
        # Predicted link tiers: a source DC that a data-shipping component reads
        # will be bundled (tier A), anything else needs a precomputed table
        # (tier B). No Delta table is read — this path stays data-free.
        _, link_rows = build_links_section(
            project_links(_fetch_project(entry_tab.doc.get("project_id"))),
            dashboard_dc_ids(stored_metadata),
            {str(c["dc_id"]) for c in stored_metadata if c.get("dc_id") and _ships_data(c)},
            precompute=False,
        )
        return ExportResult(
            manifest=None,
            tier_rows=tier_rows,
            link_rows=link_rows,
            tabs=[tab.tab_row() for tab in tabs],
        )

    if out_path is None:
        raise ProducerAError("out_path is required unless check=True")

    result = export_manifest(
        dashboard_id, export_user, single_tab=single_tab, python_runtime=python_runtime
    )
    assert result.manifest is not None
    html = render_bundle_html(result.manifest)
    # Last ceiling check, and the only one taken on the whole file (RFC §8.1).
    _refuse_oversized_render(html, result.size)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return result
