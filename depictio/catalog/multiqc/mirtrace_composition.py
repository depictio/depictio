"""miRTrace read composition per library, three partitions in one frame.

miRTrace writes three per-library breakdowns that MultiQC plots as stacked
bars and keeps, as plot input, in ``multiqc.parquet``:

``RNA type`` (plot ``mirtrace_rna_categories_plot``)
    Reads classified as miRNA, rRNA, tRNA, artifact or unknown. The miRNA
    share is the headline number of a small RNA library; a high rRNA or tRNA
    share usually means degraded RNA or a size selection that let fragments in.
``Read QC`` (plot ``mirtrace_qc_plot``)
    What happened to each read in miRTrace's own QC: adapter removed and
    length kept, adapter not found, shorter than 18 nt after trimming, low
    complexity, low base quality. On reads already trimmed upstream (as
    nf-core/smrnaseq does with fastp), "adapter not detected" is the normal
    majority.
``Clade`` (plot ``mirtrace_contamination_check_plot``)
    How many detected miRNAs are specific to each organism clade. A library
    should put nearly all of them in the clade of the sequenced species;
    miRNAs of another clade point at contamination. The unit here is miRNAs,
    not reads.

The frame is the stacked-composition contract (``sample``, ``rank``,
``taxon``, ``abundance``), so one tile switches between the three.

Source: the run's ``multiqc_data/multiqc.parquet`` (MultiQC 1.20 or newer).

Output schema:
    sample : Utf8
    rank : Utf8        RNA type | Read QC | Clade
    taxon : Utf8       category within the partition
    abundance : Float64  reads (RNA type, Read QC) or miRNAs (Clade)
    percent : Float64  of the library's total in the partition, %
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        glob_pattern="**/*_data/multiqc.parquet",
        format="parquet",
        read_kwargs={"columns": ["anchor", "type", "plot_input_data"]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "rank": pl.Utf8,
    "taxon": pl.Utf8,
    "abundance": pl.Float64,
    "percent": pl.Float64,
}

#: MultiQC plot anchor -> (partition name, category labels).
PLOTS: dict[str, tuple[str, dict[str, str]]] = {
    "mirtrace_rna_categories_plot": (
        "RNA type",
        {
            "reads_mirna": "miRNA",
            "reads_rrna": "rRNA",
            "reads_trna": "tRNA",
            "reads_artifact": "Artifact",
            "reads_unknown": "Unknown",
        },
    ),
    "mirtrace_qc_plot": (
        "Read QC",
        {
            "adapter_removed_length_ok": "Adapter removed, length kept",
            "adapter_not_detected": "Adapter not detected",
            "length_shorter_than_18": "Shorter than 18 nt",
            "low_complexity": "Low complexity",
            "low_phred": "Low base quality",
        },
    ),
    "mirtrace_contamination_check_plot": ("Clade", {}),
}


def plot_data(report: pl.DataFrame, anchor: str) -> list | None:
    """The ``data`` field of one plot's stored input, or None when absent."""
    rows = report.filter((pl.col("anchor") == anchor) & (pl.col("type") == "plot_input"))
    if rows.is_empty() or rows["plot_input_data"][0] is None:
        return None
    return json.loads(rows["plot_input_data"][0]).get("data")


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _label(key: str, labels: dict[str, str]) -> str:
    return labels.get(key) or key.replace("_", " and ").capitalize()


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per (sample, partition, category)."""
    report = sources["report"]
    rows: list[dict] = []
    for anchor, (rank, labels) in PLOTS.items():
        data = plot_data(report, anchor)
        if not data:
            continue
        for dataset in data[:1]:  # the first dataset is the count view
            for sample, categories in dataset.items():
                for key, value in categories.items():
                    number = _number(value)
                    if not number:  # missing, or a category the library has none of
                        continue
                    rows.append(
                        {
                            "sample": str(sample),
                            "rank": rank,
                            "taxon": _label(key, labels),
                            "abundance": number,
                        }
                    )
    if not rows:
        raise ValueError("mirtrace_composition: the MultiQC report carries no miRTrace plot data")
    frame = pl.DataFrame(
        rows, schema={k: EXPECTED_SCHEMA[k] for k in ("sample", "rank", "taxon", "abundance")}
    )
    frame = frame.with_columns(
        (pl.col("abundance") * 100.0 / pl.col("abundance").sum().over(["sample", "rank"]))
        .fill_nan(None)
        .alias("percent")
    )
    return frame.select(list(EXPECTED_SCHEMA)).sort(
        ["sample", "rank", "abundance"], descending=[False, False, True]
    )
