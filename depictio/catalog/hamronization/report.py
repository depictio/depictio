"""Tidy the hAMRonization ``summarize`` combined report into one row per ARG hit.

hAMRonization normalises the output of every ARG screening tool (ABRicate,
AMRFinderPlus, DeepARG, fARGene, RGI, ...) into one shared vocabulary and
``hamronization summarize`` concatenates them into a single TSV. The report
keeps the tool-specific input file name as its only sample handle, so the
recipe derives ``sample`` by stripping the per-tool prefixes the nf-core
``hamronization/*`` modules append (``<sample>.tsv.amrfinderplus``,
``<sample>.mapping.ARG.deeparg``, ``<sample>_retrieved-genes-<model>-hmmsearched.out.fargene``,
``<sample>.txt.rgi`` and the bare ``<sample>`` ABRicate writes).

Output columns:
    sample, gene_symbol, gene_name, drug_class, antimicrobial_agent,
    resistance_mechanism, tool, database, reference_accession, coverage_pct,
    coverage_frac, identity_pct, contig, sequence_id, start, stop, strand, hits
"""

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="report",
        path="reports/hamronization_summarize/hamronization_combined_report.tsv",
        format="TSV",
        read_kwargs={"infer_schema_length": 10000, "null_values": ["NA", ""]},
    ),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "gene_symbol": pl.Utf8,
    "gene_name": pl.Utf8,
    "drug_class": pl.Utf8,
    "antimicrobial_agent": pl.Utf8,
    "resistance_mechanism": pl.Utf8,
    "tool": pl.Utf8,
    "database": pl.Utf8,
    "reference_accession": pl.Utf8,
    "coverage_pct": pl.Float64,
    "coverage_frac": pl.Float64,
    "identity_pct": pl.Float64,
    "contig": pl.Utf8,
    "sequence_id": pl.Utf8,
    "start": pl.Int64,
    "stop": pl.Int64,
    "strand": pl.Utf8,
    "hits": pl.Int64,
}

# Known ARG tools hAMRonization has a parser for; the lower-cased
# ``analysis_software_name`` is matched against these when stripping the
# per-tool suffix from the input file name.
_TOOL_SUFFIX = r"(abricate|amrfinderplus|deeparg|fargene|rgi|resfinder|srax|staramr|kmerresistance|groot|ariba|csstar|tbprofiler|mykrobe|pointfinder|amrplusplus)"

# Order matters: the most specific patterns first, then the generic
# ``.<ext>.<tool>`` / ``.<tool>`` tails, then a leftover bare extension.
_SAMPLE_STRIP_PATTERNS = [
    r"_retrieved-genes-.+-hmmsearched\.out(\.fargene)?$",  # fARGene per-model files
    r"\.mapping(\.potential)?\.ARG(\.deeparg)?$",  # DeepARG ARG / potential-ARG tables
    r"\.(tsv|txt|csv|out|json|tab)\." + _TOOL_SUFFIX + r"$",
    r"\." + _TOOL_SUFFIX + r"$",
    r"\.(tsv|txt|csv|out|json|tab)$",
]


def sample_from_input_file_name(col: pl.Expr) -> pl.Expr:
    """Strip the nf-core hamronization per-tool prefixes back to the sample id."""
    expr = col
    for pattern in _SAMPLE_STRIP_PATTERNS:
        expr = expr.str.replace(pattern, "")
    return expr


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per ARG hit with a derived sample id and numeric coverage/identity."""
    df = sources["report"]

    def _col(name: str, dtype: type[pl.DataType]) -> pl.Expr:
        # A column every hAMRonization version writes may still be all-null in
        # one run (polars then infers Utf8): cast leniently instead of failing.
        if name in df.columns:
            return pl.col(name).cast(dtype, strict=False)
        return pl.lit(None).cast(dtype)

    tool = pl.col("analysis_software_name").cast(pl.Utf8).str.to_lowercase().str.strip_chars()
    out = df.select(
        sample_from_input_file_name(pl.col("input_file_name").cast(pl.Utf8)).alias("sample"),
        _col("gene_symbol", pl.Utf8).alias("gene_symbol"),
        _col("gene_name", pl.Utf8).alias("gene_name"),
        _col("drug_class", pl.Utf8).fill_null("unclassified").alias("drug_class"),
        _col("antimicrobial_agent", pl.Utf8).alias("antimicrobial_agent"),
        _col("resistance_mechanism", pl.Utf8).alias("resistance_mechanism"),
        tool.alias("tool"),
        _col("reference_database_name", pl.Utf8).alias("database"),
        _col("reference_accession", pl.Utf8).alias("reference_accession"),
        _col("coverage_percentage", pl.Float64).alias("coverage_pct"),
        _col("sequence_identity", pl.Float64).alias("identity_pct"),
        _col("input_sequence_id", pl.Utf8).alias("sequence_id"),
        _col("input_gene_start", pl.Int64).alias("start"),
        _col("input_gene_stop", pl.Int64).alias("stop"),
        _col("strand_orientation", pl.Utf8).alias("strand"),
    )
    return out.with_columns(
        # Some tools report >100 % coverage on split hits; clip so the fraction
        # stays a size-friendly 0..1.
        (pl.col("coverage_pct").clip(0.0, 100.0) / 100.0).alias("coverage_frac"),
        # Prodigal / Pyrodigal name ORFs ``<contig>_<n>``: drop the ORF index so
        # hits reported per ORF and per contig land on the same contig id.
        pl.col("sequence_id").str.replace(r"_\d+$", "").alias("contig"),
        pl.lit(1, dtype=pl.Int64).alias("hits"),
    ).select(list(EXPECTED_SCHEMA))
