"""Per-contig coverage, one row per contig and per sample mapped onto it.

`jgi_summarize_bam_contig_depths` writes the table every differential-coverage
binner is fed: one row per contig, its length, its mean depth over all samples,
then a depth and a variance column per BAM. nf-core/mag publishes one such file
per assembly at `GenomeBinning/depths/contigs/<assembler>-<sample>-depth.txt.gz`,
and in a multi-sample run every sample's reads are mapped back onto every
assembly, so the per-BAM columns are the differential coverage signal itself:
a contig deep in one sample and absent in another belongs to an organism that
is not in both.

The per-BAM columns are named after the BAM, so every assembly's file has
different column names and the files cannot be concatenated on their headers.
The scan therefore reads them WITHOUT a header, which leaves each file's header
line as its first data row, and this recipe reads the sample names back out of
it per file. That is why the raw scan must be declared with
``has_header: false`` and fixed placeholder column names.

Contigs shorter than ``MIN_CONTIG_LENGTH`` are dropped. Every binner applies a
floor of that order before it starts (MetaBAT2 defaults to 1500 bp, nf-core/mag
to 1500 as well), so the short tail is coverage nothing was ever binned on, and
in this shape it is three quarters of the rows.

Input: the ``mag_contig_depths_raw`` data collection::

    config:
      type: Table
      scan: {mode: recursive, scan_parameters: {regex_config: {pattern: '.*-depth\\.txt(\\.gz)?$'}}}
      dc_specific_properties:
        format: TSV
        polars_kwargs:
          separator: "\\t"
          has_header: false
          truncate_ragged_lines: true
          new_columns: [f0, f1, f2, f3, f4, f5, f6, f7, f8]
          include_file_paths: source_path
          infer_schema_length: 0

Output schema:
    assembly_id : Utf8      <assembler>-<sample>, the assembly the contig is in
    assembler : Utf8        assembler that built it
    sample : Utf8           sample the assembly was built from
    contig_id : Utf8        contig name inside that assembly
    contig_length : Int64   contig length in bases
    mean_depth : Float64    mean depth over every sample mapped back
    read_sample : Utf8      sample whose reads produced this row's depth
    depth : Float64         mean depth of this contig in that sample
    depth_variance : Float64  variance of that depth
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.mag_bins import file_stem

RAW_DC_TAG = "mag_contig_depths_raw"

SOURCES: list[RecipeSource] = [
    RecipeSource(ref="depths", dc_ref=RAW_DC_TAG),
]

EXPECTED_SCHEMA: dict[str, type[pl.DataType]] = {
    "assembly_id": pl.Utf8,
    "assembler": pl.Utf8,
    "sample": pl.Utf8,
    "contig_id": pl.Utf8,
    "contig_length": pl.Int64,
    "mean_depth": pl.Float64,
    "read_sample": pl.Utf8,
    "depth": pl.Float64,
    "depth_variance": pl.Float64,
}

SOURCE_PATH_COL = "source_path"

#: Shortest contig kept. Below it nothing was binned, and the rows are noise.
MIN_CONTIG_LENGTH = 1000

#: Header of the first three columns, whatever case the tool wrote them in.
_CONTIG_NAME_HEADER = "contigname"
_CONTIG_LEN_HEADER = "contiglen"
_MEAN_DEPTH_HEADER = "totalavgdepth"

#: Suffixes on the published file name, peeled to reach `<assembler>-<sample>`.
_FILE_SUFFIXES = ("-depth.txt.gz", "-depth.txt", ".txt.gz", ".txt")


def _read_sample(bam_column: str) -> str:
    """`METAMDBG-CAPES_S7-CAPES_S11.bam` -> `CAPES_S11`."""
    name = str(bam_column)
    for suffix in (".bam-var", ".bam"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.rsplit("-", 1)[-1]


def _assembly_parts(path: str) -> tuple[str, str | None, str | None]:
    """`.../METAMDBG-CAPES_S7-depth.txt.gz` -> (assembly_id, assembler, sample)."""
    assembly_id = file_stem(path, *_FILE_SUFFIXES)
    assembler, _, sample = assembly_id.partition("-")
    return (assembly_id, assembler or None, sample or None)


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Read each file's own header back out of its first row, then unpivot the BAM columns."""
    raw = sources["depths"]
    if raw.is_empty():
        raise ValueError("mag_contig_depths: the scanned depth tables are empty")
    if SOURCE_PATH_COL not in raw.columns:
        raise ValueError(
            "mag_contig_depths: the scan must set "
            f"`include_file_paths: {SOURCE_PATH_COL}`; each file carries its own column names"
        )

    field_columns = [column for column in raw.columns if column != SOURCE_PATH_COL]
    if len(field_columns) < 4:
        raise ValueError(
            f"mag_contig_depths: expected at least four data columns, got {field_columns}"
        )

    blocks: list[pl.DataFrame] = []
    for (path,), part in raw.group_by([SOURCE_PATH_COL], maintain_order=True):
        header_row = part.head(1)
        headers = {column: str(header_row[column][0] or "") for column in field_columns}
        folded = {column: value.strip().lower() for column, value in headers.items()}

        # First column wins, so a placeholder column repeating a header name
        # cannot displace the real one.
        by_header: dict[str, str] = {}
        for column, value in folded.items():
            by_header.setdefault(value, column)

        name_column = by_header.get(_CONTIG_NAME_HEADER)
        length_column = by_header.get(_CONTIG_LEN_HEADER)
        mean_column = by_header.get(_MEAN_DEPTH_HEADER)
        if name_column is None or length_column is None:
            raise ValueError(
                f"mag_contig_depths: {path} does not start with a "
                f"`{_CONTIG_NAME_HEADER}` / `{_CONTIG_LEN_HEADER}` header row; "
                "the scan must be declared with has_header false"
            )

        depth_columns = {
            _read_sample(headers[column]): column
            for column, value in folded.items()
            if value.endswith(".bam")
        }
        variance_columns = {
            _read_sample(headers[column]): column
            for column, value in folded.items()
            if value.endswith(".bam-var")
        }
        if not depth_columns:
            continue

        assembly_id, assembler, sample = _assembly_parts(str(path))
        body = (
            part.slice(1)
            .with_columns(
                pl.col(length_column)
                .cast(pl.Float64, strict=False)
                .cast(pl.Int64, strict=False)
                .alias("_length")
            )
            .filter(pl.col("_length") >= MIN_CONTIG_LENGTH)
        )
        if body.is_empty():
            continue

        for read_sample, depth_column in depth_columns.items():
            variance_column = variance_columns.get(read_sample)
            blocks.append(
                body.select(
                    pl.lit(assembly_id, dtype=pl.Utf8).alias("assembly_id"),
                    pl.lit(assembler, dtype=pl.Utf8).alias("assembler"),
                    pl.lit(sample, dtype=pl.Utf8).alias("sample"),
                    pl.col(name_column).cast(pl.Utf8).alias("contig_id"),
                    pl.col("_length").alias("contig_length"),
                    (
                        pl.col(mean_column).cast(pl.Float64, strict=False)
                        if mean_column
                        else pl.lit(None, dtype=pl.Float64)
                    ).alias("mean_depth"),
                    pl.lit(read_sample, dtype=pl.Utf8).alias("read_sample"),
                    pl.col(depth_column).cast(pl.Float64, strict=False).alias("depth"),
                    (
                        pl.col(variance_column).cast(pl.Float64, strict=False)
                        if variance_column
                        else pl.lit(None, dtype=pl.Float64)
                    ).alias("depth_variance"),
                )
            )

    if not blocks:
        raise ValueError(
            f"mag_contig_depths: no contig reached {MIN_CONTIG_LENGTH} bp in any depth table"
        )

    return (
        pl.concat(blocks, how="vertical")
        .select(list(EXPECTED_SCHEMA))
        .sort(["assembly_id", "contig_id", "read_sample"])
    )
