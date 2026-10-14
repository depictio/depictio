"""Collection kinds a Depictio may not have yet: genome-browser tracks, bioimages
and tables read from a SpatialData store.

This Depictio has none of them, so each is reported unavailable and refused.
``available`` stands in for a Depictio that has them (its models' rules are
then the models' own, checked where they live): what the builder writes for
each, the rules it keeps on its own, image stores read as one thing, and the
track manifests it writes and reads back.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.project_builder import capabilities, infer, stores, tracks, tree
from depictio.project_builder.assemble import (
    BioimageProps,
    CustomAssembly,
    DcDraft,
    GenomicTracksProps,
    LinkDraft,
    SpatialDataTableSource,
    TableProps,
    build_template,
)
from depictio.project_builder.bundle import write_manifest
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.match import match_collection
from depictio.project_builder.validate import validate_inline_template

from ..s3_stubs import write_tree
from ._fixtures import project, table_dc

TRACKS_MANIFEST = (
    b"track_id\tsample\tformat\turi\tindex_uri\tname\n"
    b"t1\tS1\tbigwig\tS1.bw\t\tS1 coverage\n"
    b"t2\tS1\t\tS1.bam\t\tS1 reads\n"
    b"t3\tS2\t\tS2.bam\t\tS2 reads\n"
    b"t4\tS2\t\tS2.weird\t\tunknown\n"
    b"t5\tS3\t\tmissing.bw\t\tgone\n"
    b"t6\tS1\tbigwig\tS1.bw\t\tagain\n"
    b"t7\tS9\t\t/etc/hosts.bed\t\tabsolute\n"
    b"t8\tS9\t\ts3://bucket/k.bw\t\tremote\n"
)

IMAGING_TREE: dict[str, bytes] = {
    "stores/s1.zarr/zarr.json": b"{}",
    "stores/s1.zarr/0/c/0/0": b"chunk",
    "stores/s2.zarr/.zattrs": b"{}",
    "stores/s2.zarr/.zgroup": b"{}",
    "stores/s2.zarr/0/0.0": b"chunk",
    "stores/nested/s3.zarr/zarr.json": b"{}",
    "stores/notes.csv": b"a,b\n1,2\n",
    "skin.zarr/zarr.json": b"{}",
    "skin.zarr/images/he/zarr.json": b"{}",
    "skin.zarr/tables/table/zarr.json": b"{}",
    "skin.zarr/shapes/spots/zarr.json": b"{}",
    "lily.ome.tif": b"II*\x00",
    "plain.tif": b"II*\x00",
    "tracks/S1.bw": b"x",
    "tracks/S1.bam": b"x",
    "tracks/S1.bam.bai": b"x",
    "tracks/S2.bam": b"x",
    "tracks/peaks.bed.gz": b"x",
    "tracks/peaks.bed.gz.tbi": b"x",
    "tracks/notes.txt": b"x",
    "tracks/manifest.tsv": TRACKS_MANIFEST,
    "samples.csv": b"sample,site\nS1,a\nS2,b\n",
}


@pytest.fixture
def imaging(tmp_path):
    return LocalDataRoot(str(write_tree(tmp_path / "imaging", IMAGING_TREE)))


@pytest.fixture
def available(monkeypatch):
    """A Depictio with the three kinds; their models' own checks stand aside."""
    formats = ("bigwig", "bedgraph", "bed", "bigbed", "vcf", "bam", "cram", "gff3")
    monkeypatch.setattr(
        capabilities, "genomic_tracks_model", lambda: SimpleNamespace(TRACK_FORMATS=formats)
    )
    monkeypatch.setattr(capabilities, "bioimage_model", lambda: SimpleNamespace())
    monkeypatch.setattr(capabilities, "spatialdata_tables", lambda: True)


def _refusal(template, *, remote: bool = False) -> str:
    with pytest.raises(BuilderRefused) as exc:
        validate_inline_template(template, remote=remote)
    assert exc.value.code == "inline_template_invalid"
    return exc.value.detail


def _properties(template: dict, index: int = 0) -> dict:
    return template["workflows"][0]["data_collections"][index]["config"]["dc_specific_properties"]


def _config(template: dict, index: int = 0) -> dict:
    return template["workflows"][0]["data_collections"][index]["config"]


def _tracks(**props) -> DcDraft:
    defaults = {"format": "tsv", "separator": "\t", "sample_column": "sample"}
    return DcDraft(
        tag="tracks",
        type="genomic_tracks",
        mode="single",
        path="tracks/manifest.tsv",
        props=GenomicTracksProps(**{**defaults, **props}),
    )


def _bioimage(tag: str = "imgs", **fields) -> DcDraft:
    props = fields.pop("props", BioimageProps())
    fields.setdefault("mode", "recursive")
    if fields["mode"] == "recursive":
        fields.setdefault("regex", r"^s\d+\.zarr$")
    return DcDraft(tag=tag, type="bioimage", props=props, **fields)


def _spatial_table(**source) -> DcDraft:
    return DcDraft(
        tag="spots",
        type="table",
        mode="single",
        path="skin.zarr",
        props=TableProps(format="spatialdata", spatialdata=SpatialDataTableSource(**source)),
    )


# ── capabilities ─────────────────────────────────────────────────────────────


class TestCapabilities:
    def test_this_depictio_offers_the_core_six(self):
        offered = capabilities.capabilities("server", True)
        by_type = {entry["type"]: entry for entry in offered["dc_types"]}
        assert [t for t, entry in by_type.items() if entry["available"]] == [
            "table",
            "multiqc",
            "image",
            "indexed_file",
            "geojson",
            "phylogeny",
        ]
        assert by_type["genomic_tracks"]["reason"] == capabilities.UNAVAILABLE["genomic_tracks"]
        assert by_type["bioimage"]["reason"] == capabilities.UNAVAILABLE["bioimage"]
        assert offered["genomic_tracks"] is None and offered["bioimage"] is None
        assert offered["table_formats"] == ["csv", "tsv", "parquet", "feather", "xls", "xlsx"]
        assert offered["link_target_types"] == ["table", "multiqc", "image"]
        assert "skip_rows" in offered["reader_options"]

    @pytest.mark.parametrize(
        ("mode", "events", "expected"),
        [
            ("server", True, {"events_enabled": True, "reason": None}),
            ("server", False, {"events_enabled": False, "reason": capabilities.EVENTS_OFF}),
            ("standalone", None, {"events_enabled": None, "reason": capabilities.EVENTS_UNKNOWN}),
        ],
    )
    def test_realtime_says_what_the_instance_does_with_it(self, mode, events, expected):
        assert capabilities.capabilities(mode, events)["realtime"] == expected
        assert capabilities.capabilities(mode, events)["mode"] == mode

    def test_a_depictio_with_the_new_kinds_offers_them(self, available):
        offered = capabilities.capabilities("standalone", None)
        assert all(entry["available"] for entry in offered["dc_types"])
        assert offered["table_formats"][-1] == "spatialdata"
        # The presets live in the API: the standalone builder takes any name.
        assert offered["genomic_tracks"]["assemblies"] == []
        assert "bigwig" in offered["genomic_tracks"]["track_formats"]
        assert offered["bioimage"] == {"formats": ["ome-zarr", "ome-tiff", "spatialdata"]}

    def test_the_models_are_looked_for_not_assumed(self):
        assert capabilities.genomic_tracks_model() is None
        assert capabilities.bioimage_model() is None
        assert capabilities.spatialdata_tables() is False


# ── unavailable here ─────────────────────────────────────────────────────────


class TestUnavailable:
    def test_genomic_tracks_are_refused_with_the_reason(self):
        detail = _refusal(build_template(project(_tracks())))
        assert detail == f"'tracks': {capabilities.UNAVAILABLE['genomic_tracks']}"

    def test_bioimages_are_refused_with_the_reason(self):
        detail = _refusal(build_template(project(_bioimage())))
        assert detail == f"'imgs': {capabilities.UNAVAILABLE['bioimage']}"

    def test_a_spatialdata_table_is_refused(self):
        detail = _refusal(build_template(project(_spatial_table())))
        assert "no tables read from SpatialData stores yet" in detail

    def test_a_track_file_stays_an_indexed_file(self, imaging):
        suggestion = infer.suggest(imaging, "tracks/S1.bam")
        assert suggestion["type"] == "indexed_file"
        assert suggestion["tracks"] is None

    def test_a_store_is_a_bioimage_with_the_reason(self, imaging):
        suggestion = infer.suggest(imaging, "stores/s1.zarr")
        assert suggestion["type"] == "bioimage"
        assert suggestion["warnings"] == [capabilities.UNAVAILABLE["bioimage"]]


# ── genomic tracks ───────────────────────────────────────────────────────────


class TestGenomicTracks:
    def test_a_local_manifest_is_written_as_the_model_reads_it(self, available):
        template = build_template(
            project(_tracks(track_id_column="track_id", default_format="bigwig"))
        )
        config = _config(template)
        assert (config["type"], config["metatype"]) == ("genomic_tracks", "Metadata")
        assert config["scan"] == {
            "mode": "single",
            "scan_parameters": {"filename": "{DATA_ROOT}/tracks/manifest.tsv"},
        }
        assert config["dc_specific_properties"] == {
            "format": "tsv",
            "polars_kwargs": {"separator": "\t"},
            "uri_column": "uri",
            "sample_column": "sample",
            "track_id_column": "track_id",
            "default_format": "bigwig",
            "assembly": "hg38",
        }
        assert validate_inline_template(template, remote=False) == []

    def test_a_tracks_folder_is_written_under_the_root(self, available):
        template = build_template(project(_tracks(tracks_base_path="")))
        assert _properties(template)["tracks_base_path"] == "{DATA_ROOT}"

    def test_under_an_s3_root_tracks_are_read_in_place(self, available):
        template = build_template(project(_tracks()), remote=True)
        properties = _properties(template)
        assert properties["remote_base_uri"] == "{DATA_ROOT}/tracks/"
        assert "tracks_base_path" not in properties
        warnings = validate_inline_template(template, remote=True)
        assert any("DEPICTIO_JBROWSE_REMOTE_S3_BUCKETS" in w for w in warnings)

    def test_a_remote_base_is_the_root_or_under_it(self, available):
        template = build_template(project(_tracks()), remote=True)
        _properties(template)["remote_base_uri"] = "s3://elsewhere/tracks/"
        assert "remote_base_uri must be a path under {DATA_ROOT}" in _refusal(template, remote=True)
        del _properties(template)["remote_base_uri"]
        assert "remote_base_uri says where tracks are" in _refusal(template, remote=True)

    def test_each_root_keeps_its_own_base(self, available):
        local = build_template(project(_tracks(tracks_base_path="results")))
        _properties(local)["remote_base_uri"] = "{DATA_ROOT}/"
        assert "remote_base_uri is for an s3:// root" in _refusal(local)
        remote = build_template(project(_tracks(tracks_base_path="results")), remote=True)
        _properties(remote)["tracks_base_path"] = "{DATA_ROOT}/results"
        assert "read in place" in _refusal(remote, remote=True)

    def test_a_custom_assembly_reads_files_of_the_root_or_urls(self, available):
        assembly = CustomAssembly(
            name="sars-cov-2",
            twobit_uri="ref/genome.2bit",
            chrom_sizes_uri="https://example.org/chrom.sizes",
            aliases=["MN908947.3"],
        )
        template = build_template(project(_tracks(assembly=assembly)))
        assert _properties(template)["assembly"] == {
            "name": "sars-cov-2",
            "aliases": ["MN908947.3"],
            "twobit_uri": "{DATA_ROOT}/ref/genome.2bit",
            "chrom_sizes_uri": "https://example.org/chrom.sizes",
        }
        assert validate_inline_template(template, remote=False) == []

    @pytest.mark.parametrize(
        ("assembly", "message"),
        [
            ({"name": "x"}, "needs a FASTA or a 2bit file"),
            ({"name": "x", "fasta_uri": "/etc/genome.fa"}, "must be a path under {DATA_ROOT}"),
            ({"name": "x", "fasta_uri": "file:///g.fa"}, "must be a path under {DATA_ROOT}"),
            ({"name": "x", "twobit_uri": "{DATA_ROOT}/../g.2bit"}, "may not contain '..'"),
            (3, "a preset name or a custom assembly"),
        ],
    )
    def test_the_assembly_rules(self, available, assembly, message):
        template = build_template(project(_tracks()))
        _properties(template)["assembly"] = assembly
        assert message in _refusal(template)

    def test_an_unknown_preset_is_a_warning_where_the_presets_are_known(
        self, available, monkeypatch
    ):
        monkeypatch.setattr(capabilities, "assemblies", lambda: ["hg38", "mm10"])
        template = build_template(project(_tracks(assembly="GRCh38")))
        assert any(
            "is not one of this server's assemblies" in w
            for w in validate_inline_template(template, remote=False)
        )
        ok = build_template(project(_tracks(assembly="HG38")))
        assert validate_inline_template(ok, remote=False) == []

    def test_settings_the_builder_never_writes_are_refused(self, available):
        template = build_template(project(_tracks()))
        _properties(template)["direct_access"] = True
        assert "unexpected genomic track settings: direct_access" in _refusal(template)

    def test_a_default_format_must_be_a_track_format(self, available):
        template = build_template(project(_tracks(default_format="hic")))
        assert "default_format must be one of" in _refusal(template)

    def test_a_link_can_target_tracks_where_links_can(self, available, monkeypatch):
        monkeypatch.setattr(
            capabilities,
            "link_target_types",
            lambda: ["table", "multiqc", "image", "genomic_tracks"],
        )
        draft = project(table_dc("samples", path="samples.csv"), _tracks())
        draft.links = [LinkDraft(source_tag="samples", source_column="sample", target_tag="tracks")]
        template = build_template(draft)
        assert template["links"][0]["target_type"] == "genomic_tracks"
        # The target field defaults to the manifest's sample column.
        assert template["links"][0]["link_config"] == {
            "resolver": "direct",
            "target_field": "sample",
        }

    def test_this_depictio_links_no_tracks(self, available):
        draft = project(table_dc("samples", path="samples.csv"), _tracks())
        draft.links = [LinkDraft(source_tag="samples", source_column="sample", target_tag="tracks")]
        assert "can't filter a genomic_tracks collection" in _refusal(build_template(draft))

    def test_match_reads_the_manifest_back(self, imaging):
        found = match_collection(imaging, "flat", None, _tracks(tracks_base_path=None))
        assert found["files"] == ["tracks/manifest.tsv"]
        assert found["schema"]["uri"] == "String"
        checks = found["tracks"]
        assert checks["rows"] == 8
        assert checks["missing_uri_column"] is False
        assert checks["unknown_format"] == ["S2.weird"]
        assert checks["duplicate_uris"] == ["S1.bw"]
        assert checks["missing_files"] == ["missing.bw"]
        assert checks["missing_indexes"] == ["S2.bam"]
        assert checks["absolute_uris"] == ["/etc/hosts.bed"]

    def test_track_files_are_not_read_as_a_manifest(self, imaging):
        dc = DcDraft(
            tag="tracks",
            type="genomic_tracks",
            mode="recursive",
            regex=r"^tracks/S\d\.bam$",
            props=GenomicTracksProps(),
        )
        found = match_collection(imaging, "flat", None, dc)
        assert found["files"] == ["tracks/S1.bam", "tracks/S2.bam"]
        assert found["tracks"] is None
        assert any("reads a manifest listing them" in w for w in found["warnings"])

    def test_a_manifest_without_the_uri_column_says_so(self, imaging):
        found = match_collection(imaging, "flat", None, _tracks(uri_column="path"))
        assert found["tracks"]["missing_uri_column"] is True

    def test_relative_uris_resolve_against_the_tracks_folder(self, imaging):
        found = match_collection(imaging, "flat", None, _tracks(tracks_base_path="elsewhere"))
        assert "S1.bw" in found["tracks"]["missing_files"]

    def test_a_suggestion_for_a_track_file_where_tracks_exist(self, imaging, available):
        suggestion = infer.suggest(imaging, "tracks/S1.bam")
        assert suggestion["type"] == "genomic_tracks"
        assert suggestion["tracks"] == {"format": "bam", "index": "tracks/S1.bam.bai"}
        assert infer.suggest(imaging, "tracks/S2.bam")["tracks"]["index"] is None


class TestTrackManifest:
    def test_picked_tracks_become_rows_relative_to_the_root(self, imaging):
        made = tracks.manifest_for(
            imaging,
            [
                "tracks/S1.bw",
                "tracks/S1.bam",
                "tracks/S1.bam.bai",
                "tracks/peaks.bed.gz",
                "tracks/notes.txt",
            ],
        )
        assert made["columns"] == list(tracks.MANIFEST_COLUMNS)
        assert made["rows"] == [
            {
                "track_id": "s1",
                "sample": "S1",
                "format": "bigwig",
                "uri": "tracks/S1.bw",
                "index_uri": "",
                "name": "S1",
            },
            {
                "track_id": "s1_2",
                "sample": "S1",
                "format": "bam",
                "uri": "tracks/S1.bam",
                "index_uri": "tracks/S1.bam.bai",
                "name": "S1",
            },
            {
                "track_id": "peaks",
                "sample": "peaks",
                "format": "bed",
                "uri": "tracks/peaks.bed.gz",
                "index_uri": "tracks/peaks.bed.gz.tbi",
                "name": "peaks",
            },
        ]
        assert made["tsv"].splitlines()[0] == "track_id\tsample\tformat\turi\tindex_uri\tname"
        assert made["warnings"] == ["1 file(s) of no known track format left out: tracks/notes.txt"]

    def test_a_track_without_its_index_is_flagged(self, imaging):
        made = tracks.manifest_for(imaging, ["tracks/S2.bam"])
        assert made["rows"][0]["index_uri"] == ""
        assert "need an index" in made["warnings"][0]

    def test_the_sample_regex_names_the_sample(self, imaging):
        made = tracks.manifest_for(imaging, ["tracks/S1.bam"], r"(?P<sample>S\d+)\.bam$")
        assert made["rows"][0]["sample"] == "S1"

    @pytest.mark.parametrize(
        ("files", "regex", "code"),
        [
            ([], None, "tracks_none"),
            (["tracks/notes.txt"], None, "tracks_none"),
            (["tracks/S1.bam"], "(", "sample_regex_invalid"),
            (["tracks/S1.bam"], r"S\d+", "sample_regex_invalid"),
        ],
    )
    def test_what_it_refuses(self, imaging, files, regex, code):
        with pytest.raises(BuilderRefused) as exc:
            tracks.manifest_for(imaging, files, regex)
        assert exc.value.code == code

    def test_a_track_that_is_not_there_is_a_404(self, imaging):
        with pytest.raises(BuilderRefused) as exc:
            tracks.manifest_for(imaging, ["tracks/gone.bw"])
        assert (exc.value.status, exc.value.code) == (404, "file_missing")

    def test_a_path_leaving_the_root_is_refused(self, imaging):
        with pytest.raises(BuilderRefused) as exc:
            tracks.manifest_for(imaging, ["../x.bw"])
        assert exc.value.code == "builder_path_refused"

    def test_a_written_manifest_is_matched_as_the_collection_s_manifest(self, imaging, tmp_path):
        made = tracks.manifest_for(imaging, ["tracks/S1.bw", "tracks/S1.bam"])
        bundle_dir = tmp_path / "imaging" / ".depictio" / "template"
        written = write_manifest("tracks", made["tsv"], bundle_dir, data_root=tmp_path / "imaging")
        assert written == {"path": ".depictio/template/tracks.tsv"}
        dc = DcDraft(
            tag="tracks",
            type="genomic_tracks",
            mode="single",
            path=written["path"],
            props=GenomicTracksProps(format="tsv", tracks_base_path=""),
        )
        checks = match_collection(imaging, "flat", None, dc)["tracks"]
        assert (checks["rows"], checks["missing_files"], checks["missing_indexes"]) == (2, [], [])

    def test_a_manifest_is_written_once_unless_overwritten(self, tmp_path):
        out = tmp_path / "root" / ".depictio" / "template"
        write_manifest("m", "a\n", out, data_root=tmp_path / "root")
        with pytest.raises(BuilderRefused) as exc:
            write_manifest("m", "b\n", out, data_root=tmp_path / "root")
        assert exc.value.code == "manifest_exists"
        write_manifest("m", "b\n", out, data_root=tmp_path / "root", overwrite=True)
        assert (out / "m.tsv").read_text() == "b\n"

    def test_a_template_folder_outside_the_root_cannot_hold_it(self, tmp_path):
        (tmp_path / "root").mkdir()
        with pytest.raises(BuilderRefused) as exc:
            write_manifest("m", "a\n", tmp_path / "home", data_root=tmp_path / "root")
        assert (exc.value.status, exc.value.code) == (409, "manifest_outside_root")

    def test_a_name_is_slugged_and_needed(self, tmp_path):
        out = tmp_path / "r" / "t"
        assert write_manifest("My Tracks.tsv", "a\n", out, data_root=tmp_path / "r") == {
            "path": "t/my_tracks.tsv"
        }
        with pytest.raises(BuilderRefused) as exc:
            write_manifest("../..", "a\n", out, data_root=tmp_path / "r")
        assert exc.value.code == "manifest_name_invalid"


# ── image stores ─────────────────────────────────────────────────────────────


class TestStores:
    def test_the_tree_shows_a_store_as_one_thing(self, imaging):
        entries = {e["name"]: e for e in tree.list_folder(imaging, "stores")["entries"]}
        assert entries["s1.zarr"]["store"] == "zarr"
        assert entries["nested"]["store"] is None
        assert entries["notes.csv"]["store"] is None

    def test_a_store_is_described_from_its_top_level(self, imaging):
        assert stores.describe_store(imaging, "stores/s1.zarr") == {
            "format": "ome-zarr",
            "ngff_version": "0.5",
            "images": [],
            "tables": [],
        }
        assert stores.describe_store(imaging, "stores/s2.zarr")["ngff_version"] == "0.4"
        assert stores.describe_store(imaging, "skin.zarr") == {
            "format": "spatialdata",
            "ngff_version": "0.5",
            "images": ["images/he"],
            "tables": ["tables/table"],
        }

    def test_a_store_suggestion_carries_what_it_holds(self, imaging, available):
        suggestion = infer.suggest(imaging, "skin.zarr")
        assert (suggestion["type"], suggestion["format"], suggestion["tag"]) == (
            "bioimage",
            "spatialdata",
            "skin",
        )
        assert suggestion["store"]["images"] == ["images/he"]
        assert suggestion["catalog"] == [] and suggestion["warnings"] == []

    def test_an_ome_tiff_is_a_bioimage(self, imaging, available):
        suggestion = infer.suggest(imaging, "lily.ome.tif")
        assert (suggestion["type"], suggestion["format"], suggestion["store"]) == (
            "bioimage",
            "ome-tiff",
            None,
        )
        assert infer.suggest(imaging, "plain.tif")["type"] == "table"

    def test_a_plain_folder_is_not_picked(self, imaging):
        with pytest.raises(BuilderRefused) as exc:
            infer.suggest(imaging, "stores/nested")
        assert (exc.value.status, exc.value.code) == (400, "folder_picked")

    def test_a_scan_registers_stores_never_their_chunks(self, imaging):
        found = match_collection(imaging, "flat", None, _bioimage(regex=r".*"))
        assert found["files"] == [
            "skin.zarr",
            "stores/nested/s3.zarr",
            "stores/s1.zarr",
            "stores/s2.zarr",
        ]
        assert found["stores"] is True and found["schema"] is None

    def test_the_store_regex_reads_the_name_then_the_path(self, imaging):
        by_name = match_collection(imaging, "flat", None, _bioimage(regex=r"^s\d+\.zarr$"))
        assert by_name["files"] == ["stores/nested/s3.zarr", "stores/s1.zarr", "stores/s2.zarr"]
        by_path = match_collection(imaging, "flat", None, _bioimage(regex=r"^stores/s\d+\.zarr$"))
        assert by_path["files"] == ["stores/s1.zarr", "stores/s2.zarr"]

    def test_a_single_store(self, imaging):
        found = match_collection(
            imaging, "flat", None, _bioimage(mode="single", path="skin.zarr", regex=None)
        )
        assert found["files"] == ["skin.zarr"] and found["warnings"] == []

    def test_an_ome_tiff_scan_keeps_ome_tiffs_outside_stores(self, imaging):
        dc = _bioimage(regex=r".*\.tif", props=BioimageProps(format="ome-tiff"))
        assert match_collection(imaging, "flat", None, dc)["files"] == ["lily.ome.tif"]

    def test_a_spatialdata_table_scans_stores(self, imaging):
        found = match_collection(imaging, "flat", None, _spatial_table())
        assert found["files"] == ["skin.zarr"] and found["schema"] is None

    def test_a_loose_table_regex_reaching_chunks_is_flagged(self, imaging):
        dc = DcDraft(
            tag="loose", type="table", mode="recursive", regex=r".*", props=TableProps(format="csv")
        )
        found = match_collection(imaging, "flat", None, dc)
        assert any("inside a .zarr store" in w for w in found["warnings"])

    def test_an_s3_root_is_not_scanned_for_stores(self, s3_root):
        found = match_collection(s3_root, "flat", None, _bioimage(regex=r".*"))
        assert found["files"] == []
        assert found["warnings"] == [
            "Image stores are read from a folder on this computer at ingest: an s3:// prefix "
            "can't be scanned for them."
        ]


class TestBioimage:
    def test_what_is_written_for_each_format(self, available):
        template = build_template(
            project(
                _bioimage(props=BioimageProps(ngff_version="0.4")),
                _bioimage(
                    "he",
                    mode="single",
                    path="skin.zarr",
                    props=BioimageProps(format="spatialdata", image_path="images/he", upload=False),
                ),
                _bioimage(
                    "lily",
                    mode="single",
                    path="lily.ome.tif",
                    props=BioimageProps(format="ome-tiff", ngff_version="0.5"),
                ),
            )
        )
        assert [_config(template, i) for i in range(3)] == [
            {
                "type": "bioimage",
                "scan": {
                    "mode": "recursive",
                    "scan_parameters": {"regex_config": {"pattern": r"^s\d+\.zarr$"}},
                },
                "dc_specific_properties": {
                    "format": "ome-zarr",
                    "ngff_version": "0.4",
                    "upload": True,
                },
            },
            {
                "type": "bioimage",
                "scan": {
                    "mode": "single",
                    "scan_parameters": {"filename": "{DATA_ROOT}/skin.zarr"},
                },
                "dc_specific_properties": {
                    "format": "spatialdata",
                    "upload": False,
                    "image_path": "images/he",
                },
            },
            {
                "type": "bioimage",
                "scan": {
                    "mode": "single",
                    "scan_parameters": {"filename": "{DATA_ROOT}/lily.ome.tif"},
                },
                # An OME-TIFF has no NGFF version.
                "dc_specific_properties": {"format": "ome-tiff", "upload": True},
            },
        ]
        assert validate_inline_template(template, remote=False) == []

    @pytest.mark.parametrize(
        ("properties", "message"),
        [
            ({"format": "spatialdata"}, "shows one image: images/<name>"),
            ({"format": "spatialdata", "image_path": "labels/x"}, "shows one image"),
            ({"format": "ome-zarr", "image_path": "images/he"}, "for a SpatialData store only"),
            (
                {"format": "ome-zarr", "remote_stores": ["s3://b/x.zarr"]},
                "unexpected bioimage settings",
            ),
        ],
    )
    def test_the_rules_it_keeps(self, available, properties, message):
        template = build_template(project(_bioimage()))
        _config(template)["dc_specific_properties"] = properties
        assert message in _refusal(template)

    def test_an_s3_root_is_refused(self, available):
        detail = _refusal(build_template(project(_bioimage()), remote=True), remote=True)
        assert "Image stores are read from a folder on this computer" in detail


class TestSpatialDataTable:
    def test_what_is_written(self, available):
        template = build_template(
            project(
                _spatial_table(
                    image="images/he", coordinates="obsm", genes=["g1", "g2"], layer="counts"
                )
            )
        )
        config = _config(template)
        assert (config["type"], config["metatype"]) == ("Table", "Metadata")
        assert config["dc_specific_properties"] == {
            "format": "spatialdata",
            "spatialdata": {
                "table": "tables/table",
                "image": "images/he",
                "coordinates": "obsm",
                "genes": ["g1", "g2"],
                "layer": "counts",
            },
        }
        assert validate_inline_template(template, remote=False) == []

    def test_defaults_are_left_to_the_model(self, available):
        assert _properties(build_template(project(_spatial_table())))["spatialdata"] == {
            "table": "tables/table"
        }

    def test_reader_options_and_map_columns_are_refused(self, available):
        template = build_template(project(_spatial_table()))
        _properties(template)["polars_kwargs"] = {"separator": ","}
        assert "takes no reader options or map columns" in _refusal(template)

    def test_an_s3_root_is_refused(self, available):
        template = build_template(project(_spatial_table()), remote=True)
        assert "A SpatialData store is read from a folder" in _refusal(template, remote=True)
