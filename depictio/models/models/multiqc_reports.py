"""
MultiQC Reports model for storing MultiQC analysis results.

This model represents individual MultiQC reports with their metadata,
S3 storage location, and relationship to data collections.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from depictio.models.models.base import MongoModel


class MultiQCMetadata(BaseModel):
    """Metadata extracted from MultiQC parquet files."""

    samples: List[str] = Field(
        default_factory=list, description="List of sample names in the MultiQC report"
    )
    modules: List[str] = Field(
        default_factory=list, description="List of MultiQC modules used in the analysis"
    )
    plots: Dict[str, Any] = Field(
        default_factory=dict, description="Plot configuration and data from MultiQC"
    )
    sample_mappings: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Mapping from canonical sample IDs to all their MultiQC variants. "
        "Example: {'SRR10070130': ['SRR10070130', 'SRR10070130_1', 'SRR10070130_2', "
        "'SRR10070130 - First read: Adapter 1', ...]}",
    )
    canonical_samples: List[str] = Field(
        default_factory=list,
        description="List of normalized canonical sample IDs (without suffixes or annotations). "
        "Used for joining with external metadata tables.",
    )

    class Config:
        extra = "forbid"


class MultiQCReport(MongoModel):
    """
    MongoDB document representing a MultiQC report.

    This model stores:
    - Extracted metadata (samples, modules, plots)
    - S3 storage location of the parquet file
    - Reference to the parent data collection
    - Processing information and timestamps
    """

    data_collection_id: str = Field(..., description="ID of the parent data collection")

    # MultiQC metadata
    metadata: MultiQCMetadata = Field(
        default_factory=MultiQCMetadata, description="Extracted MultiQC metadata"
    )

    # Storage information
    s3_location: str = Field(..., description="S3 path to the MultiQC parquet file")
    original_file_path: str = Field(..., description="Original local file path")
    file_size_bytes: Optional[int] = Field(None, description="Size of the parquet file in bytes")

    # Processing information
    processed_at: datetime = Field(
        default_factory=datetime.now, description="When the MultiQC report was processed"
    )
    multiqc_version: Optional[str] = Field(
        None, description="Version of MultiQC used to generate the report"
    )

    # Report metadata
    report_name: Optional[str] = Field(None, description="Name/identifier for this MultiQC report")

    class Config:
        extra = "forbid"

    def __str__(self) -> str:
        return (
            f"MultiQC Report {self.report_name or self.id} ({len(self.metadata.samples)} samples)"
        )

    def __repr__(self) -> str:
        return f"MultiQCReport(id={self.id}, dc_id={self.data_collection_id}, samples={len(self.metadata.samples)})"


class MultiQCManifest(MongoModel):
    """Which parquet objects a MultiQC data collection consisted of, at one moment.

    MultiQC's answer to "what did this collection look like when that dashboard
    version was saved". It works because the parquet objects are already
    content-addressed — ``s3://{bucket}/{dc_id}/{sha256}/multiqc.parquet`` —
    and every ingest writes a new one rather than rewriting an old one. Pinning
    the *set* of keys therefore reproduces the state exactly, with no copying
    and no storage-level versioning.

    One document per ingest, mirroring ``DeltaTableAggregated.aggregation``'s
    monotonic list, but as separate documents: a long-lived collection
    accumulates generations and each generation carries every location, so an
    embedded list would multiply the two and eventually meet the 16 MB BSON
    ceiling.

    Every field carries a default. ``MongoModel`` is ``extra="forbid"`` and
    reads historical documents on every load, so a shape that cannot be read
    back with fields missing is a shape that breaks on upgrade.
    """

    data_collection_id: str = Field(default="", description="ID of the parent data collection")

    #: Monotonic per data collection, starting at 1. Displayed, and used to
    #: order generations without relying on clock skew between writers.
    generation: int = Field(default=1, description="Monotonic ingest counter for this collection")

    #: sha256 over the sorted, newline-free join of ``s3_locations``. The same
    #: construction ``MultiQCPrerender.s3_locations_hash`` already uses, so a
    #: manifest and the prerender cache agree on what "the same report set"
    #: means without either having to know about the other.
    digest: str = Field(default="", description="sha256 of the sorted s3_location set")

    s3_locations: list[str] = Field(
        default_factory=list, description="Every report parquet in this generation"
    )
    sample_count: Optional[int] = Field(
        default=None, description="Distinct canonical samples across the generation"
    )
    report_count: int = Field(default=0, description="Number of reports in this generation")

    created_at: datetime = Field(
        default_factory=datetime.now, description="When this generation was recorded"
    )
    #: What produced it — ``ingest``, ``append``, ``replace``. Free-form on
    #: purpose; nothing keys behaviour on it.
    trigger: Optional[str] = Field(default=None, description="Which write path recorded this")

    class Config:
        extra = "forbid"

    def __repr__(self) -> str:
        return (
            f"MultiQCManifest(dc_id={self.data_collection_id}, gen={self.generation}, "
            f"reports={self.report_count}, digest={self.digest[:12]})"
        )
