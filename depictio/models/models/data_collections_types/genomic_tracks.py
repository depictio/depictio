"""
Genomic Tracks Data Collection Type.

A ``genomic_tracks`` DC is a *manifest table* of genome-browser tracks: one row
per track, with the file location in ``uri_column``. It is ingested like a Table
DC (the manifest becomes a Delta table, so it can be filtered, linked and
joined like any other table) and rendered by the ``jbrowse`` component.

A track ``uri`` can be:

- a relative path: resolved against ``tracks_base_path`` at ingestion, uploaded
  to Depictio's S3 under ``s3_base_folder`` and served by the API;
- ``s3://bucket/key``: read in place by the API (bucket must be allow-listed);
- ``https://host/path``: read in place by the API (host must be allow-listed),
  or fetched directly by the browser when ``direct_access`` is set.

The browser never talks to S3 itself: every byte goes through the API's
Range-capable track proxy, which re-checks access to the data collection.
"""

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Manifest file formats (same set as Table / Image DCs).
VALID_MANIFEST_FORMATS = ["csv", "tsv", "parquet", "feather", "xls", "xlsx", "mixed"]

TrackFormat = Literal[
    "bigwig",
    "bedgraph",
    "bed",
    "bigbed",
    "narrowpeak",
    "broadpeak",
    "vcf",
    "bam",
    "cram",
    "gff3",
    "gtf",
    "fasta",
]

TRACK_FORMATS: tuple[str, ...] = get_args(TrackFormat)

# Extension → format, longest suffix first so ``.vcf.gz`` wins over ``.gz``.
_EXTENSION_FORMATS: tuple[tuple[str, str], ...] = (
    (".narrowpeak.gz", "narrowpeak"),
    (".broadpeak.gz", "broadpeak"),
    (".bedgraph.gz", "bedgraph"),
    (".gff3.gz", "gff3"),
    (".gff.gz", "gff3"),
    (".gtf.gz", "gtf"),
    (".vcf.gz", "vcf"),
    (".bed.gz", "bed"),
    (".fasta.gz", "fasta"),
    (".fa.gz", "fasta"),
    (".fna.gz", "fasta"),
    (".narrowpeak", "narrowpeak"),
    (".broadpeak", "broadpeak"),
    (".bedgraph", "bedgraph"),
    (".bigwig", "bigwig"),
    (".bigbed", "bigbed"),
    (".fasta", "fasta"),
    (".gff3", "gff3"),
    (".cram", "cram"),
    (".gff", "gff3"),
    (".gtf", "gtf"),
    (".vcf", "vcf"),
    (".bam", "bam"),
    (".bed", "bed"),
    (".bw", "bigwig"),
    (".bb", "bigbed"),
    (".fna", "fasta"),
    (".fa", "fasta"),
)

# Formats whose data file needs a sibling index to be range-read.
_INDEX_SUFFIX: dict[str, str] = {"bam": ".bai", "cram": ".crai"}
# Formats read through a tabix index when the file is bgzipped.
TABIX_FORMATS = frozenset({"bed", "bedgraph", "narrowpeak", "broadpeak", "vcf", "gff3", "gtf"})


def _strip_query(uri: str) -> str:
    return uri.split("?", 1)[0].split("#", 1)[0]


def infer_track_format(uri: str) -> str | None:
    """Guess a track format from a file name or URI; None when unknown."""
    path = _strip_query(uri).lower()
    for suffix, fmt in _EXTENSION_FORMATS:
        if path.endswith(suffix):
            return fmt
    return None


def is_bgzipped(uri: str) -> bool:
    return _strip_query(uri).lower().endswith(".gz")


def infer_index_uri(uri: str, fmt: str) -> str | None:
    """Conventional index location for a track, or None when none is needed.

    BAM → ``.bai``, CRAM → ``.crai``, bgzipped tabix formats → ``.tbi`` and
    bgzipped FASTA → ``.fai`` (the ``.gzi`` is derived separately by the
    config builder). Plain-text BED/GFF/VCF are small-file formats read whole
    and need no index.
    """
    base, sep, query = uri.partition("?")
    if fmt in _INDEX_SUFFIX:
        return f"{base}{_INDEX_SUFFIX[fmt]}{sep}{query}"
    if fmt in TABIX_FORMATS and is_bgzipped(base):
        return f"{base}.tbi{sep}{query}"
    if fmt == "fasta":
        return f"{base}.fai{sep}{query}"
    return None


def genomic_tracks_s3_prefix(dc_id: str) -> str:
    """Bucket-relative folder a DC's local track files are uploaded to by default.

    Kept out of the ``<dc_id>/`` prefix delta tables use (orphan cleanup deletes
    ObjectId-shaped top-level prefixes). Shared by the CLI upload, the API
    track proxy and the project cascade delete / migration.
    """
    return f"genomic_tracks/{dc_id}/"


class CustomAssembly(BaseModel):
    """A reference assembly that is not one of the built-in presets.

    Give either an indexed FASTA (``fasta_uri`` + ``fai_uri``, plus ``gzi_uri``
    when bgzipped) or a UCSC ``twobit_uri``. URIs follow the same rules as
    track URIs (relative, ``s3://`` or ``https://``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Assembly name used by JBrowse (e.g. 'MN908947.3')")
    display_name: str | None = Field(default=None, description="Human-readable name")
    aliases: list[str] = Field(
        default_factory=list, description="Other names of the assembly (e.g. ['hg38'])"
    )
    fasta_uri: str | None = Field(default=None, description="FASTA (plain or bgzipped)")
    fai_uri: str | None = Field(default=None, description="FASTA .fai index")
    gzi_uri: str | None = Field(default=None, description="bgzip .gzi index")
    twobit_uri: str | None = Field(default=None, description="UCSC .2bit sequence")
    chrom_sizes_uri: str | None = Field(default=None, description="chrom.sizes (2bit only)")
    refname_aliases_uri: str | None = Field(
        default=None, description="Tab-separated refName alias file (e.g. chr1 ↔ 1)"
    )

    @model_validator(mode="after")
    def validate_sequence(self) -> "CustomAssembly":
        if not self.fasta_uri and not self.twobit_uri:
            raise ValueError("custom assembly needs fasta_uri or twobit_uri")
        return self


class DCGenomicTracksConfig(BaseModel):
    """Configuration of a ``genomic_tracks`` data collection.

    Example (project.yaml)::

        - data_collection_tag: sv_tracks
          config:
            type: genomic_tracks
            scan:
              mode: single
              scan_parameters:
                filename: tracks.tsv
            dc_specific_properties:
              format: tsv
              uri_column: uri
              sample_column: cell
              assembly: hg38
    """

    model_config = ConfigDict(extra="forbid")

    # Manifest table (Table DC fields, needed for delta table creation)
    format: str = Field(description="Manifest format: csv, tsv, parquet, feather, xls, xlsx")
    polars_kwargs: dict[str, Any] = Field(default_factory=dict)
    keep_columns: list[str] | None = Field(default=None)
    columns_description: dict[str, str] | None = Field(default=None)

    # Manifest columns
    uri_column: str = Field(default="uri", description="Column holding the track location")
    track_id_column: str | None = Field(
        default=None,
        description="Column with a unique track id (defaults to the row's uri)",
    )
    sample_column: str | None = Field(
        default=None,
        description="Entity column the tracks belong to (sample, cell…); used for "
        "cross-filtering and as the default selection column",
    )
    format_column: str | None = Field(
        default="format", description="Column holding the track format (optional)"
    )
    default_format: TrackFormat | None = Field(
        default=None,
        description="Format used when the manifest has no format column and the "
        "extension does not tell",
    )
    index_column: str | None = Field(
        default="index_uri",
        description="Column holding the index location (optional; inferred otherwise)",
    )
    order_column: str | None = Field(
        default=None,
        description="Column the tracks are ordered by (ascending) when the view opens "
        "and fills its first `initial_tracks`; ingestion may reorder the rows otherwise",
    )
    name_column: str | None = Field(default=None, description="Track label column")
    color_column: str | None = Field(default=None, description="Track colour column")
    category_column: str | None = Field(
        default=None, description="Track category column (track selector folders)"
    )

    # Reference
    assembly: str | CustomAssembly = Field(
        default="hg38",
        description="Assembly preset name (hg38, hg19, hs1, mm10, mm39, sacCer3, dm6, "
        "ce11, danRer11, TAIR10, wuhCor1) or a custom assembly",
    )

    # Storage
    tracks_base_path: str | None = Field(
        default=None,
        description="Local directory relative track URIs resolve against at ingestion "
        "(defaults to the manifest's directory)",
    )
    s3_base_folder: str | None = Field(
        default=None,
        description="S3 folder relative track URIs live under (set at ingestion)",
    )
    remote_base_uri: str | None = Field(
        default=None,
        description="s3:// or https:// prefix relative track URIs are read in place under "
        "(e.g. a pipeline's results folder), instead of being uploaded at ingestion",
    )
    direct_access: bool = Field(
        default=False,
        description="Let the browser fetch https:// tracks directly instead of through "
        "the API proxy (the host must send CORS + Range headers)",
    )

    # Display
    display_defaults: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-format JBrowse track config merged into every track of that "
        "format (e.g. {'bigwig': {'displays': [...]}})",
    )
    presets: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Named JBrowse config fragments components can pick with `preset:`",
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        normalized = v.lower()
        if normalized not in VALID_MANIFEST_FORMATS:
            raise ValueError(f"format must be one of {VALID_MANIFEST_FORMATS}")
        return normalized

    @field_validator("default_format", mode="before")
    @classmethod
    def normalize_default_format(cls, v: Any) -> Any:
        return v.lower() if isinstance(v, str) else v

    @field_validator("uri_column")
    @classmethod
    def validate_uri_column(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("uri_column must not be empty")
        return stripped

    @field_validator("display_defaults")
    @classmethod
    def validate_display_defaults(cls, v: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        unknown = sorted(k for k in v if k.lower() not in TRACK_FORMATS)
        if unknown:
            raise ValueError(f"display_defaults keys must be track formats, got {unknown}")
        return {k.lower(): val for k, val in v.items()}

    @field_validator("remote_base_uri")
    @classmethod
    def validate_remote_base_uri(cls, v: str | None) -> str | None:
        if not v or not v.strip():
            return None
        v = v.strip()
        if not v.lower().startswith(("s3://", "https://")):
            raise ValueError("remote_base_uri must start with 's3://' or 'https://'")
        return v if v.endswith("/") else f"{v}/"

    @field_validator("s3_base_folder")
    @classmethod
    def validate_s3_path(cls, v: str | None) -> str | None:
        if not v or not v.strip():
            return v
        if not v.startswith("s3://"):
            raise ValueError("s3_base_folder must start with 's3://'")
        return v if v.endswith("/") else f"{v}/"
