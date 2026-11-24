"""Stacked taxonomy — per-sample composition bars.

Port of ``advanced_viz/StackedTaxonomyRenderer.tsx`` (the ``figure`` useMemo,
lines 146-350). The aggregation is the whole job: tidy rows arrive as
``(sample, taxon, rank, abundance)`` quadruples and have to be pivoted into one
stacked bar trace per taxon.

Three behaviours are easy to get subtly wrong and are called out where they
happen:

* **top-N is ranked over the whole matrix**, not per sample, and everything
  below the cut is lumped into a single ``Other`` trace.
* **colours come from the taxon universe**, not the filtered subset, so
  filtering to one habitat does not re-map the palette (see ``palette.py``).
* **normalise locks the y-axis to [0, 1] with percent ticks.** Without that the
  toggle looks like a no-op on data that is already pre-normalised.

* **colours are the dashboard's.** A taxon wears the colour pinned for it in
  ``category_colors`` (under the rank shown, else under the taxon column, the
  component's own ``taxon_palette`` winning), exactly as the renderer resolves
  it; every other taxon takes the palette in order over the shown taxa. A blank
  taxon is named ``Unclassified`` (its reserved grey), as the renderer names it.

Annotation strips are drawn as the renderer draws them: one-row heatmaps on
their own y axes, stacked above (or below) the bars as fractions of the plot
area. A static export cannot know the container height, so the fractions assume
the renderer's own plot height (``TAXONOMY_PLOT_PX``), which keeps a band the
height its labels need.
"""

from __future__ import annotations

import re
from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register
from depictio.api.v1.services.advanced_viz.palette import stable_color_map
from depictio.models import palettes

_OTHER_LABEL = "Other"
_UNCLASSIFIED_LABEL = "Unclassified"
_AUTO_KEY = "*"

# The renderer's strip sizing (``StackedBarRenderer.tsx``): a band tall enough
# for its 10 px labels, a gap so its name and the bars' top tick do not touch,
# both as a share of the plot area the renderer assumes for vertical bars.
_PLOT_AREA_PX = 300
_STRIP_BAND_PX = 22
_STRIP_GAP_PX = 8
_STRIP_MISSING = "\u2014"
# Past this many bars the tilted sample labels run into each other.
_DENSE_AXIS_BARS = 40


def _strips(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The configured annotation strips that name a column."""
    return [
        s
        for s in (config.get("annotation_strips") or [])
        if isinstance(s, dict) and s.get("column")
    ]


def _columns(config: dict[str, Any]) -> list[str | None]:
    strip_cols = [s["column"] for s in _strips(config)]
    value_cols = [c for c in (config.get("value_cols") or []) if c]
    if value_cols:
        return [config.get("sample_id_col"), *value_cols, *strip_cols]
    return [
        config.get("sample_id_col"),
        config.get("taxon_col"),
        config.get("rank_col"),
        config.get("abundance_col"),
        *strip_cols,
    ]


def _pinned(category_colors: dict[str, dict[str, str]], column: str | None) -> dict[str, str]:
    """The colours pinned for one column (``columnCategoryColors``): values only,
    never the ``"*"`` auto marker."""
    layer = category_colors.get(column) if column else None
    if not isinstance(layer, dict):
        return {}
    return {str(v): c for v, c in layer.items() if v != _AUTO_KEY and isinstance(c, str) and c}


def _text_on(fill: str | None) -> str:
    """Dark or light text, whichever reads on a fill (``textOn`` in the renderer)."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (fill or "").strip())
    if not m:
        return "#212529"
    r, g, b = (int(m.group(1)[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return "#ffffff" if 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b) < 0.4 else "#212529"


def _runs(values: list[str]) -> list[tuple[str, int, int]]:
    """Consecutive equal values as ``(value, start, end)``."""
    out: list[tuple[str, int, int]] = []
    for i, v in enumerate(values):
        if out and out[-1][0] == v and out[-1][2] == i - 1:
            out[-1] = (v, out[-1][1], i)
        else:
            out.append((v, i, i))
    return out


def _natural_key(value: str) -> list[tuple[int, int | str]]:
    """Natural, case-insensitive order: ``S2`` before ``S10``."""
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.split(r"(\d+)", value)
        if part
    ]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@register("stacked_bar", columns=_columns, category_colors=True)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
    category_colors: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    sample_col = config.get("sample_id_col") or "sample_id"
    taxon_col = config.get("taxon_col") or "taxon"
    # Unset is the model default; an explicit null is a single-level composition.
    rank_col = config.get("rank_col", "rank")
    abundance_col = config.get("abundance_col") or "abundance"

    top_n = int(controls.get("top_n", config.get("top_n", 20)))
    normalise = bool(controls.get("normalise", config.get("normalise_to_one", True)))
    sample_sort = str(controls.get("sample_sort", config.get("sample_sort", "input")))
    show_legend = bool(controls.get("show_legend", config.get("show_legend", True)))

    value_cols = [c for c in (config.get("value_cols") or []) if c]
    if value_cols:
        # Wide form: one numeric column per category, melted row by row (the
        # renderer's `meltWideRows`), with no rank.
        labels = config.get("value_labels") or {}
        present = [c for c in value_cols if c in rows]
        samples, taxa, abundances, ranks = [], [], [], []
        for i, sample in enumerate(rows.get(sample_col) or []):
            for col in present:
                samples.append(str(sample if sample is not None else ""))
                taxa.append(str(labels.get(col) or col))
                abundances.append(_as_float(rows[col][i]))
    else:
        samples = [str(v if v is not None else "") for v in (rows.get(sample_col) or [])]
        # A lineage that stops above the shown rank has a blank leaf: named, so
        # its legend entry is not an unlabelled swatch.
        taxa = [
            str(v if v is not None else "").strip() or _UNCLASSIFIED_LABEL
            for v in (rows.get(taxon_col) or [])
        ]
        ranks = [str(v if v is not None else "") for v in ((rank_col and rows.get(rank_col)) or [])]
        abundances = [_as_float(v) for v in (rows.get(abundance_col) or [])]

    all_ranks: list[str] = list(dict.fromkeys(ranks))
    active_rank = (
        controls.get("rank") or config.get("default_rank") or (all_ranks[0] if all_ranks else None)
    )

    # sample -> taxon -> summed abundance, at the active rank only.
    cells: dict[str, dict[str, float]] = {}
    for i, sample in enumerate(samples):
        if active_rank and i < len(ranks) and ranks[i] != active_rank:
            continue
        taxon = taxa[i] if i < len(taxa) else ""
        value = abundances[i] if i < len(abundances) else 0.0
        bucket = cells.setdefault(sample, {})
        bucket[taxon] = bucket.get(taxon, 0.0) + value

    taxon_totals: dict[str, float] = {}
    for bucket in cells.values():
        for taxon, value in bucket.items():
            taxon_totals[taxon] = taxon_totals.get(taxon, 0.0) + value

    ranked = sorted(taxon_totals, key=lambda t: -taxon_totals[t])
    top_taxa = ranked[:top_n]
    top_set = set(top_taxa)

    ordered_samples = list(cells)
    if sample_sort == "name":
        ordered_samples.sort(key=_natural_key)
    elif sample_sort in ("total_abundance", "first_taxon", "category"):
        first_taxon = ranked[0] if ranked else None
        wanted = controls.get("sort_category", config.get("sort_category"))
        shown = [*top_taxa, *([_OTHER_LABEL] if len(ranked) > top_n else [])]
        sort_category = wanted if wanted in shown else (shown[0] if shown else None)

        def score(sample: str) -> float:
            bucket = cells.get(sample, {})
            if sample_sort == "first_taxon" and first_taxon:
                return bucket.get(first_taxon, 0.0)
            if sample_sort == "category" and sort_category:
                # The plotted value: the share when normalised.
                if sort_category == _OTHER_LABEL:
                    value = sum(v for t, v in bucket.items() if t not in top_set)
                else:
                    value = bucket.get(sort_category, 0.0)
                total = sum(bucket.values())
                return value / total if normalise and total > 0 else value
            return sum(bucket.values())

        ordered_samples.sort(key=score, reverse=True)

    series: dict[str, list[float]] = {
        t: [0.0] * len(ordered_samples) for t in [*top_taxa, _OTHER_LABEL]
    }
    for index, sample in enumerate(ordered_samples):
        bucket = cells.get(sample, {})
        total = sum(bucket.values())
        for taxon, value in bucket.items():
            key = taxon if taxon in top_set else _OTHER_LABEL
            series[key][index] += value / total if normalise and total > 0 else value

    # The renderer hands the palette to the taxa shown at the active rank (a
    # table holds every rank, whose taxa would spend the slots), else to the
    # whole universe; a taxon the dashboard pins keeps that colour.
    colours_by_column = category_colors or {}
    pinned = {
        **_pinned(colours_by_column, taxon_col),
        **_pinned(colours_by_column, active_rank if not value_cols else None),
        **{str(k): v for k, v in (config.get("taxon_palette") or {}).items() if v},
    }
    universe = top_taxa if active_rank and not value_cols else list(taxon_totals)
    colors = stable_color_map(universe, overrides=pinned, mode=theme)

    # The lumped remainder is grey so it reads as "not a taxon".
    other_color = palettes.semantic("other", theme)
    data = [
        {
            "type": "bar",
            "name": taxon,
            "x": ordered_samples,
            "y": values,
            "marker": {"color": other_color if taxon == _OTHER_LABEL else colors.get(taxon)},
        }
        for taxon, values in series.items()
        if any(v > 0 for v in values)
    ]

    strip_traces, strip_axes, strip_labels, strip_key, bar_domain = _annotation_strips(
        config, rows, sample_col, ordered_samples, colours_by_column, theme
    )
    dense = len(ordered_samples) > _DENSE_AXIS_BARS
    legend_pos = config.get("legend_pos") or "right"
    legend_title = {"text": f"{active_rank or 'Taxon'} "}
    if legend_pos == "right":
        legend: dict[str, Any] = {
            "orientation": "v",
            "x": 1.02,
            "xanchor": "left",
            "y": 1,
            "yanchor": "top",
            "title": legend_title,
            "font": {"size": 10},
        }
        legend_top_px = 0
    else:
        legend = {
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": 1.02,
            "yanchor": "bottom",
            "traceorder": "normal",
            "title": legend_title,
            "font": {"size": 10},
        }
        legend_top_px = 40 if show_legend else 0

    y_axis: dict[str, Any] = (
        {"title": {"text": "Relative abundance"}, "range": [0, 1], "tickformat": ".0%"}
        if normalise
        else {"title": {"text": abundance_col}}
    )
    y_axis["domain"] = bar_domain

    layout: dict[str, Any] = {
        "barmode": "stack",
        "margin": {"l": 60, "r": 20, "t": (44 if strip_key else 30) + legend_top_px, "b": 70},
        "xaxis": {
            "title": {"text": sample_col},
            "tickangle": -45,
            "showticklabels": not dense,
            "automargin": True,
            # Pinned to the edge of the plot area, past any strip below the
            # bars, and to the bars' order so the strips line up with them.
            "anchor": "free",
            "position": 0,
            "categoryorder": "array",
            "categoryarray": ordered_samples,
        },
        "yaxis": y_axis,
        **strip_axes,
        "annotations": strip_labels,
        "showlegend": show_legend,
        "legend": legend,
    }
    if strip_key:
        layout["legend2"] = {
            "orientation": "h",
            "x": 1,
            "xanchor": "right",
            "y": 1,
            "yanchor": "bottom",
            "font": {"size": 10},
        }
    return {"data": [*data, *strip_traces], "layout": layout}


def _annotation_strips(
    config: dict[str, Any],
    rows: dict[str, list[Any]],
    sample_col: str,
    slots: list[str],
    category_colors: dict[str, dict[str, str]],
    theme: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], bool, list[float]]:
    """The strips of per-sample categories above/below the bars.

    Returns ``(traces, axes, annotations, wants_key, bar_domain)``. Each strip
    is a one-row heatmap on its own y axis sharing the bars' x axis, a step
    colour scale giving each category its own band; a strip whose categories
    each hold a block wide enough is labelled on itself, the others get a key
    (``legend2``) above the plot.
    """
    strips = _strips(config)
    band = round(min(0.15, _STRIP_BAND_PX / _PLOT_AREA_PX), 3)
    gap = round(min(0.05, _STRIP_GAP_PX / _PLOT_AREA_PX), 3)
    step = band + gap
    n_top = sum(1 for s in strips if s.get("position", "top") != "bottom")
    n_bottom = len(strips) - n_top
    bar_domain = [round(n_bottom * step, 4), round(1 - n_top * step, 4)]

    traces: list[dict[str, Any]] = []
    axes: dict[str, Any] = {}
    labels: list[dict[str, Any]] = []
    wants_key = False
    top_cursor, bottom_cursor = 1.0, 0.0
    n_samples = len(slots)
    for k, strip in enumerate(strips):
        column = str(strip["column"])
        by_sample: dict[str, str] = {}
        for sample, value in zip(rows.get(sample_col) or [], rows.get(column) or []):
            by_sample.setdefault(
                str(sample if sample is not None else ""),
                str(value) if value is not None else _STRIP_MISSING,
            )
        values = [by_sample.get(s, _STRIP_MISSING) for s in slots]
        categories = sorted(set(values))
        palette = stable_color_map(
            categories,
            overrides={**_pinned(category_colors, column), **(strip.get("palette") or {})},
            mode=theme,
        )
        n = len(categories)
        colorscale = [
            [edge, palette[c]] for i, c in enumerate(categories) for edge in (i / n, (i + 1) / n)
        ]
        is_top = strip.get("position", "top") != "bottom"
        if is_top:
            domain = [round(top_cursor - band, 4), round(top_cursor, 4)]
            top_cursor -= step
        else:
            domain = [round(bottom_cursor, 4), round(bottom_cursor + band, 4)]
            bottom_cursor += step
        axis = f"y{k + 2}"
        label = str(strip.get("label") or column)
        axes[f"yaxis{k + 2}"] = {
            "domain": domain,
            "anchor": "x",
            "fixedrange": True,
            "showgrid": False,
            "zeroline": False,
            "ticks": "",
            "tickfont": {"size": 10},
            "automargin": True,
        }
        traces.append(
            {
                "type": "heatmap",
                "x": slots,
                "y": [label],
                "z": [[categories.index(v) for v in values]],
                "customdata": [values],
                "yaxis": axis,
                "hovertemplate": f"%{{x}}<br>{label}: %{{customdata}}<extra></extra>",
                "zmin": -0.5,
                "zmax": n - 0.5,
                "colorscale": colorscale,
                "showscale": False,
                "xgap": 0,
                "hoverongaps": False,
            }
        )
        longest: dict[str, tuple[int, int]] = {}
        for value, start, end in _runs(values):
            best = longest.get(value)
            if best is None or end - start > best[1] - best[0]:
                longest[value] = (start, end)
        min_run = max(2, -(-n_samples * 12 // 100))
        if all(c in longest and longest[c][1] - longest[c][0] + 1 >= min_run for c in categories):
            for c in categories:
                start, end = longest[c]
                labels.append(
                    {
                        "xref": "x",
                        "yref": axis,
                        "x": (start + end) / 2,
                        "y": 0,
                        "text": c,
                        "showarrow": False,
                        "font": {"size": 10, "color": _text_on(palette[c])},
                    }
                )
        else:
            wants_key = True
            traces.extend(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": [None],
                    "y": [None],
                    "name": c,
                    "legend": "legend2",
                    "legendgroup": f"strip-{column}",
                    "legendgrouptitle": {"text": label},
                    "marker": {"color": palette[c], "symbol": "square", "size": 10},
                    "hoverinfo": "skip",
                }
                for c in categories
            )
    return traces, axes, labels, wants_key, bar_domain
