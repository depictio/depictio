"""Whole-dashboard generation: plan, fill, validate, lay out, persist, review.

Backs ``POST /ai/generate-dashboard`` (see `run_generation`), the promote
route (`promote_dashboard`) and the review pass over a draft: the two
regenerate streams (`run_regeneration`), `review_dashboard` and
`list_generations`. The stream is one SSE frame per event, in the order the
React panel consumes them:

  status* -> budget -> plan -> status -> (budget*, component)* -> status ->
  component* -> status* -> dashboard -> done

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
4. check: every filled component is probed through `dashboard_probe`
   (`_Generation.check_render`) before the draft exists. The offline
   validator cannot see a binding that only fails against the data, so a
   component that would 500 in the viewer is dropped here with a
   ``render: `` error rather than saved; a run with nothing data-bound left
   ends in ``error``, like an empty fill;
5. layout: `layout_dashboard`, then `validate_envelope` once;
6. persist: `_persist_lite_dashboard` with the ``ai_generation`` draft stamp;
   an LLM-chosen title that collides gets an ``(AI draft N)`` suffix, a
   client-pinned one is a 409 reported inside the stream.

Steps 2 and 3 can also be paid for separately, which is what lets a plan be
approved before anything is filled. `GenerateDashboardRequest.plan_only`
runs steps 1 and 2 and stops on the plan event, saving no dashboard and
writing no draft; the run record keeps the plan, and its budget covers the
planning call alone. `GenerateDashboardRequest.plan` is the other half: the
plan the user approved comes back in the request body, the planning call is
skipped, and the run goes straight to step 3. That plan is client input like
any other, so `_Generation.adopt_plan` puts it through the same `parse_plan`
and `normalize_plan` a model answer goes through and re-checks every
collection it names against the ones the run was given; it is then re-emitted
as a ``plan`` event, so the client's progress panel reads both phases the
same way.

Reviewing the draft afterwards reuses steps 3 and 5 for one tile or one
section (`run_regeneration`): the plan entry comes from the run record (or
is reconstructed from the stored tile when the run is gone), the fill and
repair path is the same coroutine (`fill_component`), and the result is
written back into ``stored_metadata`` in place, keeping the tile's id and
its box. Each generated tile carries an `ai_source` stamp naming its
generation tag, because `to_full` rebuilds every other key: that stamp is
what lets a tile be found, regenerated and marked reviewed once the stream
is gone.

The run record (`generations`) is saved after the plan, after every
component and in the generator's ``finally``, so a cancelled or crashed run
stays inspectable. Every collaborator that touches Mongo or another
endpoint module is a module attribute here (``projects_collection``,
``dashboards_collection``, ``build_project_data_context``,
``compose_offers_for_project``, ``check_project_permission``,
``check_dashboard_mutation_permission``, ``_persist_lite_dashboard``,
``probe_component``) so the route tests can substitute them without a
database. The ones that live in the big endpoint modules are lazy wrappers:
importing ``dashboards_endpoints.routes`` at module load would pull the whole
dashboard API in behind the AI package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
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
from depictio.api.v1.endpoints.ai_endpoints.component_style import sanitize_style
from depictio.api.v1.endpoints.ai_endpoints.context import (
    DataContext,
    ProjectDataContext,
    build_project_data_context,
    offer_use_id,
)
from depictio.api.v1.endpoints.ai_endpoints.dashboard_layout import (
    _layout_filter_section,
    _layout_grid_section,
    layout_dashboard,
)
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
    GenerationsResponse,
    GenerationSummary,
    PromoteResponse,
    RegeneratedEvent,
    ReviewRequest,
    ReviewResponse,
    StreamEvent,
)
from depictio.api.v1.endpoints.ai_endpoints.suggest import column_type_for, viz_kind_label
from depictio.models.components.advanced_viz.catalog import role_config_key
from depictio.models.components.advanced_viz.schemas import role_dtype_specs
from depictio.models.timestamps import utc_now_str

logger = logging.getLogger(__name__)

# The planning call and its single retry with the error appended.
PLAN_ATTEMPTS = 2
# " (AI draft 2)" ... " (AI draft 5)": how many suffixed titles are tried
# when the planner's title collides with an existing dashboard.
MAX_TITLE_DRAFTS = 5
# Header text tiles are H3 like the seeded dashboards' section headers.
HEADER_ORDER = 3
# The advanced_viz config keys that hold a *list* of columns, or a setting
# rather than a column: `role_config_key` maps the list-typed roles of
# sankey, sunburst and complex_heatmap onto these. They are the exception to
# the one-column-one-role rule `_role_bindings` enforces.
MULTI_COLUMN_CONFIG_KEYS: frozenset[str] = frozenset(
    {"rank_cols", "step_cols", "value_columns", "row_annotation_cols", "compute_method"}
)
# Said in the run's warnings when it stopped at the plan: the record's status
# is `complete` (it did all it was asked) with no dashboard and no YAML, and
# this is what tells the two apart at a glance.
PLAN_ONLY_NOTE = "Plan-only run: the plan was returned and nothing was filled or saved."

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


def resolve_workflow_tags(component: dict[str, Any], project_id: Any) -> None:
    """`dashboards_endpoints.routes._resolve_workflow_tags`, imported on first use."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _resolve_workflow_tags as resolve,
    )

    resolve(component, project_id=project_id)


def regenerate_component_fields(component: dict[str, Any]) -> None:
    """`dashboards_endpoints.routes._regenerate_component_fields`, imported on first use."""
    from depictio.api.v1.endpoints.dashboards_endpoints.routes import (
        _regenerate_component_fields as regenerate,
    )

    regenerate(component)


def probe_component(component: dict[str, Any], ctx: Any | None, user: Any) -> str | None:
    """`dashboard_probe.probe_component`, imported on first use.

    None when the component renders (or when its type has no cheap probe),
    a short human-readable reason otherwise. Lazy like the collaborators
    above: the probe reaches into the advanced_viz compute endpoint, which
    has no business being imported behind a dashboard that never generates.
    """
    from depictio.api.v1.endpoints.ai_endpoints import dashboard_probe

    return dashboard_probe.probe_component(component, ctx, user)


def _sse(event: StreamEvent) -> bytes:
    """`routes._sse`: same framing as every other AI stream (lazy: routes imports this module)."""
    from depictio.api.v1.endpoints.ai_endpoints.routes import _sse as frame

    return frame(event)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@dataclass
class Budget:
    """Token, wall-clock, call and money accounting of one run.

    `event()` is the payload of the ``budget`` stream event, in the shape the
    analysis flow already emits so the React panel reads both the same way.
    A cached completion is not charged (it cost nothing) but still counts as
    a step.

    `cost_usd` is what the provider said it billed, summed over the calls
    that reported a figure at all (`CompletionUsage.cost_usd`). It stays
    None until one does, which is why it is not a plain 0.0: nothing
    reported is not the same claim as nothing spent. Only the tokens and
    the clock gate the run; the cost is reported, never enforced.
    """

    max_tokens: int
    max_seconds: float
    max_steps: int
    started: float = field(default_factory=time.monotonic)
    tokens_used: int = 0
    steps_used: int = 0
    cost_usd: float | None = None

    def charge(self, completion: llm_client.Completion) -> None:
        self.steps_used += 1
        if not completion.cached:
            self.tokens_used += completion.usage.total_tokens
            cost = completion.usage.cost_usd
            if cost is not None:
                self.cost_usd = (self.cost_usd or 0.0) + cost

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
            "cost_usd": self.cost_usd,
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_seconds": self.max_seconds,
        }

    def spent(self) -> BudgetSpent:
        return BudgetSpent(
            steps=self.steps_used,
            tokens=self.tokens_used,
            seconds=round(self.seconds, 1),
            cost_usd=self.cost_usd,
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


def ai_source_stamp(tag: str, prompt: str = "") -> dict[str, str]:
    """Per-tile provenance, in the shape the builder already writes (`{flow, prompt}`).

    `to_full` copies `catalog_source`, `use` and `ai_source` and rebuilds
    every other key of a stored component, so `ai_source` is the only place
    a generation tag survives into ``stored_metadata``. Without it a draft
    could not be reviewed tile by tile after the stream is gone: the plan
    speaks tags, the document speaks uuids.
    """
    stamp = {"flow": "generate", "tag": tag}
    if prompt:
        stamp["prompt"] = prompt
    return stamp


def generation_tag(component: dict[str, Any]) -> str:
    """The generation tag of one stored (or lite) component; ``""`` when it carries none.

    Reads the `ai_source` stamp first and falls back to a lite component's
    own `tag`, so the helper works on both sides of `to_full`.
    """
    source = component.get("ai_source")
    tag = source.get("tag") if isinstance(source, dict) else None
    return str(tag or component.get("tag") or "")


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


def render_drop_event(
    component: dict[str, Any], planned: PlannedComponent | None, error: str
) -> GeneratedComponentEvent:
    """The ``component`` event of a filled tile the render check dropped.

    The error is prefixed ``render: `` so a client can tell the two kinds of
    drop apart: a tile that never validated, and a tile that validated,
    was filled, and then would not draw. `attempts` is 0 the way every drop
    that cost no fill call is 0. The plan entry names the section; a tile
    whose entry cannot be found still gets an event, written from the tile.
    """
    detail = f"render: {error}"
    if planned is not None:
        return component_event(planned, "dropped", attempts=0, error=detail)
    return GeneratedComponentEvent(  # pragma: no cover, every filled tile has its entry
        tag=str(component.get("tag") or ""),
        section=str(component.get("section") or ""),
        component_type=component.get("component_type"),
        status="dropped",
        attempts=0,
        error=detail,
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


def unknown_collection_tags(plan: DashboardPlan, contexts: dict[str, DataContext]) -> list[str]:
    """The data collection tags `plan` names that this run was not given, sorted and unique.

    The check `plan_to_targets` makes per component, asked of the plan as a
    whole: the one-shot run drops such a component and carries on, but a
    plan handed back by the client is only trustworthy as far as it is
    checked, so naming a collection outside the run's subset ends it.
    """
    return sorted(
        {
            str(c.data_collection_tag or "")
            for c in plan.components
            if c.component_type != "text" and (c.data_collection_tag or "") not in contexts
        }
    )


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
                "ai_source": ai_source_stamp(tag),
            }
        )
        first = False
    return headers


def section_rationales(plan: DashboardPlan | None) -> list[dict[str, Any]]:
    """The planner's reason for each section, filter panel first then the grid.

    `AISectionRationale` rows in plan order, stamped into the draft so the
    review panel can say why a section is there. The section header text
    (`description`) says what the section shows; this says why it was chosen,
    and nothing renders it into the dashboard. A section the planner gave no
    reason for is skipped rather than carried as an empty row: an empty
    rationale explains less than no entry at all.
    """
    if plan is None:
        return []
    rows: list[dict[str, Any]] = []
    for kind, sections in (("filter", plan.filter_sections), ("grid", plan.grid_sections)):
        for spec in sections:
            rationale = (spec.rationale or "").strip()
            if rationale:
                rows.append({"name": spec.name, "kind": kind, "rationale": rationale})
    return rows


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


def _require_planned_type(component: dict[str, Any], planned: PlannedComponent) -> None:
    """Raise `ValueError` unless the answer is a component block of the planned type.

    Any YAML mapping parses, so an answer with no `component_type` is not a
    component at all; another type than planned is worse than useless (a
    card's fields relabelled as a figure validate as an empty scatter), and
    the repair prompt can name the mismatch instead.
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


def bind_standalone(component: dict[str, Any], planned: PlannedComponent) -> dict[str, Any]:
    """`bind_to_collection` for a tile that binds no collection (text).

    Same type check and the same pinned tag; the collection tags are cleared
    instead of pinned, because a text tile that carried one would be exported
    without it anyway (`DashboardDataLite.from_full` blanks both for text)
    and re-imported as a component the resolver cannot place.
    """
    _require_planned_type(component, planned)
    component["tag"] = planned.tag
    component["component_type"] = planned.component_type
    component["workflow_tag"] = ""
    component["data_collection_tag"] = ""
    component.pop("section", None)
    component.pop("layout", None)
    return component


def bind_to_collection(
    component: dict[str, Any], planned: PlannedComponent, ctx: DataContext
) -> dict[str, Any]:
    """Pin the tags the plan decided and fill what the model tends to leave out.

    The model is told to copy the collection tags verbatim and mostly does;
    the plan's choice wins regardless, because a component bound to another
    collection would pass the offline validator and fail at render time. A
    card or filter without `column_type` gets it from the collection's
    columns so the lite compatibility check fires (as the suggestion flow
    does); an advanced_viz gets `config.viz_kind` mirrored from `viz_kind`;
    a filter takes the plan's `group`, which is a layout decision the plan
    made across the whole section and the fill call cannot see.

    Raises `ValueError` (through `_require_planned_type`) when the answer is
    not a component block of the planned type.
    """
    _require_planned_type(component, planned)
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
    if planned.component_type == "interactive":
        # Absent from the plan, whatever the model grouped it with stands: it
        # saw the section's other filters in its dashboard context.
        if planned.group:
            component["group"] = planned.group
    if planned.component_type == "advanced_viz":
        config = component.get("config")
        if isinstance(config, dict) and component.get("viz_kind"):
            component["config"] = {"viz_kind": component["viz_kind"], **config}
    # An icon the bundled subset does not carry renders as a blank box, so the
    # decorations are held to the pickers' own lists (see component_style).
    sanitize_style(component)
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
    """config key -> column for every required role of `kind`, from the ranker's candidates.

    Roles are bound in the order `role_dtype_specs` lists them, each to its
    first candidate column that no other required role has taken. The
    ranker offers the same column to several roles whenever their accepted
    dtypes overlap (on a numeric-only collection a `rarefaction` took the
    same float column for `depth` and `metric`), and a column bound twice
    reaches `/advanced_viz/data` twice: Polars rejects the duplicate with a
    `ComputeError` and the tile 500s in the viewer. A role whose candidates
    are all taken fails the binding, so the component is dropped with a
    reason the stream can show rather than saved broken.

    List-typed roles are exempt: `rank_cols`, `step_cols` and friends
    (`role_config_key`) carry several columns on purpose and may repeat
    what a scalar role bound.
    """
    try:
        specs = role_dtype_specs(kind)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001, an unknown kind
        return {}, f"viz_kind '{kind}' is not an advanced_viz kind"
    candidates = suggestion.get("role_candidates") or {}
    bindings: dict[str, str] = {}
    taken: set[str] = set()
    for role, spec in specs.items():
        if not spec.get("required"):
            continue
        columns = [str(c) for c in (candidates.get(role) or [])]
        if not columns:
            return {}, f"viz_kind '{kind}': no column of the collection fills the role '{role}'"
        key = role_config_key(kind, role)
        if key in MULTI_COLUMN_CONFIG_KEYS:
            bindings[key] = columns[0]
            continue
        free = next((c for c in columns if c not in taken), None)
        if free is None:
            return {}, (
                f"viz_kind '{kind}': every column that fills the role '{role}' "
                f"({', '.join(columns)}) is already bound to another role"
            )
        bindings[key] = free
        taken.add(free)
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
# One component, filled by the model (shared by the run and the regenerates)
# ---------------------------------------------------------------------------


def validate_answer(
    raw: str, planned: PlannedComponent, ctx: DataContext | None
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse, bind, validate offline, then check against the collection's columns.

    `ctx` is None for a tile that binds no collection (text): the binding
    clears the collection tags instead of pinning them, and there is no
    schema to check the answer against.
    """
    try:
        component = component_yaml._parse_component_yaml(raw)
        if ctx is None:
            bind_standalone(component, planned)
        else:
            bind_to_collection(component, planned, ctx)
    except ValueError as e:
        return None, component_yaml.format_validation_error_for_llm(e)
    validated, error = validate_component(component)
    if validated is None:
        return None, error
    error = substance_error(validated) or (schema_error(validated, ctx) if ctx else None)
    if error:
        return None, error
    return validated, None


def fill_intent(planned: PlannedComponent, ctx: DataContext | None, instruction: str | None) -> str:
    """The brief handed to one fill call: the planned intent plus the reviewer's steer."""
    intent = planned.intent
    if not intent:
        tag = (ctx.data_collection_tag or ctx.data_collection_id) if ctx else ""
        intent = f"A {planned.component_type} on {tag}." if tag else f"A {planned.component_type}."
    if instruction and instruction.strip():
        intent = f"{intent}\n\nThe reviewer asks for this change: {instruction.strip()}"
    return intent


async def fill_component(
    target: FillTarget,
    *,
    complete: Callable[[list[dict[str, Any]]], Awaitable[llm_client.Completion]],
    budget: Budget,
    dashboard_title: str,
    siblings: list[str],
    instruction: str | None = None,
    after_call: Callable[[], None] | None = None,
) -> tuple[dict[str, Any] | None, GeneratedComponentEvent]:
    """The model fills one component; validated and repaired like `/ai/component-from-prompt`.

    The one fill-and-repair path: the whole-dashboard run drives it through
    `_Generation.fill_llm` and the regenerate routes through
    `regenerate_target`. `complete` is the caller's charged LLM call,
    `after_call` runs after each of them (the run collects a budget frame
    there) and `instruction` is the reviewer's steer appended to the intent.
    Returns the validated component (None when it is dropped) and its event.
    """
    planned, ctx = target.planned, target.ctx
    prompt = prompts.component_fill_prompt(
        fill_intent(planned, ctx, instruction),
        dashboard_title=dashboard_title,
        section=planned.section,
        tag=planned.tag,
        siblings=list(siblings),
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
        if attempt > 1 and budget.exhausted():
            last_error = f"{last_error} (no budget left to repair)"
            break
        attempts = attempt
        try:
            completion = await complete(messages)
        except Exception as e:  # noqa: BLE001, a provider failure drops the tile, not the run
            last_error = f"LLM error: {e}"
            logger.warning("generate-dashboard: %s on '%s'", last_error, planned.tag)
            break
        if after_call is not None:
            after_call()
        raw = completion.content
        component, error = await asyncio.to_thread(validate_answer, raw, planned, ctx)
        if component is not None and error is None:
            status = "ok" if attempt == 1 else "repaired"
            return component, component_event(planned, status, attempts=attempt)
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
    return None, component_event(planned, "dropped", attempts=attempts, error=last_error)


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


def gate_generation_feature(user: Any) -> None:
    """The gates every generating route shares, before anything is loaded.

    404 when the feature flag is off, 403 in public mode, 403 for an
    anonymous user outside single-user mode (the import route's rule).
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


def gate_generate_request(body: GenerateDashboardRequest, user: Any) -> dict[str, Any]:
    """The HTTP-status gates of `/ai/generate-dashboard`; returns the project document.

    `gate_generation_feature` first (404 flag off, 403 public mode, 403
    anonymous), then 400 on a malformed project id, 404 for an unknown
    project, 403 without editor permission, 400 when a requested data
    collection is not in the project. The document is returned so the stream
    does not load it again.
    """
    gate_generation_feature(user)
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
    # A dotted key on purpose: the rest of the stamp (the warnings, the
    # dropped tags, the planner's section rationales) is not the promote
    # route's to rewrite, and replacing `ai_generation` wholesale would drop
    # whatever a later run added to it.
    dashboards_collection.update_one(
        {"dashboard_id": oid}, {"$set": {"ai_generation.status": "promoted"}}
    )
    return PromoteResponse(dashboard_id=dashboard_id, status="promoted")


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


class _Abort(Exception):
    """A run that cannot go on; its message is the ``error`` event's detail.

    Raised anywhere in `_generate` (or `_regenerate`) and turned into
    ``error`` + ``done`` by the runner, so the terminal frames are written in
    one place.
    """


class _Stream:
    """The frames every generating stream writes, in the shape the panel reads."""

    frame: Callable[[StreamEvent], bytes]
    budget: Budget

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


class _Generation(_Stream):
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
        # tag -> the plan entry it was filled from, so the render check can
        # report a drop as the same `component` event the fill loop emits.
        self.planned_by_tag: dict[str, PlannedComponent] = {}

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
        """One outcome per planned component in the run record, latest word wins.

        The render check reports a second outcome for a tag the fill loop
        already wrote (filled, then dropped because it would not draw), so
        the row is replaced rather than appended: the record keeps one entry
        per planned component, and the history counts a tile as either ok or
        dropped, never as both.
        """
        row = event.model_dump(mode="json")
        for position, existing in enumerate(self.run.components):
            if existing.get("tag") == event.tag:
                self.run.components[position] = row
                break
        else:
            self.run.components.append(row)
        if event.status == "dropped":
            self.dropped.append(event.tag)

    def accept(self, planned: PlannedComponent, component: dict[str, Any]) -> None:
        slim = _slim(component)
        slim["ai_source"] = ai_source_stamp(planned.tag, planned.intent or self.body.prompt)
        self.components.append(slim)
        self.filled_tags.append(planned.tag)
        self.planned_by_tag[planned.tag] = planned

    def accept_plan(
        self, parsed: Any, *, strict: bool = False
    ) -> tuple[DashboardPlan | None, list[FillTarget], str | None]:
        """Parse, normalise and bind one plan payload: (plan, targets, None) or (None, [], error).

        The tail both plan sources share, so a plan the client approved goes
        through exactly the checks a model answer does: `parse_plan`,
        `normalize_plan`, the pinned title, then the binding of every
        component to a collection of this run.

        `strict` is the one difference, and it is about trust rather than
        shape: the model is planning from the collections it was shown, so a
        component bound to an unknown one is that component's problem and it
        is dropped; a plan arriving in a request body is client input, so a
        collection outside the run's subset ends the run instead of being
        quietly trimmed out of it.
        """
        try:
            plan = parse_plan(parsed)
        except (ValueError, ValidationError, json.JSONDecodeError) as e:
            return None, [], component_yaml.format_validation_error_for_llm(e)
        plan, plan_warnings = normalize_plan(
            plan,
            max_components=settings.ai.generate_max_components,
            max_sections=settings.ai.generate_max_sections,
        )
        if self.body.title and self.body.title.strip():
            plan = plan.model_copy(update={"title": self.body.title.strip()})
        outside = unknown_collection_tags(plan, self.contexts) if strict else []
        if outside:
            known = ", ".join(sorted(self.contexts)) or "(none)"
            named = ", ".join(repr(t) for t in outside)
            verb = "is" if len(outside) == 1 else "are"
            detail = (
                f"the plan binds {named}, which {verb} not among the data collections this "
                f"run was given (available: {known})"
            )
            return None, [], detail
        targets, unknown = plan_to_targets(plan, self.contexts)
        if not targets:
            notes = plan_warnings + [str(e.error) for e in unknown]
            detail = "The plan has no usable component."
            if notes:
                detail += " " + " ".join(f"{n}." for n in notes)
            return None, [], detail
        self.warnings.extend(plan_warnings)
        for event in unknown:
            self.record_component(event)
        return plan, targets, None

    async def try_plan(
        self, messages: list[dict[str, Any]]
    ) -> tuple[DashboardPlan | None, list[FillTarget], str | None, str]:
        """One planning call: (plan, targets, None, raw) or (None, [], error, raw)."""
        completion = await self.complete(messages)
        raw = completion.content
        try:
            parsed = routing._parse_json_lenient(raw)
        except (ValueError, json.JSONDecodeError) as e:
            return None, [], component_yaml.format_validation_error_for_llm(e), raw
        plan, targets, error = self.accept_plan(parsed)
        return plan, targets, error, raw

    def adopt_plan(self) -> tuple[DashboardPlan, list[FillTarget]]:
        """The plan the client approved, re-checked as if the model had just answered it.

        No LLM call and no retry: there is no one to send the error back to,
        so a plan that does not parse, or that names a collection this run
        was not given, is an `_Abort` and therefore an ``error`` event.
        """
        plan, targets, error = self.accept_plan(self.body.plan, strict=True)
        if plan is None:
            raise _Abort(f"The approved plan cannot be used: {error or '(unknown)'}")
        return plan, targets

    async def check_render(self, component: dict[str, Any]) -> str | None:
        """One filled component through `dashboard_probe`; None when it renders.

        `probe_component` never raises by contract, and the probe is a
        safety net around the fill rather than a gate on it: should it fail
        anyway (an unavailable module, a collaborator that changed shape)
        the component is kept and the run says once that it went unchecked,
        because a broken probe is not evidence about the tile.
        """
        ctx = self.contexts.get(str(component.get("data_collection_tag") or ""))
        tag = str(component.get("tag") or "")
        try:
            return await asyncio.to_thread(probe_component, component, ctx, self.user)
        except Exception as e:  # noqa: BLE001, see the docstring
            note = "The render check could not run; the components were kept unchecked."
            if note in self.warnings:
                # Whatever broke breaks for every tile: one traceback is the
                # diagnosis, the other N are noise.
                logger.warning("generate-dashboard: the render check failed on '%s': %s", tag, e)
            else:
                logger.exception("generate-dashboard: the render check could not run")
                self.warnings.append(note)
            return None

    async def fill_llm(
        self, target: FillTarget
    ) -> tuple[dict[str, Any] | None, GeneratedComponentEvent, list[bytes]]:
        """`fill_component` on this run's budget; adds the budget frames to emit.

        Returns the validated component (None when dropped), its event and
        one budget frame per LLM call.
        """
        assert self.plan is not None
        frames: list[bytes] = []
        component, event = await fill_component(
            target,
            complete=self.complete,
            budget=self.budget,
            dashboard_title=self.plan.title,
            siblings=list(self.filled_tags),
            after_call=lambda: frames.append(self.budget_frame()),
        )
        return component, event, frames

    _validate_answer = staticmethod(validate_answer)

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
        """The ``ai_generation`` stamp of the draft (`AIGenerationInfo` fields).

        `dropped` carries the tags that never made it and `sections` the
        planner's reason for each section, so the review pass can say what is
        missing and why the layout looks like it does without reading the run
        record; `reviewed` starts empty and is written by the review route.
        """
        return {
            "status": "draft",
            "model": self.model,
            "prompt": self.body.prompt,
            "generated_at": _now_iso(),
            "run_id": self.run.id,
            "warnings": list(self.warnings),
            "reviewed": [],
            "dropped": list(self.dropped),
            "sections": section_rationales(self.plan),
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

    `body.plan_only` stops the run at the plan and `body.plan` fills one the
    caller already approved; the two are mutually exclusive by the request
    model, and leaving both alone is the one-shot run.
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
    plan: DashboardPlan | None = None
    targets: list[FillTarget] = []
    if body.plan is not None:
        # Approved-plan phase: no planning call, the same parse and the same
        # checks, so the plan event below says exactly what will be filled.
        yield gen.status("reading the approved plan")
        plan, targets = gen.adopt_plan()
    else:
        yield gen.status("planning")
        messages = prompts.dashboard_plan_messages(
            ctx,
            body.prompt,
            body.title,
            max_components=settings.ai.generate_max_components,
            max_sections=settings.ai.generate_max_sections,
            warnings=gen.warnings,
        )
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
    if body.plan is not None:
        # The frame the planning call would have emitted, so the panel reads
        # the same budget-then-plan pair in both phases; nothing was spent.
        yield gen.budget_frame()
    yield gen.frame(StreamEvent(type="plan", data={"plan": gen.run.plan}))
    for event in gen.run.components:
        # Components the plan bound to an unknown collection: dropped before any fill.
        yield gen.frame(StreamEvent(type="component", data=event))
    await gen.save()

    if body.plan_only:
        # Plan-only phase: the caller pays for the plan, looks at it, and
        # pays for the fill separately by sending it back as `plan`. The
        # record keeps the plan and its budget; there is no draft to save.
        gen.warnings.append(PLAN_ONLY_NOTE)
        gen.run.status = "planned"
        await gen.save()
        yield gen.budget_frame()
        yield gen.done()
        return

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

    # 4. Render check -------------------------------------------------------
    # A component can validate offline and still refuse to draw: a role bound
    # to a column another role already took, a binding the data does not
    # support, a collection that cannot be read. Probing here, while the
    # draft is still a list of dicts, is what keeps a tile that 500s in the
    # viewer out of it; a probe with nothing to say keeps the tile.
    yield gen.status("checking")
    kept: list[dict[str, Any]] = []
    for component in gen.components:
        error = await gen.check_render(component)
        if error is None:
            kept.append(component)
            continue
        tag = str(component.get("tag") or "")
        event = render_drop_event(component, gen.planned_by_tag.get(tag), error)
        gen.record_component(event)
        gen.warnings.append(f"'{tag}' does not render and was dropped: {error}")
        yield gen.component_frame(event)
    if len(kept) != len(gen.components):
        gen.components = kept
        gen.filled_tags = [str(c.get("tag") or "") for c in kept]
        await gen.save()

    if gen.dropped:
        gen.warnings.append(
            f"{len(gen.dropped)} planned component(s) were left out: {', '.join(gen.dropped)}"
        )
    if not gen.has_data_bound():
        raise _Abort("no component could be generated")

    # 5. Layout + envelope ---------------------------------------------------
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

    # 6. Persist ------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Reviewing a draft: regenerate one tile or one section, keep or unkeep a tile
# ---------------------------------------------------------------------------

# Cap of `GET /ai/generations/{project_id}`, whatever `limit` asks for.
MAX_GENERATION_HISTORY = 50


def require_draft_dashboard(dashboard_id: str, user: Any) -> tuple[ObjectId, dict[str, Any]]:
    """The whole document of an AI-drafted dashboard the caller may edit.

    400 on a malformed id, 404 when the dashboard does not exist or carries
    no ``ai_generation`` stamp (there is no draft to review), 403 without
    editor permission. Same rule as the promote route
    (`check_dashboard_mutation_permission`), so a dashboard owner without a
    project role can still review their own draft.
    """
    try:
        oid = ObjectId(dashboard_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid dashboard_id: {e}") from e
    doc = dashboards_collection.find_one({"dashboard_id": oid})
    if not doc or not doc.get("ai_generation"):
        raise HTTPException(status_code=404, detail="No AI-generated draft with this id.")
    if not check_dashboard_mutation_permission(doc, user, "editor"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to edit this dashboard."
        )
    return oid, doc


def stored_components(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The dashboard's ``stored_metadata``, junk entries left out."""
    return [c for c in (doc.get("stored_metadata") or []) if isinstance(c, dict)]


def locate_component(doc: dict[str, Any], index: str) -> int:
    """Position in ``stored_metadata`` of the component `index` names.

    `index` is either that position (what a review panel counts) or the
    component's own ``index`` uuid, so both ways of addressing a tile work;
    anything else is a 404 rather than a silent regeneration of the wrong
    tile.
    """
    components = stored_components(doc)
    key = str(index).strip()
    if key.isdigit():
        position = int(key)
        if 0 <= position < len(components):
            return position
    else:
        for position, component in enumerate(components):
            if str(component.get("index") or "") == key:
                return position
    raise HTTPException(status_code=404, detail=f"No component '{index}' in this dashboard.")


def locate_section(doc: dict[str, Any], section: str) -> list[int]:
    """Positions of one section's components, in stored order; 404 when it holds none."""
    wanted = section.strip()
    positions = [
        i
        for i, component in enumerate(stored_components(doc))
        if str(component.get("section") or "").strip() == wanted
    ]
    if not positions:
        raise HTTPException(status_code=404, detail=f"No section '{section}' in this dashboard.")
    return positions


def _run_record(run_id: str) -> generations.GenerationRun | None:
    """The generation run behind a draft, or None when it is gone or unreadable."""
    if not run_id:
        return None
    try:
        return generations.get(run_id)
    except Exception:  # noqa: BLE001, a missing record only costs the plan
        logger.warning("regenerate: could not read run %s", run_id, exc_info=True)
        return None


def plan_of(run: generations.GenerationRun | None) -> DashboardPlan | None:
    """The run's stored plan as a `DashboardPlan`, or None when there is none to read."""
    if run is None or not run.plan:
        return None
    try:
        return DashboardPlan.model_validate(run.plan)
    except ValidationError:  # pragma: no cover, a record written by an older shape
        logger.warning("regenerate: run %s carries an unreadable plan", run.id)
        return None


def planned_for(
    component: dict[str, Any], *, tag: str, plan: DashboardPlan | None
) -> PlannedComponent:
    """The plan entry of one stored component, or one reconstructed from the tile.

    A draft outlives the run that made it (a restart, a pruned record, a
    dashboard exported and re-imported), so the entry can be gone while the
    tile is still there and still reviewable. The stored component is then
    the source of truth: its title and description become the intent, and
    its own bindings the collection and the advanced_viz hints.
    """
    if plan is not None:
        entry = next((c for c in plan.components if c.tag == tag), None)
        if entry is not None:
            return entry
    title = str(component.get("title") or "").strip()
    description = str(component.get("description") or "").strip()
    component_type = str(component.get("component_type") or "")
    intent = ". ".join(p for p in (title, description) if p)
    try:
        return PlannedComponent(
            tag=tag or str(component.get("index") or "component"),
            section=str(component.get("section") or ""),
            component_type=component_type,  # type: ignore[arg-type]
            data_collection_tag=str(component.get("data_collection_tag") or "") or None,
            intent=intent or f"A {component_type} tile.",
            use=component.get("use") or None,
            viz_kind=component.get("viz_kind") or None,
        )
    except ValidationError as e:
        raise _Abort(
            f"'{tag or component.get('index')}' is not a component this flow can regenerate: "
            f"{component_yaml.format_validation_error_for_llm(e)}"
        ) from e


def target_for(
    component: dict[str, Any], planned: PlannedComponent, contexts: dict[str, DataContext]
) -> FillTarget:
    """Bind one stored component to its collection and pick how it is re-filled.

    The mirror of `plan_to_targets` for a tile that already exists: the
    plan's collection first, the tile's own as the fallback (they differ
    once the user has edited it). Text binds nothing, and an advanced_viz
    that pins a catalog offer or a ranked kind is rebuilt deterministically.
    """
    if planned.component_type == "text":
        return FillTarget(planned, None, "text")
    ctx = contexts.get(planned.data_collection_tag or "") or contexts.get(
        str(component.get("data_collection_tag") or "")
    )
    deterministic = planned.component_type == "advanced_viz" and bool(
        planned.use or planned.viz_kind
    )
    return FillTarget(planned, ctx, "advanced_viz" if deterministic else "llm")


async def regenerate_target(
    target: FillTarget,
    *,
    complete: Callable[[list[dict[str, Any]]], Awaitable[llm_client.Completion]],
    budget: Budget,
    dashboard_title: str,
    siblings: list[str],
    instruction: str | None = None,
    plan: DashboardPlan | None = None,
) -> tuple[dict[str, Any] | None, GeneratedComponentEvent, list[str]]:
    """One tile, re-filled: (component or None, its event, warnings).

    Deterministic where the run was deterministic and free of charge, unless
    the reviewer asked for a change: an instruction can only be honoured by
    the model, so it moves a text or catalog-pinned tile onto the same fill
    and repair path (`fill_component`) as every other type.
    """
    planned = target.planned
    steered = bool(instruction and instruction.strip())
    if target.mode == "text" and not steered and plan is not None:
        return fill_text(planned, plan, first=False), component_event(planned, "ok"), []
    if target.mode == "advanced_viz" and not steered:
        assert target.ctx is not None
        component, warnings, error = await asyncio.to_thread(fill_advanced_viz, planned, target.ctx)
        if component is None:
            event = component_event(planned, "dropped", attempts=0, error=error or "(unknown)")
            return None, event, warnings
        return component, component_event(planned, "ok"), warnings
    if target.ctx is None and planned.component_type != "text":
        error = (
            f"the data collection '{planned.data_collection_tag}' this component binds is not "
            "one of the project's table collections any more"
        )
        return None, component_event(planned, "dropped", attempts=0, error=error), []
    component, event = await fill_component(
        target,
        complete=complete,
        budget=budget,
        dashboard_title=dashboard_title,
        siblings=siblings,
        instruction=instruction,
    )
    return component, event, []


async def regenerate_contexts(
    project_id: Any,
    user: Any,
    dc_ids: list[str],
    *,
    project_doc: dict[str, Any] | None = None,
) -> tuple[dict[str, DataContext], list[str]]:
    """The `DataContext` of the collections `dc_ids` names, keyed by collection tag.

    The generator's own call (`build_project_data_context`), narrowed to the
    collections the tiles being regenerated bind, with the project's catalog
    offers attached so a ``use:`` handle still resolves.
    """
    wanted = list(dict.fromkeys(d for d in dc_ids if d))
    ctx, warnings = await build_project_data_context(
        str(project_id),
        user,
        wanted or None,
        max_collections=max(1, len(wanted)) if wanted else settings.ai.generate_max_collections,
    )
    if project_doc is None:
        try:
            project_doc = await asyncio.to_thread(_project_doc, ObjectId(project_id))
        except Exception as e:  # noqa: BLE001
            logger.warning("regenerate: project document unavailable: %s", e)
            project_doc = None
    if project_doc:
        try:
            compose = await asyncio.to_thread(compose_offers_for_project, project_doc)
            attach_catalog_offers(ctx, compose)
        except Exception as e:  # noqa: BLE001, offers are an extra, not a requirement
            logger.warning("regenerate: catalog offers unavailable: %s", e)
            warnings.append("Catalog offers could not be read; regenerating without them.")
    return {c.data_collection_tag or c.data_collection_id: c for c in ctx.collections}, warnings


def stored_component(
    component: dict[str, Any], *, project_id: Any, index: str, section: str | None
) -> dict[str, Any]:
    """One validated lite component in ``stored_metadata`` shape, keeping its id.

    The import path's own chain: `to_full` for the runtime fields, then the
    tag resolution and field regeneration `_persist_lite_dashboard` runs, so
    a regenerated tile is written exactly like an imported one. Only the id
    (`index`, which the layout item points at) and the `section` are carried
    over from the tile it replaces.
    """
    lite = validate_envelope({"title": "AI", "components": [component]})
    stored = lite.to_full()["stored_metadata"][0]
    stored["index"] = index
    stored["section"] = section
    resolve_workflow_tags(stored, project_id)
    regenerate_component_fields(stored)
    return stored


def relayout_section(
    components: list[dict[str, Any]], positions: list[int], doc: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Re-run the layout pass over one section; returns the panel arrays to write.

    Boxes are section-relative (the viewer draws one sub-grid per section),
    so a section can be laid out again without moving anything else. The
    split is `layout_dashboard`'s: interactive tiles through the filter
    panel pass, everything else through the grid pass. Only the arrays that
    actually changed come back.
    """
    members = [components[i] for i in positions]
    filters = [c for c in members if c.get("component_type") == "interactive"]
    tiles = [c for c in members if c.get("component_type") != "interactive"]
    boxes: dict[str, dict[str, Any]] = {
        f"box-{laid.get('index')}": laid["layout"]
        for laid in _layout_filter_section(filters) + _layout_grid_section(tiles)
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for key in ("left_panel_layout_data", "right_panel_layout_data"):
        items = [dict(i) for i in (doc.get(key) or []) if isinstance(i, dict)]
        changed = False
        for item in items:
            box = boxes.get(str(item.get("i") or ""))
            if box:
                item.update(box)
                changed = True
        if changed:
            out[key] = items
    return out


def write_components(
    dashboard_oid: ObjectId,
    replacements: dict[int, dict[str, Any]],
    layouts: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    """Replace components in place in ``stored_metadata``, the way an edit lands.

    Positional `$set` keys touch only the tiles that changed, so the rest of
    the document (and a concurrent autosave of it) is left alone, and
    `last_saved_ts` is bumped exactly as ``/dashboards/save/{id}`` does: the
    dashboard listing's cache-buster reads it, and it must stay a string.
    """
    update: dict[str, Any] = {f"stored_metadata.{i}": c for i, c in replacements.items()}
    update.update(layouts or {})
    update["last_saved_ts"] = utc_now_str()
    dashboards_collection.update_one({"dashboard_id": dashboard_oid}, {"$set": update})


def jsonable(component: dict[str, Any]) -> dict[str, Any]:
    """A stored component with its ObjectIds and datetimes stringified, ready to stream."""
    return json.loads(json.dumps(component, default=str))


# ---------------------------------------------------------------------------
# The regenerate stream
# ---------------------------------------------------------------------------


class _Regeneration(_Stream):
    """State of one regenerate call: what it rewrites, its budget, its warnings."""

    def __init__(
        self,
        doc: dict[str, Any],
        user: Any,
        *,
        positions: list[int],
        section: str | None,
        instruction: str | None,
        user_api_key: str | None,
        frame: Callable[[StreamEvent], bytes],
    ) -> None:
        self.doc = doc
        self.user = user
        self.positions = positions
        self.section = section
        self.instruction = instruction
        self.user_api_key = user_api_key
        self.frame = frame
        self.model = llm_client.get_default_model()
        self.budget = Budget(
            max_tokens=settings.ai.generate_max_tokens_total,
            max_seconds=float(settings.ai.generate_max_wall_clock_s),
            max_steps=_max_steps(len(positions)),
        )
        self.warnings: list[str] = []

    async def complete(self, messages: list[dict[str, Any]]) -> llm_client.Completion:
        completion = await asyncio.to_thread(
            llm_client.completion_with_usage, messages, user_api_key=self.user_api_key
        )
        self.budget.charge(completion)
        return completion


async def run_regeneration(
    doc: dict[str, Any],
    current_user: Any,
    *,
    positions: list[int],
    section: str | None = None,
    instruction: str | None = None,
    user_api_key: str | None = None,
    frame: Callable[[StreamEvent], bytes] | None = None,
) -> AsyncIterator[bytes]:
    """Re-fill the components at `positions` and yield the SSE frames.

    Backs both regenerate routes (`positions` is one tile, or a whole
    section when `section` is set). The gates ran before this: `doc` is the
    draft the route loaded and the caller may edit.
    """
    reg = _Regeneration(
        doc,
        current_user,
        positions=positions,
        section=section,
        instruction=instruction,
        user_api_key=user_api_key,
        frame=frame or _sse,
    )
    try:
        async for chunk in _regenerate(reg):
            yield chunk
    except _Abort as e:
        yield reg.error(str(e))
        yield reg.done()
    except Exception:  # noqa: BLE001, never strand the stream, never leak internals
        logger.exception("regenerate: dashboard %s failed unexpectedly", doc.get("dashboard_id"))
        yield reg.error("The regeneration failed unexpectedly.")
        yield reg.done()


async def _regenerate(reg: _Regeneration) -> AsyncIterator[bytes]:
    """The regeneration itself; `_Abort` anywhere here ends the stream with `error`."""
    doc = reg.doc
    components = stored_components(doc)
    project_id = doc.get("project_id")
    dashboard_oid = doc.get("dashboard_id")
    info = doc.get("ai_generation") or {}

    # 1. The plan the tiles came from (optional: a draft outlives its run).
    yield reg.status("reading the draft")
    run = await asyncio.to_thread(_run_record, str(info.get("run_id") or ""))
    plan = plan_of(run)
    title = (plan.title if plan else "") or str(doc.get("title") or "")

    # 2. The collections the tiles bind, as the generator saw them.
    yield reg.status("reading project")
    dc_ids = [str(components[i].get("dc_id")) for i in reg.positions if components[i].get("dc_id")]
    try:
        contexts, ctx_warnings = await regenerate_contexts(project_id, reg.user, dc_ids)
    except HTTPException as e:
        raise _Abort(str(e.detail)) from e
    reg.warnings.extend(ctx_warnings)

    # 3. Re-fill, tile by tile; a tile that fails leaves the stored one alone.
    yield reg.status("regenerating")
    siblings = [t for t in (generation_tag(c) for c in components) if t]
    replacements: dict[int, dict[str, Any]] = {}
    for position in reg.positions:
        stored = components[position]
        tag = generation_tag(stored)
        planned = planned_for(stored, tag=tag, plan=plan)
        component, event, warnings = await regenerate_target(
            target_for(stored, planned, contexts),
            complete=reg.complete,
            budget=reg.budget,
            dashboard_title=title,
            siblings=[t for t in siblings if t != tag],
            instruction=reg.instruction,
            plan=plan,
        )
        reg.warnings.extend(warnings)
        if component is not None:
            slim = _slim(component)
            slim["ai_source"] = ai_source_stamp(
                planned.tag,
                (reg.instruction or "").strip() or planned.intent or str(info.get("prompt") or ""),
            )
            try:
                replacements[position] = await asyncio.to_thread(
                    stored_component,
                    slim,
                    project_id=project_id,
                    index=str(stored.get("index") or ""),
                    section=stored.get("section"),
                )
            except (ValidationError, ValueError) as e:
                # The tile validated on its own but not as a dashboard: keep
                # the stored one and say so, rather than writing a tile the
                # viewer cannot render.
                event = component_event(
                    planned,
                    "dropped",
                    attempts=event.attempts,
                    error=component_yaml.format_validation_error_for_llm(e),
                )
        yield reg.budget_frame()
        yield reg.component_frame(event)

    if not replacements:
        raise _Abort("no component could be regenerated")

    # 4. Write the tiles back, and the section's boxes with them.
    yield reg.status("saving")
    merged = list(components)
    for position, replacement in replacements.items():
        merged[position] = replacement
    layouts = relayout_section(merged, reg.positions, doc) if reg.section is not None else {}
    await asyncio.to_thread(write_components, dashboard_oid, replacements, layouts)

    written = [jsonable(merged[p]) for p in reg.positions]
    single = reg.section is None and len(reg.positions) == 1
    event = RegeneratedEvent(
        dashboard_id=str(dashboard_oid),
        section=reg.section,
        index=reg.positions[0] if single else None,
        tag=generation_tag(merged[reg.positions[0]]) if single else None,
        component=written[0] if single else None,
        components=written,
        warnings=list(reg.warnings),
    )
    yield reg.frame(StreamEvent(type="regenerated", data=event.model_dump(mode="json")))
    yield reg.done()


# ---------------------------------------------------------------------------
# Review bookkeeping and history (sync: pymongo)
# ---------------------------------------------------------------------------


def review_counts(doc: dict[str, Any], reviewed: list[str]) -> tuple[list[str], int]:
    """(reviewed tags still on the dashboard, number of reviewable tiles).

    Removing a tile is the ordinary component delete, which knows nothing
    about the draft, so a tag can outlive what it named: the kept list is
    intersected with what ``stored_metadata`` carries every time the counts
    are computed, and `total` counts the tiles that carry a generation tag.
    """
    present = {t for t in (generation_tag(c) for c in stored_components(doc)) if t}
    kept = [t for t in dict.fromkeys(reviewed) if t in present]
    return kept, len(present)


def review_dashboard(dashboard_id: str, body: ReviewRequest, user: Any) -> ReviewResponse:
    """Mark one tile of a draft reviewed (or take the mark back); sync (pymongo).

    404 without an ``ai_generation`` stamp, 403 without editor permission.
    Returns the counts the review panel shows: how many of the draft's tiles
    are kept, out of how many.
    """
    oid, doc = require_draft_dashboard(dashboard_id, user)
    info = doc.get("ai_generation") or {}
    reviewed = [str(t) for t in (info.get("reviewed") or [])]
    tag = body.tag.strip()
    if body.action == "keep":
        if tag not in reviewed:
            reviewed.append(tag)
    else:
        reviewed = [t for t in reviewed if t != tag]
    kept, total = review_counts(doc, reviewed)
    # Dotted, like the promote route's `$set`: only `reviewed` is this
    # route's to write, and the section rationales beside it must survive.
    dashboards_collection.update_one(
        {"dashboard_id": oid}, {"$set": {"ai_generation.reviewed": kept}}
    )
    return ReviewResponse(reviewed=len(kept), total=total)


def _dashboard_titles(dashboard_ids: list[str]) -> dict[str, str]:
    """dashboard_id -> title for the ids that still exist (one query, best effort)."""
    oids = []
    for dashboard_id in dashboard_ids:
        try:
            oids.append(ObjectId(dashboard_id))
        except Exception:  # noqa: BLE001, a record written before the draft was saved
            continue
    if not oids:
        return {}
    docs = dashboards_collection.find(
        {"dashboard_id": {"$in": oids}}, {"dashboard_id": 1, "title": 1}
    )
    return {str(d.get("dashboard_id")): str(d.get("title") or "") for d in docs}


def list_generations(project_id: str, user: Any, limit: int = 20) -> GenerationsResponse:
    """The project's generation runs, newest first, without their YAML or plan.

    400 on a malformed project id, 404 for an unknown project, 403 without
    viewer permission on it. `limit` is capped at `MAX_GENERATION_HISTORY`.
    """
    try:
        oid = ObjectId(project_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid project_id: {e}") from e
    if not _project_doc(oid):
        raise HTTPException(status_code=404, detail="Project not found.")
    if not check_project_permission(oid, user, "viewer"):
        raise HTTPException(
            status_code=403, detail="You don't have permission to read this project."
        )
    capped = max(1, min(int(limit), MAX_GENERATION_HISTORY))
    runs = generations.list_for_project(project_id, capped)
    titles = _dashboard_titles([r.dashboard_id for r in runs if r.dashboard_id])
    rows: list[GenerationSummary] = []
    for run in runs:
        counts = Counter(str(c.get("status") or "") for c in run.components)
        dashboard_id = str(run.dashboard_id or "")
        # A run whose draft was deleted, or that failed or was cancelled
        # before one was saved, has no live title to read; the plan it stored
        # already named the dashboard, so fall back to that rather than let
        # the history call the run untitled. A run that never got as far as a
        # plan has no name at all, which is what None says.
        title = titles.get(dashboard_id) or str((run.plan or {}).get("title") or "").strip() or None
        rows.append(
            GenerationSummary(
                id=run.id,
                dashboard_id=run.dashboard_id,
                title=title,
                dashboard_deleted=bool(dashboard_id) and dashboard_id not in titles,
                prompt=run.prompt,
                model=run.model,
                status=run.status,
                created_at=run.created_at,
                ok=counts["ok"],
                repaired=counts["repaired"],
                dropped=counts["dropped"],
                warnings=list(run.warnings),
            )
        )
    return GenerationsResponse(generations=rows)
