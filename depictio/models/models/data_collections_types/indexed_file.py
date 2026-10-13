"""Data-collection config for indexed genomic files (VCF, BAM, bigWig, GFF3, FASTA).

An ``indexed_file`` DC is file-backed and has no delta table: the pipeline's
output files (and their index sidecars) are copied to S3 at ingest, and the
browser reads them directly over HTTP range requests. That is what GenomeSpy's
lazy data sources need (indexedFasta, bigwig, bigbed, tabix, vcf, gff3, bam),
and it is the only way a 200 MB VCF becomes a track without materialising it as
a table first.

One object per sample: the scan matches one primary file per sample, the CLI
uploads it plus its index under ``indexed_file_s3_prefix(dc_id, sample)``, and
the API hands the browser a presigned URL per object
(``GET /depictio/api/v1/files/{dc_id}/{sample}/{name}``).

Layout note: the objects live under ``indexed_files/`` rather than the DC id at
the bucket root, for the same reason phylogeny trees do. The orphan cleanup
(``cleanup_orphaned_s3_files``) deletes any 24-hex top-level prefix that has no
deltatable and no MultiQC document, and an indexed_file DC has neither.
"""

from __future__ import annotations

import posixpath
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

IndexedFileFormat = Literal["vcf", "bam", "bigwig", "bigbed", "gff3", "fasta", "tabix"]

#: Formats GenomeSpy can read lazily, mapped to the index sidecar suffix the
#: parser needs. An empty string means the format is self-indexed (bigWig and
#: bigBed carry their R-tree index inside the file).
DEFAULT_INDEX_SUFFIX: dict[str, str] = {
    "vcf": ".tbi",
    "bam": ".bai",
    "gff3": ".tbi",
    "tabix": ".tbi",
    "fasta": ".fai",
    "bigwig": "",
    "bigbed": "",
}

#: Bucket-relative prefix every indexed file lands under.
INDEXED_FILE_ROOT = "indexed_files"


def indexed_file_s3_prefix(dc_id: str, sample: str) -> str:
    """Bucket-relative prefix for one sample's objects in ``dc_id``."""
    return f"{INDEXED_FILE_ROOT}/{dc_id}/{sample}"


def indexed_file_s3_key(dc_id: str, sample: str, name: str) -> str:
    """Bucket-relative key of one object, shared by the CLI upload and the API.

    ``name`` is a bare file name: any path separator, any ``..`` segment and any
    leading slash is rejected, so a caller-supplied name can never escape the
    DC's prefix.
    """
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError(f"Invalid indexed file name: {name!r}")
    if not sample or "/" in sample or "\\" in sample or sample in {".", ".."}:
        raise ValueError(f"Invalid sample name: {sample!r}")
    key = f"{indexed_file_s3_prefix(dc_id, sample)}/{name}"
    if posixpath.normpath(key) != key:
        raise ValueError(f"Invalid indexed file key: {key!r}")
    return key


#: Suffixes stripped, longest first, when a sample name is derived from a file
#: name. Compression suffixes come off with the format suffix, so
#: ``NA12878.filtered.vcf.gz`` becomes ``NA12878.filtered``.
_STRIPPED_SUFFIXES: tuple[str, ...] = (
    ".vcf.gz",
    ".vcf.bgz",
    ".gff3.gz",
    ".gff.gz",
    ".bed.gz",
    ".fa.gz",
    ".fasta.gz",
    ".bigWig",
    ".bigwig",
    ".bigBed",
    ".bigbed",
    ".vcf",
    ".gff3",
    ".gff",
    ".bed",
    ".fasta",
    ".fa",
    ".bam",
    ".bw",
    ".bb",
    ".gz",
)


def sample_from_path(path: str, sample_regex: str | None = None) -> str:
    """Name the sample a scanned file belongs to.

    ``sample_regex`` wins when it matches and declares a ``sample`` group;
    otherwise the file name with its format and compression suffixes stripped is
    used. The result is sanitised into a single S3 path segment, so a sample id
    can never introduce a separator or a traversal segment.
    """
    derived: str | None = None
    if sample_regex:
        try:
            match = re.search(sample_regex, path)
        except re.error:
            match = None
        if match:
            try:
                derived = match.group("sample")
            except IndexError:
                # A regex without a named `sample` group: fall back to the name.
                derived = None
    if not derived:
        derived = posixpath.basename(path.replace("\\", "/"))
        lowered = derived.lower()
        for suffix in sorted(_STRIPPED_SUFFIXES, key=len, reverse=True):
            if lowered.endswith(suffix.lower()):
                derived = derived[: -len(suffix)]
                break
    sanitised = re.sub(r"[^A-Za-z0-9._+-]+", "_", derived).strip("._")
    return sanitised or "sample"


class DCIndexedFileConfig(BaseModel):
    """Config for an indexed genomic file data collection.

    The DC carries no columns: a tile bound to it reads whole files from S3
    rather than rows from a delta table. ``sample_col`` is the join handle,
    not a column of this DC: it names the column a companion table DC uses for
    the same sample id, so a file-backed track can sit beside table-backed
    tracks and answer the dashboard's sample filter.
    """

    format: IndexedFileFormat = Field(
        description=(
            "File format. Each maps to one GenomeSpy lazy data source: vcf, bam, "
            "bigwig, bigbed, gff3, fasta (indexedFasta) or tabix (any other "
            "bgzip-compressed, tabix-indexed interval file such as BED)."
        )
    )
    index_suffix: str | None = Field(
        default=None,
        description=(
            "Suffix of the index sidecar, appended to the primary file name "
            "(.tbi, .bai, .fai). Null uses the format default; an empty string "
            "declares a self-indexed format such as bigwig or bigbed."
        ),
    )
    sample_regex: str | None = Field(
        default=None,
        description=(
            "Regular expression with a named group 'sample', matched against the "
            "scanned file path to name the sample. Null falls back to the file "
            "name with its format and compression suffixes stripped."
        ),
    )
    sample_col: str = Field(
        default="sample",
        description=(
            "Name the sample id is known by elsewhere in the project. Used to "
            "line a file track up with table-backed tracks and with the "
            "dashboard's sample filter; it is not a column of this DC."
        ),
    )
    assembly: str | None = Field(
        default=None,
        description=(
            "Genome assembly the files are aligned to (hg38, mm10, ...). A track "
            "reading this DC uses it for the genome axis; null leaves the choice "
            "to the component config."
        ),
    )
    max_file_size_mb: int = Field(
        default=512,
        ge=1,
        le=51200,
        description=(
            "Per-file upload cap. A primary file above it is skipped with a "
            "warning instead of pushing gigabytes into the bucket."
        ),
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("format", mode="before")
    @classmethod
    def _normalise_format(cls, v):
        if isinstance(v, str):
            normalised = v.lower().strip()
            aliases = {"bw": "bigwig", "bigWig".lower(): "bigwig", "bb": "bigbed", "gff": "gff3"}
            normalised = aliases.get(normalised, normalised)
            if normalised not in DEFAULT_INDEX_SUFFIX:
                raise ValueError(f"format must be one of {sorted(DEFAULT_INDEX_SUFFIX)}")
            return normalised
        return v

    @field_validator("index_suffix")
    @classmethod
    def _validate_index_suffix(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return v
        if not v.startswith("."):
            raise ValueError("index_suffix must start with a dot, or be empty for no index")
        if "/" in v or "\\" in v:
            raise ValueError("index_suffix must not contain a path separator")
        return v

    @property
    def effective_index_suffix(self) -> str:
        """Index suffix actually used: the explicit one, else the format default."""
        if self.index_suffix is not None:
            return self.index_suffix
        return DEFAULT_INDEX_SUFFIX[self.format]
