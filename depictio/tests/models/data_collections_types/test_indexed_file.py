"""Tests for the ``indexed_file`` data-collection type."""

import pytest
from pydantic import ValidationError

from depictio.models.models.data_collections import DataCollection, DataCollectionConfig
from depictio.models.models.data_collections_types.indexed_file import (
    DEFAULT_INDEX_SUFFIX,
    DCIndexedFileConfig,
    indexed_file_s3_key,
    indexed_file_s3_prefix,
    sample_from_path,
)


class TestDCIndexedFileConfig:
    def test_minimal_config(self):
        cfg = DCIndexedFileConfig(format="vcf")
        assert cfg.format == "vcf"
        assert cfg.index_suffix is None
        assert cfg.effective_index_suffix == ".tbi"
        assert cfg.sample_col == "sample"
        assert cfg.max_file_size_mb == 512

    @pytest.mark.parametrize(
        ("fmt", "suffix"),
        [
            ("vcf", ".tbi"),
            ("bam", ".bai"),
            ("gff3", ".tbi"),
            ("tabix", ".tbi"),
            ("fasta", ".fai"),
            ("bigwig", ""),
            ("bigbed", ""),
        ],
    )
    def test_default_index_suffix_per_format(self, fmt, suffix):
        assert DCIndexedFileConfig(format=fmt).effective_index_suffix == suffix
        assert DEFAULT_INDEX_SUFFIX[fmt] == suffix

    def test_format_aliases_are_normalised(self):
        assert DCIndexedFileConfig(format="bigWig").format == "bigwig"
        assert DCIndexedFileConfig(format="BW").format == "bigwig"
        assert DCIndexedFileConfig(format="gff").format == "gff3"

    def test_unknown_format_rejected(self):
        with pytest.raises(ValidationError):
            DCIndexedFileConfig(format="cram")

    def test_explicit_index_suffix_wins(self):
        cfg = DCIndexedFileConfig(format="vcf", index_suffix=".csi")
        assert cfg.effective_index_suffix == ".csi"

    def test_empty_index_suffix_means_self_indexed(self):
        assert DCIndexedFileConfig(format="vcf", index_suffix="").effective_index_suffix == ""

    def test_index_suffix_must_start_with_dot(self):
        with pytest.raises(ValidationError):
            DCIndexedFileConfig(format="vcf", index_suffix="tbi")

    def test_index_suffix_rejects_path_separator(self):
        with pytest.raises(ValidationError):
            DCIndexedFileConfig(format="vcf", index_suffix="./x/y")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DCIndexedFileConfig(format="vcf", unknown_field=1)

    def test_round_trip(self):
        cfg = DCIndexedFileConfig(
            format="bigwig",
            sample_regex=r"(?P<sample>[^/]+)\.bigWig$",
            sample_col="sample_id",
            assembly="hg38",
            max_file_size_mb=64,
        )
        assert DCIndexedFileConfig(**cfg.model_dump()) == cfg


class TestS3Keys:
    def test_prefix_is_not_a_bucket_root_object_id(self):
        # The orphan cleanup deletes 24-hex top-level prefixes without a
        # deltatable document, so indexed files must not live at the root.
        prefix = indexed_file_s3_prefix("646b0f3c1e4a2d7f8e5b8d00", "NA12878")
        assert prefix.startswith("indexed_files/")

    def test_key_shape(self):
        key = indexed_file_s3_key("646b0f3c1e4a2d7f8e5b8d00", "NA12878", "NA12878.vcf.gz")
        assert key == "indexed_files/646b0f3c1e4a2d7f8e5b8d00/NA12878/NA12878.vcf.gz"

    @pytest.mark.parametrize("name", ["../escape.vcf.gz", "a/b.vcf.gz", "", ".", ".."])
    def test_key_rejects_traversal_in_name(self, name):
        with pytest.raises(ValueError):
            indexed_file_s3_key("646b0f3c1e4a2d7f8e5b8d00", "NA12878", name)

    @pytest.mark.parametrize("sample", ["../escape", "a/b", "", ".."])
    def test_key_rejects_traversal_in_sample(self, sample):
        with pytest.raises(ValueError):
            indexed_file_s3_key("646b0f3c1e4a2d7f8e5b8d00", sample, "x.vcf.gz")


class TestSampleFromPath:
    def test_strips_format_and_compression_suffix(self):
        assert sample_from_path("/data/run1/NA12878.vcf.gz") == "NA12878"
        assert sample_from_path("/data/run1/S1.bigWig") == "S1"
        assert sample_from_path("/data/run1/S1.bam") == "S1"
        assert sample_from_path("/data/run1/genes.gff3.gz") == "genes"

    def test_regex_named_group_wins(self):
        path = "/data/variant_calling/haplotypecaller/HCC1395T/HCC1395T.filtered.vcf.gz"
        regex = r"variant_calling/[^/]+/(?P<sample>[^/]+)/"
        assert sample_from_path(path, regex) == "HCC1395T"

    def test_regex_without_named_group_falls_back(self):
        assert sample_from_path("/data/S9.vcf.gz", r"(S\d+)") == "S9"

    def test_invalid_regex_falls_back(self):
        assert sample_from_path("/data/S9.vcf.gz", r"(?P<sample>[") == "S9"

    def test_result_is_a_single_path_segment(self):
        assert "/" not in sample_from_path("/data/a b/weird name.vcf.gz")
        assert sample_from_path("/data/..vcf.gz") != ".."


class TestDataCollectionIntegration:
    def _dc(self, **overrides):
        payload = {
            "data_collection_tag": "sarek_vcf",
            "description": "Filtered VCFs with their tabix index",
            "config": {
                "type": "indexed_file",
                "metatype": "metadata",
                "scan": {
                    "mode": "recursive",
                    "scan_parameters": {
                        "regex_config": {"pattern": ".*\\.filtered\\.vcf\\.gz$"},
                    },
                },
                "dc_specific_properties": {"format": "vcf", "assembly": "hg38"},
            },
        }
        payload.update(overrides)
        return DataCollection(**payload)

    def test_indexed_file_dc_validates(self):
        dc = self._dc()
        assert dc.config.type == "indexed_file"
        assert isinstance(dc.config.dc_specific_properties, DCIndexedFileConfig)
        assert dc.config.dc_specific_properties.format == "vcf"
        assert dc.config.dc_specific_properties.assembly == "hg38"

    def test_type_is_case_insensitive(self):
        cfg = DataCollectionConfig(
            type="INDEXED_FILE",
            scan={
                "mode": "single",
                "scan_parameters": {"filename": "sample.vcf.gz"},
            },
            dc_specific_properties={"format": "vcf"},
        )
        assert cfg.type == "indexed_file"

    def test_format_is_required(self):
        with pytest.raises(ValidationError):
            DataCollectionConfig(
                type="indexed_file",
                scan={"mode": "single", "scan_parameters": {"filename": "s.vcf.gz"}},
                dc_specific_properties={},
            )

    def test_existing_types_still_validate(self):
        cfg = DataCollectionConfig(
            type="phylogeny",
            scan={"mode": "single", "scan_parameters": {"filename": "tree.nwk"}},
            dc_specific_properties={"format": "newick"},
        )
        assert cfg.type == "phylogeny"
