"""Genome-browser track manifest: one row per strand-coverage bigWig the run published.

nf-core/nascent writes two bigWigs per library under ``coverage_graphs/``
(deepTools bamCoverage): ``<S>.plus.bigWig`` and ``<S>.minus.bigWig``, the
reads of each strand. The manifest keeps both, in time order so the time course reads
down the browser: each library's plus strand, then its minus strand, the libraries of
one time point by name.

No colour column: the tile colours the tracks along a sequential ramp by the
library's time point (``color_scale``: ``time_point`` in the order of
``time_order``), so a later library is a darker one, in the browser and in the
binned lanes above it. Both columns come off the hub, which holds each library's
time (the design table's, or the duration its id ends in).

Sources:
    samples    ``samples`` (the sample hub): the libraries of the run and their time points

Output schema:
    track_id : Utf8     `<sample>.<strand>`, unique per file
    sample : Utf8       the library (links to the `samples` hub)
    time_point : Utf8   the library's time point label (null without a time)
    time_order : Int64  the time point's rank, 1 for the earliest (null without a time)
    format : Utf8       bigwig
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``): libraries in
                        time order, the plus strand of each before its minus strand
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
# The libraries of the run; their files are then found under the data root.
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="samples",
        dc_ref="samples",
        input_schema={"sample": pl.Utf8, "time_point": pl.Utf8, "time_order": pl.Int64},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "time_point": pl.Utf8,
    "time_order": pl.Int64,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

_BIGWIG = re.compile(r"^coverage_graphs/(?P<s>[^/]+)\.(?P<strand>plus|minus)\.bigWig$")
_STRANDS = ("plus", "minus")


def transform(sources: dict[str, pl.DataFrame | None], context=None) -> pl.DataFrame:
    """List the plus and minus bigWig of every library."""
    if context is None:
        raise ValueError("nascent tracks: needs the data root to find the bigWigs")
    hub = sources.get("samples")
    libraries = set(hub["sample"].drop_nulls().unique().to_list()) if hub is not None else set()
    if context.reads_in_place:
        # In place nothing is listed: every library has both strands.
        found = {(s, strand) for s in libraries for strand in _STRANDS}
    else:
        found = {
            (m["s"], m["strand"])
            for p in context.glob("coverage_graphs/*.bigWig")
            if (m := _BIGWIG.match(p)) and (not libraries or m["s"] in libraries)
        }
    if not found:
        raise ValueError(
            "nascent tracks: no coverage_graphs/<S>.{plus,minus}.bigWig under the data root"
        )

    times = (
        {r["sample"]: (r["time_point"], r["time_order"]) for r in hub.to_dicts()}
        if hub is not None
        else {}
    )

    def time_key(sample: str) -> tuple[bool, int, str]:
        order = times.get(sample, (None, None))[1]
        return (order is None, order or 0, sample)

    # The time course reads down the browser: libraries in time order, each library's
    # plus strand above its minus strand.
    ordered = sorted(found, key=lambda k: (*time_key(k[0]), _STRANDS.index(k[1])))
    rows = [
        {
            "track_id": f"{sample}.{strand}",
            "sample": sample,
            "time_point": times.get(sample, (None, None))[0],
            "time_order": times.get(sample, (None, None))[1],
            "format": "bigwig",
            "uri": f"coverage_graphs/{sample}.{strand}.bigWig",
            "name": f"{sample} {'+' if strand == 'plus' else '-'}",
            "category": "Strand coverage",
        }
        for sample, strand in ordered
    ]
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
