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
