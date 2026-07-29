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

Annotation strips are deliberately *not* ported. They are ``yref='paper'``
shapes positioned against live plot dimensions, and a static export cannot know
the container height, so they would land in the wrong place. ``format=html``
renders them correctly; see the module note in ``figure_registry``.
"""

from __future__ import annotations

from typing import Any

from depictio.api.v1.services.advanced_viz.figure_registry import register
from depictio.api.v1.services.advanced_viz.palette import TAB10_PALETTE, stable_color_map

#: Colour for the lumped remainder. Grey so it reads as "not a taxon".
_OTHER_COLOR = "#adb5bd"
_OTHER_LABEL = "Other"


def _columns(config: dict[str, Any]) -> list[str | None]:
    return [
        config.get("sample_id_col"),
        config.get("taxon_col"),
        config.get("rank_col"),
        config.get("abundance_col"),
    ]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@register("stacked_taxonomy", columns=_columns)
def build(
    *,
    rows: dict[str, list[Any]],
    config: dict[str, Any],
    controls: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    sample_col = config.get("sample_id_col") or "sample_id"
    taxon_col = config.get("taxon_col") or "taxon"
    rank_col = config.get("rank_col") or "rank"
    abundance_col = config.get("abundance_col") or "abundance"

    top_n = int(controls.get("top_n", config.get("top_n", 20)))
    normalise = bool(controls.get("normalise", config.get("normalise_to_one", True)))
    sample_sort = str(controls.get("sample_sort", config.get("sample_sort", "input")))
    show_legend = bool(controls.get("show_legend", config.get("show_legend", True)))

    samples = [str(v if v is not None else "") for v in (rows.get(sample_col) or [])]
    taxa = [str(v if v is not None else "") for v in (rows.get(taxon_col) or [])]
    ranks = [str(v if v is not None else "") for v in (rows.get(rank_col) or [])]
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
    if sample_sort != "input":
        first_taxon = ranked[0] if ranked else None

        def score(sample: str) -> float:
            bucket = cells.get(sample, {})
            if sample_sort == "first_taxon" and first_taxon:
                return bucket.get(first_taxon, 0.0)
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

    # Palette off the full taxon universe present in the data, matching
    # stableColorMap(taxonUniverse, PALETTE) on the TS side.
    colors = stable_color_map(taxon_totals.keys(), TAB10_PALETTE)

    data = [
        {
            "type": "bar",
            "name": taxon,
            "x": ordered_samples,
            "y": values,
            "marker": {"color": _OTHER_COLOR if taxon == _OTHER_LABEL else colors.get(taxon)},
        }
        for taxon, values in series.items()
        if any(v > 0 for v in values)
    ]

    y_axis: dict[str, Any] = (
        {"title": {"text": "Relative abundance"}, "range": [0, 1], "tickformat": ".0%"}
        if normalise
        else {"title": {"text": abundance_col}}
    )

    return {
        "data": data,
        "layout": {
            "barmode": "stack",
            "margin": {"l": 60, "r": 20, "t": 30, "b": 70},
            "xaxis": {"title": {"text": sample_col}, "tickangle": -45},
            "yaxis": y_axis,
            "showlegend": show_legend,
            "legend": {"orientation": "v", "x": 1.02, "y": 1},
        },
    }
