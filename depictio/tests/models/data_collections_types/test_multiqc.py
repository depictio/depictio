"""Tests for MultiQC data collection type model."""

import pytest
from pydantic import ValidationError

from depictio.models.models.data_collections_types.multiqc import DCMultiQC


class TestDCMultiQC:
    """Test suite for DCMultiQC model."""

    def test_valid_multiqc_config(self):
        """Test creating a valid DCMultiQC instance."""
        config = DCMultiQC(
            samples=["sample1", "sample2", "sample3"],
            modules=["fastqc", "cutadapt"],
            plots={"fastqc": ["quality"], "cutadapt": ["trimmed"]},
            s3_location="s3://bucket/path/multiqc.parquet",
            processed_files=1,
            file_size_bytes=1024000,
        )

        assert config.samples == ["sample1", "sample2", "sample3"]
        assert config.modules == ["fastqc", "cutadapt"]
        assert config.plots == {"fastqc": ["quality"], "cutadapt": ["trimmed"]}
        assert config.s3_location == "s3://bucket/path/multiqc.parquet"
        assert config.processed_files == 1
        assert config.file_size_bytes == 1024000

    def test_empty_multiqc_config(self):
        """Test creating DCMultiQC with default/empty values."""
        config = DCMultiQC()

        assert config.samples == []
        assert config.modules == []
        assert config.plots == {}
        assert config.s3_location is None
        assert config.processed_files is None
        assert config.file_size_bytes is None

    def test_partial_multiqc_config(self):
        """Test creating DCMultiQC with only some fields."""
        config = DCMultiQC(samples=["sample1", "sample2"], modules=["fastqc"])

        assert config.samples == ["sample1", "sample2"]
        assert config.modules == ["fastqc"]
        assert config.plots == {}
        assert config.s3_location is None
        assert config.processed_files is None
        assert config.file_size_bytes is None

    def test_complex_plots_structure(self):
        """Test DCMultiQC with complex plots structure."""
        complex_plots = {
            "fastqc": [
                "Sequence Counts",
                "Sequence Quality Histograms",
                {"Per Sequence GC Content": ["Percentages", "Counts"]},
                "Adapter Content",
            ],
            "cutadapt": ["Trimmed Reads", "Quality Scores"],
            "bowtie2": {"Alignment Statistics": ["Mapped", "Unmapped"]},
        }

        config = DCMultiQC(
            samples=["sample1"], modules=["fastqc", "cutadapt", "bowtie2"], plots=complex_plots
        )

        assert config.plots == complex_plots
        assert "fastqc" in config.plots
        assert "cutadapt" in config.plots
        assert "bowtie2" in config.plots

    def test_s3_location_validation(self):
        """Test S3 location field validation."""
        # Valid S3 location
        config = DCMultiQC(s3_location="s3://my-bucket/path/to/multiqc.parquet")
        assert config.s3_location == "s3://my-bucket/path/to/multiqc.parquet"

        # None is valid (optional field)
        config = DCMultiQC(s3_location=None)
        assert config.s3_location is None

    def test_file_size_validation(self):
        """Test file size field validation."""
        # Valid file size
        config = DCMultiQC(file_size_bytes=2884253)
        assert config.file_size_bytes == 2884253

        # Zero file size should be valid
        config = DCMultiQC(file_size_bytes=0)
        assert config.file_size_bytes == 0

        # None is valid (optional field)
        config = DCMultiQC(file_size_bytes=None)
        assert config.file_size_bytes is None

    def test_processed_files_validation(self):
        """Test processed files field validation."""
        # Valid processed files count
        config = DCMultiQC(processed_files=5)
        assert config.processed_files == 5

        # Single file
        config = DCMultiQC(processed_files=1)
        assert config.processed_files == 1

        # None is valid (optional field)
        config = DCMultiQC(processed_files=None)
        assert config.processed_files is None

    def test_extra_fields_forbidden(self):
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            DCMultiQC(
                samples=["sample1"],
                modules=["fastqc"],
                plots={},
                invalid_field="should_fail",  # type: ignore[call-arg]
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_real_world_data_structure(self):
        """Test with real-world MultiQC data structure from CLI processing."""
        real_world_config = DCMultiQC(
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
                "NMP_R1_L2_1",
                "SRR1067505_v10_1",
                "SRR1067505_v7_1",
                "test_1",
                "run1_2",
                "NMP_R1_L1_2_val_2",
                "NMP_R2_L1_1_val_1",
                "GY10_R1",
                "NP_D8_R1_L1_2",
                "00050101",
                "sample1_S1_L001_R2_001 - illumina_universal_adapter",
                "NMP_R1_L1_1",
                "NP_D8_R2_L1_1_val_1",
                "SRR1067505_1",
                "F1-1A_S1_R1_001",
                "NP_D8_R1_L1_1",
                "SK-GBD-000919.1",
                "SRR1067503_v10_1",
                "NP_D8_R2_L1_1",
                "SRR1067503_v7_1",
                "single",
                "NMP_R1_L1_2",
                "NMP_R1_L2_2",
                "test_2 - polya",
                "NP_D8_R1_L1_2_val_2",
                "NP_D8_R2_L1_2_val_2",
                "NP_D8_R1_L1_1_val_1",
                "NMP_R1_L2_2_val_2",
                "Theoretical GC Content",
                "SRR1067503_1",
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
            s3_location="s3://depictio-bucket/68cd8d3f364450bd1aeb14f3/multiqc.parquet",
            processed_files=1,
            file_size_bytes=2884253,
        )

        assert len(real_world_config.samples) == 41
        assert real_world_config.modules == ["fastqc"]
        assert "fastqc" in real_world_config.plots
        assert len(real_world_config.plots["fastqc"]) == 11
        assert (
            real_world_config.s3_location
            == "s3://depictio-bucket/68cd8d3f364450bd1aeb14f3/multiqc.parquet"
        )
        assert real_world_config.processed_files == 1
        assert real_world_config.file_size_bytes == 2884253

    def test_model_dump_preserves_structure(self):
        """Test that model_dump preserves the data structure."""
        config = DCMultiQC(
            samples=["sample1", "sample2"],
            modules=["fastqc", "cutadapt"],
            plots={"fastqc": ["quality", "length"]},
            s3_location="s3://bucket/path.parquet",
            processed_files=2,
            file_size_bytes=1024,
        )

        dumped = config.model_dump()

        assert dumped["samples"] == ["sample1", "sample2"]
        assert dumped["modules"] == ["fastqc", "cutadapt"]
        assert dumped["plots"] == {"fastqc": ["quality", "length"]}
        assert dumped["s3_location"] == "s3://bucket/path.parquet"
        assert dumped["processed_files"] == 2
        assert dumped["file_size_bytes"] == 1024

    def test_model_dump_excludes_none_values(self):
        """Test that model_dump can exclude None values."""
        config = DCMultiQC(
            samples=["sample1"],
            modules=["fastqc"],
            # s3_location, processed_files, file_size_bytes are None by default
        )

        dumped = config.model_dump(exclude_none=True)

        assert "samples" in dumped
        assert "modules" in dumped
        assert "plots" in dumped
        assert "s3_location" not in dumped
        assert "processed_files" not in dumped
        assert "file_size_bytes" not in dumped
