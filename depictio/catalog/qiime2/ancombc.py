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

With ``pairwise`` and ``group_col`` set, the recipe computes what the pipeline did not
run (``recipes/lib/ancombc.py``, the ``stats`` extra): every pair of levels of
``group_col`` its slices lack, from each run's barplot counts (``counts``,
``alt_counts``), and every pair for a merged taxonomy (``merged_taxonomy``, collapsed
from the ASV counts of ``feature_table``, labelled ``merged_label``). It first
recomputes the pipeline's own contrasts and stops the ingest when they do not match
(same taxa tested; estimates, standard errors and q-values within ``_AGREEMENT``): the
added pairs are only trustworthy if the same fit reproduces what the pipeline did. The
merged taxonomy has no pipeline result to check against; it runs the same fit.
"""

import logging

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

# For the pairs the pipeline did not run (params pairwise / group_col): each run's
# counts at the slices' level, as QIIME2's barplot (a row per sample, metadata
# included), and a merged taxonomy's ASV lineages with the ASV counts.
SOURCES += [
    RecipeSource(
        ref="counts",
        path="qiime2/barplot/level-2.csv",
        format="CSV",
        optional=True,
        input_schema={"index": pl.Utf8},
    ),
    RecipeSource(
        ref="alt_counts",
        path="pr2/qiime2/barplot/level-4.csv",
        format="CSV",
        optional=True,
        input_schema={"index": pl.Utf8},
    ),
    RecipeSource(
        ref="feature_table",
        # A large file: read only where the template points it (see the template).
        path="merged/qiime2/abundance_tables/feature-table.tsv",
        format="TSV",
        optional=True,
        read_kwargs={"skip_rows": 1, "infer_schema_length": 0},
    ),
    RecipeSource(ref="merged_taxonomy", dc_ref="merged_taxonomy", optional=True),
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
DEFAULT_MERGED_LABEL = "merged"
# How far the recomputed pipeline contrasts may sit from its own slices.
_AGREEMENT = 1e-4

logger = logging.getLogger("depictio-cli")


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


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _check_agreement(fitted: pl.DataFrame, pipeline: pl.DataFrame, label: str) -> None:
    """Stop when the recomputed contrasts differ from the pipeline's own slices."""
    run = label or "run"
    fitted = fitted.filter(pl.col("contrast").is_in(pipeline["contrast"].unique().to_list()))
    ours, theirs = set(fitted["id"]), set(pipeline["id"])
    if ours != theirs:
        raise ValueError(
            f"ANCOM-BC ({run}): the recipe does not reproduce the pipeline: it tests "
            f"{len(ours)} taxa, the pipeline {len(theirs)} ({len(ours ^ theirs)} differ). "
            "The settings differ (prevalence or library-size cut?); no pair was added"
        )
    joined = pipeline.join(fitted, on=["id", "contrast"], suffix="_ours")
    # A NaN or null on one side only is a disagreement: polars' max skips both.
    cols = ("lfc", "se", "q_val")
    one_sided = joined.select(
        pl.any_horizontal(
            pl.col(c).cast(pl.Float64).fill_nan(None).is_null()
            != pl.col(f"{c}_ours").cast(pl.Float64).fill_nan(None).is_null()
            for c in cols
        ).sum()
    ).item()
    if one_sided:
        raise ValueError(
            f"ANCOM-BC ({run}): the recipe does not reproduce the pipeline: {one_sided} "
            "estimates are missing or NaN on one side only. No pair was added"
        )
    gap = joined.select(
        pl.max_horizontal(
            (pl.col(c).cast(pl.Float64) - pl.col(f"{c}_ours").cast(pl.Float64)).abs().max()
            for c in cols
        )
    ).item()
    if gap is not None and gap > _AGREEMENT:
        raise ValueError(
            f"ANCOM-BC ({run}): the recipe does not reproduce the pipeline: its estimates, "
            f"standard errors or q-values differ by up to {gap:.3g} (tolerance {_AGREEMENT}). "
            "No pair was added"
        )


def _pairs(
    table,
    groups,
    column: str,
    pipeline: pl.DataFrame,
    label: str,
    base: str | None,
) -> pl.DataFrame:
    """The pairs of ``column`` a run's slices (``pipeline``) lack, labelled ``label``.

    When the run has slices, its contrasts are recomputed first: the added pairs are
    only as good as the match between this fit and the pipeline's.
    """
    from depictio.recipes.lib import ancombc as lib

    have = pipeline["contrast"].unique().to_list()
    if have and not base:
        raise ValueError(
            f"ANCOM-BC ({label or 'run'}): cannot tell the reference level of the pipeline's "
            f"contrasts {have} among the levels of {column!r}; no pair was added"
        )
    if have:
        fitted = lib.fit(table, groups, base).with_columns(
            (pl.lit(column) + pl.col("level")).alias("contrast")
        )
        _check_agreement(fitted, pipeline, label)
    added = lib.pairs(table, groups, column, base=base, skip=have)
    return added.with_columns(pl.lit(label).alias("taxonomy"))


def _computed(
    sources: dict[str, pl.DataFrame | None], params: dict, result: pl.DataFrame, labels: dict
) -> list[pl.DataFrame]:
    """The rows the recipe adds to the pipeline's (see the module docstring)."""
    column = str(params.get("group_col") or "")
    if not _truthy(params.get("pairwise")) or not column or column.startswith("{"):
        return []
    from depictio.recipes.lib import ancombc as lib

    if not lib.available():
        logger.warning(
            "ANCOM-BC pairs need scikit-bio (pip install 'depictio[stats]'): only the "
            "pipeline's own contrasts are loaded"
        )
        return []
    out = []
    base = None
    for counts_ref, label in (("counts", labels["primary"]), ("alt_counts", labels["alt"])):
        counts = sources.get(counts_ref)
        if counts is None or label is None:
            continue
        if column not in counts.columns:
            logger.warning(f"ANCOM-BC pairs: no column {column!r} in the {counts_ref} barplot")
            continue
        table, groups = lib.from_barplot(counts, column)
        mine = result.filter(
            pl.col("taxonomy").eq_missing(pl.lit(label))
            & pl.col("contrast").str.starts_with(column)
        ).select("id", "contrast", "lfc", "se", "q_val")
        run_base = lib.base_of(mine["contrast"].unique(), column, lib.levels_of(groups))
        base = base or run_base  # the merged taxonomy names its pairs as the first run
        out.append(_pairs(table, groups, column, mine, label, run_base))
    counts, feature_table, lineages = (
        sources.get(k) for k in ("counts", "feature_table", "merged_taxonomy")
    )
    if (
        counts is not None
        and feature_table is not None
        and lineages is not None
        and column in counts.columns
    ):
        _, groups = lib.from_barplot(counts, column)
        table = lib.collapse(feature_table, lineages)
        empty = pl.DataFrame(schema={"id": pl.Utf8, "contrast": pl.Utf8})
        out.append(_pairs(table, groups, column, empty, labels["merged"], base))
    return out


def transform(sources: dict[str, pl.DataFrame | None], params: dict | None = None) -> pl.DataFrame:
    """Melt each ANCOM-BC slice and join into one table with taxonomy annotations."""
    params = params or {}
    alt = {name: sources.get(f"{name}_alt") for name in _SLICES}
    has_alt = all(frame is not None for frame in alt.values())
    missing_alt = [f"{name}_alt" for name, frame in alt.items() if frame is None]
    expect_alt = str(params.get("expect_alt") or "").strip()
    expect_alt = bool(expect_alt) and not expect_alt.startswith("{")  # an unset PR2_RESULTS
    if not has_alt and expect_alt:
        raise ValueError(
            f"ANCOM-BC: the second run (PR2_RESULTS) has none of its 5 slices; missing {missing_alt}"
        )
    if not has_alt and len(missing_alt) < len(_SLICES):
        raise ValueError(
            f"ANCOM-BC: the second run has {len(_SLICES) - len(missing_alt)} of its 5 slices; "
            f"missing {missing_alt}"
        )
    has_merged = (
        _truthy(params.get("pairwise"))
        and sources.get("feature_table") is not None
        and sources.get("merged_taxonomy") is not None
    )
    if expect_alt and _truthy(params.get("pairwise")) and not has_merged:
        absent = [k for k in ("feature_table", "merged_taxonomy") if sources.get(k) is None]
        raise ValueError(f"ANCOM-BC: the merged taxonomy's test needs {absent}")

    label = pl.col("source_path").str.extract(_LABEL, 1)
    primary = (params.get("label") or DEFAULT_LABEL) if has_alt or has_merged else _NO_LABEL
    result = _melt(
        {name: sources[name] for name in _SLICES},
        label.fill_null(pl.lit(primary)),
    )
    alt_label = params.get("alt_label") or DEFAULT_ALT_LABEL
    if has_alt:
        result = pl.concat(
            [result, _melt(alt, pl.lit(alt_label))],
            how="diagonal_relaxed",
        )
    labels = {
        "primary": primary,
        "alt": alt_label if has_alt else None,
        "merged": params.get("merged_label") or DEFAULT_MERGED_LABEL,
    }
    result = pl.concat(
        [result, *_computed(sources, params, result, labels)], how="diagonal_relaxed"
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
