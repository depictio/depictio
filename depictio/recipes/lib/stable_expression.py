"""Shared parsing for nf-core/stableexpression outputs.

stableexpression downloads public expression datasets (Expression Atlas, GEO) for
one species, maps their gene ids to Ensembl, filters out samples with too many
zeros or missing values, normalises every dataset (TPM / CPM, then a quantile
normalisation to a uniform distribution, so every value lies in 0 to 1), merges
them into one gene by sample matrix and scores the most stable genes of each
expression section. The tables it publishes, and what this module reads from
them:

* ``reporting/all_genes_summary.csv``: one row per gene of the merged matrix,
  with its expression statistics (overall and per platform), its expression
  section (``section_1`` holds the most expressed genes), and, for the
  ``nb_candidates_per_section`` candidates of each section, the four stability
  measures (Normfinder, geNorm M, coefficient of variation and its robust,
  MAD-based form), their 0-1 normalised forms, the stability score (lower is
  more stable) and the rank within the section. Non-candidates carry a rank
  past the candidates that orders nothing, so it is dropped here.
* ``merged_data/all_counts.parquet`` (and ``all_counts.imputed.parquet``): the
  merged matrix, ``gene_id`` then one Float32 column per sample.
* ``merged_data/whole_design.csv``: ``batch`` (the dataset), ``condition`` (a
  group local to its dataset, ``g1``, ``g2`` ...) and ``sample``.
* ``datasets/<platform>/<normalisation>/<dataset>/<dataset>.design.csv``: the
  same design per downloaded dataset, before any filter. The directory is the
  only place a dataset's platform and normalisation state are written.
* ``statistics/``: per-dataset ID mapping counts, the samples each filter kept
  and rejected, and three ragged tables (``ratio_zeros.csv``,
  ``ratio_nulls.csv``, ``skewness.csv``: a dataset id, then one value per
  sample, no header).
* ``errors/renaming_failure_reasons.tsv`` and ``warnings/renaming_warning_reasons.tsv``:
  why a dataset's gene ids could not be mapped, or how many were.
"""

from __future__ import annotations

import re

import numpy as np
import polars as pl

from depictio.models.models.transforms import RecipeSource

#: Platform directory names under ``datasets/`` and how the dashboard prints them.
PLATFORM_LABELS: dict[str, str] = {"microarray": "Microarray", "rnaseq": "RNA-seq"}
#: Normalisation-state directory names (the data as published by the database).
NORMALISATION_LABELS: dict[str, str] = {"normalised": "Normalised", "raw": "Raw counts"}

#: The pipeline's five expression levels, most expressed first.
EXPRESSION_LEVELS: tuple[str, ...] = (
    "Very high expression",
    "High expression",
    "Medium range",
    "Low expression",
    "Very low expression",
)

#: Read any CSV as raw lines: one text column per line (the ragged statistics
#: tables have no header and a different width on every row).
LINE_READ_KWARGS: dict = {
    "separator": "\x1f",
    "has_header": False,
    "quote_char": None,
    "infer_schema_length": 0,
}
LINE_COLUMN = "column_1"

#: Read every column as text; the recipes cast what they use.
TEXT_READ_KWARGS: dict = {"infer_schema_length": 0}

_DATASET_PATH_RE = re.compile(
    r"(?:^|/)datasets/(?P<platform>[^/]+)/(?P<normalisation>[^/]+)/(?P<dataset>[^/]+)/"
)
_ATLAS_RE = re.compile(r"^(?P<accession>E_[A-Z]+_\d+)(?:_(?P<array>A_[A-Z0-9]+_\d+))?(?:_.*)?$")
_SECTION_RE = re.compile(r"(\d+)\s*$")

# The four stability measures of all_genes_summary.csv, in the pipeline's
# order (its --stability_score_weights order), with the names used here.
# Each entry: the pipeline's column, its name here, the stem of its normalised
# form and score part (``<stem>_norm``, ``<stem>_part``), and its label.
STABILITY_MEASURES: tuple[tuple[str, str, str, str], ...] = (
    ("normfinder_stability_value", "normfinder_stability", "normfinder", "Normfinder"),
    ("genorm_m_measure", "genorm_m", "genorm", "geNorm M"),
    ("coefficient_of_variation", "cv", "cv", "Coefficient of variation"),
    ("robust_coefficient_of_variation_median", "robust_cv", "robust_cv", "Robust CV"),
)
MISSING_COMPONENT = "Missing values"


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------


def platform_label(name: str | None) -> str | None:
    """``rnaseq`` -> ``RNA-seq``; an unknown platform keeps its name."""
    if name is None:
        return None
    return PLATFORM_LABELS.get(name.lower(), name)


def normalisation_label(name: str | None) -> str | None:
    """``raw`` -> ``Raw counts``; an unknown state keeps its name."""
    if name is None:
        return None
    return NORMALISATION_LABELS.get(name.lower(), name)


def accession_of(dataset: str) -> str:
    """The database accession a dataset id was built from.

    Expression Atlas ids read ``E_GEOD_10070_A_AFFY_44`` (accession, then the
    array design of a microarray experiment) or ``E_MTAB_9962_rnaseq``; the
    accession is printed the way the database writes it, ``E-GEOD-10070``. Any
    other id (GEO, a user dataset) is its own accession.
    """
    match = _ATLAS_RE.match(dataset)
    if match is None:
        return dataset
    return match.group("accession").replace("_", "-")


def array_design_of(dataset: str) -> str | None:
    """``A-AFFY-44`` for an Expression Atlas microarray dataset, else None."""
    match = _ATLAS_RE.match(dataset)
    if match is None or match.group("array") is None:
        return None
    return match.group("array").replace("_", "-")


def dataset_directories(designs: pl.DataFrame, path_col: str = "source_path") -> pl.DataFrame:
    """One row per dataset directory: ``dataset``, ``platform``, ``normalisation``.

    ``designs`` holds the per-dataset ``*.design.csv`` files read with a
    ``source_path`` column; the platform and normalisation state are the two
    directory levels above the dataset's own directory.
    """
    parts = designs.select(
        pl.col(path_col).str.extract_groups(_DATASET_PATH_RE.pattern).alias("_m")
    ).unnest("_m")
    out = (
        parts.drop_nulls("dataset")
        .unique(subset="dataset", keep="first")
        .with_columns(
            pl.col("platform").map_elements(platform_label, return_dtype=pl.Utf8),
            pl.col("normalisation").map_elements(normalisation_label, return_dtype=pl.Utf8),
        )
    )
    return out.select("dataset", "platform", "normalisation").sort("dataset")


def guess_platform(dataset: str) -> str:
    """Platform of a dataset whose directory was not published, from its id."""
    return (
        PLATFORM_LABELS["rnaseq"] if dataset.endswith("_rnaseq") else PLATFORM_LABELS["microarray"]
    )


def ragged_medians(lines: pl.DataFrame | None, name: str) -> pl.DataFrame:
    """``dataset`` and the median of its per-sample values, from a ragged table.

    ``ratio_zeros.csv``, ``ratio_nulls.csv`` and ``skewness.csv`` write a dataset
    id, then one value per sample, with no header and a different number of
    fields on every row.
    """
    if lines is None or lines.is_empty():
        return pl.DataFrame(schema={"dataset": pl.Utf8, name: pl.Float64})
    rows: list[tuple[str, float | None]] = []
    for line in lines.get_column(LINE_COLUMN).to_list():
        if line is None:
            continue
        cells = [c.strip() for c in str(line).split(",")]
        if not cells or not cells[0]:
            continue
        values = []
        for cell in cells[1:]:
            try:
                value = float(cell)
            except ValueError:
                continue
            if np.isfinite(value):
                values.append(value)
        rows.append((cells[0], float(np.median(values)) if values else None))
    return pl.DataFrame(rows, schema={"dataset": pl.Utf8, name: pl.Float64}, orient="row").unique(
        subset="dataset", keep="last"
    )


# ---------------------------------------------------------------------------
# Genes
# ---------------------------------------------------------------------------


def section_index(section: str | None) -> int | None:
    """``section_3`` -> 3."""
    if section is None:
        return None
    match = _SECTION_RE.search(section)
    return int(match.group(1)) if match else None


def section_label(index: int | None, n_sections: int) -> str | None:
    """``Section 03`` of ten: zero-padded so the sections sort as numbers do."""
    if index is None:
        return None
    width = max(2, len(str(n_sections)))
    return f"Section {index:0{width}d}"


def _float(col: str) -> pl.Expr:
    return pl.col(col).cast(pl.Float64, strict=False).fill_nan(None)


def load_gene_summary(raw: pl.DataFrame) -> pl.DataFrame:
    """``all_genes_summary.csv`` (read as text) with typed, renamed columns.

    Every gene keeps ``gene_id``; ``gene_name`` is its symbol, or its id when
    the metadata has none (a lncRNA without a name), so a label is never empty.
    ``section`` becomes ``Section 01`` ... with ``section_index``. Candidates
    keep their rank within the section as ``section_rank``; the others get null.
    The per-platform columns the pipeline writes (``rnaseq_mean``,
    ``microarray_coefficient_of_variation`` ...) are kept under short names.
    """
    needed = [
        "mean", "median", "standard_deviation", "median_absolute_deviation",
        "coefficient_of_variation", "robust_coefficient_of_variation_median",
        "ratio_nulls_in_all_samples", "ratio_nulls_in_valid_samples", "ratio_zeros",
        "expression_level_quantile_interval", "stability_score", "rank",
        *[raw for raw, _v, _s, _l in STABILITY_MEASURES],
        *[f"{raw}_normalised" for raw, _v, _s, _l in STABILITY_MEASURES],
    ]  # fmt: skip
    # A measure the run skipped (geNorm with --skip_genorm) has no column at all.
    df = raw.with_columns(
        [pl.lit(None, dtype=pl.Utf8).alias(c) for c in needed if c not in raw.columns]
    )
    sections = df.get_column("section").map_elements(section_index, return_dtype=pl.Int64)
    n_sections = int(sections.max() or 1)
    is_candidate = (
        pl.col("is_candidate").cast(pl.Int64, strict=False).fill_null(0) == 1
        if "is_candidate" in df.columns
        else _float("stability_score").is_not_null()
    )
    name = pl.col("name") if "name" in df.columns else pl.lit(None, dtype=pl.Utf8)
    name = pl.when(name.is_in(["", "None", "nan", "NaN"])).then(None).otherwise(name)
    exprs: list[pl.Expr] = [
        pl.col("gene_id"),
        name.alias("gene_symbol"),
        pl.coalesce(name, pl.col("gene_id")).alias("gene_name"),
        (pl.col("description") if "description" in df.columns else pl.lit(None, dtype=pl.Utf8))
        .replace({"": None, "None": None})
        .alias("description"),
        sections.alias("section_index"),
        is_candidate.alias("_candidate"),
        _float("mean").alias("mean"),
        _float("median").alias("median"),
        _float("standard_deviation").alias("standard_deviation"),
        _float("median_absolute_deviation").alias("mad"),
        _float("coefficient_of_variation").alias("cv"),
        _float("robust_coefficient_of_variation_median").alias("robust_cv"),
        (1 - _float("ratio_nulls_in_all_samples")).alias("measured_share"),
        _float("ratio_nulls_in_valid_samples").alias("missing_penalty"),
        _float("ratio_zeros").alias("zero_share"),
        _float("expression_level_quantile_interval").alias("expression_percentile"),
        (
            pl.col("expression_level_status")
            if "expression_level_status" in df.columns
            else pl.lit(None, dtype=pl.Utf8)
        ).alias("expression_level"),
        _float("stability_score").alias("stability_score"),
        pl.col("rank").cast(pl.Int64, strict=False).alias("_rank"),
        (
            pl.col("original_gene_ids").str.split(";").list.len().cast(pl.Int64)
            if "original_gene_ids" in df.columns
            else pl.lit(None, dtype=pl.Int64)
        ).alias("source_ids"),
    ]
    for raw_name, value_col, stem, _label in STABILITY_MEASURES:
        if value_col not in ("cv", "robust_cv"):  # both are expression statistics too, above
            exprs.append(_float(raw_name).alias(value_col))
        exprs.append(_float(f"{raw_name}_normalised").alias(f"{stem}_norm"))
    for platform in PLATFORM_LABELS:
        for stat, short in (("mean", "mean"), ("coefficient_of_variation", "cv")):
            col = f"{platform}_{stat}"
            if col in df.columns:
                exprs.append(_float(col).alias(f"{platform}_{short}"))
    out = df.select(exprs)
    out = out.with_columns(
        pl.col("section_index")
        .map_elements(lambda i: section_label(i, n_sections), return_dtype=pl.Utf8)
        .alias("section"),
        pl.when(pl.col("_candidate")).then(pl.col("_rank")).otherwise(None).alias("section_rank"),
        pl.when(pl.col("_candidate"))
        .then(pl.lit("Candidate"))
        .otherwise(pl.lit("Not a candidate"))
        .alias("candidate"),
    )
    # Which platforms measured the gene, from the per-platform means.
    platform_cols = [p for p in PLATFORM_LABELS if f"{p}_mean" in out.columns]
    if platform_cols:
        present = [pl.col(f"{p}_mean").is_not_null() for p in platform_cols]
        label = pl.lit(None, dtype=pl.Utf8)
        if len(platform_cols) == 2:
            label = (
                pl.when(present[0] & present[1])
                .then(pl.lit("Both platforms"))
                .when(present[0])
                .then(pl.lit(f"{PLATFORM_LABELS[platform_cols[0]]} only"))
                .when(present[1])
                .then(pl.lit(f"{PLATFORM_LABELS[platform_cols[1]]} only"))
                .otherwise(None)
            )
        else:
            label = (
                pl.when(present[0])
                .then(pl.lit(f"{PLATFORM_LABELS[platform_cols[0]]} only"))
                .otherwise(None)
            )
        out = out.with_columns(label.alias("platforms"))
    else:
        out = out.with_columns(pl.lit(None, dtype=pl.Utf8).alias("platforms"))
    return out.drop("_rank")


def stability_weights(candidates: pl.DataFrame) -> dict[str, float]:
    """The weights of the four measures in the stability score, recovered from it.

    The pipeline scores a candidate as ``missing_penalty + sum(w_i * norm_i)``
    over the normalised measures it computed (``--stability_score_weights``,
    0.25 each by default; a measure the run skipped, geNorm with
    ``--skip_genorm``, adds nothing). The weights are a run parameter that no
    table records, so they are solved for by least squares over the candidates
    and rounded to 4 decimals. Too few candidates, or a fit that does not
    reproduce the scores, falls back to the default equal weights.
    """
    shorts = [stem for _raw, _value, stem, _label in STABILITY_MEASURES]
    default = {short: 0.25 for short in shorts}
    usable = [s for s in shorts if candidates.get_column(f"{s}_norm").is_not_null().any()]
    if not usable or candidates.height < len(usable) + 2:
        return default
    x = candidates.select([pl.col(f"{s}_norm").fill_null(0.0) for s in usable]).to_numpy()
    y = (
        candidates.get_column("stability_score")
        - candidates.get_column("missing_penalty").fill_null(0.0)
    ).to_numpy()
    keep = np.isfinite(y)
    if keep.sum() < len(usable) + 2:
        return default
    solution, *_ = np.linalg.lstsq(x[keep], y[keep], rcond=None)
    if np.nanmax(np.abs(x[keep] @ solution - y[keep])) > 1e-3:
        return default
    weights = {s: 0.0 for s in shorts}
    weights.update({s: round(float(w), 4) for s, w in zip(usable, solution, strict=True)})
    return weights


def candidates_with_parts(summary: pl.DataFrame) -> pl.DataFrame:
    """The candidates of ``all_genes_summary.csv``, ranked, with the score split in parts."""
    genes = load_gene_summary(summary)
    candidates = genes.filter(
        (pl.col("candidate") == "Candidate") & pl.col("stability_score").is_not_null()
    )
    if candidates.is_empty():
        raise ValueError("all_genes_summary.csv holds no scored candidate gene")
    weights = stability_weights(candidates)
    return candidates.with_columns(
        overall_rank_expr(),
        pl.col("missing_penalty").fill_null(0.0),
        *[
            (pl.col(f"{stem}_norm").fill_null(0.0) * weights[stem]).alias(f"{stem}_part")
            for _raw, _value, stem, _label in STABILITY_MEASURES
        ],
    ).with_columns(
        # 1 / rank: the most stable gene in view outweighs any other, so a text
        # value's `top` aggregation (largest summed weight) names it.
        (1.0 / pl.col("overall_rank")).alias("rank_weight"),
        # Each measure's own rank within the section, 1 the steadiest: two
        # measures that agree put a gene on the diagonal of one against the other.
        *[
            pl.col(raw).rank(method="ordinal").over("section").cast(pl.Int64).alias(f"{stem}_rank")
            for raw, stem in (("normfinder_stability", "normfinder"), ("genorm_m", "genorm"))
        ],
    )


def overall_rank_expr() -> pl.Expr:
    """Rank over every candidate by stability score, 1 the most stable (ties by order)."""
    return pl.col("stability_score").rank(method="ordinal").cast(pl.Int64).alias("overall_rank")


def box_stats(values: np.ndarray) -> dict[str, float | int | None]:
    """Tukey box statistics of ``values`` (NaN dropped), as a box plot draws them.

    Quartiles are linearly interpolated (numpy's default, the renderer's too);
    each whisker ends at the furthest value within 1.5 IQR of its quartile.
    """
    v = values[np.isfinite(values)]
    if v.size == 0:
        return {
            k: None for k in ("q1", "median", "q3", "lower", "upper", "mean", "sd", "min", "max")
        } | {"n": 0}
    v = np.sort(v)
    q1, median, q3 = (float(x) for x in np.quantile(v, [0.25, 0.5, 0.75]))
    iqr = q3 - q1
    low_fence, high_fence = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = v[(v >= low_fence) & (v <= high_fence)]
    lower = float(min(inside.min(), q1)) if inside.size else q1
    upper = float(max(inside.max(), q3)) if inside.size else q3
    return {
        "q1": q1,
        "median": median,
        "q3": q3,
        "lower": lower,
        "upper": upper,
        "mean": float(v.mean()),
        "sd": float(v.std(ddof=1)) if v.size > 1 else 0.0,
        "min": float(v[0]),
        "max": float(v[-1]),
        "n": int(v.size),
    }


def gene_rows(counts: pl.DataFrame, gene_ids: list[str]) -> pl.DataFrame:
    """The rows of ``gene_ids`` in a gene by sample matrix (``gene_id`` first)."""
    return counts.filter(pl.col("gene_id").is_in(gene_ids))


# ---------------------------------------------------------------------------
# Datasets through the pipeline
# ---------------------------------------------------------------------------

#: The steps a downloaded dataset goes through, in order, with the column of
#: ``dataset_table`` that holds the samples still in after that step.
FUNNEL_STEPS: tuple[tuple[str, str], ...] = (
    ("Downloaded", "samples_downloaded"),
    ("Gene IDs mapped", "samples_id_mapped"),
    ("Zero filter", "samples_after_zero_filter"),
    ("Missing-value filter", "samples_kept"),
)

OUTCOME_MERGED = "Merged"
OUTCOME_NO_GENE = "No gene mapped"
OUTCOME_RARE_GENES = "Only rare genes"
OUTCOME_FILTERED = "All samples filtered out"


def dataset_sources() -> list[RecipeSource]:
    """The sources ``dataset_table`` reads, shared by every dataset-level recipe.

    Only the per-dataset designs are required: every run publishes them. The
    statistics tables are written by steps a run can skip (``--skip_id_mapping``)
    and the reason tables only when a dataset failed or lost ids, so each is an
    optional single file.
    """
    tsv = {"separator": "\t", "infer_schema_length": 0}
    return [
        RecipeSource(
            ref="designs",
            glob_pattern="datasets/*/*/*/*.design.csv",
            format="csv",
            read_kwargs=TEXT_READ_KWARGS,
            source_path="source_path",
            input_schema={"batch": pl.Utf8, "condition": pl.Utf8, "sample": pl.Utf8},
        ),
        RecipeSource(
            ref="id_mapping",
            path="statistics/id_mapping_stats.csv",
            format="csv",
            read_kwargs=TEXT_READ_KWARGS,
            optional=True,
        ),
        RecipeSource(
            ref="zero_filter",
            path="statistics/zero_values_filter_stats.csv",
            format="csv",
            read_kwargs=TEXT_READ_KWARGS,
            optional=True,
        ),
        RecipeSource(
            ref="missing_filter",
            path="statistics/missing_values_filter_stats.csv",
            format="csv",
            read_kwargs=TEXT_READ_KWARGS,
            optional=True,
        ),
        RecipeSource(
            ref="failures",
            path="errors/renaming_failure_reasons.tsv",
            format="csv",
            read_kwargs=tsv,
            optional=True,
        ),
        RecipeSource(
            ref="warnings",
            path="warnings/renaming_warning_reasons.tsv",
            format="csv",
            read_kwargs=tsv,
            optional=True,
        ),
        *[
            RecipeSource(
                ref=ref,
                path=f"statistics/{ref}.csv",
                format="csv",
                read_kwargs=LINE_READ_KWARGS,
                optional=True,
            )
            for ref in ("ratio_zeros", "ratio_nulls", "skewness")
        ],
    ]


def _int_frame(df: pl.DataFrame | None, columns: dict[str, str]) -> pl.DataFrame | None:
    """``dataset`` plus ``columns`` (source -> output name) cast to Int64."""
    if df is None or df.is_empty() or "dataset" not in df.columns:
        return None
    present = {src: out for src, out in columns.items() if src in df.columns}
    return df.select(
        pl.col("dataset"),
        *[pl.col(src).cast(pl.Int64, strict=False).alias(out) for src, out in present.items()],
    ).unique(subset="dataset", keep="last")


def _reasons(df: pl.DataFrame | None, name: str) -> pl.DataFrame | None:
    """``dataset`` and the reason text of an errors/ or warnings/ table."""
    if df is None or df.is_empty():
        return None
    cols = {c.lower(): c for c in df.columns}
    if "dataset" not in cols or "reason" not in cols:
        return None
    return (
        df.select(pl.col(cols["dataset"]).alias("dataset"), pl.col(cols["reason"]).alias(name))
        .group_by("dataset", maintain_order=True)
        .agg(pl.col(name).str.join(" | "))
    )


def _ensure(df: pl.DataFrame, columns: dict[str, type[pl.DataType]]) -> pl.DataFrame:
    """``df`` with every column of ``columns`` it lacks added as nulls."""
    return df.with_columns(
        [
            pl.lit(None, dtype=dtype).alias(col)
            for col, dtype in columns.items()
            if col not in df.columns
        ]
    )


def dataset_table(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per downloaded dataset, with what each step of the pipeline did to it.

    Sources (all but ``designs`` optional): ``designs`` (every
    ``datasets/*/*/*/*.design.csv`` with ``source_path``), ``id_mapping``,
    ``zero_filter``, ``missing_filter`` (the ``statistics/`` tables),
    ``failures`` / ``warnings`` (the renaming reasons) and the ragged
    ``ratio_zeros`` / ``ratio_nulls`` / ``skewness`` tables read as lines.

    A step the dataset never reached holds 0 samples, so a funnel sums
    cleanly; a run without ID mapping (``--skip_id_mapping``) counts every
    dataset as mapped.
    """
    designs = sources["designs"]
    dirs = dataset_directories(designs)
    downloaded = (
        designs.filter(pl.col("batch").is_not_null())
        .group_by(pl.col("batch").alias("dataset"))
        .agg(
            pl.col("sample").n_unique().cast(pl.Int64).alias("samples_downloaded"),
            pl.col("condition").n_unique().cast(pl.Int64).alias("conditions"),
        )
    )
    out = dirs.join(downloaded, on="dataset", how="left")

    id_stats = _int_frame(
        sources.get("id_mapping"),
        {
            "final": "genes_kept",
            "merged": "ids_merged",
            "not_valid": "genes_rare",
            "unmapped": "ids_unmapped",
        },
    )
    zero = _int_frame(
        sources.get("zero_filter"),
        {"kept": "samples_after_zero_filter", "rejected": "samples_rejected_zeros"},
    )
    missing = _int_frame(
        sources.get("missing_filter"),
        {"kept": "samples_kept", "rejected": "samples_rejected_missing"},
    )
    for frame in (id_stats, zero, missing):
        if frame is not None:
            out = out.join(frame, on="dataset", how="left")
    for ref, name in (("failures", "failure_reason"), ("warnings", "mapping_note")):
        reasons = _reasons(sources.get(ref), name)
        if reasons is not None:
            out = out.join(reasons, on="dataset", how="left")
    for ref, name in (
        ("ratio_zeros", "zero_share"),
        ("ratio_nulls", "missing_share"),
        ("skewness", "skewness"),
    ):
        out = out.join(ragged_medians(sources.get(ref), name), on="dataset", how="left")
    out = _ensure(
        out,
        {
            "genes_kept": pl.Int64,
            "ids_merged": pl.Int64,
            "genes_rare": pl.Int64,
            "ids_unmapped": pl.Int64,
            "samples_after_zero_filter": pl.Int64,
            "samples_rejected_zeros": pl.Int64,
            "samples_kept": pl.Int64,
            "samples_rejected_missing": pl.Int64,
            "failure_reason": pl.Utf8,
            "mapping_note": pl.Utf8,
        },
    )

    # Every id the dataset came with is kept, merged into another id (which
    # counts the rare genes too: ``merged`` is mapped minus kept) or unmapped.
    # A dataset that lost every gene as rare writes 0 merged, not the rare count.
    mapped = pl.col("genes_kept") + pl.max_horizontal("ids_merged", "genes_rare")
    original = mapped + pl.col("ids_unmapped")
    has_stats = pl.col("genes_kept").is_not_null()
    failed = pl.col("failure_reason").is_not_null() | (has_stats & (pl.col("genes_kept") == 0))
    out = out.with_columns(
        pl.col("dataset").map_elements(accession_of, return_dtype=pl.Utf8).alias("accession"),
        pl.col("dataset").map_elements(array_design_of, return_dtype=pl.Utf8).alias("array_design"),
        original.alias("gene_ids_in"),
        pl.when(has_stats & (original > 0))
        .then((mapped / original).round(4))
        .otherwise(None)
        .alias("mapped_share"),
        (pl.col("ids_merged") - pl.col("genes_rare")).clip(lower_bound=0).alias("ids_collapsed"),
        pl.when(failed).then(0).otherwise(1).cast(pl.Int64).alias("id_mapped"),
        pl.col("samples_after_zero_filter").fill_null(0),
        pl.col("samples_kept").fill_null(0),
        pl.col("samples_rejected_zeros").fill_null(0),
        pl.col("samples_rejected_missing").fill_null(0),
    )
    out = out.with_columns(
        pl.when(pl.col("id_mapped") == 1)
        .then(pl.col("samples_downloaded"))
        .otherwise(0)
        .alias("samples_id_mapped"),
        pl.when(pl.col("id_mapped") == 0)
        .then(
            pl.when(pl.col("failure_reason").str.contains("(?i)rare"))
            .then(pl.lit(OUTCOME_RARE_GENES))
            .otherwise(pl.lit(OUTCOME_NO_GENE))
        )
        .when(pl.col("samples_kept") == 0)
        .then(pl.lit(OUTCOME_FILTERED))
        .otherwise(pl.lit(OUTCOME_MERGED))
        .alias("outcome"),
        pl.lit(1, dtype=pl.Int64).alias("downloaded"),
        (pl.col("samples_kept") > 0).cast(pl.Int64).alias("merged"),
        pl.when(pl.col("samples_downloaded") > 0)
        .then((pl.col("samples_kept") / pl.col("samples_downloaded")).round(4))
        .otherwise(None)
        .alias("kept_share"),
    )
    return out.sort("platform", "dataset")
