"""Whole-dashboard generation: plan, fill, validate, lay out, persist.

Backs ``POST /ai/generate-dashboard`` (see `run_generation`) and the promote
route (`promote_dashboard`). The stream is one SSE frame per event, in the
order the React panel consumes them:

  status* -> budget -> plan -> status -> (budget*, component)* -> status* -> dashboard -> done

or ``error`` then ``done`` when the run cannot produce a draft. The pipeline:

1. inventory: `build_project_data_context` (table collections, ranked
   advanced_viz kinds) and the catalog offers of the project document
   (`compose_offers_for_project`, advanced_viz renders only: those are the
   renders a ``use:`` handle resolves at import time);
2. plan: one LLM call through `prompts.dashboard_plan_messages`, parsed with
   `parse_plan` and repaired with `normalize_plan`; one retry with the error
   appended, then ``error``;
3. fill, in plan order: text headers and advanced_viz deterministically
   (`fill_text`, `fill_advanced_viz`), every other type through the same
   prompt, validator and repair loop as `/ai/component-from-prompt`, plus the
   server-side schema check (`check_against_schema`); a component that
   exhausts its repairs is dropped, never the run; once the token or
   wall-clock budget is spent the remaining LLM-filled components are dropped
   with error ``budget``;
4. layout: `layout_dashboard`, then `validate_envelope` once;
5. persist: `_persist_lite_dashboard` with the ``ai_generation`` draft stamp;
   an LLM-chosen title that collides gets an ``(AI draft N)`` suffix, a
   client-pinned one is a 409 reported inside the stream.

The run record (`generations`) is saved after the plan, after every
component and in the generator's ``finally``, so a cancelled or crashed run
stays inspectable. Every collaborator that touches Mongo or another
endpoint module is a module attribute here (``projects_collection``,
``dashboards_collection``, ``build_project_data_context``,
``compose_offers_for_project``, ``check_project_permission``,
``check_dashboard_mutation_permission``, ``_persist_lite_dashboard``) so the
route tests can substitute them without a database. The ones that live in
the big endpoint modules are lazy wrappers: importing
``dashboards_endpoints.routes`` at module load would pull the whole
dashboard API in behind the AI package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import yaml
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.db import dashboards_collection, projects_collection
from depictio.api.v1.endpoints.ai_endpoints import (
    component_yaml,
    generations,
    llm_client,
    prompts,
    routing,
)
from depictio.api.v1.endpoints.ai_endpoints.context import (
    DataContext,
    ProjectDataContext,
    build_project_data_context,
    offer_use_id,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_layout import layout_dashboard
from depictio.api.v1.endpoints.ai_endpoints.dashboard_plan import (
    DashboardPlan,
    PlannedComponent,
    normalize_plan,
    parse_plan,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_validate import (
    check_against_schema,
    validate_envelope,
)
from depictio.api.v1.endpoints.ai_endpoints.schemas import (
    BudgetSpent,
    GenerateDashboardRequest,
    GeneratedComponentEvent,
    GeneratedComponentStatus,
    GeneratedDashboardEvent,
    PromoteResponse,
    StreamEvent,
)
from depictio.api.v1.endpoints.ai_endpoints.suggest import column_type_for, viz_kind_label
from depictio.models.components.advanced_viz.catalog import role_config_key
from depictio.models.components.advanced_viz.schemas import role_dtype_specs

logger = logging.getLogger(__name__)

# The planning call and its single retry with the error appended.
PLAN_ATTEMPTS = 2
# " (AI draft 2)" ... " (AI draft 5)": how many suffixed titles are tried
# when the planner's title collides with an existing dashboard.
MAX_TITLE_DRAFTS = 5
# Header text tiles are H3 like the seeded dashboards' section headers.
HEADER_ORDER = 3

FillMode = Literal["text", "advanced_viz", "llm"]

# ---------------------------------------------------------------------------
# Lazy collaborators (patched by the route tests)
# ---------------------------------------------------------------------------


def _persist_lite_dashboard(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """`dashboards_endpoints.routes._persist_lite_dashboard`, imported on first use."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _persist_lite_dashboard as persist,
    )

    return persist(*args, **kwargs)


def check_project_permission(project_id: Any, user: Any, required_permission: str) -> bool:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        check_project_permission as check,
    )

    return check(project_id, user, required_permission)


def check_dashboard_mutation_permission(doc: dict, user: Any, required_permission: str) -> bool:
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        check_dashboard_mutation_permission as check,
    )

    return check(doc, user, required_permission)


def compose_offers_for_project(project_doc: dict[str, Any]) -> dict[str, Any]:
    """`catalog_endpoints.routes.compose_offers_for_project`, imported on first use."""
    from depictio.api.v1.endpoints.catalog_endpoints.routes import (
        compose_offers_for_project as compose,
    )

    return compose(project_doc)


def _sse(event: StreamEvent) -> bytes:
    """`routes._sse`: same framing as every other AI stream (lazy: routes imports this module)."""
    from depictio.api.v1.endpoints.ai_endpoints.routes import _sse as frame

    return frame(event)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@dataclass
class Budget:
    """Token, wall-clock and call accounting of one run.

    `event()` is the payload of the ``budget`` stream event, in the shape the
    analysis flow already emits so the React panel reads both the same way.
    A cached completion is not charged (it cost nothing) but still counts as
    a step.
    """

    max_tokens: int
    max_seconds: float
    max_steps: int
    started: float = field(default_factory=time.monotonic)
    tokens_used: int = 0
    steps_used: int = 0

    def charge(self, completion: llm_client.Completion) -> None:
        self.steps_used += 1
        if not completion.cached:
            self.tokens_used += completion.usage.total_tokens

    @property
    def seconds(self) -> float:
        return time.monotonic() - self.started

    def exhausted(self) -> bool:
        return self.tokens_used >= self.max_tokens or self.seconds >= self.max_seconds

    def event(self) -> dict[str, Any]:
        return {
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "seconds": round(self.seconds, 1),
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
        }

    def spent(self) -> BudgetSpent:
        return BudgetSpent(
            steps=self.steps_used, tokens=self.tokens_used, seconds=round(self.seconds, 1)
        )


def _max_steps(n_components: int) -> int:
    """The most LLM calls a plan of `n_components` can take: the plan and every repair."""
    return PLAN_ATTEMPTS + n_components * (1 + settings.ai.generate_max_repairs_per_component)


def pick_title(requested: str | None, plan_title: str, *, draft: int = 1) -> str:
    """The dashboard title to persist.

    A client-pinned title is used verbatim; the planner's title gets an
    ``(AI draft N)`` suffix from the second attempt on, which is how a
    collision with an existing dashboard is resolved without a 409.
    """
    if requested and requested.strip():
        return requested.strip()
    base = " ".join(plan_title.split()) or "Generated dashboard"
    return base if draft <= 1 else f"{base} (AI draft {draft})"


def offers_by_dc(compose: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Catalog offers per data collection id, from `compose_offers_for_project`.

    Only advanced_viz renders become offers: they are the renders a
    ``use: <tool>/<render_id>`` handle resolves when the lite component is
    validated (`AdvancedVizLiteComponent._expand_catalog_use`). A render
    without its own id is addressed through its output id, with the kind
    kept on the offer so an output rendering several kinds stays
    unambiguous. Each offer is the dict shape `DataContext.catalog_offers`
    documents: tool, render_id, title, component_type, dc_tag, description.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    for module in compose.get("modules") or []:
        tool = str(module.get("tool_id") or "")
        if not tool:
            continue
        for match in module.get("matches") or []:
            dc_id = str(match.get("dc_id") or "")
            output_id = str(match.get("output_id") or "")
            if not dc_id or not output_id:
                continue
            for render in match.get("renders_as") or []:
                if not isinstance(render, dict) or render.get("component") != "advanced_viz":
                    continue
                kind = str(render.get("kind") or "")
                render_id = str(render.get("id") or output_id.removeprefix(f"{tool}_"))
                key = (dc_id, tool, render_id, kind)
                if key in seen:
                    continue
                seen.add(key)
                name = str(match.get("name") or output_id)
                out.setdefault(dc_id, []).append(
                    {
                        "tool": tool,
                        "render_id": render_id,
                        "title": f"{viz_kind_label(kind)} of {name}" if kind else name,
                        "component_type": "advanced_viz",
                        "dc_tag": str(match.get("dc_tag") or ""),
                        "description": str(match.get("description") or ""),
                        "viz_kind": kind or None,
                    }
                )
    return out


def attach_catalog_offers(ctx: ProjectDataContext, compose: dict[str, Any]) -> int:
    """Fill `DataContext.catalog_offers` on every collection of `ctx`; returns the offer count."""
    by_dc = offers_by_dc(compose)
    total = 0
    for collection in ctx.collections:
        offers = by_dc.get(str(collection.data_collection_id), [])
        collection.catalog_offers = offers
        total += len(offers)
    return total


def component_event(
    planned: PlannedComponent,
    status: GeneratedComponentStatus,
    *,
    attempts: int = 1,
    error: str | None = None,
) -> GeneratedComponentEvent:
    """The ``component`` stream event of one planned component.

    `attempts` counts the fill calls the model was given; pass 0 for a
    component dropped before the fill loop could call it at all.
    """
    return GeneratedComponentEvent(
        tag=planned.tag,
        section=planned.section,
        component_type=planned.component_type,
        status=status,
        attempts=attempts,
        error=error,
    )


@dataclass
class FillTarget:
    """One planned component with the collection it binds and how it is filled."""

    planned: PlannedComponent
    ctx: DataContext | None
    mode: FillMode


def plan_to_targets(
    plan: DashboardPlan, contexts: dict[str, DataContext]
) -> tuple[list[FillTarget], list[GeneratedComponentEvent]]:
    """Bind every planned component to its collection and pick its fill mode.

    `contexts` is keyed by data collection tag. text needs no collection and
    is filled deterministically; advanced_viz is deterministic when the plan
    pinned a catalog offer (`use`) or a ranked kind (`viz_kind`) and goes to
    the model otherwise; everything else is an LLM fill. A data-bound
    component naming a collection outside `contexts` is dropped here (the
    plan normaliser only checks the tag is present), returned as a
    ``dropped`` event so the client still sees it.
    """
    targets: list[FillTarget] = []
    dropped: list[GeneratedComponentEvent] = []
    for planned in plan.components:
        if planned.component_type == "text":
            targets.append(FillTarget(planned, None, "text"))
            continue
        ctx = contexts.get(planned.data_collection_tag or "")
        if ctx is None:
            known = ", ".join(sorted(contexts)) or "(none)"
            dropped.append(
                component_event(
                    planned,
                    "dropped",
                    attempts=0,
                    error=(
                        f"data collection '{planned.data_collection_tag}' is not one of the "
                        f"project's table collections (available: {known})"
                    ),
                )
            )
            continue
        deterministic = planned.component_type == "advanced_viz" and bool(
            planned.use or planned.viz_kind
        )
        targets.append(FillTarget(planned, ctx, "advanced_viz" if deterministic else "llm"))
    return targets, dropped


def fill_text(planned: PlannedComponent, plan: DashboardPlan, *, first: bool) -> dict[str, Any]:
    """A planned text tile, written from the plan without an LLM call.

    The title is its grid section's name (the plan title when the section
    is unknown), the body the section's description; the first text tile of
    the dashboard falls back to the plan subtitle so the intro is not lost
    when the planner described no section.
    """
    spec = next((s for s in plan.grid_sections if s.name == planned.section), None)
    title = spec.name if spec else plan.title
    body = (spec.description if spec else None) or (plan.subtitle if first else None) or ""
    return {
        "tag": planned.tag,
        "component_type": "text",
        "title": title,
        "order": HEADER_ORDER,
        "body": body,
    }


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.casefold()).strip("-") or "section"


def section_headers(plan: DashboardPlan, components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One header text tile per grid section that holds a tile but no text yet.

    The planner is told the server writes each section's header from its
    description, so it plans none; the layout puts a text tile first in
    every grid section. Tags are ``<section-slug>-header``, made unique
    against the components already present.
    """
    # A filled component carries no `section` until the layout writes it; the
    # plan says where each tag goes.
    section_of = {c.tag: c.section for c in plan.components}
    taken = {str(c.get("tag") or "") for c in components}
    used: dict[str, set[str]] = {}
    for comp in components:
        section = str(comp.get("section") or section_of.get(str(comp.get("tag") or ""), ""))
        used.setdefault(section, set()).add(str(comp.get("component_type") or ""))
    headers: list[dict[str, Any]] = []
    first = not any(c.get("component_type") == "text" for c in components)
    for spec in plan.grid_sections:
        types = used.get(spec.name, set())
        if not types or "text" in types:
            continue
        base = f"{_slug(spec.name)}-header"
        tag, n = base, 1
        while tag in taken:
            n += 1
            tag = f"{base}-{n}"
        taken.add(tag)
        headers.append(
            {
                "tag": tag,
                "section": spec.name,
                "component_type": "text",
                "title": spec.name,
                "order": HEADER_ORDER,
                "body": spec.description or (plan.subtitle if first else None) or "",
            }
        )
        first = False
    return headers


def validate_component(component: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """One component dict through the CLI validator: (validated, None) or (None, error text).

    Dumped to YAML first so a deterministic candidate takes exactly the path
    an LLM answer takes (`component_yaml.validate_single`).
    """
    try:
        text = yaml.safe_dump(component, sort_keys=False, allow_unicode=True)
        return component_yaml.validate_single(text), None
    except (ValidationError, ValueError, yaml.YAMLError) as e:
        return None, component_yaml.format_validation_error_for_llm(e)


def bind_to_collection(
    component: dict[str, Any], planned: PlannedComponent, ctx: DataContext
) -> dict[str, Any]:
    """Pin the tags the plan decided and fill what the model tends to leave out.

    The model is told to copy the collection tags verbatim and mostly does;
    the plan's choice wins regardless, because a component bound to another
    collection would pass the offline validator and fail at render time. A
    card or filter without `column_type` gets it from the collection's
    columns so the lite compatibility check fires (as the suggestion flow
    does); an advanced_viz gets `config.viz_kind` mirrored from `viz_kind`.

    Raises `ValueError` when the answer names no `component_type` (any YAML
    mapping parses; only a component block is worth validating) or another
    type than planned: a card's fields relabelled as a figure would validate
    as an empty scatter, and the repair prompt can name the mismatch instead.
    """
    emitted = str(component.get("component_type") or "").strip().lower()
    if not emitted:
        raise ValueError(
            f"The answer is not a component block: it has no component_type "
            f"(expected '{planned.component_type}')"
        )
    if emitted != planned.component_type:
        raise ValueError(
            f"component_type must be '{planned.component_type}' (the plan's), got '{emitted}'"
        )
    component["tag"] = planned.tag
    component["component_type"] = planned.component_type
    component["workflow_tag"] = ctx.workflow_tag or ""
    component["data_collection_tag"] = ctx.data_collection_tag or ""
    component.pop("section", None)
    component.pop("layout", None)
    if planned.component_type in ("card", "interactive") and not component.get("column_type"):
        column = component.get("column_name")
        dtype = next((c.dtype for c in ctx.columns if c.name == column), None)
        column_type = column_type_for(dtype)
        if column_type:
            component["column_type"] = column_type
    if planned.component_type == "advanced_viz":
        config = component.get("config")
        if isinstance(config, dict) and component.get("viz_kind"):
            component["config"] = {"viz_kind": component["viz_kind"], **config}
    return component


def substance_error(component: dict[str, Any]) -> str | None:
    """Reject a validated component that would render nothing.

    The lite figure defaults to a scatter with no bindings, so a UI-mode
    figure without a single `dict_kwargs` column passes the validator and
    draws an empty plot; the repair prompt asks for the bindings instead.
    """
    if component.get("component_type") == "figure" and component.get("mode", "ui") != "code":
        if not (component.get("dict_kwargs") or component.get("figure_params")):
            return (
                "figure: dict_kwargs is empty; bind at least one column (x, y, color, ...) "
                "from DATASET SCHEMA"
            )
    return None


def schema_error(component: dict[str, Any], ctx: DataContext) -> str | None:
    """`check_against_schema` on one validated component, as repair-prompt text or None."""
    lite = validate_envelope({"title": "AI", "components": [component]})
    tag = ctx.data_collection_tag or ctx.data_collection_id
    findings = check_against_schema(lite, {tag: ctx})
    if not findings:
        return None
    return "Schema check failed:\n" + "\n".join(f"- {f['field']}: {f['message']}" for f in findings)


def _role_bindings(kind: str, suggestion: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    """config key -> column for every required role of `kind`, from the ranker's candidates."""
    try:
        specs = role_dtype_specs(kind)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001, an unknown kind
        return {}, f"viz_kind '{kind}' is not an advanced_viz kind"
    candidates = suggestion.get("role_candidates") or {}
    bindings: dict[str, str] = {}
    for role, spec in specs.items():
        if not spec.get("required"):
            continue
        columns = candidates.get(role) or []
        if not columns:
            return {}, f"viz_kind '{kind}': no column of the collection fills the role '{role}'"
        bindings[role_config_key(kind, role)] = str(columns[0])
    return bindings, None


def fill_advanced_viz(
    planned: PlannedComponent, ctx: DataContext
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    """An advanced_viz from a catalog offer or a ranked kind, no LLM call.

    Returns ``(component, warnings, error)``. With `use`, the component is
    the bare ``use:`` handle (plus the offer's kind when the handle is an
    output id) validated through the lite model, which expands it into
    ``viz_kind`` + ``config`` from the catalog; when that fails and the plan
    also named a `viz_kind`, the ranked path is tried and the offer is
    dropped with a warning. The ranked path binds every required role to
    the ranker's first candidate under the key the renderer reads
    (`role_config_key`).
    """
    warnings: list[str] = []
    tag = ctx.data_collection_tag or ctx.data_collection_id
    base: dict[str, Any] = {
        "tag": planned.tag,
        "component_type": "advanced_viz",
        "workflow_tag": ctx.workflow_tag or "",
        "data_collection_tag": ctx.data_collection_tag or "",
    }

    if planned.use:
        offer = next((o for o in ctx.catalog_offers if offer_use_id(o) == planned.use), None)
        kind = (offer or {}).get("viz_kind") or planned.viz_kind
        candidate = {**base, "use": planned.use}
        if offer and offer.get("title"):
            candidate["title"] = str(offer["title"])
        if kind:
            candidate["viz_kind"] = kind
        validated, error = validate_component(candidate)
        if validated is not None:
            return validated, warnings, None
        if offer is None:
            error = f"'{planned.use}' is not one of the catalog offers of '{tag}'"
        if not planned.viz_kind:
            return None, warnings, f"catalog offer '{planned.use}' could not be used: {error}"
        warnings.append(
            f"'{planned.tag}': catalog offer '{planned.use}' could not be used ({error}); "
            f"built a {planned.viz_kind} from the ranked bindings instead"
        )

    kind = planned.viz_kind or ""
    suggestion = next((s for s in ctx.viz_suggestions if s.get("viz_kind") == kind), None)
    if suggestion is None:
        return None, warnings, f"viz_kind '{kind}' is not a recommended kind for '{tag}'"
    bindings, error = _role_bindings(kind, suggestion)
    if error:
        return None, warnings, error
    candidate = {
        **base,
        "title": f"{viz_kind_label(kind)} of {tag}",
        "viz_kind": kind,
        "config": {"viz_kind": kind, **bindings},
    }
    validated, error = validate_component(candidate)
    if validated is None:
        return None, warnings, f"ranked {kind} did not validate: {error}"
    return validated, warnings, None


def _slim(component: dict[str, Any]) -> dict[str, Any]:
    """Drop the runtime uuid and empty values before the component goes into the envelope."""
    return {k: v for k, v in component.items() if k != "index" and v is not None and v != ""}


_TAG_IN_MESSAGE_RE = re.compile(r"\[([^\]]+)\]")


def offending_tags(exc: BaseException, components: list[dict[str, Any]]) -> set[str]:
    """Tags an envelope validation error points at, by index (`components.<i>`) or ``[tag]`` prefix."""
    tags: set[str] = set()
    if not isinstance(exc, ValidationError):
        return tags
    for err in exc.errors():
        loc = err.get("loc", ())
        if len(loc) >= 2 and loc[0] == "components" and isinstance(loc[1], int):
            if loc[1] < len(components):
                tags.add(str(components[loc[1]].get("tag") or ""))
        for match in _TAG_IN_MESSAGE_RE.findall(str(err.get("msg", ""))):
            if any(c.get("tag") == match for c in components):
                tags.add(match)
    tags.discard("")
    return tags


def _envelope_error(exc: BaseException) -> str:
    """The stream's ``error`` detail for an envelope that did not validate."""
    return (
        "The assembled dashboard did not validate: "
        f"{component_yaml.format_validation_error_for_llm(exc)}"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


# ---------------------------------------------------------------------------
# Gates (called by the route before the stream starts)
# ---------------------------------------------------------------------------


def _project_doc(project_oid: ObjectId) -> dict[str, Any] | None:
    return projects_collection.find_one({"_id": project_oid})


def _project_dc_ids(project_doc: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for wf in project_doc.get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        for dc in wf.get("data_collections") or []:
            if isinstance(dc, dict) and dc.get("_id") is not None:
                ids.add(str(dc["_id"]))
    return ids


def gate_generate_request(body: GenerateDashboardRequest, user: Any) -> dict[str, Any]:
    """The HTTP-status gates of `/ai/generate-dashboard`; returns the project document.

    404 when the feature flag is off, 403 in public mode, 403 for an
    anonymous user outside single-user mode (the import route's rule), 400
    on a malformed project id, 404 for an unknown project, 403 without
    editor permission, 400 when a requested data collection is not in the
    project. The document is returned so the stream does not load it again.
    """
    if not settings.ai.generate_dashboard_enabled:
        raise HTTPException(status_code=404, detail="Dashboard generation is not enabled.")
    if settings.auth.is_public_mode:
        raise HTTPException(
            status_code=403, detail="Dashboard generation is disabled in public/demo mode."
        )
    if getattr(user, "is_anonymous", False) and not settings.auth.is_single_user_mode:
        raise HTTPException(
            status_code=403,
            detail="Anonymous users cannot generate dashboards. Please login to continue.",
        )
    try:
        project_oid = ObjectId(body.project_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid project_id: {e}") from e
    project = _project_doc(project_oid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    if not check_project_permission(project_oid, user, "editor"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to create dashboards in this project.",
        )
    known = _project_dc_ids(project)
    unknown = [d for d in body.data_collection_ids if d not in known]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"data_collection_id(s) not in this project: {', '.join(unknown)}",
        )
    return project


def promote_dashboard(dashboard_id: str, user: Any) -> PromoteResponse:
    """Flip a draft's ``ai_generation.status`` to ``promoted``; sync (pymongo).

    404 when the dashboard does not exist or carries no ``ai_generation``
    stamp, 403 without editor permission (`check_dashboard_mutation_permission`,
    so a dashboard owner without a project role can still promote their draft).
    """
    try:
        oid = ObjectId(dashboard_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid dashboard_id: {e}") from e
    doc = dashboards_collection.find_one(
        {"dashboard_id": oid}, {"project_id": 1, "permissions": 1, "ai_generation": 1}
    )
    if not doc or not doc.get("ai_generation"):
        raise HTTPException(status_code=404, detail="No AI-generated draft with this id.")
    if not check_dashboard_mutation_permission(doc, user, "editor"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to promote this dashboard."
        )
    dashboards_collection.update_one(
        {"dashboard_id": oid}, {"$set": {"ai_generation.status": "promoted"}}
    )
    return PromoteResponse(dashboard_id=dashboard_id, status="promoted")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


class _Abort(Exception):
    """A run that cannot go on; its message is the ``error`` event's detail.

    Raised anywhere in `_generate` and turned into ``error`` + ``done`` by
    `run_generation`, so the terminal frames are written in one place.
    """


class _Generation:
    """State of one run: the record, the budget, the filled components, the warnings."""

    def __init__(
        self,
        body: GenerateDashboardRequest,
        user: Any,
        *,
        user_api_key: str | None,
        project_doc: dict[str, Any] | None,
        frame: Callable[[StreamEvent], bytes],
    ) -> None:
        self.body = body
        self.user = user
        self.user_api_key = user_api_key
        self.project_doc = project_doc
        self.frame = frame
        self.model = llm_client.get_default_model()
        self.run = generations.new_run(body.project_id, body.prompt, self.model)
        self.budget = Budget(
            max_tokens=settings.ai.generate_max_tokens_total,
            max_seconds=float(settings.ai.generate_max_wall_clock_s),
            max_steps=_max_steps(settings.ai.generate_max_components),
        )
        self.warnings: list[str] = []
        self.plan: DashboardPlan | None = None
        self.contexts: dict[str, DataContext] = {}
        self.components: list[dict[str, Any]] = []
        self.dropped: list[str] = []
        self.filled_tags: list[str] = []

    # -- frames -------------------------------------------------------------

    def status(self, message: str) -> bytes:
        return self.frame(StreamEvent(type="status", data={"message": message}))

    def budget_frame(self) -> bytes:
        return self.frame(StreamEvent(type="budget", data=self.budget.event()))

    def error(self, detail: str) -> bytes:
        return self.frame(StreamEvent(type="error", data={"detail": detail}))

    def done(self) -> bytes:
        return self.frame(StreamEvent(type="done"))

    def component_frame(self, event: GeneratedComponentEvent) -> bytes:
        return self.frame(StreamEvent(type="component", data=event.model_dump(mode="json")))

    # -- run record ---------------------------------------------------------

    def _sync_record(self) -> None:
        self.run.warnings = list(self.warnings)
        self.run.budget_spent = self.budget.spent()

    async def save(self) -> None:
        self._sync_record()
        await asyncio.to_thread(generations.save, self.run)

    def fail(self, detail: str) -> None:
        self.run.status = "failed"
        self.warnings.append(detail)

    def finish(self) -> None:
        """Final save, sync so it also runs while the generator is being closed."""
        if self.run.status == "running":
            self.run.status = "cancelled"
        self._sync_record()
        try:
            generations.save(self.run)
        except Exception:  # noqa: BLE001, the record must never mask the stream's outcome
            logger.exception("generate-dashboard: could not save run %s", self.run.id)

    # -- LLM ----------------------------------------------------------------

    async def complete(self, messages: list[dict[str, Any]]) -> llm_client.Completion:
        completion = await asyncio.to_thread(
            llm_client.completion_with_usage, messages, user_api_key=self.user_api_key
        )
        self.budget.charge(completion)
        return completion

    # -- steps --------------------------------------------------------------

    def record_component(self, event: GeneratedComponentEvent) -> None:
        self.run.components.append(event.model_dump(mode="json"))
        if event.status == "dropped":
            self.dropped.append(event.tag)

    def accept(self, planned: PlannedComponent, component: dict[str, Any]) -> None:
        self.components.append(_slim(component))
        self.filled_tags.append(planned.tag)

    async def try_plan(
        self, messages: list[dict[str, Any]]
    ) -> tuple[DashboardPlan | None, list[FillTarget], str | None, str]:
        """One planning call: (plan, targets, None, raw) or (None, [], error, raw)."""
        completion = await self.complete(messages)
        raw = completion.content
        try:
            parsed = routing._parse_json_lenient(raw)
            plan = parse_plan(parsed)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            return None, [], component_yaml.format_validation_error_for_llm(e), raw
        plan, plan_warnings = normalize_plan(
            plan,
            max_components=settings.ai.generate_max_components,
            max_sections=settings.ai.generate_max_sections,
        )
        if self.body.title and self.body.title.strip():
            plan = plan.model_copy(update={"title": self.body.title.strip()})
        targets, unknown = plan_to_targets(plan, self.contexts)
        if not targets:
            notes = plan_warnings + [str(e.error) for e in unknown]
            detail = "The plan has no usable component."
            if notes:
                detail += " " + " ".join(f"{n}." for n in notes)
            return None, [], detail, raw
        self.warnings.extend(plan_warnings)
        for event in unknown:
            self.record_component(event)
        return plan, targets, None, raw

    async def fill_llm(
        self, target: FillTarget
    ) -> tuple[dict[str, Any] | None, GeneratedComponentEvent, list[bytes]]:
        """The model fills one component; validated and repaired like `/ai/component-from-prompt`.

        Returns the validated component (None when dropped), its event and
        the budget frames to emit (one per LLM call).
        """
        planned, ctx = target.planned, target.ctx
        assert ctx is not None and self.plan is not None
        frames: list[bytes] = []
        tag = ctx.data_collection_tag or ctx.data_collection_id
        intent = planned.intent or f"A {planned.component_type} on {tag}."
        prompt = prompts.component_fill_prompt(
            intent,
            dashboard_title=self.plan.title,
            section=planned.section,
            tag=planned.tag,
            siblings=list(self.filled_tags),
            use=planned.use,
            viz_kind=planned.viz_kind,
        )
        messages = prompts.component_from_prompt_messages(
            ctx, prompt, component_type=planned.component_type
        )
        max_attempts = 1 + settings.ai.generate_max_repairs_per_component
        last_error = "(unknown)"
        attempts = 0
        for attempt in range(1, max_attempts + 1):
            if attempt > 1 and self.budget.exhausted():
                last_error = f"{last_error} (no budget left to repair)"
                break
            attempts = attempt
            try:
                completion = await self.complete(messages)
            except Exception as e:  # noqa: BLE001, a provider failure drops the tile, not the run
                last_error = f"LLM error: {e}"
                logger.warning("generate-dashboard: %s on '%s'", last_error, planned.tag)
                break
            frames.append(self.budget_frame())
            raw = completion.content
            component, error = await asyncio.to_thread(self._validate_answer, raw, planned, ctx)
            if component is not None and error is None:
                status = "ok" if attempt == 1 else "repaired"
                return component, component_event(planned, status, attempts=attempt), frames
            last_error = error or "(unknown)"
            logger.warning(
                "generate-dashboard: '%s' attempt %d failed: %s", planned.tag, attempt, last_error
            )
            messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": f"{last_error}\n\nRe-emit the corrected YAML only: no prose, no fences.",
                },
            ]
        return (
            None,
            component_event(planned, "dropped", attempts=attempts, error=last_error),
            frames,
        )

    @staticmethod
    def _validate_answer(
        raw: str, planned: PlannedComponent, ctx: DataContext
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Parse, bind, validate offline, then check against the collection's columns."""
        try:
            component = component_yaml._parse_component_yaml(raw)
            bind_to_collection(component, planned, ctx)
        except ValueError as e:
            return None, component_yaml.format_validation_error_for_llm(e)
        validated, error = validate_component(component)
        if validated is None:
            return None, error
        error = substance_error(validated) or schema_error(validated, ctx)
        if error:
            return None, error
        return validated, None

    def envelope(self, title: str) -> dict[str, Any]:
        assert self.plan is not None
        components, filter_sections, grid_sections = layout_dashboard(
            self.plan, self.components + section_headers(self.plan, self.components)
        )
        lite: dict[str, Any] = {"title": title}
        if self.plan.subtitle:
            lite["subtitle"] = self.plan.subtitle
        lite["filter_sections"] = filter_sections
        lite["grid_sections"] = grid_sections
        lite["components"] = components
        return lite

    def has_data_bound(self) -> bool:
        return any(c.get("component_type") != "text" for c in self.components)

    def generation_info(self) -> dict[str, Any]:
        return {
            "status": "draft",
            "model": self.model,
            "prompt": self.body.prompt,
            "generated_at": _now_iso(),
            "run_id": self.run.id,
            "warnings": list(self.warnings),
        }


async def run_generation(
    body: GenerateDashboardRequest,
    current_user: Any,
    *,
    user_api_key: str | None,
    project_doc: dict[str, Any] | None = None,
    frame: Callable[[StreamEvent], bytes] | None = None,
) -> AsyncIterator[bytes]:
    """Drive one whole-dashboard generation and yield its SSE frames.

    `project_doc` is the document the route already loaded for its gates
    (loaded here when absent, e.g. when driven directly). `frame` formats
    one `StreamEvent`; it defaults to the routes' ``_sse``.
    """
    gen = _Generation(
        body,
        current_user,
        user_api_key=user_api_key,
        project_doc=project_doc,
        frame=frame or _sse,
    )
    try:
        async for chunk in _generate(gen):
            yield chunk
    except _Abort as e:
        gen.fail(str(e))
        yield gen.error(str(e))
        yield gen.done()
    except Exception:  # noqa: BLE001, never strand the stream, never leak internals
        logger.exception("generate-dashboard: run %s failed unexpectedly", gen.run.id)
        gen.fail("The generation failed unexpectedly; see the server log.")
        yield gen.error("The generation failed unexpectedly.")
        yield gen.done()
    finally:
        gen.finish()


async def _generate(gen: _Generation) -> AsyncIterator[bytes]:
    """The pipeline itself; `_Abort` anywhere here ends the stream with `error`."""
    body = gen.body

    # 1. Inventory ---------------------------------------------------------
    yield gen.status("reading project")
    try:
        ctx, ctx_warnings = await build_project_data_context(
            body.project_id,
            gen.user,
            body.data_collection_ids or None,
            max_collections=settings.ai.generate_max_collections,
        )
    except HTTPException as e:
        raise _Abort(str(e.detail)) from e
    gen.warnings.extend(ctx_warnings)
    if not ctx.collections:
        raise _Abort("The project has no table data collection to build a dashboard on.")
    gen.contexts = {c.data_collection_tag or c.data_collection_id: c for c in ctx.collections}

    yield gen.status("inventorying")
    project_doc = gen.project_doc
    if project_doc is None:
        try:
            project_doc = await asyncio.to_thread(_project_doc, ObjectId(body.project_id))
        except Exception as e:  # noqa: BLE001
            logger.warning("generate-dashboard: project document unavailable: %s", e)
            project_doc = None
    if project_doc:
        try:
            compose = await asyncio.to_thread(compose_offers_for_project, project_doc)
            attach_catalog_offers(ctx, compose)
        except Exception as e:  # noqa: BLE001, offers are an extra, not a requirement
            logger.warning("generate-dashboard: catalog offers unavailable: %s", e)
            gen.warnings.append("Catalog offers could not be read; planning without them.")

    # 2. Plan --------------------------------------------------------------
    yield gen.status("planning")
    messages = prompts.dashboard_plan_messages(
        ctx,
        body.prompt,
        body.title,
        max_components=settings.ai.generate_max_components,
        max_sections=settings.ai.generate_max_sections,
        warnings=gen.warnings,
    )
    plan: DashboardPlan | None = None
    targets: list[FillTarget] = []
    plan_error: str | None = None
    for _ in range(PLAN_ATTEMPTS):
        try:
            plan, targets, plan_error, raw = await gen.try_plan(messages)
        except Exception as e:  # noqa: BLE001
            raise _Abort(f"LLM error: {e}") from e
        yield gen.budget_frame()
        if plan is not None:
            break
        messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    f"{plan_error}\n\nRespond again with the corrected JSON plan only, "
                    "no prose, no fences."
                ),
            },
        ]
    if plan is None:
        raise _Abort(f"The planner did not produce a usable plan: {plan_error or '(unknown)'}")
    gen.plan = plan
    gen.budget.max_steps = _max_steps(len(targets))
    gen.run.plan = plan.model_dump(mode="json")
    yield gen.frame(StreamEvent(type="plan", data={"plan": gen.run.plan}))
    for event in gen.run.components:
        # Components the plan bound to an unknown collection: dropped before any fill.
        yield gen.frame(StreamEvent(type="component", data=event))
    await gen.save()

    # 3. Fill --------------------------------------------------------------
    yield gen.status("filling")
    first_text = True
    for target in targets:
        planned = target.planned
        if target.mode == "text":
            gen.accept(planned, fill_text(planned, plan, first=first_text))
            first_text = False
            event = component_event(planned, "ok")
        elif target.mode == "advanced_viz":
            assert target.ctx is not None
            component, fill_warnings, error = await asyncio.to_thread(
                fill_advanced_viz, planned, target.ctx
            )
            gen.warnings.extend(fill_warnings)
            if component is None:
                event = component_event(planned, "dropped", attempts=0, error=error or "(unknown)")
            else:
                gen.accept(planned, component)
                event = component_event(planned, "ok")
        elif gen.budget.exhausted():
            # Only the LLM fills below spend budget; the two branches above
            # cost nothing and always run.
            event = component_event(planned, "dropped", attempts=0, error="budget")
        else:
            component, event, frames = await gen.fill_llm(target)
            for chunk in frames:
                yield chunk
            if component is not None:
                gen.accept(planned, component)
        gen.record_component(event)
        yield gen.component_frame(event)
        await gen.save()

    if gen.dropped:
        gen.warnings.append(
            f"{len(gen.dropped)} planned component(s) were left out: {', '.join(gen.dropped)}"
        )
    if not gen.has_data_bound():
        raise _Abort("no component could be generated")

    # 4. Layout + envelope ---------------------------------------------------
    yield gen.status("laying out")
    title = pick_title(body.title, plan.title)
    lite_dict = gen.envelope(title)
    try:
        lite = await asyncio.to_thread(validate_envelope, lite_dict)
    except (ValidationError, ValueError) as e:
        # One retry without the components the error points at; an error that
        # names none, or that leaves nothing data-bound, ends the run.
        culprits = offending_tags(e, lite_dict["components"])
        if not culprits:
            raise _Abort(_envelope_error(e)) from e
        gen.warnings.append(
            f"Dropped {', '.join(sorted(culprits))}: the assembled dashboard did not validate"
        )
        gen.components = [c for c in gen.components if c.get("tag") not in culprits]
        gen.dropped.extend(sorted(culprits))
        if not gen.has_data_bound():
            raise _Abort("no component could be generated") from e
        lite_dict = gen.envelope(title)
        try:
            lite = await asyncio.to_thread(validate_envelope, lite_dict)
        except (ValidationError, ValueError) as e2:
            raise _Abort(_envelope_error(e2)) from e2

    # 5. Persist ------------------------------------------------------------
    yield gen.status("saving")
    project_oid = ObjectId(body.project_id)
    for draft in range(1, MAX_TITLE_DRAFTS + 1):
        title = pick_title(body.title, plan.title, draft=draft)
        lite = lite.model_copy(update={"title": title})
        lite_dict["title"] = title
        try:
            payload = await asyncio.to_thread(
                _persist_lite_dashboard,
                lite,
                project_oid,
                gen.user,
                overwrite=body.overwrite,
                extra_fields={"ai_generation": gen.generation_info()},
            )
            break
        except HTTPException as e:
            if e.status_code == 409 and not body.title and draft < MAX_TITLE_DRAFTS:
                gen.warnings.append(
                    f"A dashboard titled '{title}' already exists; trying "
                    f"'{pick_title(None, plan.title, draft=draft + 1)}'"
                )
                continue
            raise _Abort("title exists" if e.status_code == 409 else str(e.detail)) from e
    else:  # pragma: no cover, the last draft raises instead of continuing
        raise _Abort("title exists")

    dashboard_yaml = yaml.safe_dump(lite_dict, sort_keys=False, allow_unicode=True)
    gen.run.dashboard_id = str(payload.get("dashboard_id") or "")
    gen.run.yaml = dashboard_yaml
    gen.run.status = "complete"
    event = GeneratedDashboardEvent(
        dashboard_id=gen.run.dashboard_id,
        title=str(payload.get("title") or title),
        project_id=body.project_id,
        yaml=dashboard_yaml,
        warnings=list(gen.warnings),
        dropped=list(gen.dropped),
    )
    yield gen.frame(StreamEvent(type="dashboard", data=event.model_dump(mode="json")))
    yield gen.done()
