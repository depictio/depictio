from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator


class JBrowse2TrackType(str, Enum):
    """Supported JBrowse2 track types."""

    BED = "bed"
    BIGWIG = "bigwig"
    MULTI_BIGWIG = "multi_bigwig"


class MultiTrackPattern(BaseModel):
    """Configuration for grouping files into composite multi-track displays.

    Used with MULTI_BIGWIG track type to group multiple BigWig files into a single
    MultiQuantitativeTrack. Generic: works for any grouping (strand pairing,
    condition grouping, replicate merging, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    group_by: str
    """Wildcard name to group files into one composite track (e.g., 'sample')."""

    sub_track_by: str
    """Wildcard name to create sub-tracks within each group (e.g., 'strand', 'condition')."""

    sub_track_colors: dict[str, str] | None = None
    """Optional color per sub-track value. E.g., {'W': 'rgb(244,164,96)', 'C': 'rgb(102,139,139)'}."""


class DCJBrowse2Config(BaseModel):
    """Configuration for JBrowse2 data collections.

    Supports BED (indexed with tabix), BigWig (single quantitative track),
    and Multi BigWig (composite MultiQuantitativeTrack) track types.
    """

    model_config = ConfigDict(extra="forbid")

    track_type: JBrowse2TrackType
    """Type of JBrowse2 track to render."""

    assembly_name: str = "hg38"
    """Reference assembly name (must match a key in DEFAULT_ASSEMBLIES)."""

    index_extension: str | None = "tbi"
    """Index file extension for BED tracks (e.g., 'tbi', 'csi')."""

    category: list[str] | None = None
    """JBrowse2 track category hierarchy for organizing tracks in the track selector."""

    display_config: dict | None = None
    """Optional display configuration overrides (color, height, renderer settings)."""

    multi_track_pattern: MultiTrackPattern | None = None
    """Configuration for multi-track grouping. Required when track_type is MULTI_BIGWIG."""

    jbrowse_template_override: dict | None = None
    """Full JBrowse2 track template override. When provided, replaces the built-in template."""

    # Processing metadata (populated during CLI processing)
    s3_session_location: str | None = None
    """S3 location of the generated JBrowse2 session config JSON."""

    @model_validator(mode="after")
    def validate_track_type_constraints(self):
        if self.track_type == JBrowse2TrackType.MULTI_BIGWIG and self.multi_track_pattern is None:
            raise ValueError("multi_track_pattern is required when track_type is 'multi_bigwig'")
        if self.track_type == JBrowse2TrackType.BED and self.index_extension is None:
            raise ValueError("index_extension is required when track_type is 'bed'")
        return self
