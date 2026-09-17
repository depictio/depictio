"""
MultiQC Reports model for storing MultiQC analysis results.

This model represents individual MultiQC reports with their metadata,
S3 storage location, and relationship to data collections.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from depictio.models.models.base import MongoModel

# The anchor a MultiQC parquet stores its general-statistics rows under, and the
# per-pipeline anchors that stand in for it (nf-core/viralrecon publishes the
# same table as a custom-content plot; the nanopore route suffixes it `_table`).
# Shared so the render path, ingestion and the builder all agree on what "the
# report has a general-statistics table" means.
GENERAL_STATS_ANCHOR = "general_stats_table"
GENERAL_STATS_FALLBACK_ANCHORS = (
    "summary_variants_metrics_plot",
    "summary_assembly_metrics_plot",
    "summary_variants_metrics_plot_table",
    "summary_assembly_metrics_plot_table",
)


def general_stats_available(flags: Iterable[Optional[bool]]) -> bool:
    """Whether a General Stats tile can render over a set of reports.

    ``flags`` are the reports' ``metadata.has_general_stats``. One report that
    has the table is enough, because a render concatenates every parquet of the
    data collection. The tile is only withheld when every report is known to
    lack it: a report ingested before the flag existed carries None, and hiding
    on that would drop working tiles on data nobody re-ingested.
    """
    values = list(flags)
    if any(f is True for f in values):
        return True
    return not (values and all(f is False for f in values))


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
    has_general_stats: Optional[bool] = Field(
        None,
        description="Whether the parquet carries general-statistics rows. MultiQC assembles "
        "that table from every module that ran, so it appears in neither `modules` nor "
        "`plots` and can only be read from the parquet's anchors. None on reports ingested "
        "before this was recorded, which callers treat as unknown rather than absent.",
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
