"""Readable labels and normalised matrices out of Bambu's count files.

Bambu writes two count matrices side by side, ``counts_gene.txt`` and
``counts_transcript.txt``, and labels their rows with a GTF attribute string
rather than an identifier::

    ccds_id CCDS10000; exon_id ENSE00001512396; exon_number 5; gene_biotype protein_coding; ENSG00000183828

Whatever the annotation's granularity, the Ensembl gene id and the biotype are
always in that string, so every recipe that touches a Bambu output needs the
same two extractions. DEXSeq re-emits the same string through R's
``write.csv`` with the spaces squeezed out
(``exon_idENSE...;gene_biotypeprotein_coding;ENSG...``), which is why the
patterns below tolerate a missing separator.

The second half of the module is the matrix work the quantification recipes
share: read the ragged ``counts_gene.txt`` header, name the sample columns,
melt to long with CPM, and build the log-CPM matrix the PCA, the sample
correlation and the top-variable heatmap all start from. Counts-per-million is
computed against the FULL library (every row of the matrix) before any feature
filter, so filtering a recipe's output never moves the normalisation.

Shared here rather than copied because five catalog recipes and three
pipeline-local ones need exactly this, and recipes may not import each other.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from depictio.recipes.lib.sample_ids import strip_stage_suffixes

#: Ensembl gene id, anywhere in the attribute string.
GENE_ID_PATTERN = r"(ENSG\d+)"
#: ``gene_biotype protein_coding`` and ``gene_biotypeprotein_coding`` both.
BIOTYPE_PATTERN = r"gene_biotype\s*([A-Za-z0-9_.+-]+)"
#: ``exon_id ENSE00001512396``, the only part of the string that is row-unique.
EXON_ID_PATTERN = r"(ENSE\d+)"

#: Features under this total count across the run are dropped from the long
#: outputs: they carry no signal and multiply the row count by six.
MIN_TOTAL_COUNT = 1.0


def gene_id_expr(column: str) -> pl.Expr:
    """The Ensembl gene id inside a Bambu row label."""
    return pl.col(column).str.extract(GENE_ID_PATTERN, 1)


def gene_biotype_expr(column: str) -> pl.Expr:
    """The Ensembl biotype inside a Bambu row label."""
    return pl.col(column).str.extract(BIOTYPE_PATTERN, 1)


def exon_id_expr(column: str) -> pl.Expr:
    """The Ensembl exon id inside a Bambu row label, when the label has one."""
    return pl.col(column).str.extract(EXON_ID_PATTERN, 1)


def sample_names(header_row: tuple) -> list[str]:
    """Sample ids of a Bambu header line, stage suffixes (``.sorted``) removed."""
    return [strip_stage_suffixes(str(value)) for value in header_row]


def name_sample_columns(counts: pl.DataFrame, names: list[str]) -> tuple[pl.DataFrame, str]:
    """Rename the generic trailing columns of a headerless read to sample ids.

    Returns the renamed frame and the name of the leading descriptor column.
    Raises when the header and the data rows disagree on how many samples the
    matrix holds, which is the one way a ragged Bambu file can be misread
    silently.
    """
    descriptor, *generic = counts.columns
    if len(generic) != len(names):
        raise ValueError(
            f"bambu counts: {len(generic)} data columns after the descriptor but "
            f"{len(names)} sample names in the header"
        )
    renamed = counts.rename(dict(zip(generic, names, strict=True)))
    return renamed.with_columns(
        [pl.col(c).cast(pl.Float64, strict=False) for c in names]
    ), descriptor


def cpm_scales(wide: pl.DataFrame, samples: list[str]) -> dict[str, float]:
    """Sample -> the factor that turns one of its counts into a CPM.

    The library size is the sample's total over the WHOLE frame, so a feature
    filter applied afterwards cannot move the normalisation. An empty column
    scales to zero rather than dividing by zero.
    """
    library_sizes = {c: float(wide[c].sum() or 0.0) for c in samples}
    return {c: (1_000_000.0 / size if size else 0.0) for c, size in library_sizes.items()}


def melt_counts(
    wide: pl.DataFrame,
    id_columns: list[str],
    samples: list[str],
    *,
    min_total: float = MIN_TOTAL_COUNT,
) -> pl.DataFrame:
    """Wide feature x sample counts -> long rows with CPM and log CPM.

    ``cpm`` uses each sample's column total over the whole input frame, so the
    ``min_total`` feature filter applied afterwards cannot shift it.
    ``log_cpm`` is ``log2(cpm + 1)``.
    """
    scales = cpm_scales(wide, samples)
    kept = wide.filter(pl.sum_horizontal(samples) >= min_total)
    long = kept.unpivot(
        index=id_columns,
        on=samples,
        variable_name="sample",
        value_name="count",
    )
    scale = pl.col("sample").replace_strict(scales, default=0.0, return_dtype=pl.Float64)
    return long.with_columns(
        pl.col("count").cast(pl.Float64),
        (pl.col("count").cast(pl.Float64) * scale).alias("cpm"),
    ).with_columns((pl.col("cpm") + 1.0).log(base=2).alias("log_cpm"))


def log_cpm_matrix(wide: pl.DataFrame, id_column: str, samples: list[str]) -> pl.DataFrame:
    """Wide counts -> wide log2(CPM + 1), same shape, same column order."""
    scales = cpm_scales(wide, samples)
    return wide.select(
        pl.col(id_column),
        *[((pl.col(c).cast(pl.Float64) * scales[c]) + 1.0).log(base=2).alias(c) for c in samples],
    )


def condition_of(sample: str) -> str:
    """The group a replicate belongs to, for matrices that carry no sample sheet.

    Bambu's matrices name their columns after the samplesheet's ``sample``, and
    every long-read RNA samplesheet this catalog has seen spells a replicate
    ``<group>_R<n>`` / ``<group>_rep<n>``. Falling back to the sample id keeps
    the column populated when it does not.
    """
    stem = str(sample)
    for token in ("_R", "_r", "_rep", "_REP", "_Rep"):
        head, sep, tail = stem.rpartition(token)
        if sep and head and tail.isdigit():
            return head
    return stem


#: Columns a DESeq2-on-Bambu frame publishes, in order. Matches the
#: pipeline-agnostic ``deseq2/results`` output so a dashboard tile can keep
#: using its catalog renders, with the readable label columns appended.
DESEQ2_COLUMNS: dict[str, type[pl.DataType]] = {
    "contrast": pl.Utf8,
    "gene_id": pl.Utf8,
    "gene_biotype": pl.Utf8,
    "feature_label": pl.Utf8,
    "exon_id": pl.Utf8,
    "base_mean": pl.Float64,
    "log2fc": pl.Float64,
    "lfc_se": pl.Float64,
    "pvalue": pl.Float64,
    "padj": pl.Float64,
    "log2_base_mean": pl.Float64,
    "neg_log10_padj": pl.Float64,
    "significant": pl.Boolean,
    "direction": pl.Utf8,
}

#: DESeq2's own defaults, and the thresholds the volcano tiles draw at.
PADJ_THRESHOLD = 0.05
LFC_THRESHOLD = 1.0
#: ``-log10(padj)`` where padj underflowed to 0; beyond this the axis is noise.
NEG_LOG10_CAP = 300.0

#: Used when the samplesheet does not name exactly two conditions.
FALLBACK_CONTRAST = "all"


def contrast_label(samplesheet: pl.DataFrame | None) -> str:
    """``A549 vs K562`` from the sheet's two condition groups, else ``all``."""
    if samplesheet is None or "sample" not in samplesheet.columns:
        return FALLBACK_CONTRAST
    groups = (
        samplesheet.select(
            pl.col("sample").cast(pl.Utf8).str.replace(r"_R\d+$", "").alias("condition")
        )
        .drop_nulls()
        .unique()
        .sort("condition")["condition"]
        .to_list()
    )
    return f"{groups[0]} vs {groups[1]}" if len(groups) == 2 else FALLBACK_CONTRAST


def deseq2_on_bambu(raw: pl.DataFrame, contrast: str) -> pl.DataFrame:
    """A DESeq2 results table whose row labels are Bambu attribute strings.

    Takes the raw scan of ``deseq2.results.txt`` (R ``write.csv``: an unnamed
    first column of row names, every column read as text) and returns the tidy
    differential frame every volcano / MA / QQ / barplot tile expects, with a
    readable ``gene_id`` and a ``gene_biotype`` extracted from the row label
    rather than the label itself. Keeping the full label in ``feature_label``
    means nothing is lost, only demoted out of the axis.

    Row granularity is left alone: DESeq2 tested the annotation entries it was
    given, so collapsing them here would be inventing a statistic.
    """
    label = raw.columns[0]
    numeric = {
        "baseMean": "base_mean",
        "log2FoldChange": "log2fc",
        "lfcSE": "lfc_se",
        "pvalue": "pvalue",
        "padj": "padj",
    }
    missing = [c for c in numeric if c not in raw.columns]
    if missing:
        raise ValueError(f"deseq2 results: table lacks columns {missing}")

    frame = raw.with_columns(
        pl.lit(contrast, dtype=pl.Utf8).alias("contrast"),
        gene_id_expr(label).alias("gene_id"),
        gene_biotype_expr(label).fill_null("unannotated").alias("gene_biotype"),
        pl.col(label).cast(pl.Utf8).alias("feature_label"),
        exon_id_expr(label).alias("exon_id"),
        *[
            pl.col(source).cast(pl.Float64, strict=False).alias(name)
            for source, name in numeric.items()
        ],
    )
    frame = frame.with_columns(
        # A label with no Ensembl id still has to plot, so it keeps the string.
        pl.coalesce(pl.col("gene_id"), pl.col("feature_label")).alias("gene_id"),
        (pl.col("base_mean") + 1.0).log(base=2).alias("log2_base_mean"),
        # A null padj (DESeq2's NA on an independently filtered gene) has no
        # significance to plot and stays null; only a padj that underflowed to
        # 0 is capped, and `min_horizontal` would have read the null as 0.
        pl.when(pl.col("padj").is_null())
        .then(None)
        .when(pl.col("padj") > 0)
        .then(pl.min_horizontal(-pl.col("padj").log10(), pl.lit(NEG_LOG10_CAP)))
        .otherwise(NEG_LOG10_CAP)
        .cast(pl.Float64)
        .alias("neg_log10_padj"),
    )
    significant = (pl.col("padj") < PADJ_THRESHOLD) & (pl.col("log2fc").abs() >= LFC_THRESHOLD)
    return frame.with_columns(
        significant.fill_null(False).alias("significant"),
        pl.when(~significant.fill_null(False))
        .then(pl.lit("not significant"))
        .when(pl.col("log2fc") > 0)
        .then(pl.lit("up"))
        .otherwise(pl.lit("down"))
        .alias("direction"),
    ).select(list(DESEQ2_COLUMNS))


def spearman_matrix(values: np.ndarray) -> np.ndarray:
    """Spearman correlation between the COLUMNS of ``values``.

    Rank each column, then Pearson on the ranks; numpy only, so no scipy.
    Ties are given their average rank, which is what makes it Spearman rather
    than a rank-order approximation.
    """
    ranks = np.empty_like(values, dtype=np.float64)
    for j in range(values.shape[1]):
        column = values[:, j]
        order = np.argsort(column, kind="mergesort")
        sorted_column = column[order]
        column_ranks = np.empty(len(column), dtype=np.float64)
        start = 0
        for i in range(1, len(sorted_column) + 1):
            if i == len(sorted_column) or sorted_column[i] != sorted_column[start]:
                column_ranks[order[start:i]] = 0.5 * (start + i - 1) + 1.0
                start = i
        ranks[:, j] = column_ranks
    centred = ranks - ranks.mean(axis=0)
    norms = np.sqrt((centred**2).sum(axis=0))
    norms[norms == 0.0] = 1.0
    return (centred / norms).T @ (centred / norms)
