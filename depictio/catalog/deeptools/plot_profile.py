"""deepTools metagene profile in long form, one row per sample and bin.

``plotProfile --outFileNameData`` writes a three-line file per sample: a row of
sparse bin LABELS (only the anchors deepTools drew are filled in, e.g.
``-3.0Kb``, ``TSS``, ``TES``, ``3.0Kb``), a row of bin NUMBERS, and one data row
per (sample, region group) holding the mean signal in each bin. It is a table
turned on its side, so this recipe transposes it into the long form every curve
renderer wants.

The x axis is the bin index, not a genomic coordinate, because the two flavours
of ``computeMatrix`` produce different axes and only the bin index is common to
both: ``reference-point`` gives a window centred on one anchor, while
``scale-regions`` stretches every gene body to the same number of bins, so no
single base offset exists. ``bin_label`` carries deepTools' own anchors on the
handful of bins that have one and is null elsewhere, which is what lets a
dashboard place a reference marker at the TSS without hard-coding the window.

Reading a sideways table through the recipe loader
--------------------------------------------------
The loader concatenates every matched file, so the two header rows reappear once
per sample. They are read as data (``has_header: false``) and dropped here on
their first cell, which deepTools always spells ``bin labels`` and ``bins``.

Output schema:
    sample : Utf8        library plotProfile ran on
    group : Utf8         region group deepTools plotted (nf-core plots "genes")
    bin : Int64          1-based bin index along the plotted window
    bin_label : Utf8     deepTools' anchor label at that bin, null in between
    signal : Float64     mean signal in that bin
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

# `has_header: false` so the two header rows arrive as data and survive the
# concatenation of several files; `infer_schema_length: 0` because the first
# row of the first file is all text and the rest is numeric.
_READ_KWARGS = {
    "has_header": False,
    "infer_schema_length": 0,
    "truncate_ragged_lines": True,
    "null_values": ["nan", "NA", ""],
}

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="profiles",
        glob_pattern="**/*.plotProfile.tab",
        format="TSV",
        read_kwargs=_READ_KWARGS,
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "group": pl.Utf8,
    "bin": pl.Int64,
    "bin_label": pl.Utf8,
    "signal": pl.Float64,
}

# First cell of the two header rows, as deepTools spells them.
_LABEL_ROW = "bin labels"
_BIN_ROW = "bins"


def _row_kind(first_cell: str | None) -> str:
    value = (first_cell or "").strip().lower()
    if value == _LABEL_ROW:
        return "labels"
    if value == _BIN_ROW:
        return "bins"
    return "data"


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Transpose every sample's row of bin means into one row per bin."""
    raw = sources["profiles"]
    if raw.is_empty():
        raise ValueError("deeptools_plot_profile: the matched plotProfile files are empty")

    columns = raw.columns
    if len(columns) < 3:
        raise ValueError(
            f"deeptools_plot_profile: expected sample, group and at least one bin, got {columns}"
        )

    labels: dict[int, str] = {}
    bins: list[int] = []
    rows: list[dict] = []
    for record in raw.iter_rows(named=True):
        cells = [record[c] for c in columns]
        kind = _row_kind(cells[0])
        if kind == "labels":
            # Sparse: only the anchors deepTools drew carry a label. Recorded by
            # position so the bin row below can name them.
            for index, cell in enumerate(cells[2:]):
                if cell not in (None, ""):
                    labels[index] = str(cell).strip()
            continue
        if kind == "bins":
            bins = [int(float(cell)) if cell not in (None, "") else 0 for cell in cells[2:]]
            continue
        sample = strip_stage_suffixes(str(cells[0]).strip())
        group = str(cells[1]).strip() if cells[1] not in (None, "") else "all"
        for index, cell in enumerate(cells[2:]):
            if cell in (None, ""):
                continue
            rows.append(
                {
                    "sample": sample,
                    "group": group,
                    # Fall back to the position when the file carried no bin row.
                    "bin": bins[index] if index < len(bins) else index + 1,
                    "bin_label": labels.get(index),
                    "signal": cell,
                }
            )

    if not rows:
        raise ValueError("deeptools_plot_profile: no file carried a data row under its header")

    return (
        pl.DataFrame(rows, infer_schema_length=None)
        .with_columns(
            pl.col("sample").cast(pl.Utf8),
            pl.col("group").cast(pl.Utf8),
            pl.col("bin").cast(pl.Int64, strict=False),
            pl.col("bin_label").cast(pl.Utf8),
            pl.col("signal").cast(pl.Float64, strict=False),
        )
        .select(list(EXPECTED_SCHEMA))
        .sort(["sample", "group", "bin"])
    )
