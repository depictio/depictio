"""Dash-free payload computer for ``depictio catalog preview`` (React viewer).

Builds, for a catalog output's ``renders_as`` on its bundled ``fixture``, the
``window.__CATALOG_PREVIEW__`` blob the standalone viewer bundle consumes: a list
of ``StoredMetadata`` dicts + a ``data`` map of per-render payloads in the exact
shapes ``packages/depictio-react-core/src/api.ts`` returns. The standalone bundle
renders these through the viewer's real ``ComponentRenderer`` (see
``depictio/viewer/src/catalog-preview/``).

No Dash imports: figures use plotly-express / a trusted exec of the catalog's
code snippet; cards/tables use polars. ``advanced_viz`` / ``multiqc`` / ``image``
are emitted as metadata without data yet (the bundle shows a friendly
placeholder) — Phase B wires their computes.
"""

from __future__ import annotations

import json
import math
from typing import Any

import yaml

from depictio.models.components.advanced_viz.catalog import CATALOG_DIR

# Prebuilt single-file viewer bundle (`pnpm run build:catalog-preview`).
TEMPLATE_PATH = CATALOG_DIR.parent / "viewer" / "dist-catalog-preview" / "catalog-preview.html"

# depictio brand colourway (from depictio/dash/colors.py — inlined to stay Dash-free).
_DEPICTIO_COLORWAY = [
    "#9966CC",
    "#6495ED",
    "#45B8AC",
    "#8BC34A",
    "#F9CB40",
    "#F68B33",
    "#E6779F",
    "#7A5DC7",
]
_CARD_ACCENTS = ["#45B8AC", "#7A5DC7", "#6495ED", "#8BC34A", "#F68B33", "#E6779F"]
_TABLE_PREVIEW_ROWS = 1000


class CatalogPayloadError(Exception):
    """Raised when a catalog output cannot be turned into a preview payload."""


def _load_fixture_df(output: Any):  # -> pl.DataFrame
    import polars as pl

    # Fixtures are co-located in catalog/<tool>/ and resolved by the model
    # (`_source_dir / fixture`), NOT under projects/.
    path = output.fixture_file()
    if path is None:
        raise CatalogPayloadError(
            f"output {output.id!r} has no 'fixture' to preview — add a bundled sample "
            "co-located in catalog/<tool>/"
        )
    if not path.exists():
        raise CatalogPayloadError(f"fixture not found: {path}")
    if path.suffix == ".parquet":
        return pl.read_parquet(path)
    sep = "\t" if path.suffix == ".tsv" else ","
    return pl.read_csv(path, separator=sep).head(_TABLE_PREVIEW_ROWS)


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------


def _apply_template(fig) -> None:
    fig.update_layout(
        template="plotly_white",
        colorway=_DEPICTIO_COLORWAY,
        margin={"l": 50, "r": 20, "t": 40, "b": 50},
        autosize=True,
    )


def _figure_payload(df, render) -> dict[str, Any]:
    import plotly.express as px
    import plotly.graph_objects as go  # noqa: F401 — exposed to catalog code

    if render.code:
        ns: dict[str, Any] = {"df": df, "px": px, "go": go}
        import numpy as np
        import pandas as pd
        import polars as pl

        ns.update(pd=pd, pl=pl, np=np)
        try:
            exec(render.code, ns)  # noqa: S102 — trusted, repo-authored catalog snippet
        except Exception as exc:
            raise CatalogPayloadError(f"figure code failed: {exc}") from exc
        fig = ns.get("fig")
        if fig is None or not hasattr(fig, "to_plotly_json"):
            raise CatalogPayloadError("figure code did not define a Plotly 'fig'")
    else:
        fn = getattr(px, render.visu_type or "", None)
        if fn is None:
            raise CatalogPayloadError(f"unknown plotly-express visu_type {render.visu_type!r}")
        fig = fn(df.to_pandas(), **render.dict_kwargs)

    _apply_template(fig)
    return {
        "figure": fig.to_plotly_json(),
        "metadata": {"visu_type": render.visu_type or "code", "filter_applied": False},
    }


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


def _aggregate(df, column: str, aggregation: str):
    if column not in df.columns:
        raise CatalogPayloadError(f"card column {column!r} absent from fixture {list(df.columns)}")
    col = df[column]
    fn = {
        "count": col.len,
        "sum": col.sum,
        "average": col.mean,
        "median": col.median,
        "min": col.min,
        "max": col.max,
        "variance": col.var,
        "std_dev": col.std,
        "nunique": col.n_unique,
    }.get(aggregation)
    if fn is not None:
        value = fn()
    elif aggregation == "range":
        value = col.max() - col.min()
    elif aggregation in ("q1", "q3"):
        value = col.quantile(0.25 if aggregation == "q1" else 0.75, interpolation="linear")
    elif aggregation == "mode":
        modes = col.mode()
        value = modes[0] if len(modes) else None
    else:
        raise CatalogPayloadError(f"unsupported card aggregation {aggregation!r}")
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _box_plot_stats(df, column: str) -> dict[str, Any]:
    """Tukey box-plot stats for the DepictioCard `box_plot` secondary layout.

    Matches the server's ``box_plot_stats`` aggregation shape consumed by
    ``card/SecondaryMetrics.tsx`` (min/max/q1/q3/median/mean + 1.5×IQR whiskers
    + outliers).
    """
    if column not in df.columns:
        raise CatalogPayloadError(f"card column {column!r} absent from fixture {list(df.columns)}")
    col = df[column].drop_nulls()
    if len(col) == 0:
        raise CatalogPayloadError(f"box_plot card column {column!r} has no values")
    q1 = float(col.quantile(0.25, interpolation="linear"))
    q3 = float(col.quantile(0.75, interpolation="linear"))
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = col.filter((col >= lo_fence) & (col <= hi_fence))
    outliers = col.filter((col < lo_fence) | (col > hi_fence)).to_list()
    return {
        "min": float(col.min()),
        "max": float(col.max()),
        "q1": q1,
        "q3": q3,
        "median": float(col.median()),
        "mean": float(col.mean()),
        "lower_whisker": float(inside.min()) if len(inside) else float(col.min()),
        "upper_whisker": float(inside.max()) if len(inside) else float(col.max()),
        "outliers": [float(x) for x in outliers],
        "outlier_count": len(outliers),
    }


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


def _table_payload(df) -> dict[str, Any]:
    import polars as pl

    columns = []
    for name in df.columns:
        numeric = df[name].dtype in (
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
            pl.Float32,
            pl.Float64,
        )
        columns.append(
            {
                "field": name,
                "headerName": name.replace("_", " ").title(),
                "type": "numericColumn" if numeric else "text",
            }
        )
    return {"columns": columns, "rows": df.to_dicts(), "total": df.height}


# ---------------------------------------------------------------------------
# Advanced viz (client-side `fetchAdvancedVizData` kinds)
# ---------------------------------------------------------------------------

# Kinds whose viewer renderer computes server-side via a Celery dispatch/poll
# (not wired into the offline preview yet) — shown as a placeholder.
_ADVANCED_VIZ_DISPATCH_KINDS = frozenset(
    {"embedding", "upset_plot", "upset", "coverage_track", "sankey"}
)


def _advanced_viz_config_and_data(df, render) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the advanced-viz ``config`` blob + the projected role columns.

    Mirrors ``buildAdvancedVizConfigBlob`` (``<role>_col`` per role; sunburst's
    ``ranks`` → ``rank_cols``; ``compute_method`` stays scalar). The renderer
    fetches the role columns via ``fetchAdvancedVizData`` and plots client-side,
    so the payload is just those columns projected from the fixture.
    """
    config: dict[str, Any] = {"viz_kind": render.kind}
    columns: list[str] = []
    for role, col in (render.roles or {}).items():
        if render.kind == "sunburst" and role == "ranks":
            config["rank_cols"] = col
            columns.extend(col if isinstance(col, list) else [col])
        elif role == "compute_method":
            config["compute_method"] = col
        else:
            config[f"{role}_col"] = col
            columns.append(col)

    # Sunburst needs ≥2 hierarchical rank columns. Catalog cards bind only
    # `abundance` and let the runtime auto-bind the taxonomy ranks by name;
    # mirror that here so the offline preview has its hierarchy.
    if render.kind == "sunburst" and "rank_cols" not in config:
        _TAXO_RANKS = ("Domain", "Kingdom", "Phylum", "Class", "Order", "Family", "Genus", "Species")
        inferred = [c for c in _TAXO_RANKS if c in df.columns]
        if len(inferred) >= 2:
            config["rank_cols"] = inferred
            columns.extend(inferred)

    present = [c for c in dict.fromkeys(columns) if c in df.columns]
    missing = [c for c in dict.fromkeys(columns) if c not in df.columns]
    if missing:
        raise CatalogPayloadError(
            f"advanced_viz {render.kind}: column(s) {missing} absent from fixture {list(df.columns)}"
        )
    rows = {c: df[c].to_list() for c in present}
    return config, {
        "columns": present,
        "rows": rows,
        "row_count": df.height,
        "filter_applied": False,
    }


def _coverage_track_payload(df, render) -> tuple[dict[str, Any], dict[str, Any]]:
    """coverage_track: the renderer plots client-side from projected columns, so
    the dispatch 'result' is just the role columns + a summary (no Celery)."""
    roles = render.roles or {}
    chrom, pos, val = roles.get("chromosome"), roles.get("position"), roles.get("value")
    for name, col in (("chromosome", chrom), ("position", pos), ("value", val)):
        if not col or col not in df.columns:
            raise CatalogPayloadError(
                f"coverage_track: role '{name}' column {col!r} absent from fixture {list(df.columns)}"
            )
    sample_col = "sample" if "sample" in df.columns else None
    end_col = "end" if "end" in df.columns else None

    config: dict[str, Any] = {
        "viz_kind": "coverage_track",
        "chromosome_col": chrom,
        "position_col": pos,
        "value_col": val,
    }
    if sample_col:
        config["sample_col"] = sample_col
    if end_col:
        config["end_col"] = end_col

    proj = [c for c in dict.fromkeys([chrom, pos, val, end_col, sample_col]) if c]
    result = {
        "rows": {c: df[c].to_list() for c in proj},
        "columns": {
            "chromosome": chrom,
            "position": pos,
            "value": val,
            "end": end_col,
            "sample": sample_col,
            "category": None,
        },
        "summary": {
            "row_count": df.height,
            "chromosomes": df[chrom].unique().to_list(),
            "samples": df[sample_col].unique().to_list() if sample_col else [],
            "n_samples": df[sample_col].n_unique() if sample_col else 0,
            "mean_value": float(df[val].mean()),
            "max_value": float(df[val].max()),
        },
        "row_count": df.height,
    }
    return config, result


# ---------------------------------------------------------------------------
# MultiQC (pre-compute Plotly figures from the parquet plot_input_data column)
# ---------------------------------------------------------------------------

_MULTIQC_MAX_PLOTS = 3


def _multiqc_module(anchor: str) -> str:
    """MultiQC module that owns a plot anchor — its leading token.

    Anchors are prefixed by the producing module: ``fastqc_*``, ``samtools-*``,
    ``bcftools_stats_*``, ``mosdepth-*``, … One catalog output per module keys
    off this so each ``section: <module>`` card surfaces only that tool's plots.
    """
    import re

    return re.split(r"[-_]", anchor or "")[0]


def _multiqc_payload(df, render) -> list[dict[str, Any]]:
    """Pre-compute Plotly figures for a multiqc render from the parquet fixture.

    Returns a list of ``{"figure": <plotly_json>, "anchor": str}`` dicts —
    one per successfully rendered plot.  The caller stores them in
    ``data["figures"]`` keyed by ``<index>-<i>``.
    """
    import json as _json

    from multiqc.core.special_case_modules.load_multiqc_data import load_plot_input

    section = render.section or "report"

    # Rows with renderable plot data; for a per-module card keep only the plots
    # whose anchor belongs to that module ("report" = the whole parquet).
    plot_rows = df.filter(df["plot_input_data"].is_not_null())
    rows_sorted = [
        r
        for r in plot_rows.iter_rows(named=True)
        if section == "report" or _multiqc_module(r["anchor"]) == section
    ]

    results = []
    for row in rows_sorted:
        if len(results) >= _MULTIQC_MAX_PLOTS:
            break
        try:
            pid = _json.loads(row["plot_input_data"])
            _, plot = load_plot_input(pid)
            if plot is None or isinstance(plot, str) or not hasattr(plot, "get_figure"):
                continue  # not a renderable Plot (table/raw section)
            fig = plot.get_figure(0)
            fig.update_layout(
                template="plotly_white",
                margin={"l": 50, "r": 20, "t": 50, "b": 50},
                autosize=True,
            )
            results.append({"figure": fig.to_plotly_json(), "anchor": row["anchor"]})
        except Exception:  # noqa: BLE001 — skip unrenderable plots gracefully
            continue
    return results


# ---------------------------------------------------------------------------
# ComplexHeatmap (pre-computed offline via plotly-complexheatmap)
# ---------------------------------------------------------------------------


def _complex_heatmap_payload(df, render) -> dict[str, Any]:
    """Pre-compute a ComplexHeatmap figure from the fixture.

    Returns a ``ComplexHeatmapResult``-shaped dict that the mockApi's
    ``dispatchComplexHeatmap`` / ``finishedJob`` exposes via ``DATA().compute[dc_id]``.

    Roles:
      - ``index``: row-label column (required).
      - ``column`` + ``value``: present iff the fixture is in long format and
        needs pivoting (long → wide) before clustering.
    """
    import polars as pl
    from plotly_complexheatmap import ComplexHeatmap

    _NUMERIC = (
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    )

    roles = render.roles or {}
    index_col = roles.get("index")
    pivot_col = roles.get("column")
    value_col = roles.get("value")

    # Main's catalog binds complex_heatmap with `roles: {}` and lets the live
    # backend infer structure from the DC. Replicate that inference so the
    # offline preview renders: index = first string column; if the rest is a
    # single numeric value + extra category columns it's long-format (pivot
    # index×highest-cardinality-category → value), else it's a wide numeric matrix.
    if not index_col:
        str_cols = [c for c in df.columns if df[c].dtype in (pl.Utf8, pl.Categorical)]
        num_cols = [c for c in df.columns if df[c].dtype in _NUMERIC]
        if not str_cols:
            raise CatalogPayloadError(
                f"complex_heatmap: cannot infer index — no string column in {list(df.columns)}"
            )
        index_col = str_cols[0]
        other_str = [c for c in str_cols if c != index_col]
        if len(num_cols) == 1 and other_str:
            pivot_col = max(other_str, key=lambda c: df[c].n_unique())
            value_col = num_cols[0]

    if index_col not in df.columns:
        raise CatalogPayloadError(
            f"complex_heatmap: index column {index_col!r} absent from fixture {list(df.columns)}"
        )

    if pivot_col and value_col:
        for c in (pivot_col, value_col):
            if c not in df.columns:
                raise CatalogPayloadError(
                    f"complex_heatmap: pivot column {c!r} absent from fixture {list(df.columns)}"
                )
        wide = df.pivot(values=value_col, index=index_col, on=pivot_col, aggregate_function="mean")
        pdf = wide.fill_null(0.0).to_pandas().set_index(index_col)
    else:
        numeric_cols = [
            c
            for c in df.columns
            if c != index_col
            and df[c].dtype
            in (
                pl.Float32,
                pl.Float64,
                pl.Int8,
                pl.Int16,
                pl.Int32,
                pl.Int64,
                pl.UInt8,
                pl.UInt16,
                pl.UInt32,
                pl.UInt64,
            )
        ]
        if not numeric_cols:
            raise CatalogPayloadError(
                f"complex_heatmap: no numeric value columns found (index={index_col!r})"
            )
        pdf = df.select([index_col] + numeric_cols).to_pandas().set_index(index_col)

    hm = ComplexHeatmap(pdf, cluster_rows=True, cluster_cols=True)
    fig = hm.to_plotly()
    _apply_template(fig)
    # Shape mirrors ComplexHeatmapResult (row_count/col_count/compute_ms expected by renderer)
    return {
        "figure": fig.to_plotly_json(),
        "row_count": len(pdf),
        "col_count": len(pdf.columns),
        "compute_ms": 0,
        "load_ms": 0,
    }


# ---------------------------------------------------------------------------
# Single-output payload
# ---------------------------------------------------------------------------


def _empty_data() -> dict[str, Any]:
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


# Per-kind preview heights (advanced-viz plots vary a lot in vertical density).
_AV_PREVIEW_HEIGHT = {
    "oncoplot": 700,
    "complex_heatmap": 680,
    "upset_plot": 560,
    "upset": 560,
    "sankey": 560,
    "manhattan": 460,
    "lollipop": 420,
}
_FIGURE_PREVIEW_HEIGHT = 540
_FIXTURE_PREVIEW_ROWS = 50


def _advanced_viz_defaults(df, render, config: dict[str, Any]) -> None:
    """Set sensible default viz params so the plot isn't bare on first open."""
    if render.kind == "manhattan":
        score_col = (render.roles or {}).get("score")
        if score_col and score_col in df.columns and "score_threshold" not in config:
            try:
                config["score_threshold"] = round(float(df[score_col].quantile(0.95)), 4)
            except Exception:  # noqa: BLE001 — defaults are best-effort
                pass
        config.setdefault("top_n_labels", 8)


def advanced_viz_persist_config(output: Any, render, df: Any = None) -> dict[str, Any] | None:
    """The ``config`` blob to persist for an advanced_viz render.

    Returns *exactly* the config the offline preview renders with — role bindings
    (``<role>_col`` + the ``rank_cols`` / ``compute_method`` special cases) plus
    the same data-derived viz-control defaults (e.g. manhattan ``score_threshold``,
    ``top_n_labels``). Mirrors ``buildAdvancedVizConfigBlob`` on the JS side, so a
    component added from the catalog renders identically to the catalog preview
    instead of re-deriving a bare config from roles alone.

    Returns ``None`` (caller falls back to the role-only blob) when the render is
    not advanced_viz or can't be grounded against the fixture (missing file /
    missing columns) — never raises, so it can be called inline from compose.
    """
    if render.component != "advanced_viz":
        return None
    try:
        if df is None:
            df = _load_fixture_df(output)
    except CatalogPayloadError:
        return None
    if df is None:
        return None
    try:
        if render.kind == "coverage_track":
            config, _ = _coverage_track_payload(df, render)
            return config
        config, _ = _advanced_viz_config_and_data(df, render)
        _advanced_viz_defaults(df, render, config)
        return config
    except CatalogPayloadError:
        return None


def _render_variant(render) -> str:
    """Sub-label qualifying a component (the type itself is shown as a badge).

    e.g. figure → ``code``/``box``; advanced_viz → ``manhattan``; card → ``mean``.
    """
    if render.component == "figure":
        return "code" if render.code else str(render.visu_type or "")
    if render.component == "card":
        return str(render.aggregation or "")
    if render.component == "advanced_viz":
        return str(render.kind or "")
    return ""


class _LiteralStr(str):
    """Marker so multi-line strings (figure code) dump as a YAML ``|`` block."""


def _literal_representer(dumper: yaml.Dumper, data: _LiteralStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


yaml.add_representer(_LiteralStr, _literal_representer)


def _render_yaml(render) -> str:
    """The render's own ``renders_as`` declaration, as a copy-pasteable YAML item.

    Replaces per-channel binding chips: the raw YAML *is* the parameters (roles,
    plotly kwargs, code…), so a contributor sees — and can lift — the exact
    catalog spec that produced the component below it.
    """
    spec = render.model_dump(exclude_none=True, exclude_defaults=True)
    # keep `component` first, then the rest in declaration order
    ordered = {"component": spec.pop("component")}
    ordered.update(spec)
    for k, v in ordered.items():
        if isinstance(v, str) and "\n" in v:
            ordered[k] = _LiteralStr(v.rstrip("\n"))
    body = yaml.dump(
        ordered, sort_keys=False, default_flow_style=False, allow_unicode=True, width=100
    )
    lines = body.rstrip("\n").splitlines()
    # render as a single YAML list item ("- component: …")
    return "\n".join(["- " + lines[0]] + ["  " + ln for ln in lines[1:]])


def _output_info(output: Any, tool: Any = None, df: Any = None) -> dict[str, Any]:
    """Identity + provenance shown in the preview header (so it's not 'blind').

    Identity is per-output overridable but defaults to the parent tool's — so a
    flat single-output tool (e.g. iVar) still shows its nf-core / bio.tools / EDAM
    links even though they're declared at the tool level. ``df`` is optional: the
    gallery lists outputs whose fixture couldn't load, so the data-shape fields
    are only added when a fixture was read.
    """
    out_edam = list(output.edam_operations) + list(output.edam_formats)
    edam = out_edam or (list(tool.edam_topics) if tool else [])
    info: dict[str, Any] = {
        "id": output.id,
        "description": output.description or "",
        "mode": output.mode,
        "find": output.find.model_dump(exclude_none=True),
        "recipe": output.recipe,
        "fixture": output.fixture,
        "nf_core_url": output.nf_core_url or (tool.nf_core_url if tool else None),
        "biotools_url": output.biotools_url or (tool.biotools_url if tool else None),
        "edam": edam,
    }
    if df is not None:
        info["n_rows"] = df.height
        info["n_cols"] = df.width
        info["columns"] = list(df.columns)
    return info


def _render_meta(render, output: Any, i: int) -> dict[str, Any]:
    """The data-free part of a render's metadata (badge type, variant, YAML, ids).

    Shared by the live preview (which then adds computed data) and the gallery's
    metadata-only path (which lists badges + copyable YAML without a fixture).
    """
    index = f"{output.id}-{i}"
    meta: dict[str, Any] = {
        "index": index,
        "component_type": render.component,
        "wf_id": "catalog::wf",
        "dc_id": f"catalog::{index}",
        "_variant": _render_variant(render),
        "_yaml": _render_yaml(render),
    }
    binds = _render_binds(render)
    if binds:
        meta["_binds"] = binds
    return meta


def _render_binds(render) -> dict[str, str]:
    """Flat ``label → column/value`` map of what a render binds — the answer to
    "what columns does this need?". advanced_viz roles, a figure's plotly-express
    kwargs, or a card's column+aggregation. Surfaced as a "Binds" table on the
    detail page and folded into the gallery search haystack."""
    binds: dict[str, str] = {}
    for role, col in (render.roles or {}).items():
        binds[role] = ", ".join(col) if isinstance(col, list) else str(col)
    for arg, col in (getattr(render, "dict_kwargs", None) or {}).items():
        binds[arg] = str(col)
    if getattr(render, "column", None):
        binds["column"] = str(render.column)
    if getattr(render, "aggregation", None):
        binds["aggregation"] = str(render.aggregation)
    return binds


def _fixture_preview(df) -> dict[str, Any]:
    head = df.head(_FIXTURE_PREVIEW_ROWS)
    return {"columns": list(df.columns), "rows": head.to_dicts(), "total": df.height}


def _normalise_theme(theme: str) -> str:
    return "dark" if theme == "dark" else "light"


_NON_TABULAR_COMPONENTS = frozenset({"image", "interactive", "text", "map"})


def build_payload(output: Any, theme: str = "light", tool: Any = None) -> dict[str, Any]:
    """Compute the full ``window.__CATALOG_PREVIEW__`` blob for an output."""
    # Outputs whose renders are all non-tabular (multiqc, image, …) don't need a
    # fixture — they show metadata + copyable YAML with a friendly placeholder.
    all_non_tabular = all(r.component in _NON_TABULAR_COMPONENTS for r in output.renders_as)
    df = None if all_non_tabular else _load_fixture_df(output)
    data = _empty_data()
    renders: list[dict[str, Any]] = []

    for i, render in enumerate(output.renders_as):
        meta = _render_meta(render, output, i)
        index = meta["index"]
        dc_id = meta["dc_id"]
        comp = render.component
        try:
            if comp == "multiqc":
                plots = _multiqc_payload(df, render) if df is not None else []
                if plots:
                    meta["_preview_height"] = 460
                    # mockApi.renderMultiQC looks up DATA().multiqc[metadata.index]
                    # and expects {figure: <plotly_json>} — one figure per render.
                    data["multiqc"][index] = {"figure": plots[0]["figure"]}
                    meta["_multiqc_anchor"] = plots[0]["anchor"]
                else:
                    meta["_unsupported"] = "preview for 'multiqc' is not wired yet"
                renders.append(meta)
                continue
            if comp in _NON_TABULAR_COMPONENTS:
                meta["_unsupported"] = f"preview for '{comp}' is not wired yet"
                renders.append(meta)
                continue
            if df is None:
                meta["_error"] = "no fixture — cannot preview"
                renders.append(meta)
                continue
            if comp == "figure":
                meta["visu_type"] = render.visu_type or "scatter"
                if render.code:
                    meta["mode"] = "code"  # code shown via the _yaml block
                meta["_preview_height"] = _FIGURE_PREVIEW_HEIGHT
                data["figures"][index] = _figure_payload(df, render)
            elif comp == "card":
                meta["column_name"] = render.column
                meta["icon_color"] = _CARD_ACCENTS[i % len(_CARD_ACCENTS)]
                if render.secondary_layout == "box_plot":
                    # Tukey box-plot card: hero = declared aggregation (defaults to
                    # median), distribution in the strip.
                    stats = _box_plot_stats(df, render.column)
                    meta["title"] = render.column
                    meta["aggregation"] = render.aggregation or "median"
                    meta["aggregations"] = ["box_plot_stats"]
                    meta["secondary_layout"] = "box_plot"
                    meta["icon_name"] = "mdi:chart-box-outline"
                    data["cards"]["values"][index] = (
                        _aggregate(df, render.column, render.aggregation)
                        if render.aggregation
                        else stats["median"]
                    )
                    data["cards"]["secondary"][index] = {"box_plot_stats": stats}
                    data["cards"]["aggregations"][index] = ["box_plot_stats"]
                else:
                    meta["aggregation"] = render.aggregation
                    meta["icon_name"] = "mdi:chart-line"
                    data["cards"]["values"][index] = _aggregate(
                        df, render.column, render.aggregation
                    )
            elif comp == "table":
                data["tables"][index] = _table_payload(df)
            elif comp == "advanced_viz" and render.kind == "coverage_track":
                config, result = _coverage_track_payload(df, render)
                meta["viz_kind"] = render.kind
                meta["config"] = config
                meta["_preview_height"] = _AV_PREVIEW_HEIGHT.get("coverage_track", 460)
                data["compute"][dc_id] = result
            elif comp == "advanced_viz" and render.kind == "complex_heatmap":
                # mockApi.dispatchComplexHeatmap → finishedJob(dc_id) → DATA().compute[dc_id]
                # Store ComplexHeatmapResult so ComplexHeatmapRenderer gets its figure immediately.
                meta["viz_kind"] = "complex_heatmap"
                meta["_preview_height"] = _AV_PREVIEW_HEIGHT.get("complex_heatmap", 680)
                data["compute"][dc_id] = _complex_heatmap_payload(df, render)
            elif comp == "advanced_viz" and render.kind in _ADVANCED_VIZ_DISPATCH_KINDS:
                meta["_unsupported"] = (
                    f"preview for advanced_viz '{render.kind}' (server-computed) is not wired yet"
                )
            elif comp == "advanced_viz":
                config, av = _advanced_viz_config_and_data(df, render)
                _advanced_viz_defaults(df, render, config)
                meta["viz_kind"] = render.kind
                meta["config"] = config
                meta["_preview_height"] = _AV_PREVIEW_HEIGHT.get(render.kind, 480)
                data["advancedVizData"][dc_id] = av
            else:
                # Phase B: multiqc / image / map / interactive / text.
                meta["_unsupported"] = (
                    f"preview for '{comp}' is not wired yet (figure/card/table/advanced_viz supported)"
                )
        except Exception as exc:  # noqa: BLE001 — one bad render degrades to a per-card error, never blanks the page
            meta["_error"] = str(exc)
        renders.append(meta)

    return {
        "output": _output_info(output, tool, df),
        "fixturePreview": _fixture_preview(df) if df is not None else None,
        "theme": _normalise_theme(theme),
        "renders": renders,
        "data": data,
    }


# ---------------------------------------------------------------------------
# Gallery (all outputs on one page; one bundle, two CLI entry points)
# ---------------------------------------------------------------------------


def _merge_data(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Fold one output's ``data`` map into the gallery-wide map.

    Keys are globally unique (``<output.id>-<i>`` / ``catalog::<index>``), so a
    flat ``dict.update`` never collides — including the nested ``cards`` sub-maps.
    """
    for key, value in src.items():
        if key == "cards":
            for sub in ("values", "secondary", "aggregations"):
                dst["cards"][sub].update(value[sub])
        else:
            dst[key].update(value)


def _entry_from_blob(blob: dict[str, Any]) -> dict[str, Any]:
    """The successful gallery entry (output meta + renders + fixture) from a built blob."""
    return {
        "output": blob["output"],
        "fixturePreview": blob["fixturePreview"],
        "renders": blob["renders"],
        "ok": True,
    }


def _output_entry(output: Any, tool: Any, theme: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """One gallery entry + the data to merge. Resilient: an output whose fixture
    can't load (or has none) is still listed with badges + copyable YAML."""
    try:
        blob = build_payload(output, theme, tool)
        return _entry_from_blob(blob), blob["data"]
    except Exception as exc:  # noqa: BLE001 — one unbuildable output must not sink the whole gallery
        entry = {
            "output": _output_info(output, tool),
            "fixturePreview": None,
            "renders": [_render_meta(r, output, i) for i, r in enumerate(output.renders_as)],
            "ok": False,
            "error": str(exc),
        }
        return entry, {}


def _tool_dict(tool: Any, outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """A tool group (identity + its output entries) in the gallery payload."""
    return {
        "id": tool.id,
        "name": tool.name,
        "description": tool.description or "",
        "homepage": tool.homepage,
        "nf_core_url": tool.nf_core_url,
        "biotools_url": tool.biotools_url,
        "edam_topics": list(tool.edam_topics),
        "outputs": outputs,
    }


def build_gallery_payload(entries: Any, theme: str = "light") -> dict[str, Any]:
    """Compute the full multi-output ``window.__CATALOG_PREVIEW__`` blob.

    Same schema as a single preview but with every tool/output embedded and
    ``initialOutputId`` left null so the bundle opens on the gallery grid.
    """
    data = _empty_data()
    tools: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in entries:
        outputs = []
        for output in entry.outputs:
            # _merge_data folds all outputs into one data map keyed by output id —
            # an id reused across tools would silently overwrite. IDs are unique
            # within a tool (validated); enforce it across tools here too.
            if output.id in seen_ids:
                raise CatalogPayloadError(
                    f"output id {output.id!r} appears in more than one tool — "
                    "catalog output ids must be globally unique for the gallery"
                )
            seen_ids.add(output.id)
            out_entry, out_data = _output_entry(output, entry, theme)
            _merge_data(data, out_data)
            outputs.append(out_entry)
        tools.append(_tool_dict(entry, outputs))
    return {
        "theme": _normalise_theme(theme),
        "initialOutputId": None,
        "tools": tools,
        "data": data,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _logo_data_uris() -> dict[str, str]:
    """Return base64 data-URIs for the MultiQC logo SVGs (offline-safe)."""
    import base64

    logos_dir = TEMPLATE_PATH.parent.parent / "public" / "logos"
    result: dict[str, str] = {}
    for name in ("multiqc_icon_dark.svg", "multiqc_icon_white.svg"):
        path = logos_dir / name
        if path.exists():
            b64 = base64.b64encode(path.read_bytes()).decode()
            result[f"/dashboard-beta/logos/{name}"] = f"data:image/svg+xml;base64,{b64}"
    return result


def _json_safe(o: Any) -> Any:
    """Replace non-finite floats (NaN / ±Infinity) with ``None``.

    Plotly figures and computed stats can carry NaN/Inf; Python's ``json`` emits
    them as bare ``NaN``/``Infinity`` tokens, which are valid for ``json.loads``
    but make the browser's ``JSON.parse`` throw — blanking the embedded bundle.
    """
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    # numpy arrays / scalars — Plotly UI-mode figures (px.* on a pandas frame)
    # keep numpy in their traces; json.dumps(default=str) would stringify an
    # ndarray into a useless "['a' 'b']" blob. Convert to plain Python first.
    if hasattr(o, "dtype") and hasattr(o, "tolist"):
        return _json_safe(o.tolist())
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def _inject(payload: dict[str, Any]) -> str:
    """Embed a computed payload into the prebuilt single-file bundle."""
    if not TEMPLATE_PATH.exists():
        raise CatalogPayloadError(
            f"catalog-preview bundle not built: {TEMPLATE_PATH} is missing — run "
            f"`cd depictio/viewer && pnpm run build:catalog-preview`"
        )
    blob = json.dumps(_json_safe(payload), default=str).replace("</", "<\\/")
    html = TEMPLATE_PATH.read_text().replace("__CATALOG_PAYLOAD__", blob)
    # Patch server-relative logo paths → inline data URIs so they render offline.
    for server_path, data_uri in _logo_data_uris().items():
        html = html.replace(server_path, data_uri)
    return html


def render_html(
    output: Any,
    theme: str = "light",
    tool: Any = None,
    render_id: str | None = None,
) -> str:
    """Inject a single output (wrapped as a one-item gallery) into the bundle.

    Opens straight into the output's detail view via ``initialOutputId``.
    When ``render_id`` is given only the matching render is included, so the
    iframe shows a single component rather than the full output page.
    """
    blob = build_payload(output, theme, tool)
    if render_id is not None:
        blob = {
            **blob,
            "renders": [r for r in blob["renders"] if r.get("index") == render_id],
        }
    outputs = [_entry_from_blob(blob)]
    # No parent tool (e.g. a bare output id): fabricate a one-tool group from the output.
    if tool is not None:
        tool_group = _tool_dict(tool, outputs)
    else:
        tool_group = {
            "id": output.id,
            "name": output.id,
            "description": "",
            "homepage": None,
            "nf_core_url": None,
            "biotools_url": None,
            "edam_topics": [],
            "outputs": outputs,
        }
    payload = {
        "theme": blob["theme"],
        "initialOutputId": output.id,
        "initialRenderId": render_id,
        "tools": [tool_group],
        "data": blob["data"],
    }
    return _inject(payload)


def render_gallery_html(entries: Any, theme: str = "light") -> str:
    """Inject the whole catalog (gallery + every output's live payload)."""
    return _inject(build_gallery_payload(entries, theme))
