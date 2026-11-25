"""Merge ANCOM-BC differential abundance results (5 slices) into one long-format table.

Each slice is read by a glob so a run can hold several analyses of the same
samples side by side, e.g. ANCOM-BC against two reference databases. A file named
``<slice>.<label>.csv`` (``lfc_slice.pr2.csv``) carries its rows under
``taxonomy = <label>``; the file ampliseq writes (``lfc_slice.csv``) has no label
and leaves the column empty. A dashboard switches between the labels with a filter
on ``taxonomy``.

A second run of the same reads, against another database, sits in its own results
folder, which a glob cannot reach: the ``<slice>_alt`` sources read its five slices
by path (the template points them there) and label its rows ``alt_label``. Only
then do the primary run's unlabelled rows take ``label``, so a single run keeps an
empty ``taxonomy``.
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.lineage import leaf_rank, root_rank

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="lfc",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/lfc_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="p_val",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/p_val_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="q_val",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/q_val_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="w",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/w_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
    RecipeSource(
        ref="se",
        glob_pattern="qiime2/ancombc/differentials/Category-habitat-level-2/se_slice*.csv",
        format="CSV",
        source_path="source_path",
        input_schema={
            "id": pl.Utf8,
        },
    ),
]

# The second run's slices, by plain path: absent unless the template sets them.
SOURCES += [
    RecipeSource(
        ref=f"{name}_alt",
        path=f"pr2/qiime2/ancombc/differentials/Category-habitat-level-4/{name}_slice.csv",
        format="CSV",
        optional=True,
        input_schema={"id": pl.Utf8},
    )
    for name in ("lfc", "p_val", "q_val", "w", "se")
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "id": pl.Utf8,
    "contrast": pl.Utf8,
    "lfc": pl.Float64,
    "p_val": pl.Float64,
    "q_val": pl.Float64,
    "w": pl.Float64,
    "se": pl.Float64,
    "Kingdom": pl.Utf8,
    "Phylum": pl.Utf8,
    "neg_log10_qval": pl.Float64,
    "significant": pl.Boolean,
    "taxonomy": pl.Utf8,
}


# A slice named ``lfc_slice.pr2.csv`` holds the rows labelled "pr2"; the plain
# ``lfc_slice.csv`` has no label.
_LABEL = r"_slice\.([^/.]+)\.csv$"
_NO_LABEL = ""
_SLICES = ("lfc", "p_val", "q_val", "w", "se")
# ampliseq's default database, and the PR2 run of the template's PR2_RESULTS.
DEFAULT_LABEL = "silva"
DEFAULT_ALT_LABEL = "pr2"


def _melt(frames: dict[str, pl.DataFrame], taxonomy: pl.Expr) -> pl.DataFrame:
    """One run's five slices, melted to one row per taxon and contrast."""
    contrast_cols = [
        c for c in frames["lfc"].columns if c not in ("id", "(Intercept)", "source_path")
    ]
    melted = {
        name: frames[name]
        .select("id", taxonomy.alias("taxonomy"), *contrast_cols)
        .unpivot(
            on=contrast_cols,
            index=["id", "taxonomy"],
            variable_name="contrast",
            value_name=name,
        )
        .with_columns(pl.col(name).cast(pl.Float64, strict=False))
        for name in _SLICES
    }
    result = melted["lfc"]
    for name in _SLICES[1:]:
        result = result.join(melted[name], on=["id", "taxonomy", "contrast"], how="left")
    return result


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    """Melt each ANCOM-BC slice and join into one table with taxonomy annotations."""
    params = params or {}
    alt = {name: sources.get(f"{name}_alt") for name in _SLICES}
    has_alt = all(frame is not None for frame in alt.values())

    label = pl.col("source_path").str.extract(_LABEL, 1)
    primary = (params.get("label") or DEFAULT_LABEL) if has_alt else _NO_LABEL
    result = _melt(
        {name: sources[name] for name in _SLICES},
        label.fill_null(pl.lit(primary)),
    )
    if has_alt:
        alt_label = params.get("alt_label") or DEFAULT_ALT_LABEL
        result = pl.concat(
            [result, _melt(alt, pl.lit(alt_label))],
            how="diagonal_relaxed",
        )

    # The Phylum is the lineage's leaf: the template points the five slices at the
    # ANCOM-BC level that *is* Phylum for the run's reference database, whatever
    # depth sits above it. The Kingdom is its root, not the leaf's parent, which is a
    # Supergroup or Division for a database read below Phylum (PR2).
    result = result.with_columns(
        root_rank(pl.col("id")).alias("Kingdom"),
        leaf_rank(pl.col("id")).alias("Phylum"),
        (-pl.col("q_val").log(base=10)).alias("neg_log10_qval"),
        (pl.col("q_val") < 0.05).alias("significant"),
        pl.when(pl.col("taxonomy") == _NO_LABEL)
        .then(None)
        .otherwise(pl.col("taxonomy"))
        .alias("taxonomy"),
    )

    return result.select(
        "id",
        "contrast",
        "lfc",
        "p_val",
        "q_val",
        "w",
        "se",
        "Kingdom",
        "Phylum",
        "neg_log10_qval",
        "significant",
        "taxonomy",
    )
