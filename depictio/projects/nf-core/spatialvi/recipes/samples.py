"""The nf-core/spatialvi sample hub: one row per sample, every design column.

spatialvi does not publish its validated sample sheet, and a sample can enter
the pipeline two ways: raw FASTQs run through Space Ranger (``<sample>/
spaceranger/outs/`` is published) or an existing Space Ranger ``outs/``
directory (``spaceranger_dir`` column, nothing published under
``spaceranger/``). Every sample of either route gets ``<sample>/data/
<sample>_svg.csv`` when the downstream analysis ran, so the hub is the union of
the samples those two file families name, keyed on the directory name the
pipeline uses (``meta.id``).

The design comes from ``METADATA_FILE`` (the ``metadata`` collection): the
pipeline's own sample sheet, or any table whose ``METADATA_ID_COL`` column
holds the sample ids. Its columns are carried as text. ``GROUP_COL`` names the
column the group filter reads; when the design table lacks it (or there is no
design table) the column is added with one value, ``all samples``, so the
filter and the cards still resolve.

Sources:
    metrics   ``spaceranger_metrics_raw`` (optional)
    svg       ``squidpy_svg_raw`` (optional)
    metadata  the optional ``metadata`` collection

Params:
    id_col     the design table's sample column (METADATA_ID_COL)
    group_col  the design column to group by (GROUP_COL)

Output schema:
    sample : Utf8           sample id, as the run's directories name it
    input_route : Utf8      "Space Ranger run by the pipeline" |
                            "Space Ranger outs given"
    <GROUP_COL> : Utf8      design group, "all samples" when absent
    <design columns> : Utf8 one per other design-table column
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="metrics", dc_ref="spaceranger_metrics_raw", optional=True),
    RecipeSource(ref="svg", dc_ref="squidpy_svg_raw", optional=True),
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "input_route": pl.Utf8,
}
# Design columns (GROUP_COL included) are run-dependent; validated dynamically.
OPTIONAL_SCHEMA: dict[str, type[pl.DataType]] = {}

_RAN = "Space Ranger run by the pipeline"
_GIVEN = "Space Ranger outs given"
_NO_GROUP = "all samples"
_METRICS_RE = r"(?:^|/)([^/]+)/spaceranger/outs/metrics_summary\.csv$"
_SVG_RE = r"(?:^|/)([^/]+)/data/[^/]+_svg\.csv$"


def _samples(df: pl.DataFrame | None, pattern: str) -> set[str]:
    if df is None or df.is_empty() or "source_path" not in df.columns:
        return set()
    path = pl.col("source_path").cast(pl.Utf8).str.replace_all(r"\\", "/")
    found = df.select(path.str.extract(pattern, 1).alias("s"))["s"].drop_nulls()
    return set(found.to_list())


def _design(metadata: pl.DataFrame | None, id_col: str | None) -> pl.DataFrame | None:
    if metadata is None or metadata.is_empty():
        return None
    if not id_col or id_col not in metadata.columns:
        id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    keep = [c for c in metadata.columns if c not in (id_col, "source_path", "sample")]
    return metadata.select(
        pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("sample"),
        *[pl.col(c).cast(pl.Utf8) for c in keep],
    ).unique(subset="sample", keep="first")


def transform(
    sources: dict[str, pl.DataFrame | None], params: dict[str, str] | None = None
) -> pl.DataFrame:
    params = params or {}
    ran = _samples(sources.get("metrics"), _METRICS_RE)
    analysed = _samples(sources.get("svg"), _SVG_RE)
    design = _design(sources.get("metadata"), (params.get("id_col") or "").strip())
    names = ran | analysed
    if not names and design is not None:
        names = set(design["sample"].to_list())
    if not names:
        raise ValueError(
            "spatialvi samples: no <sample>/spaceranger/outs/metrics_summary.csv, no "
            "<sample>/data/<sample>_svg.csv and no design table to name the samples"
        )
    hub = pl.DataFrame({"sample": sorted(names)}).with_columns(
        pl.when(pl.col("sample").is_in(sorted(ran)))
        .then(pl.lit(_RAN))
        .otherwise(pl.lit(_GIVEN))
        .alias("input_route")
    )
    if design is not None:
        hub = hub.join(design, on="sample", how="left")
    group_col = (params.get("group_col") or "").strip()
    if group_col and group_col not in hub.columns:
        hub = hub.with_columns(pl.lit(_NO_GROUP).alias(group_col))
    elif group_col:
        hub = hub.with_columns(pl.col(group_col).fill_null(_NO_GROUP))
    head = list(EXPECTED_SCHEMA)
    return hub.select(head + [c for c in hub.columns if c not in head]).sort("sample")
