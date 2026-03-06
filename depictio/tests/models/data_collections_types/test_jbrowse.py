"""Unit tests for JBrowse2 Data Collection models and templates."""

import pytest
from pydantic import ValidationError

from depictio.models.models.data_collections_types.jbrowse import (
    DCJBrowse2Config,
    JBrowse2TrackType,
    MultiTrackPattern,
)
from depictio.models.models.data_collections_types.jbrowse_templates import (
    DEFAULT_ASSEMBLIES,
    JBrowse2SessionConfig,
    JBrowse2TrackConfig,
    build_session_config,
    get_track_template,
    populate_and_validate_template,
    populate_template_recursive,
)


class TestDCJBrowse2Config:
    """Test suite for DCJBrowse2Config model."""

    def test_valid_bed_config(self):
        config = DCJBrowse2Config(track_type="bed", index_extension="tbi")
        assert config.track_type == JBrowse2TrackType.BED
        assert config.assembly_name == "hg38"
        assert config.index_extension == "tbi"

    def test_valid_bigwig_config(self):
        config = DCJBrowse2Config(track_type="bigwig")
        assert config.track_type == JBrowse2TrackType.BIGWIG
        assert config.assembly_name == "hg38"

    def test_valid_multi_bigwig_config(self):
        config = DCJBrowse2Config(
            track_type="multi_bigwig",
            multi_track_pattern=MultiTrackPattern(
                group_by="sample",
                sub_track_by="strand",
                sub_track_colors={"W": "rgb(244,164,96)", "C": "rgb(102,139,139)"},
            ),
        )
        assert config.track_type == JBrowse2TrackType.MULTI_BIGWIG
        assert config.multi_track_pattern.group_by == "sample"
        assert config.multi_track_pattern.sub_track_by == "strand"

    def test_multi_bigwig_requires_pattern(self):
        with pytest.raises(ValidationError, match="multi_track_pattern is required"):
            DCJBrowse2Config(track_type="multi_bigwig")

    def test_bed_requires_index_extension(self):
        with pytest.raises(ValidationError, match="index_extension is required"):
            DCJBrowse2Config(track_type="bed", index_extension=None)

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            DCJBrowse2Config(track_type="bed", unknown_field="value")

    def test_custom_assembly(self):
        config = DCJBrowse2Config(track_type="bigwig", assembly_name="mm10")
        assert config.assembly_name == "mm10"

    def test_category_list(self):
        config = DCJBrowse2Config(
            track_type="bigwig",
            category=["Strand-seq", "Counts"],
        )
        assert config.category == ["Strand-seq", "Counts"]

    def test_display_config(self):
        config = DCJBrowse2Config(
            track_type="bigwig",
            display_config={"height": 100, "color": "red"},
        )
        assert config.display_config["height"] == 100

    def test_template_override(self):
        custom_template = {"type": "FeatureTrack", "trackId": "{trackId}"}
        config = DCJBrowse2Config(
            track_type="bed",
            jbrowse_template_override=custom_template,
        )
        assert config.jbrowse_template_override == custom_template

    def test_s3_session_location(self):
        config = DCJBrowse2Config(
            track_type="bigwig",
            s3_session_location="s3://bucket/dc123/jbrowse_session.json",
        )
        assert config.s3_session_location == "s3://bucket/dc123/jbrowse_session.json"


class TestMultiTrackPattern:
    """Test suite for MultiTrackPattern model."""

    def test_minimal(self):
        p = MultiTrackPattern(group_by="sample", sub_track_by="strand")
        assert p.group_by == "sample"
        assert p.sub_track_by == "strand"
        assert p.sub_track_colors is None

    def test_with_colors(self):
        p = MultiTrackPattern(
            group_by="sample",
            sub_track_by="condition",
            sub_track_colors={"treated": "blue", "control": "gray"},
        )
        assert p.sub_track_colors["treated"] == "blue"

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            MultiTrackPattern(group_by="x", sub_track_by="y", extra="bad")


class TestPopulateTemplate:
    """Test template population."""

    def test_simple_substitution(self):
        template = {"name": "{name}", "id": "{id}"}
        result = populate_template_recursive(template, {"name": "test", "id": "123"})
        assert result == {"name": "test", "id": "123"}

    def test_nested_substitution(self):
        template = {"outer": {"inner": "{value}"}}
        result = populate_template_recursive(template, {"value": "hello"})
        assert result["outer"]["inner"] == "hello"

    def test_list_substitution(self):
        template = ["{a}", "{b}"]
        result = populate_template_recursive(template, {"a": "1", "b": "2"})
        assert result == ["1", "2"]

    def test_non_string_passthrough(self):
        template = {"count": 42, "flag": True, "nothing": None}
        result = populate_template_recursive(template, {})
        assert result == {"count": 42, "flag": True, "nothing": None}

    def test_partial_substitution(self):
        template = {"name": "{name}", "unfilled": "{missing}"}
        result = populate_template_recursive(template, {"name": "test"})
        assert result["name"] == "test"
        assert result["unfilled"] == "{missing}"


class TestJBrowse2TrackConfig:
    """Test track config validation."""

    def test_valid_feature_track(self):
        config = JBrowse2TrackConfig(
            type="FeatureTrack",
            trackId="abc123",
            name="Test BED",
            assemblyNames=["GRCh38"],
            adapter={"type": "BedTabixAdapter"},
        )
        assert config.type == "FeatureTrack"
        assert config.trackId == "abc123"

    def test_valid_quantitative_track(self):
        config = JBrowse2TrackConfig(
            type="QuantitativeTrack",
            trackId="bw001",
            name="Test BigWig",
            assemblyNames=["GRCh38"],
            adapter={"type": "BigWigAdapter"},
        )
        assert config.type == "QuantitativeTrack"

    def test_valid_multi_quantitative_track(self):
        config = JBrowse2TrackConfig(
            type="MultiQuantitativeTrack",
            trackId="mbw001",
            name="Multi BigWig",
            assemblyNames=["GRCh38"],
            adapter={"type": "MultiWiggleAdapter", "subadapters": []},
        )
        assert config.type == "MultiQuantitativeTrack"

    def test_invalid_track_type(self):
        with pytest.raises(ValidationError, match="track type must be one of"):
            JBrowse2TrackConfig(
                type="InvalidType",
                trackId="x",
                name="x",
                assemblyNames=["GRCh38"],
                adapter={"type": "x"},
            )

    def test_empty_track_id(self):
        with pytest.raises(ValidationError, match="trackId must not be empty"):
            JBrowse2TrackConfig(
                type="FeatureTrack",
                trackId="   ",
                name="x",
                assemblyNames=["GRCh38"],
                adapter={"type": "x"},
            )

    def test_adapter_requires_type(self):
        with pytest.raises(ValidationError, match="adapter must have a 'type' key"):
            JBrowse2TrackConfig(
                type="FeatureTrack",
                trackId="x",
                name="x",
                assemblyNames=["GRCh38"],
                adapter={"location": "somewhere"},
            )

    def test_unfilled_placeholders_rejected(self):
        with pytest.raises(ValidationError, match="unfilled placeholders"):
            JBrowse2TrackConfig(
                type="FeatureTrack",
                trackId="abc",
                name="{unfilled_name}",
                assemblyNames=["GRCh38"],
                adapter={"type": "BedTabixAdapter"},
            )


class TestGetTrackTemplate:
    """Test template retrieval."""

    def test_bed_template(self):
        t = get_track_template("bed")
        assert t["type"] == "FeatureTrack"
        assert "{trackId}" in t["trackId"]

    def test_bigwig_template(self):
        t = get_track_template("bigwig")
        assert t["type"] == "QuantitativeTrack"

    def test_multi_bigwig_template(self):
        t = get_track_template("multi_bigwig")
        assert t["type"] == "MultiQuantitativeTrack"

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown track type"):
            get_track_template("vcf")

    def test_override_returns_copy(self):
        override = {"type": "CustomTrack", "trackId": "{trackId}"}
        t = get_track_template("bed", override=override)
        assert t["type"] == "CustomTrack"
        # Ensure it's a copy, not the same object
        t["type"] = "Modified"
        assert override["type"] == "CustomTrack"

    def test_template_is_deep_copy(self):
        t1 = get_track_template("bed")
        t2 = get_track_template("bed")
        t1["trackId"] = "modified"
        assert t2["trackId"] == "{trackId}"


class TestPopulateAndValidate:
    """Test combined populate + validate."""

    def test_bed_template_valid(self):
        template = get_track_template("bed")
        values = {
            "trackId": "abc123",
            "name": "test.bed.gz",
            "assemblyName": "GRCh38",
            "category": "Segmentation",
            "uri": "http://s3.example.com/test.bed.gz",
            "indexUri": "http://s3.example.com/test.bed.gz.tbi",
        }
        track = populate_and_validate_template(template, values)
        assert track.trackId == "abc123"
        assert track.type == "FeatureTrack"

    def test_bigwig_template_valid(self):
        template = get_track_template("bigwig")
        values = {
            "trackId": "bw001",
            "name": "counts.bigwig",
            "assemblyName": "GRCh38",
            "category": "Counts",
            "uri": "http://s3.example.com/counts.bigwig",
            "color": "blue",
        }
        track = populate_and_validate_template(template, values)
        assert track.trackId == "bw001"
        assert track.type == "QuantitativeTrack"

    def test_missing_placeholder_fails(self):
        template = get_track_template("bed")
        values = {
            "trackId": "abc",
            "name": "test",
            "assemblyName": "GRCh38",
            "category": "Test",
            # Missing uri and indexUri
        }
        with pytest.raises(ValidationError, match="unfilled placeholders"):
            populate_and_validate_template(template, values)


class TestBuildSessionConfig:
    """Test session config builder."""

    def test_valid_session(self):
        track = JBrowse2TrackConfig(
            type="FeatureTrack",
            trackId="t1",
            name="Track 1",
            assemblyNames=["GRCh38"],
            adapter={"type": "BedTabixAdapter"},
        )
        session = build_session_config("hg38", [track])
        assert isinstance(session, JBrowse2SessionConfig)
        assert len(session.assemblies) == 1
        assert session.assemblies[0]["name"] == "GRCh38"
        assert len(session.tracks) == 1

    def test_unknown_assembly_raises(self):
        track = JBrowse2TrackConfig(
            type="FeatureTrack",
            trackId="t1",
            name="Track 1",
            assemblyNames=["GRCh38"],
            adapter={"type": "BedTabixAdapter"},
        )
        with pytest.raises(ValueError, match="Unknown assembly"):
            build_session_config("unknown_assembly", [track])

    def test_default_assemblies_has_hg38(self):
        assert "hg38" in DEFAULT_ASSEMBLIES
        hg38 = DEFAULT_ASSEMBLIES["hg38"]
        assert hg38["name"] == "GRCh38"
        assert "sequence" in hg38
