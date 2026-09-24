"""One row per assembly: Merqury's QV joined to its k-mer completeness.

Merqury writes the assembly QV to `<prefix>.qv` (assembly name, k-mers found
only in the assembly, all assembly k-mers, QV, error rate) and the completeness
to `<prefix>.completeness.stats` (assembly name, k-mer set, solid k-mers in the
assembly, solid k-mers in the reads, percent). Neither file has a header, and
the assembly is keyed here on the file prefix, the name the pipeline gave the
run, because the name inside the file is the FASTA stem and can differ from it.

A haplotype-resolved run lists each haplotype and a `Both` row; the `Both` row
is kept, since it is the figure for the assembly as a whole. The completeness
file of a trio run carries hap-mer rows as well; only the `all` row is kept.

Inputs, both recursive Table scans with the same reader settings::

    merqury_qv_raw:            regex '^[^.]+\\.qv$'   (the per-sequence `<prefix>.<asm>.qv` files are excluded)
    merqury_completeness_raw:  regex '^.+\\.completeness\\.stats$'   (optional)
    dc_specific_properties:
      format: TSV
      polars_kwargs: {separator: "\\t", has_header: false, include_file_paths: source_path,
                      infer_schema_length: 0, new_columns: [c1, c2, c3, c4, c5]}

Output schema:
    assembly_id : Utf8              the file prefix
    merqury_name : Utf8             the assembly name Merqury printed
    asm_only_kmers : Int64          k-mers in the assembly never seen in the reads
    total_kmers : Int64             all k-mers of the assembly
    qv : Float64                    consensus quality value (null for an error-free assembly)
    error_rate : Float64            per-base error rate the QV stands for
    solid_kmers_assembly : Int64    solid read k-mers found in the assembly (null without completeness)
    solid_kmers_reads : Int64       solid read k-mers (null without completeness)
    kmer_completeness : Float64     percent of solid read k-mers recovered (null without completeness)
"""

from __future__ import annotations

from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource

QV_DC_TAG = "merqury_qv_raw"
COMPLETENESS_DC_TAG = "merqury_completeness_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="qv", dc_ref=QV_DC_TAG),
    RecipeSource(ref="completeness", dc_ref=COMPLETENESS_DC_TAG, optional=True),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "merqury_name": pl.Utf8,
    "asm_only_kmers": pl.Int64,
    "total_kmers": pl.Int64,
    "qv": pl.Float64,
    "error_rate": pl.Float64,
    "solid_kmers_assembly": pl.Int64,
    "solid_kmers_reads": pl.Int64,
    "kmer_completeness": pl.Float64,
}

SOURCE_PATH_COL = "source_path"


def file_prefix(source_path: str, suffix: str) -> str:
    """`<dir>/<prefix><suffix>` -> `<prefix>`."""
    name = PurePosixPath(source_path.replace("\\", "/")).name
    return name.removesuffix(suffix)


def _columns(frame: pl.DataFrame) -> list[str]:
    return [c for c in frame.columns if c != SOURCE_PATH_COL]


def _number(column: str, dtype: type[pl.DataType]) -> pl.Expr:
    value = pl.col(column).cast(pl.Utf8).str.strip_chars().cast(pl.Float64, strict=False)
    # "+inf" / "inf" parse to infinity: an assembly with no error k-mer has no finite QV.
    value = pl.when(value.is_infinite()).then(None).otherwise(value)
    return value.cast(pl.Int64, strict=False) if dtype == pl.Int64 else value


def _tidy_qv(raw: pl.DataFrame) -> pl.DataFrame:
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError("merqury_assembly_qv: the QV scan must include_file_paths: source_path")
    cols = _columns(raw)
    if len(cols) < 5:
        raise ValueError(f"merqury_assembly_qv: expected 5 QV columns, got {cols}")
    name, asm_only, total, qv, error = cols[:5]
    frame = raw.select(
        pl.col(SOURCE_PATH_COL)
        .map_elements(lambda p: file_prefix(p, ".qv"), return_dtype=pl.Utf8)
        .alias("assembly_id"),
        pl.col(name).cast(pl.Utf8).alias("merqury_name"),
        _number(asm_only, pl.Int64).alias("asm_only_kmers"),
        _number(total, pl.Int64).alias("total_kmers"),
        _number(qv, pl.Float64).alias("qv"),
        _number(error, pl.Float64).alias("error_rate"),
    ).drop_nulls(["merqury_name"])
    # Haplotype-resolved runs: keep the `Both` row; otherwise the single row.
    return (
        frame.with_columns((pl.col("merqury_name") == "Both").alias("_both"))
        .sort(["assembly_id", "_both"], descending=[False, True])
        .unique(subset=["assembly_id"], keep="first", maintain_order=True)
        .drop("_both")
    )


def _tidy_completeness(raw: pl.DataFrame | None) -> pl.DataFrame:
    schema = {
        "assembly_id": pl.Utf8,
        "solid_kmers_assembly": pl.Int64,
        "solid_kmers_reads": pl.Int64,
        "kmer_completeness": pl.Float64,
    }
    if raw is None or raw.is_empty() or SOURCE_PATH_COL not in raw.columns:
        return pl.DataFrame(schema=schema)
    cols = _columns(raw)
    if len(cols) < 5:
        return pl.DataFrame(schema=schema)
    _, kmer_set, solid_asm, solid_reads, percent = cols[:5]
    return (
        raw.filter(pl.col(kmer_set).cast(pl.Utf8).str.strip_chars() == "all")
        .select(
            pl.col(SOURCE_PATH_COL)
            .map_elements(lambda p: file_prefix(p, ".completeness.stats"), return_dtype=pl.Utf8)
            .alias("assembly_id"),
            _number(solid_asm, pl.Int64).alias("solid_kmers_assembly"),
            _number(solid_reads, pl.Int64).alias("solid_kmers_reads"),
            _number(percent, pl.Float64).alias("kmer_completeness"),
        )
        .unique(subset=["assembly_id"], keep="first")
    )


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """Key the QV rows on their file prefix and attach the completeness row."""
    raw_qv = sources["qv"]
    if raw_qv is None or raw_qv.is_empty():
        raise ValueError("merqury_assembly_qv: the scanned QV files are empty")
    qv = _tidy_qv(raw_qv)
    if qv.is_empty():
        raise ValueError("merqury_assembly_qv: no QV file carried a data row")
    completeness = _tidy_completeness(sources.get("completeness"))
    return (
        qv.join(completeness, on="assembly_id", how="left")
        .select(list(EXPECTED_SCHEMA))
        .sort("assembly_id")
    )
