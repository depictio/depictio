"""Contig count per recovered bin, from mag's cross-binner contig-to-bin map.

nf-core/mag runs up to five binners (MetaBAT2, MaxBin2, CONCOCT/MetaBinner,
SemiBin2, COMEBin) over each assembly and writes one flat table,
`GenomeBinning/contig_to_bin/contig_to_bin_map.tsv`, with a row per
(assembly, contig, binner, bin) membership call, no per-bin quality metrics
(no CheckM2/BUSCO/GUNC table ships beside it in this megatest run; those
numbers only reach Depictio through the MultiQC general-stats panel). This
recipe is the closest thing to a "bin summary" table the local data supports:
one row per bin, counting the contigs each binner placed in it.

`assembly_id` is `<ASSEMBLER>-<SAMPLE>` (e.g. `FLYE-CAPES_S11`); the sample
names in this megatest never contain a hyphen, so splitting on the first `-`
recovers both fields cleanly.

Output schema:
    sample : Utf8      sample the assembly was built from
    assembler : Utf8   FLYE, MEGAHIT, METAMDBG or SPAdes
    binner : Utf8      COMEBin, MaxBin2, MetaBAT2, MetaBinner or SemiBin2
    bin_id : Utf8      bin identifier as the binner wrote it
    n_contigs : Int64  contigs this binner placed in this bin
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="bins", dc_ref="mag_contig_to_bin_raw"),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "assembler": pl.Utf8,
    "binner": pl.Utf8,
    "bin_id": pl.Utf8,
    "n_contigs": pl.Int64,
}

_REQUIRED = ["assembly_id", "contig_id", "binner", "bin_id"]


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Count contigs per (sample, assembler, binner, bin)."""
    df = sources["bins"]
    missing = [c for c in _REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"mag bin_summary: contig_to_bin_map lacks columns {missing}")

    split = pl.col("assembly_id").cast(pl.Utf8).str.split_exact("-", 1)
    df = df.with_columns(
        split.struct.field("field_0").alias("assembler"),
        split.struct.field("field_1").alias("sample"),
        pl.col("binner").cast(pl.Utf8),
        pl.col("bin_id").cast(pl.Utf8),
    )

    out = (
        df.group_by(["sample", "assembler", "binner", "bin_id"])
        .agg(pl.len().alias("n_contigs"))
        .with_columns(pl.col("n_contigs").cast(pl.Int64))
        .sort(["sample", "assembler", "binner", "bin_id"])
    )
    return out
