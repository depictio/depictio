"""Prompt templates for the AI flows.

Kept in one place so prompt iteration is decoupled from route handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from typing import cast, get_args

from pydantic import BaseModel

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.ai_endpoints.context import (
    COMPONENT_DC_TYPES,
    DashboardContext,
    DashboardDataContext,
    DataContext,
    InventoryEntry,
    ProjectDataContext,
    ProjectInventory,
    offer_use_id,
    role_candidates_line,
)
from depictio.api.v1.endpoints.ai_endpoints.executor import grammar_block
from depictio.api.v1.endpoints.ai_endpoints.schemas import AnalyzeMode, ComponentType
from depictio.models.components.constants import (
    AGGREGATION_COMPATIBILITY,
    INTERACTIVE_COMPATIBILITY,
    MAP_STYLES,
    MAP_TYPES,
    MAX_INTERACTIVE_GROUP_SIZE,
    VISU_TYPES,
)
from depictio.models.components.lite import CardLiteComponent

# ---------------------------------------------------------------------------
# Component-from-prompt: per-type constraint sheets + YAML examples
# ---------------------------------------------------------------------------


def _aggregation_lines() -> str:
    return "\n".join(
        f"  {col_type:9s} -> {', '.join(aggs)}"
        for col_type, aggs in AGGREGATION_COMPATIBILITY.items()
    )


def _card_layout_lines() -> str:
    """Advertise the multi-metric layouts straight from the lite model.

    Derived rather than hand-written so a new ``secondary_layout`` option
    (or a changed companion-field contract in the field description) shows
    up in the prompt without anyone remembering to update it.
    """
    field = CardLiteComponent.model_fields["secondary_layout"]
    layouts = ", ".join(get_args(field.annotation))
    return f"  secondary_layout ∈ {{{layouts}}}\n  {field.description}"


def _interactive_lines() -> str:
    return "\n".join(
        f"  {col_type:9s} -> {', '.join(types) if types else '(unsupported)'}"
        for col_type, types in INTERACTIVE_COMPATIBILITY.items()
    )


# How many ranked kinds the advanced_viz sheet lists: the confident ones up to
# MAX_ADVANCED_VIZ_KINDS, or the best FALLBACK_ADVANCED_VIZ_KINDS when nothing
# reaches the recommended score. Candidate columns per role are capped too.
MAX_ADVANCED_VIZ_KINDS = 6
FALLBACK_ADVANCED_VIZ_KINDS = 3
MAX_ROLE_CANDIDATES = 4


@cache
def _viz_config_models() -> dict[str, type[BaseModel]]:
    """viz_kind -> its config model, read off the ``VizConfig`` union."""
    from depictio.models.components.advanced_viz.configs import VizConfig

    union = get_args(VizConfig)[0]
    return {model.model_fields["viz_kind"].default: model for model in get_args(union)}


def _advanced_viz_sheet(data_ctx: DataContext | None) -> str:
    """ADVANCED_VIZ sheet, ranked against the columns of the request's DC.

    Eighteen kinds with a dozen config keys each would drown the prompt, so
    the sheet is generated per request from the same scorer that drives the
    builder's "Recommended" picker: the confident kinds (score at or above
    RECOMMENDED_SCORE), or the best few when nothing reaches it. Every role
    is printed under the exact config key the renderer reads
    (``role_config_key`` covers the list-typed exceptions), with the columns
    the ranker already matched to it. The kind's remaining config keys are
    listed by name because the config models forbid unknown keys.
    """
    from depictio.models.components.advanced_viz.catalog import role_config_key
    from depictio.models.components.advanced_viz.schemas import (
        RECOMMENDED_SCORE,
        role_dtype_specs,
        suggest_viz_kinds,
    )

    schema = {c.name: c.dtype for c in data_ctx.columns} if data_ctx else {}
    ranked = suggest_viz_kinds(schema, dc_type=data_ctx.dc_type if data_ctx else None)
    picks = [s for s in ranked if s.score >= RECOMMENDED_SCORE][:MAX_ADVANCED_VIZ_KINDS]
    if not picks:
        picks = ranked[:FALLBACK_ADVANCED_VIZ_KINDS]

    lines = [
        "ADVANCED_VIZ: domain-specific plot. Required: viz_kind, config.",
        "config.viz_kind must repeat viz_kind. Choose ONE kind below (ranked by fit to",
        "the DATASET SCHEMA) and bind each role to a column under the exact config key",
        "shown. config accepts ONLY the keys listed for that kind; unknown keys are",
        "rejected. Leave optional settings out unless the user asks for them.",
    ]
    for suggestion in picks:
        kind = suggestion.viz_kind
        lines.append(f"- viz_kind: {kind} (fit {suggestion.score:.2f})")
        role_keys: set[str] = set()
        for role, spec in role_dtype_specs(kind).items():
            key = role_config_key(kind, role)
            role_keys.add(key)
            need = "required" if spec["required"] else "optional"
            dtypes = "|".join(cast("list[str]", spec["dtypes"]))
            line = f"    config.{key}: {need} column ({dtypes})"
            description = str(spec["description"] or "").strip()
            if description:
                line += f". {description}"
            candidates = (suggestion.role_candidates.get(role) or [])[:MAX_ROLE_CANDIDATES]
            if candidates:
                line += f" Candidates: {', '.join(candidates)}."
            lines.append(line)
        model = _viz_config_models().get(kind)
        if model is not None:
            fields = model.model_fields
            required = [
                f"{name} ({info.description})" if info.description else name
                for name, info in fields.items()
                if info.is_required() and name not in role_keys
            ]
            optional = [
                name
                for name, info in fields.items()
                if not info.is_required() and name != "viz_kind" and name not in role_keys
            ]
            if required:
                lines.append(f"    required settings: {'; '.join(required)}")
            if optional:
                lines.append(f"    optional settings: {', '.join(optional)}")
        if suggestion.unmet_roles:
            lines.append(f"    no compatible column for: {', '.join(suggestion.unmet_roles)}")
    return "\n".join(lines)


# One sheet per component type. Most are static text; a callable is rendered
# per request against the DataContext (None for types with no data source).
_CONSTRAINT_SHEETS: dict[str, str | Callable[[DataContext | None], str]] = {
    "figure": (
        f"FIGURE: Plotly Express chart. Required: visu_type, dict_kwargs.\n"
        f"  visu_type ∈ {{{', '.join(VISU_TYPES)}}}\n"
        "  dict_kwargs maps Plotly Express kwargs (x, y, color, ...) to column names.\n"
        "  Reference only columns from the DATASET SCHEMA. Histogram does not require y.\n"
        "  Optional: mode='ui' (default) or mode='code' with code_content for custom code."
    ),
    "card": (
        "CARD: single aggregated statistic. Required: aggregation, column_name, column_type.\n"
        "Allowed aggregation × column_type:\n"
        f"{_aggregation_lines()}\n"
        "Optional: aggregations (list of secondary stats, same compatibility rules),\n"
        "secondary_layout — how the strip under the hero renders. Match the user's\n"
        "wording: 'histogram'/'distribution' -> histogram, 'box plot' -> box_plot,\n"
        "'trend'/'over time' -> trend, 'top N'/'breakdown' -> top_n. Never leave the\n"
        "default 'vertical' when the user names a visual style.\n"
        f"{_card_layout_lines()}\n"
        "filter_expr (Polars expression scoped to the DC), icon_name, icon_color, title."
    ),
    "interactive": (
        "INTERACTIVE: filter control. Required: interactive_component_type, column_name, column_type.\n"
        "Allowed interactive_component_type × column_type:\n"
        f"{_interactive_lines()}\n"
        "Timeline requires timescale ∈ (year, month, day, hour, minute).\n"
        "Optional: filter_expr, placement (left|top — only Timeline supports top),\n"
        f"group (≤ {MAX_INTERACTIVE_GROUP_SIZE} components share a group), title, icon_name."
    ),
    "table": (
        "TABLE: tabular view of the DC. Optional: columns (list of column names to show),\n"
        "page_size (default 10), sortable, filterable, row_selection_enabled +\n"
        "row_selection_column (selecting rows filters other components)."
    ),
    "text": (
        "TEXT: narrative tile, a heading plus one paragraph. It has no data source:\n"
        "do NOT emit workflow_tag or data_collection_tag.\n"
        "  title: the heading text.\n"
        "  body: ONE paragraph. Only inline **bold**, *italic* and `code` are rendered;\n"
        "  no lists, no headings, no links, no line breaks.\n"
        "  order: heading level 1-6 (default 1; 2-3 for a section, 4-6 for a note).\n"
        "  alignment ∈ {left, center, right} (default left).\n"
        "  vertical_alignment ∈ {top, center, bottom} (default center)."
    ),
    "image": (
        "IMAGE: thumbnail grid from an image-path column. Required: image_column.\n"
        "Optional: thumbnail_size (px, default 150), columns (grid width, default 4),\n"
        "max_images (default 20). s3_base_folder is resolved server-side; omit unless\n"
        "the user explicitly overrides it."
    ),
    "multiqc": (
        "MULTIQC: render a single MultiQC plot. Required: selected_module, selected_plot.\n"
        "Both names must match an entry in the DC's MultiQC catalog. Ask the user if\n"
        "the prompt is too vague to disambiguate."
    ),
    "map": (
        f"MAP: tile-based map. Required: map_type ∈ {{{', '.join(MAP_TYPES)}}}.\n"
        "scatter_map / density_map require lat_column + lon_column (both numeric).\n"
        "density_map additionally requires z_column.\n"
        "choropleth_map requires locations_column + color_column + a geojson source\n"
        "(geojson_data, geojson_url, or geojson_dc_id).\n"
        f"map_style ∈ {{{', '.join(MAP_STYLES)}}}. Optional: color_column, size_column,\n"
        "hover_columns, text_column, opacity, size_max, title."
    ),
    "advanced_viz": _advanced_viz_sheet,
}


_YAML_EXAMPLES: dict[str, str] = {
    "figure": """\
component_type: figure
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
visu_type: scatter
dict_kwargs:
  x: <column>
  y: <column>
  color: <column>
""",
    "card": """\
component_type: card
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
aggregation: average
column_name: <column>
column_type: float64
""",
    "interactive": """\
component_type: interactive
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
interactive_component_type: MultiSelect
column_name: <column>
column_type: object
""",
    "table": """\
component_type: table
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
columns: []
""",
    "text": """\
component_type: text
title: <heading>
order: 3
alignment: left
vertical_alignment: top
body: <one paragraph>
""",
    "image": """\
component_type: image
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
image_column: <column>
""",
    "multiqc": """\
component_type: multiqc
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
selected_module: <module name>
selected_plot: <plot name>
""",
    "map": """\
component_type: map
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
map_type: scatter_map
lat_column: <numeric column>
lon_column: <numeric column>
""",
    "advanced_viz": """\
component_type: advanced_viz
workflow_tag: <workflow_tag from context>
data_collection_tag: <data_collection_tag from context>
viz_kind: volcano
config:
  viz_kind: volcano
  feature_id_col: <string column>
  effect_size_col: <float column>
  significance_col: <float column>
  significance_threshold: 0.05
  effect_threshold: 1.0
""",
}


def _constraint_sheet(component_type: ComponentType, data_ctx: DataContext | None) -> str:
    """The constraint sheet for one type; rendered per request when it is data-driven."""
    sheet = _CONSTRAINT_SHEETS[component_type]
    return sheet(data_ctx) if callable(sheet) else sheet


def _example_yaml(component_type: ComponentType) -> str:
    return _YAML_EXAMPLES[component_type]


def _data_tags_block(ctx: DataContext) -> str:
    """Hand the LLM the workflow_tag + data_collection_tag explicitly.

    Without this the model would guess from the project name and produce
    YAML that fails to resolve against MongoDB.
    """
    return (
        f"workflow_tag: {ctx.workflow_tag or '(unknown)'}\n"
        f"data_collection_tag: {ctx.data_collection_tag or ctx.dc_name or '(unknown)'}"
    )


def component_from_prompt_messages(
    ctx: DataContext | None,
    prompt: str,
    component_type: ComponentType,
    current: dict | None = None,
    *,
    dashboard_block: str | None = None,
) -> list[dict]:
    """System + user messages for the /ai/component-from-prompt endpoint.

    `current` is set in the "modify existing component" flow — we
    include its YAML representation so the LLM can produce a revision
    rather than a from-scratch component.

    `ctx` is None for a component with no data source (text). The dataset
    sections are then replaced by `dashboard_block`, a summary of what is
    already on the dashboard, so the model writes text that fits the tiles
    it will sit next to. With a data source, `dashboard_block` is optional
    extra context and the prompt is otherwise unchanged.
    """
    mode_note = "REVISE an existing component" if current else "CREATE a new component"

    current_block = ""
    if current:
        # Lazy import to avoid circular: component_yaml.dump_single is
        # in the same package and pulls in DashboardDataLite indirectly.
        from depictio.api.v1.endpoints.ai_endpoints.component_yaml import dump_single

        current_block = (
            "\nCURRENT COMPONENT (YAML the user is revising):\n"
            f"```yaml\n{dump_single(current)}```\n"
            "Modify the fields the user asked to change. Preserve everything else.\n"
        )

    # Always present for a type with no data source (it is then the only
    # context there is); opt-in extra context for the data-driven types.
    if dashboard_block or ctx is None:
        dashboard_section = (
            "\nDASHBOARD COMPONENTS (already on the dashboard):\n"
            f"{dashboard_block or '(no dashboard context available)'}\n"
        )
    else:
        dashboard_section = ""
    if ctx is not None:
        tags_rule = "- Use the workflow_tag and data_collection_tag from CONTEXT verbatim."
        context_section = f"""CONTEXT:
{ctx.metadata_block()}

DATA SOURCE TAGS (use these literally):
{_data_tags_block(ctx)}

DATASET SCHEMA:
{ctx.schema_block()}

SAMPLE ROWS:
{ctx.sample_block()}
{dashboard_section}"""
        columns_rule = "- Reference only column names that appear in DATASET SCHEMA."
    else:
        tags_rule = (
            "- Do not emit workflow_tag or data_collection_tag: this type has no data source."
        )
        context_section = (
            "CONTEXT:\n"
            "This component has no data source. It is a narrative tile on a dashboard.\n"
            f"{dashboard_section}"
        )
        columns_rule = (
            "- Describe what CONTEXT says is on the dashboard; do not invent numbers or columns."
        )

    system = f"""You are filling a single Depictio dashboard component for the user.
You will {mode_note} of type "{component_type}".

OUTPUT FORMAT — strict:
- Emit ONE YAML mapping describing the component.
- No prose, no Markdown fences, no comments — YAML only.
{tags_rule}

{context_section}
COMPONENT CONSTRAINTS:
{_constraint_sheet(component_type, ctx)}

EXAMPLE SHAPE FOR component_type="{component_type}":
```yaml
{_example_yaml(component_type)}```
{current_block}
RULES:
{columns_rule}
- Match user intent literally: if they ask for "histogram of x", emit a histogram
  with that x — do not add color/facet/size unless they explicitly asked.
- The YAML must be valid against the Depictio Lite schema for the chosen type.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


# ---------------------------------------------------------------------------
# Component routing: prompt -> (component_type, data_collection_tag)
# ---------------------------------------------------------------------------

# What each type is and when a user's wording calls for it, which is the
# question the router answers. The constraint sheets say how to *fill* a type
# and are far too long for the router, so this is its own short description.
_ROUTING_HINTS: dict[str, str] = {
    "figure": (
        "Plotly Express chart. Use for a generic chart (scatter, bar, box, "
        "histogram, line, violin) of a table."
    ),
    "card": (
        "single aggregated statistic. Use for one headline number (count, mean, "
        "sum, min, max), optionally with a breakdown."
    ),
    "interactive": (
        "filter control. Use for a widget (select, slider, date range) that "
        "narrows the other tiles."
    ),
    "table": "tabular view. Use for the raw rows of a collection.",
    "text": (
        "narrative tile, a heading plus one paragraph. Use for prose only "
        "(title, introduction, note). Never needs a data collection."
    ),
    "image": "thumbnail grid. Use for a gallery from an image-path column.",
    "multiqc": "one MultiQC report plot. Use for QC metrics per sample.",
    "map": (
        "tile-based map. Use for points or regions on a geographic map "
        "(needs latitude/longitude columns)."
    ),
    "advanced_viz": (
        "domain-specific plot. Use for a bioinformatics figure: volcano, MA, "
        "Manhattan, PCA/UMAP embedding, enrichment dot plot, complex heatmap, "
        "phylogenetic tree."
    ),
}


def _type_lines(allowed_types: list[ComponentType]) -> str:
    lines = []
    for t in allowed_types:
        fits = sorted(COMPONENT_DC_TYPES.get(t, frozenset()))
        fits_note = (
            f" Fits collections of type: {', '.join(fits)}." if fits else " Uses no collection."
        )
        lines.append(f"- {t}: {_ROUTING_HINTS[t]}{fits_note}")
    return "\n".join(lines)


ROUTE_ANSWER_SHAPE = """{
  "component_type": "<one of the allowed types>",
  "data_collection_tag": "<one tag from INVENTORY, or null for text>",
  "reason": "<one sentence>",
  "alternatives": ["<other plausible tags from INVENTORY, at most 3>"]
}"""


def route_component_messages(
    prompt: str,
    inventory: ProjectInventory,
    allowed_types: list[ComponentType],
    pinned_type: ComponentType | None = None,
    pinned_dc_tag: str | None = None,
) -> list[dict]:
    """System + user messages for the routing call.

    The model sees one line per allowed component type (what it is, when
    to use it, which collection types fit) and one line per collection of
    the project (tag, type, on-dashboard marker, description, columns),
    then names the type and the tag as strict JSON. A pinned type or tag
    is stated as fixed so the model only fills in the other half.
    """
    pins = []
    if pinned_type:
        pins.append(f'- component_type is fixed to "{pinned_type}". Return it unchanged.')
    if pinned_dc_tag:
        pins.append(f'- data_collection_tag is fixed to "{pinned_dc_tag}". Return it unchanged.')
    pins_block = ("\nPINNED BY THE USER:\n" + "\n".join(pins) + "\n") if pins else ""

    project = f" of project {inventory.project_name!r}" if inventory.project_name else ""
    system = f"""You route a dashboard-component request: given the user's wording, pick the
component type to build and the data collection to build it on. You do not
build the component.

COMPONENT TYPES (allowed answers):
{_type_lines(allowed_types)}

INVENTORY (data collections{project}; "on dashboard" = already used by this dashboard):
{inventory.text_block()}
{pins_block}
RULES:
- Pick exactly one component_type and, unless it is text, exactly one
  data_collection_tag copied verbatim from INVENTORY.
- Prefer collections marked "on dashboard" unless the request clearly needs
  another one (it names columns or a subject only another collection has).
- text never needs a collection: set data_collection_tag to null.
- The collection's type must fit the component type (see the type lines).
- alternatives lists other collections that could also serve the request
  (tags from INVENTORY only, none of them the chosen one). Empty when none.
- reason is one short sentence the user will read.

Respond with valid JSON of the form:
{ROUTE_ANSWER_SHAPE}
Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


# ---------------------------------------------------------------------------
# Typed suggestions: "what would you add to this dashboard?"
# ---------------------------------------------------------------------------

SUGGESTION_ANSWER_SHAPE = """{
  "suggestions": [
    {
      "component_type": "<one of the allowed types>",
      "data_collection_tag": "<tag copied from a DATA COLLECTIONS heading, or null for text>",
      "title": "<short noun phrase>",
      "rationale": "<one or two sentences: why this component on this data>",
      "component": {"<the type's fields, same keys as the YAML shapes, as JSON>": "..."}
    }
  ]
}"""


# advanced_viz, when the type is open: the per-collection LEGAL SPACES carry
# the ranked kinds and their exact config keys (see suggest.advanced_viz_space_lines),
# so the sheet only states the shape and the judgement the ranker cannot make.
_ADVANCED_VIZ_SUGGEST_SHEET = (
    "ADVANCED_VIZ: domain-specific plot. Required: viz_kind, config.\n"
    "  config.viz_kind repeats viz_kind; config has exactly the keys listed for that\n"
    "  kind in the collection's LEGAL SPACES (extra keys are rejected).\n"
    "  Propose one only when the kind is what the data is about (a volcano needs\n"
    "  effect sizes and p-values, a rarefaction curve needs sequencing depth), never\n"
    "  because the column types happen to fit."
)
_ADVANCED_VIZ_SUGGEST_EXAMPLE = (
    "component_type=advanced_viz (JSON):\n"
    '{"viz_kind": "<kind from LEGAL SPACES>", '
    '"config": {"viz_kind": "<same kind>", "<config key>": "<column>", ...}}'
)


def _suggest_collection_block(
    entry: InventoryEntry,
    ctx: DataContext | None,
    spaces: list[str],
) -> str:
    """One collection for the suggestion prompt: metadata + schema + samples, or the inventory line."""
    head = f"### data_collection_tag: {entry.data_collection_tag}"
    if entry.on_dashboard:
        head += " (on dashboard)"
    if ctx is not None:
        body = (
            f"{ctx.metadata_block()}\n"
            f"SCHEMA:\n{ctx.schema_block()}\n"
            f"SAMPLE ROWS:\n{ctx.sample_block()}"
        )
    else:
        body = entry.to_prompt_line()
    if spaces:
        space_block = "LEGAL SPACES (pick from these only):\n" + "\n".join(
            f"  {line}" for line in spaces
        )
    else:
        space_block = "LEGAL SPACES: (none of the allowed data types fits this collection)"
    return f"{head}\n{body}\n{space_block}"


def suggest_components_messages(
    targets: list[InventoryEntry],
    contexts_by_dc: dict[str, DataContext],
    dashboard_ctx: DashboardContext,
    llm_types: list[ComponentType],
    spaces_by_dc: dict[str, list[str]],
    n: int,
) -> list[dict]:
    """System + user messages for the LLM step of /ai/suggest-components.

    The model sees what the dashboard already shows (so it does not repeat
    it), each target collection with its legal component spaces computed
    server-side, the constraint sheets of the types it may propose, and
    answers strict JSON. table is never in `llm_types` (ranked
    deterministically); advanced_viz is there only when the type is open,
    with its ranked kinds and config keys inside the LEGAL SPACES.
    """
    collections = "\n\n".join(
        _suggest_collection_block(
            entry,
            contexts_by_dc.get(entry.data_collection_id),
            spaces_by_dc.get(entry.data_collection_id) or [],
        )
        for entry in targets
    )
    # advanced_viz carries its own sheet and a JSON (not YAML) example: its
    # kinds live in the per-collection LEGAL SPACES, not in a static shape.
    sheet_types = [t for t in llm_types if t not in ("advanced_viz", "table")]
    sheet_list = [_constraint_sheet(t, None) for t in sheet_types]
    example_list = [f"component_type={t}:\n```yaml\n{_example_yaml(t)}```" for t in sheet_types]
    if "advanced_viz" in llm_types:
        sheet_list.append(_ADVANCED_VIZ_SUGGEST_SHEET)
        example_list.append(_ADVANCED_VIZ_SUGGEST_EXAMPLE)
    sheets = "\n\n".join(sheet_list)
    examples = "\n".join(example_list)
    if len(llm_types) == 1:
        mix_rule = f'- Every item has component_type "{llm_types[0]}".'
    else:
        mix_rule = (
            "- Mix the component types: no type more than twice, and never the same "
            "type on the same column twice."
        )
    if len(targets) > 1:
        spread_rule = (
            '- Prefer collections marked "on dashboard"; spread the items over the '
            "collections when more than one fits."
        )
    elif targets:
        spread_rule = (
            f'- Every data item uses data_collection_tag "{targets[0].data_collection_tag}".'
        )
    else:
        spread_rule = "- No data collection is in scope: describe the dashboard as it is."

    system = f"""You propose new components for an existing Depictio dashboard. Look at what
it already shows and at the data collections below, and propose {n} components
that add information the dashboard does not show yet.

DASHBOARD COMPONENTS (already on the dashboard; do not repeat them):
{dashboard_ctx.components_block()}

CURRENT FILTERS:
{dashboard_ctx.filters_block()}

DATA COLLECTIONS (in scope for the new components):
{collections or "(no data collection in scope)"}

ALLOWED COMPONENT TYPES: {", ".join(llm_types)}

COMPONENT CONSTRAINTS:
{sheets}

FIELD SHAPES (emit the same keys as JSON inside "component"; the server fills
component_type, workflow_tag and data_collection_tag):
{examples}

RULES:
- Propose exactly {n} items, each a different idea. Anything DASHBOARD COMPONENTS
  already shows counts as a repeat (same type on the same column).
{mix_rule}
{spread_rule}
- Use only column names listed under the collection you pick. For card and
  interactive, take column_type and aggregation / interactive_component_type
  from that collection's LEGAL SPACES.
- data_collection_tag is copied verbatim from the collection heading; null for text.
- text describes what the dashboard shows; it never uses a collection and never
  invents numbers.
- title is a short noun phrase; rationale is one or two sentences the user reads.

Respond with valid JSON of the form:
{SUGGESTION_ANSWER_SHAPE}
Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Suggest {n} components to add to this dashboard."},
    ]


# ---------------------------------------------------------------------------
# Kept legacy prompts for /ai/suggest-figures (deprecated) and /ai/analyze
# ---------------------------------------------------------------------------


def suggest_figures_messages(ctx: DataContext, n: int) -> list[dict]:
    """Prompt of the deprecated /ai/suggest-figures route; the viewer uses suggest-components."""
    system = f"""You are a data visualization expert. Propose {n} distinct Plotly Express plots
that surface the most useful patterns in this dataset. Favor variety
(distribution, comparison, relationship) over slight variations of the same
chart. Avoid suggesting the same column pair twice.

CONTEXT:
{ctx.metadata_block()}

DATASET SCHEMA:
{ctx.schema_block()}

SAMPLE ROWS:
{ctx.sample_block()}

Respond with valid JSON of the form:
{{"suggestions": [<PlotSuggestion>, <PlotSuggestion>, ...]}}

Each PlotSuggestion follows this schema:
{{
    "visu_type": "{"|".join(VISU_TYPES)}",
    "dict_kwargs": {{"x": "column_name", "y": "column_name", ...}},
    "title": "Chart title",
    "explanation": "Why this plot is useful"
}}

- "dict_kwargs" must NOT be empty. For non-histogram plots, "x" is required.
- Reference only column names that appear in the dataset schema.
- Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Suggest {n} figures."},
    ]


def _data_block(
    data_ctx: DataContext,
    multi: DashboardDataContext | None,
    warnings: list[str] | None,
) -> tuple[str, list[str]]:
    """Render the data section, degrading gracefully under the char budget.

    `max_context_chars` has always been documented as a hard cap and has
    only ever been enforced on the section-summary prompt. Describing N
    schemas instead of one is exactly the case that overruns it, so this
    is where it starts to matter. Sample rows go first (they illustrate
    shape, they are not evidence), then whole collections from the tail.
    Whatever is dropped is reported, because a silently shortened context
    reads to the model as the complete picture.
    """
    budget = settings.ai.max_context_chars
    notes: list[str] = []

    if multi is None or not multi.collections:
        return (
            f"DATASET SCHEMA:\n{data_ctx.schema_block()}\n\n"
            f"SAMPLE ROWS:\n{data_ctx.sample_block()}",
            [],
        )

    def render(collections: list[DataContext], with_samples: bool) -> str:
        view = DashboardDataContext(
            dashboard_id=multi.dashboard_id, collections=collections, joins=multi.joins
        )
        return (
            f"DATA COLLECTIONS:\n{view.collections_block(with_samples=with_samples)}\n\n"
            f"DECLARED JOINS:\n{view.joins_block()}"
        )

    kept = list(multi.collections)
    block = render(kept, True)
    if len(block) > budget:
        block = render(kept, False)
        notes.append("Sample rows were omitted from the context to stay within the size budget.")
    while len(block) > budget and len(kept) > 1:
        dropped = kept.pop()
        notes.append(
            f"Data collection '{dropped.data_collection_tag or dropped.data_collection_id}' "
            "was left out of the context to stay within the size budget."
        )
        block = render(kept, False)

    if warnings is not None:
        warnings.extend(notes)
    return block, [c.data_collection_tag or c.data_collection_id for c in kept]


def analyze_messages(
    data_ctx: DataContext,
    dashboard_ctx: DashboardContext,
    user_prompt: str,
    selected_component_id: str | None,
    mode: AnalyzeMode = "mutate",
    multi: DashboardDataContext | None = None,
    warnings: list[str] | None = None,
) -> list[dict]:
    """System prompt for the analyze flow, in one of two exclusive modes.

    ``mutate`` asks for the original envelope: reasoning, optional Polars
    code, an answer, and dashboard actions the user can Apply.

    ``analyze`` is read-only. `actions` is absent from the envelope and
    stripped server-side if the model emits it anyway, so the surface
    rendering the reply never has to guess whether an Apply button
    belongs there.

    `mode` is the first field of the envelope in both cases: the loop is
    driven by blocking completions today, so nothing reads it early, but
    it keeps the door open for token-level streaming to route the
    rendering before the reply is complete.
    """
    selected = (
        f"\nThe user has selected component '{selected_component_id}'."
        if selected_component_id
        else ""
    )
    if mode == "analyze":
        role = """You are a data analyst producing a traceable analysis report for a
bioinformatics dashboard. You answer by computing, step by step. You do
NOT change the dashboard: this request is read-only, and any dashboard
action you propose will be discarded."""
        envelope = """{
  "mode": "analyze",
  "plan": "on your FIRST reply only: 2-4 lines stating how you will approach the question",
  "thought": "what this step is for",
  "code": "<polars expression, or empty string when you are done>",
  "answer": "final narrative in Markdown — only when code is empty",
  "findings": [
      {"claim": "one specific, quantified statement",
       "evidence_step_ids": [<indices of the executed steps that prove it>],
       "confidence": "low" | "medium" | "high"}
  ]
}"""
        rules = """- Iterate: explore, verify, cross-check. You will see your remaining
  budget (steps, tokens, seconds) after every step — plan to conclude
  before it runs out rather than being cut off.
- Every finding MUST cite evidence_step_ids of steps that ran
  successfully. A finding without evidence is dropped server-side.
  The sample rows illustrate the shape of the data; they are never
  evidence. Steps are numbered from 0 in the order they executed.
- Prefer aggregates over row dumps; output is capped per step.
- Do NOT emit an "actions" key. It will be discarded.
- Do not wrap the JSON in markdown fences."""
        contract = ""
    else:
        role = """You are a data analyst assistant for a bioinformatics dashboard.
You can answer questions about the data and propose changes to the dashboard."""
        envelope = """{
  "mode": "mutate",
  "thought": "what you intend to do",
  "code": "<polars expression or empty string>",
  "answer": "natural-language answer once you have the result",
  "actions": {
      "figure_mutations": [{"component_id": "...", "dict_kwargs_patch": {...}, "reason": "..."}],
      "filter_proposals": [<FilterProposal>, ...]
  }
}"""
        rules = """- Use the `code` field if and only if you need to compute something.
- Use `actions.filter_proposals` to change what data the dashboard shows.
- Use `actions.figure_mutations` to propose patches to existing figures
  (keys mapped to null are removed).
- Do not wrap the JSON in markdown fences."""
        contract = f"\n{FILTER_PROPOSAL_CONTRACT}\n"

    data_block, tags = _data_block(data_ctx, multi, warnings)

    system = f"""{role}

CONTEXT:
{data_ctx.metadata_block()}

{data_block}

DASHBOARD COMPONENTS:
{dashboard_ctx.components_block()}

CURRENT DASHBOARD FIGURES:
{dashboard_ctx.figures_block()}

CURRENT FILTERS (already applied to the data above; None = unset):
{dashboard_ctx.filters_block()}
{selected}

{grammar_block(tags)}

Respond with valid JSON of the form:
{envelope}
{contract}
{rules}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]


def analysis_continuation(
    step_index: int,
    step_output: str,
    rows_in: int | None,
    rows_out: int | None,
    seconds: float,
    *,
    steps_left: int,
    tokens_left: int,
    seconds_left: float,
    conclude: bool,
) -> str:
    """The message that drives the read-only loop forward.

    The earlier continuation told the model, verbatim, to set `code` to ''
    and answer — which capped every analysis at exactly one executed step
    no matter what MAX_ANALYZE_STEPS said. This one permits iteration and
    shows the countdown, so concluding is a decision rather than an
    interruption.
    """
    cardinality = ""
    if rows_in is not None:
        arrow = f"{rows_in:,} rows in"
        if rows_out is not None:
            arrow += f" -> {rows_out:,} rows out"
        cardinality = f" ({arrow}, {seconds:.1f}s)"

    header = f"Observation for step {step_index}{cardinality}:\n{step_output}"
    if conclude:
        return (
            f"{header}\n\n"
            "Your budget is exhausted. Respond with the same JSON envelope, "
            'set "code" to "", and provide your final "answer" and "findings" '
            "based on the steps that already ran."
        )
    return (
        f"{header}\n\n"
        f"Budget remaining: {steps_left} steps, ~{tokens_left:,} tokens, "
        f"{seconds_left:.0f}s.\n"
        'Respond with the same JSON envelope. Set "code" to your next '
        'expression to keep investigating, or set "code" to "" and provide '
        'your final "answer" and "findings".'
    )


# ---------------------------------------------------------------------------
# Filter proposals (analyze + resolve-filters)
# ---------------------------------------------------------------------------
#
# The grammar recited below is the one enforced by `validate_filter_expr`
# in `depictio/models/components/filter_expr.py`, NOT the executor's
# allowlist. They are separate sandboxes guarding different lifetimes: a
# filter_expr is persisted on the dashboard document and re-evaluated on
# every render, whereas executor code runs once and is discarded. That is
# why this grammar is the narrower of the two and why `.over(...)`,
# `is_between` and `str.contains` appearing here says nothing about what
# `grammar_block()` will accept.

FILTER_PROPOSAL_CONTRACT = """\
Each FilterProposal is one of three kinds:
1. Set an existing interactive component (PREFERRED whenever a listed
   interactive component covers the column you want to constrain — the user
   sees and can adjust the widget):
   {"kind": "set_widget", "component_id": "<id from CURRENT FILTERS>",
    "value": <widget value>, "reason": "..."}
2. A Polars filter expression on the data collection (for conditions no
   widget covers). Grammar: col('<column>') with comparisons (==, !=, >,
   >=, <, <=), combined with & | ~ and parentheses; helpers: is_in([...]),
   is_between(a, b), str.contains/starts_with/ends_with, and mean/sum/min/
   max/count/median (optionally .over('<column>')):
   {"kind": "filter_expr", "filter_expr": "(col('depth') >= 30) & (col('qc') == 'pass')",
    "reason": "..."}
3. A percentile threshold — NEVER hand-compute percentile cutoffs; the
   server resolves the quantile on the live data. "top 3% of X" is
   q=0.97 with op ">=", "bottom 5%" is q=0.05 with op "<=":
   {"kind": "threshold", "threshold": {"column": "<numeric column>",
    "kind": "quantile", "q": 0.97, "op": ">="}, "reason": "..."}\
"""


def resolve_filters_messages(
    data_ctx: DataContext,
    dashboard_ctx: DashboardContext,
    user_prompt: str,
) -> list[dict]:
    """Single-shot NL → filter proposals (no ReAct loop).

    The model only plans filters here — no code execution, no prose
    analysis. Kept separate from `analyze_messages` so the drawer's
    "apply to dashboard" box stays fast and cheap.
    """
    system = f"""You translate a user's natural-language request into dashboard filters.

CONTEXT:
{data_ctx.metadata_block()}

DATASET SCHEMA:
{data_ctx.schema_block()}

SAMPLE ROWS:
{data_ctx.sample_block()}

CURRENT FILTERS (interactive components on the dashboard, with their applied values):
{dashboard_ctx.filters_block()}

Respond with valid JSON of the form:
{{
  "explanation": "one short sentence describing what will be filtered",
  "proposals": [<FilterProposal>, ...]
}}

{FILTER_PROPOSAL_CONTRACT}

- Reference only columns from DATASET SCHEMA.
- Emit the smallest set of proposals that satisfies the request.
- If the request is not a filtering request, return an empty proposals
  list and say why in "explanation".
- Do not wrap the JSON in markdown fences.
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------------------
# Whole-dashboard generation: plan prompt + per-component fill tail
# ---------------------------------------------------------------------------

# Types the planner may use, derived from the component Literal: every type a
# table collection can back (the generator reads table collections only) plus
# text, which has no data source. image needs an image collection and multiqc a
# MultiQC report, so neither is offered.
PLAN_COMPONENT_TYPES: tuple[ComponentType, ...] = tuple(
    t
    for t in get_args(ComponentType)
    if t == "text" or "table" in COMPONENT_DC_TYPES.get(t, frozenset())
)
# Offer lines in the plan prompt: a project recognised by several catalog
# tools would otherwise list every render of every module.
MAX_PLAN_OFFERS = 20
MAX_PLAN_ROLE_CANDIDATES = 3
# Above this many distinct values a MultiSelect is unusable and the schema
# check rejects it; the planner is told the same number.
MAX_MULTISELECT_DISTINCT = 50

PLAN_ANSWER_SHAPE = """{
  "title": "<dashboard title, a short noun phrase>",
  "subtitle": "<one sentence on what the dashboard answers>",
  "filter_sections": [
    {"name": "<section name>", "icon": "<Iconify id, e.g. mdi:filter-variant>",
     "color": "<Mantine palette name, e.g. teal>", "description": "<one sentence>"}
  ],
  "grid_sections": [
    {"name": "<section name>", "icon": "<Iconify id>", "color": "<palette name>",
     "description": "<one sentence; becomes the section header text>"}
  ],
  "components": [
    {"tag": "<unique snake_case handle>",
     "section": "<a filter_sections name for interactive, a grid_sections name otherwise>",
     "component_type": "<one of COMPONENT TYPES>",
     "data_collection_tag": "<tag copied from a dc[...] heading, or null for text>",
     "intent": "<one or two sentences: what it shows, which columns, which aggregation or chart>",
     "use": "<tool/render_id copied from CATALOG OFFERS; omit unless reproducing an offer>",
     "viz_kind": "<kind copied from ADVANCED VIZ CANDIDATES; advanced_viz only, omit otherwise>"}
  ]
}"""


def _plan_type_lines() -> str:
    return "\n".join(f"- {t}: {_ROUTING_HINTS[t]}" for t in PLAN_COMPONENT_TYPES)


def _plan_offer_lines(ctx: ProjectDataContext) -> list[str]:
    """`- use: "<tool>/<render_id>" on <dc_tag>: <type>, <title>`, at most MAX_PLAN_OFFERS."""
    lines: list[str] = []
    for c in ctx.collections:
        tag = c.data_collection_tag or c.data_collection_id
        for offer in c.catalog_offers:
            if len(lines) >= MAX_PLAN_OFFERS:
                return lines
            kind = offer.get("component_type") or "component"
            title = offer.get("title") or offer.get("render_id") or ""
            lines.append(f'- use: "{offer_use_id(offer)}" on {tag}: {kind}, {title}')
    return lines


def _plan_viz_lines(ctx: ProjectDataContext) -> list[str]:
    """`- <viz_kind> on <dc_tag>: <role> -> <best columns>; ...` per candidate."""
    lines: list[str] = []
    for c in ctx.collections:
        tag = c.data_collection_tag or c.data_collection_id
        for suggestion in c.viz_suggestions:
            roles = role_candidates_line(suggestion, MAX_PLAN_ROLE_CANDIDATES)
            lines.append(f"- {suggestion.get('viz_kind')} on {tag}: {roles}")
    return lines


def dashboard_plan_messages(
    ctx: ProjectDataContext,
    prompt: str,
    title: str | None,
    *,
    max_components: int,
    max_sections: int,
    warnings: list[str] | None = None,
) -> list[dict]:
    """System + user messages for the planning call of /ai/generate-dashboard.

    The model lays the dashboard out as a funnel (cohort filters, per-section
    KPI cards, figures, one reference table) over the project's collections
    and answers strict JSON: sections plus one entry per component with an
    intent the fill pass turns into YAML. It never writes component YAML
    here. The user message is the project block (schemas, samples, ranked
    advanced_viz candidates, catalog offers) followed by the user's intent
    and, when pinned, the title. `warnings` collects the context cuts
    `project_block` had to make.
    """
    offer_lines = _plan_offer_lines(ctx)
    viz_lines = _plan_viz_lines(ctx)
    offers_block = "\n".join(offer_lines) if offer_lines else "(none recognised)"
    viz_block = "\n".join(viz_lines) if viz_lines else "(none: do not plan advanced_viz)"

    system = f"""You plan a complete Depictio dashboard for a project's data collections. You do
not fill the components: you decide which ones exist, on which collection, in
which section, and describe each one's intent for a second pass that writes
its YAML.

LAYOUT (a funnel, top to bottom):
1. Cohort filters: interactive components in the left panel (filter_sections)
   that narrow every other tile.
2. Per-section KPI cards: headline numbers for what the section is about.
3. Figures: charts, and advanced_viz when a candidate below fits the data.
4. Reference table: one table at the end for the raw rows.
Each grid section opens with a header the server writes from its description.
Typical grid sections: an overview of cards, one or two analysis sections of
figures, a reference section holding the table.

COMPONENT TYPES:
{_plan_type_lines()}

CATALOG OFFERS (renders recognised on the collections; reproduce one by copying its use id):
{offers_block}

ADVANCED VIZ CANDIDATES (viz_kind on collection: role -> best columns):
{viz_block}

LIMITS:
- At most {max_components} components and at most {max_sections} grid sections.
- At least one interactive filter, in a filter section.
- Card rows come in multiples of 4 per section: plan 4 or 8 cards in a section,
  never 3.
- At most one table, last, in the reference section.
- MultiSelect only on columns with at most {MAX_MULTISELECT_DISTINCT} distinct
  values (see distinct= in the schema); numbers get a Slider or RangeSlider.
- advanced_viz only with a viz_kind listed under ADVANCED VIZ CANDIDATES for
  that collection; map only when the collection has latitude and longitude
  columns.
- Reference only columns listed under the collection you pick; text needs no
  collection (data_collection_tag null).
- A component's section names a section you declared: interactive components
  go in filter_sections, everything else in grid_sections.
- Tags are unique snake_case handles; intents are concrete (columns,
  aggregation, chart kind) so the fill pass needs no guessing.

Respond with valid JSON of the form:
{PLAN_ANSWER_SHAPE}
Do not wrap the JSON in markdown fences.
"""
    intent = prompt.strip() or "(none given: build the most useful overview of this project)"
    user = f"{ctx.project_block(warnings)}\n\nUSER INTENT:\n{intent}"
    if title:
        user += f"\n\nREQUESTED TITLE: {title}\nUse it as the dashboard title verbatim."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def component_fill_prompt(
    intent: str,
    *,
    dashboard_title: str,
    section: str,
    tag: str,
    siblings: list[str],
    use: str | None = None,
    viz_kind: str | None = None,
    role_bindings: dict | None = None,
) -> str:
    """The user prompt of one fill call: the planned intent plus a DASHBOARD CONTEXT tail.

    Appended to the intent handed to `component_from_prompt_messages`, so the
    single-component prompt (sheets, examples, rules) is reused unchanged and
    the model still knows which dashboard, section and neighbours the tile
    belongs to. `siblings` are the tags already filled; `use` pins a catalog
    render to reproduce; `viz_kind` and `role_bindings` pin an advanced_viz
    kind and the role -> column bindings the ranker chose.
    """
    lines = [
        "DASHBOARD CONTEXT:",
        f'- dashboard: "{dashboard_title}"',
        f'- section: "{section}"',
        f"- this component's tag: {tag}",
        f"- already filled in this dashboard: {', '.join(siblings) if siblings else '(none yet)'}",
    ]
    if use:
        lines.append(
            f'- reproduce the catalog render "{use}": keep its chart kind and column bindings.'
        )
    if viz_kind:
        bindings = ", ".join(f"{role}={column}" for role, column in (role_bindings or {}).items())
        line = f"- viz_kind: {viz_kind}"
        if bindings:
            line += f"; keep these role bindings: {bindings}"
        lines.append(line)
    lines.append(
        "- Show what the intent asks for and nothing the siblings already show; "
        "give it a short title."
    )
    return f"{intent.strip()}\n\n" + "\n".join(lines)
