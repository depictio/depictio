"""Tests for MultiQC reports models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from depictio.models.models.multiqc_reports import MultiQCMetadata, MultiQCReport


class TestMultiQCMetadata:
    """Test suite for MultiQCMetadata model."""

    def test_valid_metadata(self):
        """Test creating a valid MultiQCMetadata instance."""
        metadata = MultiQCMetadata(
            samples=["sample1", "sample2", "sample3"],
            modules=["fastqc", "multiqc"],
            plots={"fastqc": ["quality", "length"], "multiqc": ["summary"]},
        )
        assert metadata.samples == ["sample1", "sample2", "sample3"]
        assert metadata.modules == ["fastqc", "multiqc"]
        assert metadata.plots == {"fastqc": ["quality", "length"], "multiqc": ["summary"]}

    def test_empty_metadata(self):
        """Test creating MultiQCMetadata with empty values."""
        metadata = MultiQCMetadata()
        assert metadata.samples == []
        assert metadata.modules == []
        assert metadata.plots == {}

    def test_extra_fields_forbidden(self):
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            MultiQCMetadata(
                samples=["sample1"],
                modules=["fastqc"],
                plots={},
                invalid_field="should_fail",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_samples_validation(self):
        """Test samples field validation."""
        # Valid samples list
        metadata = MultiQCMetadata(samples=["sample_1", "sample-2", "sample.3"])
        assert len(metadata.samples) == 3

        # Empty samples list is valid
        metadata = MultiQCMetadata(samples=[])
        assert metadata.samples == []

    def test_plots_complex_structure(self):
        """Test plots field with complex nested structure."""
        complex_plots = {
            "fastqc": [
                "Sequence Counts",
                "Sequence Quality Histograms",
                {"Per Sequence GC Content": ["Percentages", "Counts"]},
                "Adapter Content",
            ],
            "cutadapt": ["Trimmed Reads", "Quality Scores"],
        }
        metadata = MultiQCMetadata(plots=complex_plots)
        assert metadata.plots == complex_plots


class TestMultiQCReport:
    """Test suite for MultiQCReport model."""

    def test_valid_report(self):
        """Test creating a valid MultiQCReport instance."""
        metadata = MultiQCMetadata(
            samples=["sample1", "sample2"], modules=["fastqc"], plots={"fastqc": ["quality"]}
        )

        report = MultiQCReport(
            data_collection_id="507f1f77bcf86cd799439011",
            metadata=metadata,
            s3_location="s3://bucket/path/multiqc.parquet",
            original_file_path="/path/to/multiqc.parquet",
            report_name="Test MultiQC Report",
        )

        assert report.data_collection_id == "507f1f77bcf86cd799439011"
        assert report.metadata == metadata
        assert report.s3_location == "s3://bucket/path/multiqc.parquet"
        assert report.original_file_path == "/path/to/multiqc.parquet"
        assert report.report_name == "Test MultiQC Report"
        assert isinstance(report.processed_at, datetime)
        assert report.file_size_bytes is None
        assert report.multiqc_version is None

    def test_report_with_optional_fields(self):
        """Test creating MultiQCReport with all optional fields."""
        metadata = MultiQCMetadata()
        processed_time = datetime.now()

        report = MultiQCReport(
            data_collection_id="507f1f77bcf86cd799439012",
            metadata=metadata,
            s3_location="s3://bucket/report.parquet",
            original_file_path="/local/path/report.parquet",
            file_size_bytes=1024768,
            processed_at=processed_time,
            multiqc_version="1.21.0",
            report_name="Complete MultiQC Report",
        )

        assert report.file_size_bytes == 1024768
        assert report.processed_at == processed_time
        assert report.multiqc_version == "1.21.0"
        assert report.report_name == "Complete MultiQC Report"

    def test_required_fields_validation(self):
        """Test that required fields are validated."""
        metadata = MultiQCMetadata()

        # Missing data_collection_id
        with pytest.raises(ValidationError) as exc_info:
            MultiQCReport(
                metadata=metadata,
                s3_location="s3://bucket/path.parquet",
                original_file_path="/path/file.parquet",
            )
        assert "data_collection_id" in str(exc_info.value)

        # Missing s3_location
        with pytest.raises(ValidationError) as exc_info:
            MultiQCReport(
                data_collection_id="507f1f77bcf86cd799439011",
                metadata=metadata,
                original_file_path="/path/file.parquet",
            )
        assert "s3_location" in str(exc_info.value)

        # Missing original_file_path
        with pytest.raises(ValidationError) as exc_info:
            MultiQCReport(
                data_collection_id="507f1f77bcf86cd799439011",
                metadata=metadata,
                s3_location="s3://bucket/path.parquet",
            )
        assert "original_file_path" in str(exc_info.value)

    def test_extra_fields_forbidden(self):
        """Test that extra fields are rejected."""
        metadata = MultiQCMetadata()

        with pytest.raises(ValidationError) as exc_info:
            MultiQCReport(
                data_collection_id="507f1f77bcf86cd799439011",
                metadata=metadata,
                s3_location="s3://bucket/path.parquet",
                original_file_path="/path/file.parquet",
                extra_field="should_fail",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_str_representation(self):
        """Test string representation of MultiQCReport."""
        metadata = MultiQCMetadata(samples=["sample1", "sample2", "sample3"])

        report = MultiQCReport(
            data_collection_id="507f1f77bcf86cd799439011",
            metadata=metadata,
            s3_location="s3://bucket/path.parquet",
            original_file_path="/path/file.parquet",
            report_name="Test Report",
        )

        str_repr = str(report)
        assert "Test Report" in str_repr
        assert "3 samples" in str_repr

    def test_repr_representation(self):
        """Test repr representation of MultiQCReport."""
        metadata = MultiQCMetadata(samples=["sample1", "sample2"])

        report = MultiQCReport(
            data_collection_id="507f1f77bcf86cd799439011",
            metadata=metadata,
            s3_location="s3://bucket/path.parquet",
            original_file_path="/path/file.parquet",
        )

        repr_str = repr(report)
        assert "MultiQCReport" in repr_str
        assert "507f1f77bcf86cd799439011" in repr_str
        assert "samples=2" in repr_str

    def test_model_dump_json_mode(self):
        """Test model_dump with JSON mode for datetime serialization."""
        metadata = MultiQCMetadata(samples=["sample1"])
        processed_time = datetime(2025, 9, 19, 12, 0, 0)

        report = MultiQCReport(
            data_collection_id="507f1f77bcf86cd799439011",
            metadata=metadata,
            s3_location="s3://bucket/path.parquet",
            original_file_path="/path/file.parquet",
            processed_at=processed_time,
        )

        # Test JSON mode serialization
        json_data = report.model_dump(mode="json")
        assert isinstance(json_data["processed_at"], str)
        assert "2025-09-19T12:00:00" in json_data["processed_at"]

    def test_real_world_data_structure(self):
        """Test with real-world MultiQC data structure."""
        real_world_metadata = MultiQCMetadata(
            samples=[
                "NMP_R2_L1_2_val_2",
                "NMP_R1_L2_1_val_1",
                "test_2",
                "test_1 - polya",
                "sample1_S1_L001_R2_001",
                "NMP_R1_L2_1",
                "NMP_R1_L1_1_val_1",
                "NMP_R2_L1_2",
                "single - polya",
                "test",
                "NP_D8_R2_L1_2",
            ],
            modules=["fastqc"],
            plots={
                "fastqc": [
                    "Sequence Counts",
                    "Sequence Quality Histograms",
                    "Per Sequence Quality Scores",
                    {"Per Sequence GC Content": ["Percentages", "Counts"]},
                    "Per Base N Content",
                    "Sequence Length Distribution",
                    "Sequence Duplication Levels",
                    "Overrepresented sequences by sample",
                    "Top overrepresented sequences",
                    "Adapter Content",
                    "Status Checks",
                ]
            },
        )

        report = MultiQCReport(
            data_collection_id="68cd8d3f364450bd1aeb14f3",
            metadata=real_world_metadata,
            s3_location="s3://depictio-bucket/68cd8d3f364450bd1aeb14f3/multiqc.parquet",
            original_file_path="/path/to/multiqc_data/multiqc.parquet",
            file_size_bytes=2884253,
            report_name="MultiQC Report - multiqc_data",
        )

        assert len(report.metadata.samples) == 11
        assert report.metadata.modules == ["fastqc"]
        assert "fastqc" in report.metadata.plots
        assert report.file_size_bytes == 2884253
