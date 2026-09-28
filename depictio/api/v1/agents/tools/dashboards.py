"""Agent tools that author dashboards: drafts only, never the user's own dashboards.

``propose_component`` validates one lite component (the CLI loader
``component_yaml.validate_single``), runs the generator's render check
(``dashboard_gen.probe_verdict``) and adds it to a draft copy of the dashboard.
The draft is an ordinary AI draft (an ``ai_generation`` stamp with status
``draft``, the "AI draft" badge, the editor's review panel): the agent run gets
one draft per source dashboard, keyed by ``ToolContext.run_id``, and every
later proposal of that run lands in the same draft. The source dashboard is
read, never written; promoting or discarding the draft stays with the user.

``suggest_components`` and ``generate_dashboard`` wrap the in-app assistant's
services (``suggest.suggest_components``, ``dashboard_gen.run_generation``)
with the same gates as their routes. Both spend the server's LLM budget, so
they are hidden unless ``settings.mcp.enable_llm_tools`` and the assistant
itself are on.

``list_component_types`` is the authoring reference: the lite component types,
their required fields and the constraint sheet the assistant's own prompts use.
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from typing import Any

import yaml
from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.envelope import untrusted
from depictio.api.v1.agents.registry import ToolError, agent_tool
from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import dashboards_collection
from depictio.api.v1.endpoints.ai_endpoints import component_yaml, dashboard_gen
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    ComponentType,
    GenerateDashboardRequest,
    StreamEvent,
    SuggestComponentsRequest,
)
from depictio.models.models.dashboards import DashboardDataLite

# Suffixes tried when "<title> (agent draft)" is taken in the project.
MAX_DRAFT_TITLES = 5
# Types that bind no data collection, so there is nothing to resolve or probe.
STANDALONE_TYPES = frozenset({"text"})
MAX_RATIONALE_CHARS = 2000


def _editor_path(dashboard_id: str) -> str:
    """Where a user reviews an AI draft: the editor, which carries the review panel."""
    return f"/dashboard-edit/{dashboard_id}"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposeComponentArgs(_Args):
    dashboard_id: str = Field(
        description="The dashboard to extend. A draft this run already made is reused."
    )
    component: dict[str, Any] = Field(
        description=(
            "One lite component, as in dashboard YAML: component_type, workflow_tag, "
            "data_collection_tag, title and the type's own fields (see list_component_types). "
            "Optional section and tag."
        )
    )
    rationale: str = Field(
        min_length=1,
        max_length=MAX_RATIONALE_CHARS,
        description="Why this component answers the user's question; shown to the reviewer.",
    )


class SuggestComponentsArgs(_Args):
    dashboard_id: str
    component_type: ComponentType | None = Field(
        default=None, description="Pin one type; left empty, types are mixed."
    )
    data_collection_id: str | None = Field(
        default=None, description="Pin one data collection of the dashboard's project."
    )
    n: int = Field(default=4, ge=1, le=8)


class GenerateDashboardArgs(_Args):
    project_id: str
    prompt: str = Field(
        default="",
        max_length=2000,
        description="What the dashboard should show; empty asks for a general overview.",
    )
    data_collection_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Restrict the planner to these collections of the project.",
    )


class ListComponentTypesArgs(_Args):
    component_type: ComponentType | None = Field(
        default=None,
        description="Give one type for its full field list, constraints and a YAML example.",
    )


# ---------------------------------------------------------------------------
# Gates and helpers
# ---------------------------------------------------------------------------
def _gate_draft_writes(user: Any) -> None:
    """The rules of ``POST /dashboards/import/yaml``, which also persists a lite dashboard."""
    if settings.auth.is_public_mode:
        raise ToolError("Dashboard drafts are disabled in public/demo mode", status=403)
    if getattr(user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise ToolError("Anonymous users cannot create dashboards", status=403)


def _oid(value: str, what: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ToolError(f"Invalid {what}: {value!r}", status=400) from exc


def _source_of(doc: dict[str, Any]) -> str | None:
    """The source dashboard id an agent draft was copied from, if it is one."""
    return (doc.get("ai_generation") or {}).get("source_dashboard_id")


def _is_run_draft(doc: dict[str, Any], ctx: ToolContext) -> bool:
    info = doc.get("ai_generation") or {}
    return (
        info.get("status") == "draft"
        and info.get("run_id") == ctx.run_id
        and _source_of(doc) is not None
    )


def _load_dashboard(dashboard_id: str) -> dict[str, Any]:
    doc = dashboards_collection.find_one({"dashboard_id": _oid(dashboard_id, "dashboard_id")})
    if not doc:
        raise ToolError("Dashboard not found", status=404)
    return doc


def _find_run_draft(ctx: ToolContext, source: dict[str, Any]) -> dict[str, Any] | None:
    """This run's draft of ``source``, or None (then a new draft is made)."""
    if _is_run_draft(source, ctx):
        return source
    return dashboards_collection.find_one(
        {
            "project_id": source.get("project_id"),
            "ai_generation.run_id": ctx.run_id,
            "ai_generation.status": "draft",
            "ai_generation.source_dashboard_id": str(source["dashboard_id"]),
        }
    )


def _lite_dict_of(doc: dict[str, Any]) -> dict[str, Any]:
    """The dashboard as the YAML export sees it (tags, not ids), as a plain dict.

    The same enrich + ``from_full`` path ``GET /dashboards/{id}/yaml`` takes,
    on a copy: ``enrich_dashboard_with_tags`` mutates what it is given.
    """
    from depictio.models.yaml_serialization.utils import enrich_dashboard_with_tags

    enriched = enrich_dashboard_with_tags(copy.deepcopy(doc))
    lite = DashboardDataLite.from_full(enriched)
    return yaml.safe_load(lite.to_yaml()) or {}


def _validate(component: dict[str, Any]) -> dict[str, Any]:
    validated, error = dashboard_gen.validate_component(component)
    if validated is None:
        raise ToolError(f"The component does not validate:\n{error}", status=422)
    return validated


def _probe_context(component: dict[str, Any], project_id: Any) -> SimpleNamespace | None:
    """Resolve the component's tags in the dashboard's project, as the import will."""
    if component.get("component_type") in STANDALONE_TYPES:
        return None
    stub = {
        "workflow_tag": component.get("workflow_tag") or "",
        "data_collection_tag": component.get("data_collection_tag") or "",
    }
    dashboard_gen.resolve_workflow_tags(stub, project_id)
    if not stub.get("wf_id") or not stub.get("dc_id"):
        # The import would silently drop a component it cannot bind
        # (``_filter_unresolved_components``); say so instead.
        raise ToolError(
            f"workflow_tag {stub['workflow_tag']!r} / data_collection_tag "
            f"{stub['data_collection_tag']!r} do not resolve in the dashboard's project",
            status=422,
        )
    return SimpleNamespace(data_collection_id=str(stub["dc_id"]), workflow_id=str(stub["wf_id"]))


def _unique_tag(wanted: str | None, taken: set[str], component_type: str) -> str:
    base = (wanted or "").strip() or f"agent-{component_type}"
    tag, n = base, 2
    while tag in taken:
        tag, n = f"{base}-{n}", n + 1
    return tag


def _place(components: list[dict[str, Any]], new: dict[str, Any]) -> None:
    """Give ``new`` a section and a box under everything else in that section.

    Boxes are the generator's defaults on the 8-column grid
    (``dashboard_layout``). Grid positions are section-relative and
    interactives live in their own panel, so only those neighbours count. With
    no section given, a filter joins the first filter section and a tile the
    last grid section, as ``layout_dashboard`` places a component the plan
    does not know.
    """
    from depictio.api.v1.endpoints.ai_endpoints import dashboard_layout as dl

    component_type = str(new.get("component_type") or "")
    is_filter = component_type == "interactive"
    neighbours = [
        c
        for c in components
        if (c.get("component_type") == "interactive") == is_filter
        and c.get("placement") not in ("top", "floating")
    ]
    if not new.get("section"):
        sections = [c["section"] for c in neighbours if c.get("section")]
        if sections:
            new["section"] = sections[0] if is_filter else sections[-1]
    section = new.get("section")
    bottom = 0
    for comp in neighbours:
        if comp.get("section") == section:
            box = comp.get("layout") or {}
            bottom = max(bottom, int(box.get("y", 0)) + int(box.get("h", 0)))
    size = {
        "interactive": dl.INTERACTIVE_BOX,
        "text": dl.TEXT_BOX,
        "card": dl.CARD_BOX,
        "advanced_viz": dl.ADVANCED_VIZ_BOX,
        "table": dl.TABLE_BOX,
    }.get(component_type, dl.CHART_BOX)
    new["layout"] = {"x": 0, "y": bottom, "w": size["w"], "h": size["h"]}


def _stamp(
    ctx: ToolContext,
    rationale: str,
    source_id: str,
    check: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """The ``ai_generation`` stamp (``AIGenerationInfo``) of an agent draft."""
    prev = previous or {}
    return {
        "status": "draft",
        "model": ctx.agent_model or ctx.agent_name,
        "prompt": rationale,
        "generated_at": dashboard_gen._now_iso(),
        "run_id": ctx.run_id,
        "warnings": list(prev.get("warnings") or []),
        "reviewed": list(prev.get("reviewed") or []),
        "dropped": list(prev.get("dropped") or []),
        "sections": list(prev.get("sections") or []),
        "checks": [*(prev.get("checks") or []), check],
        "source_dashboard_id": source_id,
        "agent": ctx.agent_name,
    }


def _draft_title(source_title: str, n: int) -> str:
    return f"{source_title} (agent draft)" if n == 1 else f"{source_title} (agent draft {n})"


def _persist_draft(
    ctx: ToolContext,
    lite_dict: dict[str, Any],
    project_id: Any,
    stamp: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    source_title: str,
) -> dict[str, Any]:
    """Write the draft: replace this run's draft in place, or insert a new one.

    Never overwrites anything else. A new draft is inserted with
    ``overwrite=False`` (a taken title is a 409, so the next suffix is tried);
    an existing one is replaced by title only after checking that the title
    still points at that very draft.
    """
    persist = dashboard_gen._persist_lite_dashboard
    if existing is not None:
        title = str(existing.get("title") or "")
        holder = dashboards_collection.find_one(
            {"title": title, "project_id": existing.get("project_id")}, {"dashboard_id": 1}
        )
        if not holder or holder.get("dashboard_id") != existing.get("dashboard_id"):
            raise ToolError(
                "The run's draft title is now used by another dashboard; start a new run",
                status=409,
            )
        lite_dict["title"] = title
        lite = dashboard_gen.validate_envelope(lite_dict)
        return persist(
            lite, project_id, ctx.user, overwrite=True, extra_fields={"ai_generation": stamp}
        )
    for n in range(1, MAX_DRAFT_TITLES + 1):
        lite_dict["title"] = _draft_title(source_title, n)
        lite = dashboard_gen.validate_envelope(lite_dict)
        try:
            return persist(
                lite, project_id, ctx.user, overwrite=False, extra_fields={"ai_generation": stamp}
            )
        except HTTPException as exc:
            if exc.status_code != 409 or n == MAX_DRAFT_TITLES:
                raise
    raise ToolError("No free draft title", status=409)  # pragma: no cover


def _propose(ctx: ToolContext, args: ProposeComponentArgs) -> dict[str, Any]:
    """The whole propose flow; synchronous (pymongo, the probe), run in a thread."""
    _gate_draft_writes(ctx.user)
    source = _load_dashboard(args.dashboard_id)
    project_id = source.get("project_id")
    if not project_id:
        raise ToolError("The dashboard belongs to no project", status=400)
    # Making a draft is creating a dashboard in the project: editor, as for
    # the YAML import and the generator.
    if not dashboard_gen.check_project_permission(project_id, ctx.user, "editor"):
        raise ToolError(
            "You need editor permission on the project to draft dashboards in it", status=403
        )

    draft = _find_run_draft(ctx, source)
    source_id = (_source_of(draft) if draft is not None else None) or str(source["dashboard_id"])
    if draft is not None and draft is not source:
        # Same gate as the review routes on a draft.
        dashboard_gen.require_draft_dashboard(str(draft["dashboard_id"]), ctx.user)

    component = _validate(dict(args.component))
    component_type = str(component.get("component_type") or "")
    probe_ctx = _probe_context(component, project_id)
    verdict = dashboard_gen.probe_verdict(component, probe_ctx, ctx.user)
    probe = {"status": verdict.status, "detail": verdict.detail}
    if verdict.status == "failed":
        raise ToolError(
            f"The component would not render against its data: {verdict.detail}. "
            "Nothing was added; fix the binding and propose it again.",
            status=422,
        )

    base = draft if draft is not None else source
    lite_dict = _lite_dict_of(base)
    components = [c for c in lite_dict.get("components") or [] if isinstance(c, dict)]
    tag = _unique_tag(
        component.get("tag"), {str(c.get("tag") or "") for c in components}, component_type
    )
    component["tag"] = tag
    component.pop("index", None)
    _place(components, component)
    component["ai_source"] = {"flow": "agent", "tag": tag, "prompt": args.rationale}
    lite_dict["components"] = [*components, component]
    # A draft is its own main tab: copied from a child tab it must not join
    # the source's tab family. The id is minted by the persist step.
    lite_dict["is_main_tab"] = True
    for key in ("parent_dashboard_tag", "tab_order", "dashboard_id"):
        lite_dict.pop(key, None)

    check = {
        "tag": tag,
        "attempts": 1,
        "repair": "",
        "checks": [
            {"layer": "model", "status": "passed", "detail": ""},
            {"layer": "render", "status": verdict.status, "detail": verdict.detail},
        ],
    }
    stamp = _stamp(
        ctx, args.rationale, source_id, check, (draft or {}).get("ai_generation") or None
    )
    try:
        payload = _persist_draft(
            ctx,
            lite_dict,
            project_id,
            stamp,
            existing=draft,
            source_title=str(source.get("title") or "Dashboard"),
        )
    except (ValidationError, ValueError) as exc:
        raise ToolError(
            "The draft did not validate with this component in it: "
            + component_yaml.format_validation_error_for_llm(exc),
            status=422,
        ) from exc

    draft_id = str(payload.get("dashboard_id") or "")
    return {
        "draft_dashboard_id": draft_id,
        "draft_title": untrusted(str(payload.get("title") or "")),
        "source_dashboard_id": source_id,
        "reused_draft": draft is not None,
        "component_tag": tag,
        "component_type": component_type,
        "probe": probe,
        "review_path": _editor_path(draft_id),
        "note": "Draft only: the source dashboard is unchanged; the user reviews and promotes it.",
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@agent_tool(
    name="propose_component",
    scope="edit_dashboard",
    description=(
        "Add one component to a DRAFT copy of a dashboard for the user to review; the "
        "dashboard itself is never changed. The component (lite YAML shape, see "
        "list_component_types) is validated and render-checked against one row of its "
        "data first; a failing check is an error and nothing is saved. All proposals of "
        "one run go into the same draft. Returns the draft id, the probe verdict "
        "(passed, or skipped with the reason) and the editor path where the user reviews it."
    ),
    input_model=ProposeComponentArgs,
    writes=True,
)
async def propose_component(ctx: ToolContext, args: ProposeComponentArgs) -> dict[str, Any]:
    return await asyncio.to_thread(_propose, ctx, args)


def _llm_tools_enabled() -> bool:
    return bool(settings.mcp.enable_llm_tools and settings.ai.enabled)


@agent_tool(
    name="suggest_components",
    scope="edit_dashboard",
    description=(
        "Ask the in-app assistant what to add to a dashboard: up to n validated lite "
        "components (ranked from the data, plus one LLM call) with a rationale each. "
        "Nothing is saved; pass a suggestion's `component` to propose_component to draft "
        "it. Spends the server's LLM budget."
    ),
    input_model=SuggestComponentsArgs,
    enabled=_llm_tools_enabled,
)
async def suggest_components(ctx: ToolContext, args: SuggestComponentsArgs) -> dict[str, Any]:
    from depictio.api.v1.endpoints.ai_endpoints import suggest as suggest_mod
    from depictio.api.v1.endpoints.ai_endpoints.context import (
        build_dashboard_context,
        build_data_context,
        build_project_inventory,
    )

    response = await suggest_mod.suggest_components(
        SuggestComponentsRequest(**args.model_dump()),
        ctx.user,
        user_api_key=None,
        build_inventory=build_project_inventory,
        build_dashboard_ctx=build_dashboard_context,
        build_data_ctx=build_data_context,
    )
    return {
        "suggestions": [
            {
                "component_type": s.component_type,
                "data_collection_id": s.data_collection_id,
                "title": untrusted(s.title),
                "rationale": untrusted(s.rationale),
                "origin": s.origin,
                "component": s.component,
            }
            for s in response.suggestions
        ],
        "warnings": response.warnings,
    }


def _generation_enabled() -> bool:
    return _llm_tools_enabled() and bool(settings.ai.generate_dashboard_enabled)


@agent_tool(
    name="generate_dashboard",
    scope="edit_dashboard",
    description=(
        "Have the in-app assistant draft a whole new dashboard for a project from a prompt "
        "(plan, fill, render-check every component, lay out). The result is a new AI draft "
        "the user reviews; no existing dashboard is touched. Slow (minutes) and spends the "
        "server's LLM budget. Returns the draft id, per-component outcomes and warnings."
    ),
    input_model=GenerateDashboardArgs,
    writes=True,
    enabled=_generation_enabled,
)
async def generate_dashboard(ctx: ToolContext, args: GenerateDashboardArgs) -> dict[str, Any]:
    # No title and no overwrite: the planner picks a title and a collision gets
    # an "(AI draft N)" suffix, so a generation can never replace a dashboard.
    body = GenerateDashboardRequest(
        project_id=args.project_id,
        prompt=args.prompt,
        data_collection_ids=list(args.data_collection_ids),
    )
    project_doc = await asyncio.to_thread(dashboard_gen.gate_generate_request, body, ctx.user)

    events: list[StreamEvent] = []

    def collect(event: StreamEvent) -> bytes:
        events.append(event)
        return b""

    async for _ in dashboard_gen.run_generation(
        body, ctx.user, user_api_key=None, project_doc=project_doc, frame=collect
    ):
        pass

    components = [
        {k: e.data.get(k) for k in ("tag", "component_type", "section", "status", "error")}
        for e in events
        if e.type == "component"
    ]
    errors = [str(e.data.get("detail") or "") for e in events if e.type == "error"]
    dashboard = next((e.data for e in reversed(events) if e.type == "dashboard"), None)
    if dashboard is None:
        raise ToolError(errors[-1] if errors else "The generation produced no dashboard", 502)
    draft_id = str(dashboard.get("dashboard_id") or "")
    return {
        "draft_dashboard_id": draft_id,
        "title": untrusted(str(dashboard.get("title") or "")),
        "project_id": dashboard.get("project_id"),
        "components": components,
        "dropped": dashboard.get("dropped") or [],
        "warnings": dashboard.get("warnings") or [],
        "review_path": _editor_path(draft_id),
    }


def _field_lines(model: type[BaseModel], *, skip: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, field in model.model_fields.items():
        if name in skip:
            continue
        label = (field.description or "").strip()
        out[name] = ("(required) " if field.is_required() else "") + label
    return out


# The base fields every lite component shares; described once.
_COMMON_FIELDS = {
    "tag",
    "index",
    "component_type",
    "title",
    "description",
    "title_size",
    "title_align",
    "section",
    "workflow_tag",
    "data_collection_tag",
}


@agent_tool(
    name="list_component_types",
    scope="read",
    description=(
        "The dashboard component types an agent can author, as lite YAML components. "
        "Without an argument: every type with its required fields and a one-line summary, "
        "plus the fields all types share. With component_type: that type's full field "
        "list, its constraints (allowed values) and a YAML example."
    ),
    input_model=ListComponentTypesArgs,
)
async def list_component_types(ctx: ToolContext, args: ListComponentTypesArgs) -> dict[str, Any]:
    from depictio.api.v1.endpoints.ai_endpoints import prompts
    from depictio.models.components.lite import BaseLiteComponent

    type_map = DashboardDataLite._COMPONENT_TYPE_MAP
    if args.component_type is not None:
        model = type_map[args.component_type]
        return {
            "component_type": args.component_type,
            "required": [n for n, f in model.model_fields.items() if f.is_required()],
            "fields": _field_lines(model, skip=_COMMON_FIELDS),
            "constraints": prompts._constraint_sheet(args.component_type, None),
            "example_yaml": prompts._example_yaml(args.component_type),
        }
    return {
        "common_fields": _field_lines(BaseLiteComponent, skip={"index"}),
        "types": [
            {
                "component_type": name,
                "required": [n for n, f in model.model_fields.items() if f.is_required()],
                "summary": prompts._constraint_sheet(name, None).splitlines()[0],
            }
            for name, model in type_map.items()
        ],
        "note": "text binds no data collection; every other type needs workflow_tag and "
        "data_collection_tag from the project.",
    }
