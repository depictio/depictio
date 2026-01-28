"""
Models for universal DC linking configuration.

This module defines the data models for configuring links between data collections
that enable cross-DC filtering without pre-computing joined data. Links support
various DC types (table, multiqc, jbrowse2, images, geomap) with pluggable resolvers.

Key concepts:
- Links: Lightweight, typed relationships between DCs for cross-DC filtering
- Resolvers: Pluggable strategies for mapping source values to target identifiers
- Runtime resolution: Values are resolved at runtime, not pre-computed
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from depictio.models.models.base import PyObjectId


class LinkConfig(BaseModel):
    """Configuration for how to resolve link values between data collections.

    The resolver determines the strategy used to map source values to target identifiers:
    - direct: 1:1 mapping - same value in source and target
    - sample_mapping: Expand canonical IDs to sample name variants (for MultiQC)
    - pattern: Template substitution (e.g., "{sample}.bam" -> "S1.bam")
    - regex: Match target values using regex pattern
    - wildcard: Glob-style matching (e.g., "S1*" matches "S1_R1.bam")

    Example:
        LinkConfig(
            resolver="sample_mapping",
            mappings={"S1": ["S1_R1", "S1_R2"], "S2": ["S2_R1"]},
            target_field="sample_name"
        )
    """

    resolver: Literal["direct", "sample_mapping", "pattern", "regex", "wildcard"] = Field(
        default="direct",
        description="Resolution strategy for mapping source values to target identifiers",
    )

    mappings: dict[str, list[str]] | None = Field(
        default=None,
        description="Explicit value mappings for sample_mapping resolver. "
        "Maps canonical IDs to lists of variants. "
        "Example: {'S1': ['S1_R1', 'S1_R2'], 'S2': ['S2_R1']}",
    )

    pattern: str | None = Field(
        default=None,
        description="Template pattern for pattern resolver. "
        "Use {sample} as placeholder. Example: '{sample}.bam' or '{sample}_*.vcf'",
    )

    target_field: str | None = Field(
        default=None,
        description="Field name in target DC to match against resolved values. "
        "For MultiQC, typically 'sample_name'. For tables, the column name.",
    )

    case_sensitive: bool = Field(
        default=True,
        description="Whether value matching is case-sensitive",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str | None) -> str | None:
        """Validate that pattern contains a placeholder if provided."""
        if v is not None and "{sample}" not in v:
            raise ValueError("Pattern must contain {sample} placeholder")
        return v


class DCLink(BaseModel):
    """Universal link between data collections for cross-DC filtering.

    A link defines a relationship between a source DC (where filters are applied)
    and a target DC (which receives the filtered values). The link_config determines
    how values are resolved from source to target.

    Phase 1 supports:
    - table: Direct column mapping or link-based filtering
    - multiqc: Sample name resolution via sample_mappings

    Future phases will add:
    - jbrowse2: Track visibility based on sample patterns
    - images: Image selection based on metadata patterns
    - geomap: Marker/region filtering

    Example YAML configuration:
        links:
          - source_dc_id: "metadata_table_dc_id"
            source_column: "sample_id"
            target_dc_id: "multiqc_dc_id"
            target_type: "multiqc"
            link_config:
              resolver: "sample_mapping"
              target_field: "sample_name"
            description: "Link metadata samples to MultiQC variants"
    """

    id: PyObjectId = Field(default_factory=PyObjectId)

    source_dc_id: str = Field(
        ...,
        description="Data collection ID for the source (where filters are applied)",
    )

    source_column: str = Field(
        ...,
        description="Column name in source DC containing values to resolve",
    )

    target_dc_id: str = Field(
        ...,
        description="Data collection ID for the target (receives resolved values)",
    )

    target_type: Literal["table", "multiqc"] = Field(
        ...,
        description="Type of the target DC. Determines which resolver strategies are valid. "
        "Phase 1 supports: 'table', 'multiqc'. "
        "Future: 'jbrowse2', 'images', 'geomap'",
    )

    link_config: LinkConfig = Field(
        default_factory=LinkConfig,
        description="Configuration for value resolution between DCs",
    )

    description: str | None = Field(
        default=None,
        description="Human-readable description of the link purpose",
    )

    enabled: bool = Field(
        default=True,
        description="Whether this link is active. Disabled links are ignored during resolution.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def convert_id_field(cls, values: dict) -> dict:
        """Convert MongoDB _id field to id for compatibility."""
        if not isinstance(values, dict):
            return values
        # Convert _id to id if present (from MongoDB documents)
        if "_id" in values:
            values["id"] = values.pop("_id")
        return values

    @field_validator("source_dc_id", "target_dc_id")
    @classmethod
    def validate_dc_ids(cls, v: str) -> str:
        """Ensure DC IDs are non-empty strings."""
        if not v or not v.strip():
            raise ValueError("DC ID cannot be empty")
        return v.strip()

    @field_validator("source_column")
    @classmethod
    def validate_source_column(cls, v: str) -> str:
        """Ensure source column is a non-empty string."""
        if not v or not v.strip():
            raise ValueError("Source column cannot be empty")
        return v.strip()


class LinkResolutionRequest(BaseModel):
    """Request to resolve filtered values via a link.

    Used when a filter is applied on a source DC and the resolved values
    need to be applied to a target DC.

    Example:
        LinkResolutionRequest(
            source_dc_id="metadata_dc_id",
            source_column="sample_id",
            filter_values=["S1", "S2"],
            target_dc_id="multiqc_dc_id"
        )
    """

    source_dc_id: str = Field(
        ...,
        description="Data collection ID where the filter was applied",
    )

    source_column: str = Field(
        ...,
        description="Column name that was filtered",
    )

    filter_values: list[Any] = Field(
        ...,
        description="Values from the filter to resolve to target DC",
    )

    target_dc_id: str = Field(
        ...,
        description="Target data collection ID to resolve values for",
    )

    model_config = ConfigDict(extra="forbid")


class LinkResolutionResponse(BaseModel):
    """Response with resolved target values from a link resolution request.

    Contains the resolved values that should be used to filter the target DC,
    along with metadata about the resolution process.

    Example response:
        {
            "resolved_values": ["S1_R1", "S1_R2", "S2_R1"],
            "link_id": "link_001",
            "resolver_used": "sample_mapping",
            "match_count": 3,
            "target_type": "multiqc",
            "source_count": 2,
            "unmapped_values": []
        }
    """

    resolved_values: list[str] = Field(
        ...,
        description="List of resolved values to apply to target DC",
    )

    link_id: str = Field(
        ...,
        description="ID of the link used for resolution",
    )

    resolver_used: str = Field(
        ...,
        description="Name of the resolver strategy that was applied",
    )

    match_count: int = Field(
        ...,
        description="Number of values successfully resolved",
    )

    target_type: str = Field(
        ...,
        description="Type of the target DC (table, multiqc, etc.)",
    )

    source_count: int = Field(
        default=0,
        description="Number of source values in the request",
    )

    unmapped_values: list[str] = Field(
        default_factory=list,
        description="Source values that could not be mapped (for debugging)",
    )

    model_config = ConfigDict(extra="forbid")


class LinkCreateRequest(BaseModel):
    """Request to create a new DC link.

    Example:
        LinkCreateRequest(
            source_dc_id="metadata_dc_id",
            source_column="sample_id",
            target_dc_id="multiqc_dc_id",
            target_type="multiqc",
            link_config=LinkConfig(resolver="sample_mapping"),
            description="Link metadata to MultiQC"
        )
    """

    source_dc_id: str = Field(..., description="Source data collection ID")
    source_column: str = Field(..., description="Column name in source DC")
    target_dc_id: str = Field(..., description="Target data collection ID")
    target_type: Literal["table", "multiqc"] = Field(..., description="Target DC type")
    link_config: LinkConfig = Field(default_factory=LinkConfig)
    description: str | None = Field(default=None)
    enabled: bool = Field(default=True)

    model_config = ConfigDict(extra="forbid")


class LinkUpdateRequest(BaseModel):
    """Request to update an existing DC link.

    All fields are optional - only provided fields will be updated.
    """

    source_dc_id: str | None = Field(default=None)
    source_column: str | None = Field(default=None)
    target_dc_id: str | None = Field(default=None)
    target_type: Literal["table", "multiqc"] | None = Field(default=None)
    link_config: LinkConfig | None = Field(default=None)
    description: str | None = Field(default=None)
    enabled: bool | None = Field(default=None)

    model_config = ConfigDict(extra="forbid")
