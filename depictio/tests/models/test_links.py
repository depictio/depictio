"""Unit tests for DC Links model with image support."""

import pytest
from pydantic import ValidationError

from depictio.models.models.base import PyObjectId
from depictio.models.models.links import (
    DCLink,
    LinkConfig,
    LinkCreateRequest,
    LinkResolutionRequest,
    LinkResolutionResponse,
    LinkUpdateRequest,
)


class TestLinkConfig:
    """Test suite for LinkConfig model."""

    def test_default_config(self):
        """Test default LinkConfig creation."""
        config = LinkConfig()
        assert config.resolver == "direct"
        assert config.mappings is None
        assert config.pattern is None
        assert config.target_field is None
        assert config.case_sensitive is True

    def test_sample_mapping_resolver(self):
        """Test sample_mapping resolver configuration."""
        config = LinkConfig(
            resolver="sample_mapping",
            mappings={"S1": ["S1_R1", "S1_R2"], "S2": ["S2_R1"]},
            target_field="sample_name",
        )
        assert config.resolver == "sample_mapping"
        assert config.mappings == {"S1": ["S1_R1", "S1_R2"], "S2": ["S2_R1"]}
        assert config.target_field == "sample_name"

    def test_pattern_resolver(self):
        """Test pattern resolver configuration."""
        config = LinkConfig(
            resolver="pattern",
            pattern="{sample}.bam",
            target_field="filename",
        )
        assert config.resolver == "pattern"
        assert config.pattern == "{sample}.bam"
        assert config.target_field == "filename"

    def test_pattern_validation_missing_placeholder(self):
        """Test pattern validation requires {sample} placeholder."""
        with pytest.raises(ValidationError) as exc_info:
            LinkConfig(resolver="pattern", pattern="sample.bam")
        assert "Pattern must contain {sample} placeholder" in str(exc_info.value)

    def test_wildcard_resolver(self):
        """Test wildcard resolver configuration."""
        config = LinkConfig(
            resolver="wildcard",
            pattern="{sample}*",
            target_field="filename",
        )
        assert config.resolver == "wildcard"
        assert config.pattern == "{sample}*"

    def test_regex_resolver(self):
        """Test regex resolver configuration."""
        config = LinkConfig(
            resolver="regex",
            pattern="{sample}_.*\\.fastq",
            target_field="filename",
        )
        assert config.resolver == "regex"

    def test_case_insensitive_matching(self):
        """Test case_sensitive flag can be disabled."""
        config = LinkConfig(resolver="direct", case_sensitive=False)
        assert config.case_sensitive is False

    def test_extra_fields_forbidden(self):
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            LinkConfig(resolver="direct", unknown_field="value")  # type: ignore[call-arg]
        assert "extra" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()


class TestDCLink:
    """Test suite for DCLink model with image support."""

    def test_valid_image_link_minimal(self):
        """Test creating minimal valid image DC link."""
        link = DCLink(
            source_dc_id="metadata_dc_id",
            source_column="sample_id",
            target_dc_id="image_dc_id",
            target_type="image",
        )
        assert link.source_dc_id == "metadata_dc_id"
        assert link.source_column == "sample_id"
        assert link.target_dc_id == "image_dc_id"
        assert link.target_type == "image"
        assert link.enabled is True
        assert isinstance(link.id, PyObjectId)

    def test_valid_image_link_full(self):
        """Test creating full image DC link with all fields."""
        link = DCLink(
            source_dc_id="metadata_dc_id",
            source_column="sample_id",
            target_dc_id="image_dc_id",
            target_type="image",
            link_config=LinkConfig(
                resolver="pattern",
                pattern="{sample}_image.png",
                target_field="image_path",
            ),
            description="Link samples to images",
            enabled=True,
        )
        assert link.link_config.resolver == "pattern"
        assert link.link_config.pattern == "{sample}_image.png"
        assert link.description == "Link samples to images"

    def test_valid_table_link(self):
        """Test creating table DC link."""
        link = DCLink(
            source_dc_id="dc1",
            source_column="col1",
            target_dc_id="dc2",
            target_type="table",
        )
        assert link.target_type == "table"

    def test_valid_multiqc_link(self):
        """Test creating multiqc DC link."""
        link = DCLink(
            source_dc_id="dc1",
            source_column="sample",
            target_dc_id="multiqc_dc",
            target_type="multiqc",
        )
        assert link.target_type == "multiqc"

    def test_invalid_target_type(self):
        """Test invalid target_type is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DCLink(
                source_dc_id="dc1",
                source_column="col1",
                target_dc_id="dc2",
                target_type="invalid_type",  # type: ignore[arg-type]
            )
        assert "target_type" in str(exc_info.value)

    def test_source_dc_id_required(self):
        """Test source_dc_id is required."""
        with pytest.raises(ValidationError) as exc_info:
            DCLink(  # type: ignore[call-arg]
                source_column="col1",
                target_dc_id="dc2",
                target_type="table",
            )
        assert "source_dc_id" in str(exc_info.value)

    def test_source_column_required(self):
        """Test source_column is required."""
        with pytest.raises(ValidationError) as exc_info:
            DCLink(  # type: ignore[call-arg]
                source_dc_id="dc1",
                target_dc_id="dc2",
                target_type="table",
            )
        assert "source_column" in str(exc_info.value)

    def test_source_column_empty_rejected(self):
        """Test empty source_column is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DCLink(
                source_dc_id="dc1",
                source_column="  ",
                target_dc_id="dc2",
                target_type="table",
            )
        assert "Source column cannot be empty" in str(exc_info.value)

    def test_dc_id_objectid_conversion(self):
        """Test DC IDs are converted from ObjectId to string."""
        from bson import ObjectId

        obj_id = ObjectId()
        link = DCLink(
            source_dc_id=obj_id,  # type: ignore[arg-type]
            source_column="col1",
            target_dc_id=str(obj_id),
            target_type="table",
        )
        assert link.source_dc_id == str(obj_id)
        assert isinstance(link.source_dc_id, str)

    def test_mongodb_id_field_conversion(self):
        """Test _id field is converted to id (MongoDB compatibility)."""
        from bson import ObjectId

        mongo_doc = {
            "_id": ObjectId(),
            "source_dc_id": "dc1",
            "source_column": "col",
            "target_dc_id": "dc2",
            "target_type": "table",
        }
        link = DCLink(**mongo_doc)
        assert hasattr(link, "id")
        assert link.id is not None

    def test_disabled_link(self):
        """Test creating disabled link."""
        link = DCLink(
            source_dc_id="dc1",
            source_column="col1",
            target_dc_id="dc2",
            target_type="table",
            enabled=False,
        )
        assert link.enabled is False

    def test_extra_fields_forbidden(self):
        """Test extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DCLink(
                source_dc_id="dc1",
                source_column="col1",
                target_dc_id="dc2",
                target_type="table",
                unknown_field="value",  # type: ignore[call-arg]
            )
        assert "extra" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()


class TestLinkResolutionModels:
    """Test suite for link resolution request/response models."""

    def test_link_resolution_request(self):
        """Test creating link resolution request."""
        request = LinkResolutionRequest(
            source_dc_id="metadata_dc_id",
            source_column="sample_id",
            filter_values=["S1", "S2", "S3"],
            target_dc_id="image_dc_id",
        )
        assert request.source_dc_id == "metadata_dc_id"
        assert request.source_column == "sample_id"
        assert len(request.filter_values) == 3
        assert request.target_dc_id == "image_dc_id"

    def test_link_resolution_response(self):
        """Test creating link resolution response."""
        response = LinkResolutionResponse(
            resolved_values=["S1_img.png", "S2_img.png", "S3_img.png"],
            link_id="link_123",
            resolver_used="pattern",
            match_count=3,
            target_type="image",
            source_count=3,
            unmapped_values=[],
        )
        assert len(response.resolved_values) == 3
        assert response.match_count == 3
        assert response.resolver_used == "pattern"
        assert response.target_type == "image"

    def test_link_resolution_response_with_unmapped(self):
        """Test response with unmapped values."""
        response = LinkResolutionResponse(
            resolved_values=["S1_img.png"],
            link_id="link_123",
            resolver_used="pattern",
            match_count=1,
            target_type="image",
            source_count=3,
            unmapped_values=["S2", "S3"],
        )
        assert len(response.unmapped_values) == 2
        assert response.match_count == 1


class TestLinkRequestModels:
    """Test suite for link CRUD request models."""

    def test_link_create_request_image(self):
        """Test creating link create request for image DC."""
        request = LinkCreateRequest(
            source_dc_id="metadata_dc",
            source_column="sample_id",
            target_dc_id="image_dc",
            target_type="image",
            link_config=LinkConfig(
                resolver="pattern",
                pattern="{sample}.png",
                target_field="image_path",
            ),
            description="Link metadata to images",
        )
        assert request.target_type == "image"
        assert request.link_config.resolver == "pattern"

    def test_link_update_request_partial(self):
        """Test link update with partial fields."""
        request = LinkUpdateRequest(
            description="Updated description",
            enabled=False,
        )
        assert request.description == "Updated description"
        assert request.enabled is False
        assert request.source_dc_id is None
        assert request.target_type is None

    def test_link_update_request_link_config(self):
        """Test updating link config."""
        request = LinkUpdateRequest(
            link_config=LinkConfig(
                resolver="direct",
                target_field="new_field",
            )
        )
        assert request.link_config is not None
        assert request.link_config.resolver == "direct"
