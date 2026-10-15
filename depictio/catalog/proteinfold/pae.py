"""Predicted aligned error of every top-ranked model, binned to a fixed grid.

Each engine writes one N x N matrix per model to
``<engine>[/<mode>]/<target>/paes/<target>_<k>_pae.tsv``: row i, column j is
the expected position error (in angstroms) at residue j when the model is
aligned on residue i. Low values off the diagonal mean two regions (two
domains, two chains of a complex) are placed confidently relative to each
other. Only the top-ranked model is kept: ``k`` is 0 for AlphaFold2 and
RoseTTAFold All-Atom but 1 for ColabFold, which is the rule
``PAE_SAMPLE_REGEX`` (``depictio.recipes.lib.proteinfold``) selects the files of
the ``pae`` indexed-file collection by, so both name the same matrix. Residues are
averaged into at most ``BINS`` equal bins per axis so every structure fits one
heatmap: row ``bin`` k and column ``bNN`` with the same number cover the same
residues. Residues count from 1 over the chains in order (the matrix carries no
chain ids). ``mean_pae`` is the row's mean over its residues, so its average over
a structure's rows is the matrix mean; values are rounded to 3 decimals.

The matrix is read by ``depictio.recipes.lib.pae.read_pae``; a file that does not
hold a square matrix of numbers is left out.

Sources:
    pae  ``**/paes/*_[01]_pae.tsv``, one text line per row
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.pae import read_pae
from depictio.recipes.lib.proteinfold import (
    PAE_SAMPLE_REGEX,
    RAW_LINE_INPUT_SCHEMA,
    RAW_LINE_READ_KWARGS,
    locate_target_file,
    raw_blocks,
)

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="pae",
        glob_pattern="**/paes/*_[01]_pae.tsv",
        format="csv",
        read_kwargs=RAW_LINE_READ_KWARGS,
        source_path="source_path",
        input_schema=RAW_LINE_INPUT_SCHEMA,
    ),
]

BINS = 64
BIN_COLUMNS = [f"b{k:02d}" for k in range(1, BINS + 1)]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "entity": pl.Utf8,
    "engine": pl.Utf8,
    "target": pl.Utf8,
    "bin": pl.Int64,
    "residue_range": pl.Utf8,
    "mean_pae": pl.Float64,
    **dict.fromkeys(BIN_COLUMNS, pl.Float64),
}


def _binned(
    matrix: list[list[float]],
) -> tuple[list[tuple[int, int]], list[list[float | None]], list[float]]:
    n = len(matrix)
    bins = min(n, BINS)
    of = [i * bins // n for i in range(n)]
    sums = [[0.0] * bins for _ in range(bins)]
    counts = [[0] * bins for _ in range(bins)]
    for i, row in enumerate(matrix):
        bi = of[i]
        for j, value in enumerate(row):
            sums[bi][of[j]] += value
            counts[bi][of[j]] += 1
    # Mean over every residue pair of the row bin, not over its bin means.
    row_means = [sum(sums[a]) / max(sum(counts[a]), 1) for a in range(bins)]
    spans = []
    for b in range(bins):
        members = [i for i in range(n) if of[i] == b]
        spans.append((members[0] + 1, members[-1] + 1))
    means: list[list[float | None]] = [
        [sums[a][b] / counts[a][b] if counts[a][b] else None for b in range(bins)]
        for a in range(bins)
    ]
    return spans, means, row_means


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """PAE matrices -> one row per (entity, row bin), one column per column bin."""
    top: dict[str, tuple[str, list[str]]] = {}
    for path, lines in raw_blocks(sources["pae"]):
        # The glob reads the first two models of every engine; which one is the
        # top-ranked is the rule of the pae collection, not a lowest-number guess.
        if not re.search(PAE_SAMPLE_REGEX, path):
            continue
        top.setdefault(locate_target_file(path).entity, (path, lines))

    rows: list[dict[str, object]] = []
    for entity, (path, lines) in sorted(top.items()):
        loc = locate_target_file(path)
        try:
            matrix = read_pae("\n".join(lines))
        except ValueError:
            continue
        spans, means, row_means = _binned(matrix)
        for b, ((start, end), values, row_mean) in enumerate(
            zip(spans, means, row_means, strict=True)
        ):
            row: dict[str, object] = {
                "entity": entity,
                "engine": loc.engine,
                "target": loc.target,
                "bin": b + 1,
                "residue_range": f"{start}-{end}" if end > start else str(start),
                "mean_pae": round(row_mean, 3),
            }
            row.update({c: None if v is None else round(v, 3) for c, v in zip(BIN_COLUMNS, values)})
            rows.append(row)
    if not rows:
        return pl.DataFrame(schema=OUTPUT_SCHEMA)
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
