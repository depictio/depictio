"""The nf-core/genomeqc genome hub: one row per assembly, every per-genome number.

Every tab filters through this table, so it has to exist on every route. It is
keyed on the assembly name the pipeline uses for its output directories
(``quast/<assembly>/``, ``busco/genome/<assembly>/``...), read from the QUAST
reports, which every route writes; every other tool only adds columns, and a
tool the run skipped leaves its columns null:

* QUAST: length, sequences, N50 / N90, L50 / L90, GC, Ns; QUAST labels a row
  after the FASTA, so the hub also keeps that label (``assembly_label``) for
  the collections keyed on it (the QUAST tables, the MultiQC report);
* BUSCO on the assembly (``genome`` mode) and on its proteins (``proteins``
  mode, only with an annotation);
* the karyotype: sequences holding a complete BUSCO;
* tidk: the repeat unit searched;
* AGAT (protein-coding genes), gene overlaps, OrthoFinder and the
  ortho seq count, only with an annotation;
* FCS-GX (genomeqc's contamination table and the flagged ranges),
  FCS-adaptor and Tiara, only with decontamination;
* RepeatMasker, only with ``--te repeatmasker``.

Design columns come from the optional design table (``METADATA_FILE``): the
assembly name is its ``sample`` column, or its first column, and every other
column is joined under its own name. Without one the hub carries a constant
``__no_group__`` column, the value ``GROUP_COL`` falls back to.

Output schema: ``genome``, the design columns (or ``__no_group__``), then the
columns of ``OUTPUT_SCHEMA`` after ``genome``, in order.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.quast_report import column_map

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="quast_raw",
        dc_ref="quast_assembly_raw",
        input_schema={"Assembly": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="quast",
        dc_ref="quast_assembly_report",
        input_schema={
            "assembly_id": pl.Utf8,
            "n_contigs": pl.Int64,
            "total_length": pl.Int64,
            "n50": pl.Int64,
        },
    ),
    RecipeSource(ref="busco", dc_ref="busco_batch_summary", optional=True),
    RecipeSource(ref="karyotype", dc_ref="busco_karyotype", optional=True),
    RecipeSource(ref="tidk", dc_ref="tidk_search_windows", optional=True),
    RecipeSource(ref="genes", dc_ref="agat_gene_models", optional=True),
    RecipeSource(ref="overlaps", dc_ref="gene_overlaps", optional=True),
    RecipeSource(ref="orthology", dc_ref="orthofinder_species_stats", optional=True),
    RecipeSource(ref="synteny", dc_ref="ortho_seq_count", optional=True),
    RecipeSource(ref="contamination", dc_ref="fcsgx_contamination", optional=True),
    RecipeSource(ref="gx", dc_ref="fcsgx_actions", optional=True),
    RecipeSource(ref="adaptor", dc_ref="fcsadaptor_actions", optional=True),
    RecipeSource(ref="tiara", dc_ref="tiara_classifications", optional=True),
    RecipeSource(ref="repeats", dc_ref="repeatmasker_masking_summary", optional=True),
    # No input_schema: the design table's id is its `sample` column or its first
    # one, and every other column is a data-named factor.
    RecipeSource(ref="metadata", dc_ref="metadata", optional=True),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it (the design
# columns, run-dependent, sit right after `genome`).
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "assembly_label": pl.Utf8,
    "total_length": pl.Int64,
    "n_contigs": pl.Int64,
    "largest_contig": pl.Int64,
    "n50": pl.Int64,
    "n90": pl.Int64,
    "l50": pl.Int64,
    "l90": pl.Int64,
    "gc_percent": pl.Float64,
    "ns_per_100_kbp": pl.Float64,
    "busco_lineage": pl.Utf8,
    "busco_complete_pct": pl.Float64,
    "busco_single_pct": pl.Float64,
    "busco_duplicated_pct": pl.Float64,
    "busco_fragmented_pct": pl.Float64,
    "busco_missing_pct": pl.Float64,
    "protein_complete_pct": pl.Float64,
    "protein_duplicated_pct": pl.Float64,
    "protein_missing_pct": pl.Float64,
    "sequences_with_busco": pl.Int64,
    "repeat_unit": pl.Utf8,
    "genes": pl.Int64,
    "transcripts": pl.Int64,
    "transcripts_per_gene": pl.Float64,
    "exons_per_transcript": pl.Float64,
    "single_exon_gene_pct": pl.Float64,
    "mean_gene_length": pl.Float64,
    "mean_cds_length": pl.Float64,
    "overlapping_pct": pl.Float64,
    "contained_same_strand": pl.Int64,
    "genes_in_orthogroups_pct": pl.Float64,
    "unassigned_genes": pl.Int64,
    "species_specific_orthogroups": pl.Int64,
    "syntenic_sequences": pl.Int64,
    "contaminant_pct": pl.Float64,
    "gx_flagged_ranges": pl.Int64,
    "gx_flagged_bp": pl.Int64,
    "adaptor_ranges": pl.Int64,
    "tiara_sequences": pl.Int64,
    "prokaryotic_sequences": pl.Int64,
    "unknown_sequences": pl.Int64,
    "masked_pct": pl.Float64,
    "interspersed_pct": pl.Float64,
}
# Design columns are run-dependent and pass through unvalidated.
OPTIONAL_OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {}

#: Column ``GROUP_COL`` resolves to when the run gives no design table.
NO_GROUP_COL = "__no_group__"
NO_GROUP_VALUE = "All genomes"

#: Directory names that say nothing about the assembly (a run-level QUAST dir).
_GENERIC_DIRS = {"quast", "qc", "report", "reports", "results"}


def _present(df: pl.DataFrame | None, *cols: str) -> bool:
    return df is not None and not df.is_empty() and all(c in df.columns for c in cols)


def genome_from_quast_path(source_path: str, label: str) -> str:
    """``quast/A/A.quast/transposed_report.tsv`` -> ``A``; the QUAST label otherwise."""
    parent = PurePosixPath(str(source_path).replace("\\", "/")).parent.name
    name = re.sub(r"\.quast$", "", parent)
    return label if not name or name.lower() in _GENERIC_DIRS else name


def _quast(raw: pl.DataFrame, report: pl.DataFrame) -> pl.DataFrame:
    mapping = column_map(raw.columns)

    def _int(folded: str) -> pl.Expr:
        original = mapping.get(folded)
        if original is None:
            return pl.lit(None, dtype=pl.Int64)
        return pl.col(original).cast(pl.Float64, strict=False).cast(pl.Int64, strict=False)

    keys = raw.select(
        pl.struct("source_path", "Assembly")
        .map_elements(
            lambda r: genome_from_quast_path(r["source_path"], r["Assembly"]),
            return_dtype=pl.Utf8,
        )
        .alias("genome"),
        pl.col("Assembly").cast(pl.Utf8).alias("assembly_label"),
        _int("n90").alias("n90"),
        _int("l90").alias("l90"),
    ).unique(subset="genome", keep="first", maintain_order=True)
    cols = ["n_contigs", "total_length", "largest_contig", "n50", "l50", "gc_percent"]
    cols += ["ns_per_100_kbp"]
    stats = report.select(
        pl.col("assembly_id").alias("assembly_label"), *[c for c in cols if c in report.columns]
    ).unique(subset="assembly_label", keep="first")
    return keys.join(stats, on="assembly_label", how="left")


def _busco(busco: pl.DataFrame) -> list[pl.DataFrame]:
    mode = pl.col("busco_mode") if "busco_mode" in busco.columns else pl.lit(None, pl.Utf8)
    genome_runs = busco.filter(mode.is_null() | (mode == "genome")).unique(
        subset="assembly_id", keep="first"
    )
    protein_runs = busco.filter(mode == "proteins").unique(subset="assembly_id", keep="first")
    parts = [
        genome_runs.select(
            pl.col("assembly_id").alias("genome"),
            pl.col("lineage").alias("busco_lineage"),
            pl.col("complete_pct").alias("busco_complete_pct"),
            pl.col("single_pct").alias("busco_single_pct"),
            pl.col("duplicated_pct").alias("busco_duplicated_pct"),
            pl.col("fragmented_pct").alias("busco_fragmented_pct"),
            pl.col("missing_pct").alias("busco_missing_pct"),
        )
    ]
    if not protein_runs.is_empty():
        parts.append(
            protein_runs.select(
                pl.col("assembly_id").alias("genome"),
                pl.col("complete_pct").alias("protein_complete_pct"),
                pl.col("duplicated_pct").alias("protein_duplicated_pct"),
                pl.col("missing_pct").alias("protein_missing_pct"),
            )
        )
    return parts


def _counts(frame: pl.DataFrame, flagged_col: str, bp_col: str | None) -> pl.DataFrame:
    flagged = pl.col("action") != "none"
    aggs = [flagged.sum().cast(pl.Int64).alias(flagged_col)]
    if bp_col is not None:
        aggs.append(pl.col("flagged_bp").filter(flagged).sum().cast(pl.Int64).alias(bp_col))
    return frame.group_by("genome").agg(aggs)


def design_columns(metadata: pl.DataFrame | None, reserved: set[str]) -> pl.DataFrame | None:
    """The design table keyed on ``genome``, every other column as Delta-safe text."""
    if metadata is None or metadata.is_empty() or metadata.width < 2:
        return None
    id_col = "sample" if "sample" in metadata.columns else metadata.columns[0]
    keep: dict[str, str] = {}
    for col in metadata.columns:
        if col == id_col:
            continue
        safe = re.sub(r"[^0-9A-Za-z]+", "_", col.strip()).strip("_") or "column"
        if safe in reserved or safe in keep.values():
            continue
        keep[col] = safe
    if not keep:
        return None
    return (
        metadata.select(
            pl.col(id_col).cast(pl.Utf8).str.strip_chars().alias("genome"),
            *[pl.col(c).cast(pl.Utf8).alias(s) for c, s in keep.items()],
        )
        .filter(pl.col("genome").is_not_null())
        .unique(subset="genome", keep="first", maintain_order=True)
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    hub = _quast(sources["quast_raw"], sources["quast"])
    parts: list[pl.DataFrame] = []

    busco = sources.get("busco")
    if _present(busco, "assembly_id", "complete_pct"):
        parts.extend(_busco(busco))

    karyotype = sources.get("karyotype")
    if _present(karyotype, "genome", "sequence"):
        parts.append(
            karyotype.group_by("genome").agg(
                pl.col("sequence").n_unique().cast(pl.Int64).alias("sequences_with_busco")
            )
        )

    tidk = sources.get("tidk")
    if _present(tidk, "genome", "repeat_unit"):
        parts.append(
            tidk.drop_nulls("repeat_unit").group_by("genome").agg(pl.col("repeat_unit").first())
        )

    genes = sources.get("genes")
    if _present(genes, "genome", "feature_type", "genes"):
        cols = ["genes", "transcripts", "transcripts_per_gene", "exons_per_transcript"]
        cols += ["single_exon_gene_pct", "mean_gene_length", "mean_cds_length"]
        parts.append(
            genes.filter(pl.col("feature_type") == "mrna")
            .unique(subset="genome", keep="first")
            .select("genome", *[c for c in cols if c in genes.columns])
        )

    overlaps = sources.get("overlaps")
    if _present(overlaps, "genome", "overlapping_pct"):
        parts.append(overlaps.select("genome", "overlapping_pct", "contained_same_strand"))

    orthology = sources.get("orthology")
    if _present(orthology, "genome", "genes_in_orthogroups_pct"):
        parts.append(
            orthology.select(
                "genome",
                "genes_in_orthogroups_pct",
                "unassigned_genes",
                "species_specific_orthogroups",
            )
        )

    synteny = sources.get("synteny")
    if _present(synteny, "Species"):
        value = next((c for c in synteny.columns if c != "Species"), None)
        if value is not None:
            parts.append(
                synteny.select(
                    pl.col("Species").cast(pl.Utf8).alias("genome"),
                    pl.col(value).cast(pl.Int64, strict=False).alias("syntenic_sequences"),
                )
            )

    contamination = sources.get("contamination")
    if _present(contamination, "species", "contaminant_pct"):
        parts.append(
            contamination.select(
                pl.col("species").cast(pl.Utf8).alias("genome"),
                pl.col("contaminant_pct").cast(pl.Float64, strict=False),
            )
        )

    gx = sources.get("gx")
    if _present(gx, "genome", "action"):
        parts.append(_counts(gx, "gx_flagged_ranges", "gx_flagged_bp"))

    adaptor = sources.get("adaptor")
    if _present(adaptor, "genome", "action"):
        parts.append(_counts(adaptor, "adaptor_ranges", None))

    tiara = sources.get("tiara")
    if _present(tiara, "genome", "tiara_class"):
        # The raw assembly's classes when the run classified it twice.
        stage = tiara.get_column("stage") if "stage" in tiara.columns else None
        if stage is not None and (stage == "raw").any():
            tiara = tiara.filter(pl.col("stage") == "raw")
        parts.append(
            tiara.group_by("genome").agg(
                pl.len().cast(pl.Int64).alias("tiara_sequences"),
                pl.col("tiara_class")
                .is_in(["bacteria", "archaea", "prokarya"])
                .sum()
                .cast(pl.Int64)
                .alias("prokaryotic_sequences"),
                (pl.col("tiara_class") == "unknown")
                .sum()
                .cast(pl.Int64)
                .alias("unknown_sequences"),
            )
        )

    repeats = sources.get("repeats")
    if _present(repeats, "genome", "masked_pct"):
        parts.append(repeats.select("genome", "masked_pct", "interspersed_pct"))

    for part in parts:
        hub = hub.join(part.unique(subset="genome", keep="first"), on="genome", how="left")
    for col, dtype in OUTPUT_SCHEMA.items():
        if col not in hub.columns:
            hub = hub.with_columns(pl.lit(None, dtype=dtype).alias(col))
    out = hub.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()])

    design = design_columns(sources.get("metadata"), set(OUTPUT_SCHEMA))
    if design is not None:
        out = out.join(design, on="genome", how="left").select(
            "genome", *design.columns[1:], *list(OUTPUT_SCHEMA)[1:]
        )
    else:
        out = out.with_columns(pl.lit(NO_GROUP_VALUE).alias(NO_GROUP_COL)).select(
            "genome", NO_GROUP_COL, *list(OUTPUT_SCHEMA)[1:]
        )
    return out.sort("genome")
