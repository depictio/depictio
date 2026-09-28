"""Agent tools to find things: projects, dashboards, their components and schemas.

Access follows the REST routes: dashboard listings through
``load_dashboards_from_db``, projects and single dashboards through
``check_project_permission(..., "viewer")``, the gate of
``GET /dashboards/get/{id}``.

The ``*_summary`` / ``*_detail`` functions take a user rather than a
``ToolContext`` so other front ends (MCP resources) can serve the same content.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.envelope import untrusted
from depictio.api.v1.agents.registry import agent_tool
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import dashboards_collection, deltatables_collection, projects_collection

TEXT_PREVIEW_CHARS = 200
MAX_KEY_CONFIG_ENTRIES = 12

# Component fields worth showing in a one-line summary, whatever the type.
_KEY_FIELDS: tuple[str, ...] = (
    "visu_type",
    "mode",
    "viz_kind",
    "aggregation",
    "aggregations",
    "column_name",
    "interactive_component_type",
    "value",
    "filter_expr",
    "selection_column",
    "secondary_layout",
    "breakdown_col",
    "trend_col",
    "attrition_cols",
    "columns",
    "row_selection_column",
    "image_column",
    "map_type",
    "lat_column",
    "lon_column",
    "color_column",
    "size_column",
    "locations_column",
    "selected_module",
    "selected_plot",
)

# Figure ``dict_kwargs`` that bind data columns (the rest is styling).
FIGURE_ROLE_KEYS: tuple[str, ...] = (
    "x",
    "y",
    "z",
    "color",
    "size",
    "symbol",
    "facet_row",
    "facet_col",
    "names",
    "values",
    "hover_name",
    "hover_data",
    "text",
    "line_group",
    "barmode",
    "histfunc",
    "nbins",
)

# Stored fields that are internal plumbing, never useful to an agent.
_INTERNAL_FIELDS: frozenset[str] = frozenset(
    {
        "_id",
        "dc_config",
        "cols_json",
        "last_updated",
        "displayed_data_count",
        "total_data_count",
        "was_sampled",
        "filter_applied",
        "parent_index",
        "project_id",
    }
)
# User-authored free text inside a component.
_FREE_TEXT_FIELDS: frozenset[str] = frozenset({"title", "description", "body", "code_content"})


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Shared lookups (also used by the data tools)
# ---------------------------------------------------------------------------
def load_viewable_dashboard(user: Any, dashboard_id: str) -> dict[str, Any]:
    """The dashboard document, or the same HTTP error ``GET /dashboards/get/{id}`` raises."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    try:
        oid = ObjectId(str(dashboard_id))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid dashboard id: {dashboard_id!r}")
    doc = dashboards_collection.find_one({"dashboard_id": oid})
    if not doc:
        raise HTTPException(
            status_code=404, detail=f"Dashboard with ID '{dashboard_id}' not found."
        )
    project_id = doc.get("project_id")
    if not project_id:
        raise HTTPException(status_code=500, detail="Dashboard is not associated with a project.")
    if not check_project_permission(project_id, user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this dashboard."
        )
    return doc


def find_component(doc: dict[str, Any], index: str) -> dict[str, Any]:
    """The stored component whose ``index`` (or ``tag``) is ``index``, else 404."""
    for comp in doc.get("stored_metadata") or []:
        if str(comp.get("index")) == index or (comp.get("tag") and comp.get("tag") == index):
            return comp
    raise HTTPException(
        status_code=404,
        detail=f"No component '{index}' on this dashboard tab; list them with get_dashboard.",
    )


def dc_index(project_doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """``{dc_id: {tag, workflow_tag, type}}`` for every data collection of a project."""
    out: dict[str, dict[str, Any]] = {}
    if not project_doc:
        return out

    def add(dc: dict[str, Any], workflow_tag: str | None) -> None:
        dc_id = dc.get("_id") or dc.get("id")
        if dc_id is None:
            return
        out[str(dc_id)] = {
            "tag": dc.get("data_collection_tag"),
            "workflow_tag": workflow_tag,
            "type": (dc.get("config") or {}).get("type"),
        }

    for wf in project_doc.get("workflows") or []:
        for dc in wf.get("data_collections") or []:
            add(dc, wf.get("workflow_tag"))
    for dc in project_doc.get("data_collections") or []:
        add(dc, None)
    return out


def dc_schema(dc_id: str) -> list[dict[str, Any]] | None:
    """Columns recorded at ingest (``[{name, type}]``), or None when unknown.

    Read off the deltatable's ``aggregation_columns_specs`` like the dashboard
    routes do, so no data is loaded.
    """
    try:
        dt = deltatables_collection.find_one({"data_collection_id": ObjectId(str(dc_id))})
    except Exception as exc:
        logger.warning(f"agents: deltatable lookup failed for {dc_id}: {exc}")
        return None
    aggregations = (dt or {}).get("aggregation") or []
    raw = (aggregations[-1] or {}).get("aggregation_columns_specs") if aggregations else None
    if isinstance(raw, list):
        cols = [
            {"name": e["name"], "type": e.get("type")}
            for e in raw
            if isinstance(e, dict) and e.get("name")
        ]
        return cols or None
    if isinstance(raw, dict):  # legacy shape: {column: specs}
        return [
            {"name": name, "type": (specs or {}).get("type") if isinstance(specs, dict) else None}
            for name, specs in raw.items()
        ] or None
    return None


def _short(value: Any) -> Any:
    """Keep scalars and short lists of scalars; drop nested blobs."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list) and len(value) <= 20:
        if all(isinstance(v, (str, int, float, bool)) or v is None for v in value):
            return value
    return None


def key_config(comp: dict[str, Any]) -> dict[str, Any]:
    """The few fields that say what a component shows (columns, aggregation, kind)."""
    out: dict[str, Any] = {}
    for key in _KEY_FIELDS:
        value = _short(comp.get(key))
        if value not in (None, "", []):
            out[key] = value
    kwargs = comp.get("dict_kwargs")
    if isinstance(kwargs, dict):
        for key in FIGURE_ROLE_KEYS:
            value = _short(kwargs.get(key))
            if value not in (None, "", []):
                out[key] = value
    config = comp.get("config")
    if isinstance(config, dict):  # advanced_viz role bindings
        roles = {
            k: v
            for k, v in config.items()
            if k != "viz_kind" and isinstance(v, str) and v and len(v) <= 80
        }
        if roles:
            out["config"] = dict(list(roles.items())[:MAX_KEY_CONFIG_ENTRIES])
    if "filter_expr" in out:
        out["filter_expr"] = untrusted(str(out["filter_expr"]))
    return dict(list(out.items())[: MAX_KEY_CONFIG_ENTRIES + 4])


def _component_line(
    comp: dict[str, Any], dcs: dict[str, dict[str, Any]], tab: dict[str, Any] | None = None
) -> dict[str, Any]:
    comp_type = comp.get("component_type") or comp.get("type") or ""
    dc_id = str(comp["dc_id"]) if comp.get("dc_id") else None
    line: dict[str, Any] = {
        "index": str(comp.get("index")) if comp.get("index") is not None else None,
        "type": comp_type,
        "title": untrusted(comp.get("title")) if comp.get("title") else None,
    }
    if dc_id:
        line["dc_id"] = dc_id
        line["dc_tag"] = (dcs.get(dc_id) or {}).get("tag")
    for field in ("section", "placement", "group"):
        if comp.get(field):
            line[field] = comp[field]
    if tab is not None:
        line["tab"] = tab
    config = key_config(comp)
    if config:
        line["config"] = config
    if comp_type == "text" and comp.get("body"):
        line["body_preview"] = untrusted(str(comp["body"])[:TEXT_PREVIEW_CHARS])
    return {k: v for k, v in line.items() if v is not None}


def _family(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every tab of the dashboard's family, main tab first, in tab order."""
    main_id = (
        doc["dashboard_id"] if doc.get("is_main_tab", True) else doc.get("parent_dashboard_id")
    )
    if not main_id:
        return [doc]
    main = (
        doc
        if doc.get("dashboard_id") == main_id
        else dashboards_collection.find_one({"dashboard_id": ObjectId(str(main_id))}) or doc
    )
    children = list(
        dashboards_collection.find({"parent_dashboard_id": ObjectId(str(main_id))}).sort(
            "tab_order", 1
        )
    )
    return [main, *[c for c in children if c.get("dashboard_id") != main.get("dashboard_id")]]


def _tab_ref(doc: dict[str, Any]) -> dict[str, Any]:
    is_main = doc.get("is_main_tab", True)
    title = doc.get("main_tab_name") if is_main and doc.get("main_tab_name") else doc.get("title")
    return {
        "dashboard_id": str(doc.get("dashboard_id")),
        "title": untrusted(title) if title else None,
        "is_main_tab": bool(is_main),
        "tab_order": doc.get("tab_order"),
        "component_count": len(doc.get("stored_metadata") or []),
    }


# ---------------------------------------------------------------------------
# Core functions (user-level, reusable outside the tool registry)
# ---------------------------------------------------------------------------
def projects_summary(user: Any) -> list[dict[str, Any]]:
    """Projects ``user`` may view, decided per project by ``check_project_permission``.

    Raw documents rather than ``_async_get_all_projects``: that helper validates
    every project into the full model, so one legacy document would fail the
    whole listing, and it ignores the ``"*"`` viewer wildcard the dashboard
    routes honour.
    """
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import check_project_permission

    projection = {
        "name": 1,
        "is_public": 1,
        "template_origin": 1,
        "workflows._id": 1,
        "workflows.data_collections._id": 1,
        "data_collections._id": 1,
    }
    projects = [
        p
        for p in projects_collection.find({}, projection).sort("name", 1)
        if check_project_permission(p["_id"], user, "viewer")
    ]
    ids = [p["_id"] for p in projects]
    dashboard_counts: dict[str, int] = {}
    if ids:
        for row in dashboards_collection.aggregate(
            [
                {"$match": {"project_id": {"$in": ids}, "is_main_tab": {"$ne": False}}},
                {"$group": {"_id": "$project_id", "n": {"$sum": 1}}},
            ]
        ):
            dashboard_counts[str(row["_id"])] = row["n"]
    out = []
    for p in projects:
        workflows = p.get("workflows") or []
        dc_count = sum(len(wf.get("data_collections") or []) for wf in workflows) + len(
            p.get("data_collections") or []
        )
        origin = p.get("template_origin") or {}
        out.append(
            {
                "project_id": str(p["_id"]),
                "name": untrusted(p.get("name")),
                "is_public": bool(p.get("is_public", False)),
                "template_id": origin.get("template_id"),
                "workflow_count": len(workflows),
                "data_collection_count": dc_count,
                "dashboard_count": dashboard_counts.get(str(p["_id"]), 0),
            }
        )
    return out


def dashboards_summary(user: Any, project_id: str | None = None) -> list[dict[str, Any]]:
    from depictio.api.v1.endpoints.dashboards_endpoints.core_functions import (
        load_dashboards_from_db,
    )

    result = load_dashboards_from_db(
        owner=user.id, admin_mode=False, user=user, include_child_tabs=True
    )
    if not result.get("success"):
        return []
    rows = result["dashboards"]
    if project_id:
        rows = [d for d in rows if str(d.get("project_id")) == str(project_id)]

    counts: dict[str, int] = {}
    oids = [ObjectId(str(d["dashboard_id"])) for d in rows if d.get("dashboard_id")]
    if oids:
        for row in dashboards_collection.aggregate(
            [
                {"$match": {"dashboard_id": {"$in": oids}}},
                {
                    "$project": {
                        "dashboard_id": 1,
                        "n": {"$size": {"$ifNull": ["$stored_metadata", []]}},
                    }
                },
            ]
        ):
            counts[str(row["dashboard_id"])] = row["n"]

    def entry(d: dict[str, Any]) -> dict[str, Any]:
        did = str(d.get("dashboard_id"))
        return {
            "dashboard_id": did,
            "title": untrusted(d.get("title")),
            "project_id": str(d.get("project_id")) if d.get("project_id") else None,
            "component_count": counts.get(did, 0),
            "updated": d.get("last_saved_ts") or None,
        }

    mains = [d for d in rows if d.get("is_main_tab", True) is not False]
    children: dict[str, list[dict[str, Any]]] = {}
    for d in rows:
        if d.get("is_main_tab", True) is False and d.get("parent_dashboard_id"):
            children.setdefault(str(d["parent_dashboard_id"]), []).append(d)

    out = []
    for d in sorted(mains, key=lambda x: str(x.get("title") or "")):
        item = entry(d)
        tabs = sorted(children.get(item["dashboard_id"], []), key=lambda x: x.get("tab_order") or 0)
        if tabs:
            item["tabs"] = [entry(t) for t in tabs]
        out.append(item)
    return out


def dashboard_summary(user: Any, dashboard_id: str, *, include_tabs: bool = False) -> dict:
    """Compact structure of one dashboard tab (or its whole family)."""
    doc = load_viewable_dashboard(user, dashboard_id)
    project = projects_collection.find_one({"_id": ObjectId(str(doc["project_id"]))}) or {}
    dcs = dc_index(project)
    family = _family(doc)

    if include_tabs:
        components = [
            _component_line(c, dcs, tab={"dashboard_id": str(t.get("dashboard_id"))})
            for t in family
            for c in t.get("stored_metadata") or []
        ]
    else:
        components = [_component_line(c, dcs) for c in doc.get("stored_metadata") or []]

    parent = doc.get("parent_dashboard_id")
    return {
        "dashboard_id": str(doc["dashboard_id"]),
        "title": untrusted(doc.get("title")),
        "subtitle": untrusted(doc.get("subtitle")) if doc.get("subtitle") else None,
        "project_id": str(doc["project_id"]),
        "project_name": untrusted(project.get("name")) if project.get("name") else None,
        "is_main_tab": doc.get("is_main_tab", True) is not False,
        "parent_dashboard_id": str(parent) if parent else None,
        "updated": doc.get("last_saved_ts") or None,
        "tabs": [_tab_ref(t) for t in family] if len(family) > 1 else [],
        "data_collections": [
            {"dc_id": dc_id, **meta}
            for dc_id, meta in dcs.items()
            if any(c.get("dc_id") == dc_id for c in components)
        ],
        "components": components,
    }


def _lite_dump(comp: dict[str, Any], dcs: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The component as its YAML (lite) model sees it, or None when it does not convert."""
    from depictio.models.models.dashboards import DashboardDataLite

    dc_meta = dcs.get(str(comp.get("dc_id"))) or {}
    tagged = {
        **comp,
        "workflow_tag": comp.get("workflow_tag") or dc_meta.get("workflow_tag") or "",
        "data_collection_tag": comp.get("data_collection_tag") or dc_meta.get("tag") or "",
    }
    try:
        lite = DashboardDataLite.from_full({"stored_metadata": [tagged]})
        dumped = lite.model_dump(exclude_none=True, mode="json").get("components") or []
    except Exception as exc:
        logger.debug(f"agents: lite conversion of component {comp.get('index')} failed: {exc}")
        return None
    if not dumped:
        return None
    return {k: v for k, v in dumped[0].items() if v not in ("", [], {}, None)}


def _plain_dump(comp: dict[str, Any]) -> dict[str, Any]:
    from depictio.models.models.base import convert_objectid_to_str

    return convert_objectid_to_str(
        {k: v for k, v in comp.items() if k not in _INTERNAL_FIELDS and v not in ("", [], {}, None)}
    )


def component_detail(user: Any, dashboard_id: str, index: str) -> dict[str, Any]:
    """Full config of one component plus the columns of its data collection."""
    doc = load_viewable_dashboard(user, dashboard_id)
    comp = find_component(doc, index)
    project = projects_collection.find_one({"_id": ObjectId(str(doc["project_id"]))}) or {}
    dcs = dc_index(project)

    config = _lite_dump(comp, dcs) or _plain_dump(comp)
    for field in _FREE_TEXT_FIELDS:
        if isinstance(config.get(field), str):
            config[field] = untrusted(config[field])
    if isinstance(config.get("filter_expr"), str):
        config["filter_expr"] = untrusted(config["filter_expr"])

    dc_id = str(comp["dc_id"]) if comp.get("dc_id") else None
    out: dict[str, Any] = {
        "dashboard_id": str(doc["dashboard_id"]),
        "index": str(comp.get("index")),
        "type": comp.get("component_type"),
        "dc_id": dc_id,
        "wf_id": str(comp["wf_id"]) if comp.get("wf_id") else None,
        "dc_tag": (dcs.get(dc_id or "") or {}).get("tag"),
        "config": config,
    }
    if dc_id:
        schema = dc_schema(dc_id)
        out["schema"] = schema
        if schema is None:
            out["schema_note"] = "Column schema not recorded; use describe_data_collection."
    return out


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class ListProjectsArgs(_Args):
    pass


class ListDashboardsArgs(_Args):
    project_id: str | None = Field(
        default=None, description="Only dashboards of this project (id from list_projects)."
    )


class GetDashboardArgs(_Args):
    dashboard_id: str = Field(description="Dashboard or tab id (from list_dashboards).")
    include_tabs: bool = Field(
        default=False,
        description="Also list the components of every other tab of the same dashboard.",
    )


class GetComponentArgs(_Args):
    dashboard_id: str = Field(description="Dashboard tab id the component lives on.")
    index: str = Field(description="Component index, as listed by get_dashboard.")


@agent_tool(
    name="list_projects",
    scope="read",
    description=(
        "List the projects you can see: id, name, template id when created from a "
        "template, and counts of workflows, data collections and dashboards. "
        "Start here, then call list_dashboards."
    ),
    input_model=ListProjectsArgs,
)
async def list_projects(ctx: ToolContext, args: ListProjectsArgs) -> list[dict[str, Any]]:
    return projects_summary(ctx.user)


@agent_tool(
    name="list_dashboards",
    scope="read",
    description=(
        "List dashboards you can see, optionally for one project: id, title, project id, "
        "component count, last save time, and child tabs nested under their main tab. "
        "Each tab is its own dashboard id."
    ),
    input_model=ListDashboardsArgs,
)
async def list_dashboards(ctx: ToolContext, args: ListDashboardsArgs) -> list[dict[str, Any]]:
    return dashboards_summary(ctx.user, args.project_id)


@agent_tool(
    name="get_dashboard",
    scope="read",
    description=(
        "Compact summary of one dashboard tab: its tabs, the data collections it uses and "
        "one line per component (index, type, title, data collection, key config such as "
        "x/y/color, aggregation, filter column or viz kind, and section). Use the component "
        "index with get_component and get_component_data."
    ),
    input_model=GetDashboardArgs,
)
async def get_dashboard(ctx: ToolContext, args: GetDashboardArgs) -> dict[str, Any]:
    return dashboard_summary(ctx.user, args.dashboard_id, include_tabs=args.include_tabs)


@agent_tool(
    name="get_component",
    scope="read",
    description=(
        "Full configuration of one component (as in the dashboard YAML) plus the column "
        "names and dtypes of its data collection. Does not load data; use "
        "get_component_data for values."
    ),
    input_model=GetComponentArgs,
)
async def get_component(ctx: ToolContext, args: GetComponentArgs) -> dict[str, Any]:
    return component_detail(ctx.user, args.dashboard_id, args.index)
