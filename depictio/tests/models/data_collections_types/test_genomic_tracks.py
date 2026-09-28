"""Unit tests for the genomic_tracks data collection and the jbrowse lite component."""

import pytest
import yaml
from pydantic import ValidationError

from depictio.models.components.lite import JBrowseLiteComponent
from depictio.models.models.dashboards import (
    _JBROWSE_DEFAULTS,
    _JBROWSE_FIELDS,
    DashboardDataLite,
)
from depictio.models.models.data_collections import DataCollectionConfig, Scan, ScanSingle
from depictio.models.models.data_collections_types.genomic_tracks import (
    TRACK_FORMATS,
    CustomAssembly,
    DCGenomicTracksConfig,
    genomic_tracks_s3_prefix,
    infer_index_uri,
    infer_track_format,
    is_bgzipped,
)


class TestDCGenomicTracksConfig:
    def test_minimal_defaults(self):
        config = DCGenomicTracksConfig(format="tsv")
        assert config.uri_column == "uri"
        assert config.format_column == "format"
        assert config.index_column == "index_uri"
        assert config.assembly == "hg38"
        assert config.s3_base_folder is None
        assert config.direct_access is False
        assert config.display_defaults == {}

    def test_manifest_format_is_normalised(self):
        assert DCGenomicTracksConfig(format="TSV").format == "tsv"

    @pytest.mark.parametrize("fmt", ["csv", "tsv", "parquet", "feather", "xls", "xlsx"])
    def test_valid_manifest_formats(self, fmt):
        assert DCGenomicTracksConfig(format=fmt).format == fmt

    def test_invalid_manifest_format(self):
        with pytest.raises(ValidationError, match="format must be one of"):
            DCGenomicTracksConfig(format="bigwig")

    def test_default_format_is_lowercased_and_checked(self):
        assert DCGenomicTracksConfig(format="csv", default_format="BigWig").default_format == (
            "bigwig"
        )
        with pytest.raises(ValidationError):
            DCGenomicTracksConfig(format="csv", default_format="wiggle")

    def test_empty_uri_column_rejected(self):
        with pytest.raises(ValidationError, match="uri_column must not be empty"):
            DCGenomicTracksConfig(format="csv", uri_column="  ")

    def test_uri_column_stripped(self):
        assert DCGenomicTracksConfig(format="csv", uri_column=" path ").uri_column == "path"

    def test_display_defaults_keys_are_track_formats(self):
        config = DCGenomicTracksConfig(
            format="csv", display_defaults={"BigWig": {"displays": [{"type": "X"}]}}
        )
        assert set(config.display_defaults) == {"bigwig"}
        with pytest.raises(ValidationError, match="display_defaults keys"):
            DCGenomicTracksConfig(format="csv", display_defaults={"wiggle": {}})

    def test_s3_base_folder_gets_trailing_slash(self):
        config = DCGenomicTracksConfig(format="csv", s3_base_folder="s3://bucket/tracks")
        assert config.s3_base_folder == "s3://bucket/tracks/"

    def test_s3_base_folder_must_be_s3(self):
        with pytest.raises(ValidationError, match="must start with 's3://'"):
            DCGenomicTracksConfig(format="csv", s3_base_folder="/local/tracks")

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            DCGenomicTracksConfig(format="csv", image_column="x")  # type: ignore[call-arg]

    def test_custom_assembly(self):
        config = DCGenomicTracksConfig(
            format="csv", assembly={"name": "MN908947.3", "fasta_uri": "ref/genome.fa"}
        )
        assert isinstance(config.assembly, CustomAssembly)
        assert config.assembly.fasta_uri == "ref/genome.fa"

    def test_custom_assembly_needs_fasta_or_twobit(self):
        with pytest.raises(ValidationError, match="fasta_uri or twobit_uri"):
            CustomAssembly(name="x")
        assert CustomAssembly(name="x", twobit_uri="x.2bit").twobit_uri == "x.2bit"

    def test_custom_assembly_forbids_extra(self):
        with pytest.raises(ValidationError):
            CustomAssembly(name="x", fasta_uri="a.fa", sequence="a.fa")  # type: ignore[call-arg]

    def test_s3_prefix_is_not_an_objectid_prefix(self):
        prefix = genomic_tracks_s3_prefix("646b0f3c1e4a2d7f8e5b8ca9")
        assert prefix == "genomic_tracks/646b0f3c1e4a2d7f8e5b8ca9/"


class TestFormatInference:
    @pytest.mark.parametrize(
        "uri, fmt",
        [
            ("a.bw", "bigwig"),
            ("a.bigWig", "bigwig"),
            ("a.bb", "bigbed"),
            ("a.bed", "bed"),
            ("a.bed.gz", "bed"),
            ("a.narrowPeak", "narrowpeak"),
            ("a.narrowPeak.gz", "narrowpeak"),
            ("a.broadPeak", "broadpeak"),
            ("a.bedGraph.gz", "bedgraph"),
            ("a.vcf", "vcf"),
            ("a.vcf.gz", "vcf"),
            ("a.bam", "bam"),
            ("a.cram", "cram"),
            ("a.gff", "gff3"),
            ("a.gff3.gz", "gff3"),
            ("a.gtf", "gtf"),
            ("a.fa", "fasta"),
            ("a.fna.gz", "fasta"),
            ("https://host/x/a.bw?token=1#frag", "bigwig"),
            ("a.txt", None),
            ("a.gz", None),
        ],
    )
    def test_infer_track_format(self, uri, fmt):
        assert infer_track_format(uri) == fmt

    def test_every_inferred_format_is_a_track_format(self):
        for uri in ("a.bw", "a.bb", "a.bed", "a.vcf", "a.bam", "a.cram", "a.gtf", "a.fa"):
            assert infer_track_format(uri) in TRACK_FORMATS

    @pytest.mark.parametrize(
        "uri, fmt, index",
        [
            ("a.bam", "bam", "a.bam.bai"),
            ("a.cram", "cram", "a.cram.crai"),
            ("a.vcf.gz", "vcf", "a.vcf.gz.tbi"),
            ("a.bed.gz", "bed", "a.bed.gz.tbi"),
            ("a.gff3.gz", "gff3", "a.gff3.gz.tbi"),
            ("a.fa", "fasta", "a.fa.fai"),
            ("a.fa.gz", "fasta", "a.fa.gz.fai"),
            ("a.bed", "bed", None),
            ("a.vcf", "vcf", None),
            ("a.bw", "bigwig", None),
            ("a.bb", "bigbed", None),
            ("https://h/a.bam?sig=1", "bam", "https://h/a.bam.bai?sig=1"),
        ],
    )
    def test_infer_index_uri(self, uri, fmt, index):
        assert infer_index_uri(uri, fmt) == index

    def test_is_bgzipped_ignores_query(self):
        assert is_bgzipped("https://h/a.vcf.gz?x=1")
        assert not is_bgzipped("a.vcf")


class TestDataCollectionDispatch:
    def _config(self, props):
        return DataCollectionConfig(
            type="genomic_tracks",
            scan=Scan(mode="single", scan_parameters=ScanSingle(filename="tracks.tsv")),
            dc_specific_properties=props,  # type: ignore[arg-type]
        )

    def test_dict_becomes_tracks_config(self):
        config = self._config({"format": "tsv", "sample_column": "cell"})
        assert config.type == "genomic_tracks"
        assert isinstance(config.dc_specific_properties, DCGenomicTracksConfig)
        assert config.dc_specific_properties.sample_column == "cell"

    def test_type_case_insensitive(self):
        config = DataCollectionConfig(
            type="Genomic_Tracks",
            scan=Scan(mode="single", scan_parameters=ScanSingle(filename="t.csv")),
            dc_specific_properties={"format": "csv"},  # type: ignore[arg-type]
        )
        assert isinstance(config.dc_specific_properties, DCGenomicTracksConfig)

    def test_invalid_props_raise(self):
        with pytest.raises(ValidationError):
            self._config({"format": "csv", "display_defaults": {"nope": {}}})

    def test_scan_required(self):
        with pytest.raises(ValidationError, match="scan field is required"):
            DataCollectionConfig(
                type="genomic_tracks",
                dc_specific_properties={"format": "csv"},  # type: ignore[arg-type]
            )


# --------------------------------------------------------------------------
# jbrowse lite component
# --------------------------------------------------------------------------


_JBROWSE_BASE = {
    "tag": "genome",
    "component_type": "jbrowse",
    "workflow_tag": "wf/x",
    "data_collection_tag": "tracks",
}


class TestJBrowseLiteComponent:
    def test_defaults(self):
        comp = JBrowseLiteComponent(tag="g", workflow_tag="wf", data_collection_tag="t")
        assert comp.component_type == "jbrowse"
        assert comp.track_mode == "filtered"
        assert comp.max_tracks == 20
        assert comp.initial_tracks == 5
        assert comp.default_tracks == []
        assert comp.show_annotation is True
        assert comp.selection_enabled is False
        assert comp.selection_mode == "feature_click"
        assert comp.track_labels == "offset"
        assert comp.config_overrides == {}

    def test_defaults_table_matches_model(self):
        assert set(_JBROWSE_DEFAULTS) == set(_JBROWSE_FIELDS)
        assert _JBROWSE_DEFAULTS["max_tracks"] == 20
        assert _JBROWSE_DEFAULTS["default_tracks"] == []

    def test_bounds(self):
        with pytest.raises(ValidationError):
            JBrowseLiteComponent(tag="g", workflow_tag="w", data_collection_tag="t", max_tracks=0)
        with pytest.raises(ValidationError):
            JBrowseLiteComponent(
                tag="g", workflow_tag="w", data_collection_tag="t", track_mode="some"
            )

    def test_locus_from(self):
        comp = JBrowseLiteComponent(
            tag="g",
            workflow_tag="w",
            data_collection_tag="t",
            locus_from={
                "data_collection_tag": "calls",
                "chrom_column": "chrom",
                "start_column": "start",
            },
        )
        assert comp.locus_from is not None
        assert comp.locus_from.padding == 5000


def _full_jbrowse(**fields) -> dict:
    comp = {
        "index": "jb-1",
        "component_type": "jbrowse",
        "wf_id": "wf",
        "dc_id": "dc",
        **_JBROWSE_DEFAULTS,
    }
    comp.update(fields)
    return comp


def _lite_from_full(comp: dict) -> DashboardDataLite:
    return DashboardDataLite.from_full(
        {
            "dashboard_id": "d1",
            "title": "T",
            "project_id": "p1",
            "version": "1.0.0",
            "stored_metadata": [comp],
        }
    )


def _as_dict(comp) -> dict:
    return comp if isinstance(comp, dict) else comp.model_dump(exclude_unset=True)


class TestJBrowseDashboardRoundTrip:
    def test_to_full_carries_every_jbrowse_field(self):
        lite = DashboardDataLite(
            version="1.0.0",
            title="t",
            project_tag="p",
            components=[{**_JBROWSE_BASE, "max_tracks": 8, "preset": "signal"}],
        )
        stored = lite.to_full()["stored_metadata"][0]
        assert stored["component_type"] == "jbrowse"
        assert stored["max_tracks"] == 8
        assert stored["preset"] == "signal"
        for field in _JBROWSE_FIELDS:
            assert field in stored
        assert stored["track_labels"] == "offset"

    def test_export_skips_defaults(self):
        comp = _as_dict(_lite_from_full(_full_jbrowse()).components[0])
        assert not (set(comp) & set(_JBROWSE_FIELDS))

    def test_export_keeps_non_defaults(self):
        overrides = {"tracks": {"t1": {"name": "Renamed"}}}
        comp = _as_dict(
            _lite_from_full(
                _full_jbrowse(
                    location="chr1:1-100",
                    max_tracks=7,
                    selection_enabled=True,
                    selection_column="cell",
                    show_overview=False,
                    config_overrides=overrides,
                )
            ).components[0]
        )
        assert comp["location"] == "chr1:1-100"
        assert comp["max_tracks"] == 7
        assert comp["selection_enabled"] is True
        assert comp["selection_column"] == "cell"
        assert comp["show_overview"] is False
        assert comp["config_overrides"] == overrides
        assert "track_mode" not in comp
        assert "initial_tracks" not in comp

    def test_yaml_round_trip(self):
        lite = DashboardDataLite(
            version="1.0.0",
            title="t",
            project_tag="p",
            components=[
                {
                    **_JBROWSE_BASE,
                    "track_mode": "all",
                    "default_tracks": ["genes"],
                    "config_overrides": {"view": {"trackLabels": "hidden"}},
                }
            ],
        )
        reimported = DashboardDataLite(**yaml.safe_load(lite.to_yaml()))
        comp = _as_dict(reimported.components[0])
        assert comp["track_mode"] == "all"
        assert comp["default_tracks"] == ["genes"]
        assert comp["config_overrides"] == {"view": {"trackLabels": "hidden"}}

    def test_full_lite_full_keeps_fields(self):
        full = _full_jbrowse(max_tracks=3, assembly="hg19", show_annotation=False)
        lite = _lite_from_full(full)
        comp = _as_dict(lite.components[0])
        assert comp["assembly"] == "hg19"
        assert comp["show_annotation"] is False
        stored = lite.to_full()["stored_metadata"][0]
        assert stored["max_tracks"] == 3
        assert stored["assembly"] == "hg19"
        assert stored["show_annotation"] is False
        assert stored["initial_tracks"] == 5
