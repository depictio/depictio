"""Shared expansion of the ``use: <tool>/<ref>`` dashboard authoring handle.

A dashboard tile can reference a catalog render instead of re-declaring its
binding inline::

    - use: multiqc/fastqc            # → component_type: multiqc, selected_module: fastqc
      data_collection_tag: multiqc_data
      config: { selected_plot: "Sequence Counts" }

``resolve_use`` looks the render up in the catalog (by **render id** first, then
by **output id** with a component-type/kind disambiguator) and returns the tile
dict augmented with ``component_type`` plus the kind-specific binding fields, so
the normal lite-component union routes and validates it like an inline tile.

This is the single source of truth for every component kind (advanced_viz,
multiqc, card, figure, table, interactive). ``AdvancedVizLiteComponent`` and
``DashboardDataLite`` both delegate here.
"""

from __future__ import annotations

from typing import Any


def _find_render(entry: Any, short: str, component_type: str | None, viz_kind: str | None):
    """Resolve ``<ref>`` to a single catalog Render.

    Render-id handle first (``ivar/manhattan``), then output-id fallback
    (``pangolin/report`` + a ``component_type``/``viz_kind`` to disambiguate when
    the output has more than one render).
    """
    # 1) Render-id handle — addresses one render directly, any component kind.
    render = next(
        (r for o in entry.outputs for r in (o.renders_as or []) if r.id == short),
        None,
    )
    if render is not None:
        return render

    # 2) Output-id fallback.
    output = next(
        (o for o in entry.outputs if o.id in (f"{entry.id}_{short}", short)),
        None,
    )
    if output is None:
        render_ids = [r.id for o in entry.outputs for r in (o.renders_as or []) if r.id]
        raise ValueError(
            f"`use`: tool {entry.id!r} has no render id or output {short!r} "
            f"(render ids {sorted(render_ids)}; outputs {[o.id for o in entry.outputs]})"
        )

    candidates = list(output.renders_as or [])
    if not candidates:
        raise ValueError(f"`use`: catalog output {output.id!r} has no renders")

    # Narrow by the tile's declared component_type when given.
    if component_type is not None:
        candidates = [r for r in candidates if r.component == component_type]
        if not candidates:
            raise ValueError(f"`use`: output {output.id!r} has no {component_type!r} render")
    # advanced_viz can still render several kinds — pick with viz_kind.
    if len(candidates) > 1 and viz_kind is not None:
        picked = [r for r in candidates if r.kind == viz_kind]
        if not picked:
            raise ValueError(
                f"`use`: output {output.id!r} has no advanced_viz kind {viz_kind!r} "
                f"(have {[r.kind for r in candidates]})"
            )
        candidates = picked

    if len(candidates) == 1:
        return candidates[0]
    if all(r.component == "advanced_viz" for r in candidates):
        raise ValueError(
            f"`use`: output {output.id!r} renders multiple kinds "
            f"{[r.kind for r in candidates]} — set `viz_kind` to pick one, or use a render id"
        )
    raise ValueError(
        f"`use`: output {output.id!r} renders multiple components "
        f"{[(r.component, r.kind) for r in candidates]} — set `component_type` "
        "(and `viz_kind` for advanced_viz) to pick one, or use a render id"
    )


def _render_to_fields(render: Any) -> dict[str, Any]:
    """Map a non-advanced_viz Render to its lite-component binding fields."""
    c = render.component
    if c == "multiqc":
        # `section` names the MultiQC module; the dashboard supplies the plot.
        return {"selected_module": render.section} if render.section else {}
    if c == "card":
        fields: dict[str, Any] = {
            "column_name": render.column,
            "aggregation": render.aggregation,
        }
        if render.aggregations:
            fields["aggregations"] = render.aggregations
        if render.secondary_layout is not None:
            fields["secondary_layout"] = render.secondary_layout
        if render.breakdown_col is not None:
            fields["breakdown_col"] = render.breakdown_col
        if render.top_n_count is not None:
            fields["top_n_count"] = render.top_n_count
        if render.coverage_max is not None:
            fields["coverage_max"] = render.coverage_max
        if render.filter_expr is not None:
            fields["filter_expr"] = render.filter_expr
        return fields
    if c == "figure":
        if render.code:
            return {"mode": "code", "code_content": render.code}
        fields = {}
        if render.visu_type is not None:
            fields["visu_type"] = render.visu_type
        if render.dict_kwargs:
            fields["dict_kwargs"] = dict(render.dict_kwargs)
        return fields
    if c == "interactive":
        return {
            "interactive_component_type": render.interactive_component_type,
            "column_name": render.column,
        }
    # table (and any future binding-free kind)
    return {}


def resolve_use(data: dict[str, Any]) -> dict[str, Any]:
    """Expand a tile dict carrying ``use: <tool>/<ref>`` into a typed-component dict.

    Returns ``data`` unchanged when there is no ``use`` handle. Otherwise returns
    a new dict with ``component_type`` set and the render's bindings inherited;
    user-supplied ``config:`` keys always win over inherited bindings.
    """
    if not isinstance(data, dict) or not data.get("use"):
        return data

    # Lazy import: avoids a module-load cycle (catalog ← models ← component).
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    ref = data["use"]
    if not isinstance(ref, str) or "/" not in ref:
        raise ValueError(f"`use` must be '<tool>/<render-id-or-output>', got {ref!r}")
    tool_id, short = ref.split("/", 1)

    entries = {e.id: e for e in load_catalog_entries()}
    entry = entries.get(tool_id)
    if entry is None:
        raise ValueError(f"`use`: unknown catalog tool {tool_id!r} (have {sorted(entries)})")

    user_cfg = data.get("config") or {}
    render = _find_render(
        entry,
        short,
        component_type=data.get("component_type"),
        viz_kind=data.get("viz_kind") or user_cfg.get("viz_kind"),
    )

    # advanced_viz keeps its bindings under a nested `config` (role → <role>_col).
    if render.component == "advanced_viz":
        inherited = {f"{role}_col": col for role, col in (render.roles or {}).items()}
        merged = {**inherited, **user_cfg, "viz_kind": render.kind}
        return {**data, "component_type": "advanced_viz", "viz_kind": render.kind, "config": merged}

    # Flat-field kinds (multiqc/card/figure/table/interactive): the catalog render
    # supplies default bindings, the tile's own explicit top-level fields win over
    # them (so a dashboard keeps its overrides inline), and a `config:` block wins
    # over everything (parity with the advanced_viz override channel).
    inherited = _render_to_fields(render)
    explicit = {k: v for k, v in data.items() if k != "config"}
    out = {**inherited, **explicit, **user_cfg}
    out["component_type"] = render.component
    return out
