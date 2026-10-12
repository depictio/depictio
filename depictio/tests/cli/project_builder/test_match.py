"""Which files a data collection would ingest, and whether they agree with each other."""

from __future__ import annotations

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot, data_root_for
from depictio.project_builder import match
from depictio.project_builder.assemble import (
    DcDraft,
    GeoJSONProps,
    ImageProps,
    IndexedFileProps,
    MultiQCProps,
    PhylogenyProps,
    TableProps,
)
from depictio.project_builder.errors import BuilderRefused

from ..s3_stubs import S3_KEY_PREFIX, S3_ROOT, install_s3_listing, s3_cli_config, write_tree
from ._fixtures import QUANT, RUN_TREE, scan_dc, table_dc

RESULT_KEYS = {
    "regex",
    "files",
    "count",
    "runs",
    "truncated",
    "schema",
    "consistent",
    "mismatches",
    "missing_indexes",
    "warnings",
}

# A tree for the bounds: the same file name at every depth, and where a run would be.
BOUNDS_TREE = {
    "quant.tsv": QUANT,
    "star/S1/quant.tsv": QUANT,
    "star/S2/deep/nested/quant.tsv": QUANT,
    "work/ab/cd/quant.tsv": QUANT,
    "run_1/quant.tsv": QUANT,
    "run_1/star/S1/quant.tsv": QUANT,
    "run_2/quant.tsv": QUANT,
    "logs/quant.tsv": QUANT,
}


def _match(root, dc, structure="flat", runs_regex=None):
    return match.match_collection(root, structure, runs_regex, dc)


# ── a single file ────────────────────────────────────────────────────────────


class TestSingleFile:
    def test_a_file_that_is_there(self, root):
        result = _match(root, table_dc(path="samplesheet.csv"))
        assert set(result) == RESULT_KEYS
        assert result["regex"] is None
        assert result["files"] == ["samplesheet.csv"]
        assert result["count"] == 1
        assert result["runs"] == []
        assert result["truncated"] is False
        assert result["schema"] == {"sample": "String", "condition": "String"}
        assert result["consistent"] is True
        assert result["mismatches"] == []
        assert result["missing_indexes"] == []
        assert result["warnings"] == []

    def test_a_file_that_is_not_there_yet(self, root):
        result = _match(root, table_dc(path="not/yet.csv"))
        assert result["files"] == [] and result["count"] == 0
        assert result["warnings"] == ["No file matches yet."]
        assert result["schema"] is None and result["consistent"] is None

    def test_a_path_leaving_the_root_is_refused(self, root):
        for path in ("../x.csv", "/etc/passwd", "~/x.csv"):
            with pytest.raises(BuilderRefused) as exc:
                _match(root, table_dc(path=path))
            assert (exc.value.status, exc.value.code) == (400, "builder_path_refused")

    def test_the_path_is_cleaned_before_it_is_looked_up(self, root):
        assert _match(root, table_dc(path="star//S1/./quant.tsv"))["files"] == ["star/S1/quant.tsv"]

    def test_a_single_multiqc_parquet_is_a_recursive_match_of_that_path(self, root):
        rel = "multiqc/multiqc_data/multiqc.parquet"
        dc = DcDraft(tag="mqc", type="multiqc", mode="single", path=rel, props=MultiQCProps())
        result = _match(root, dc)
        assert result["files"] == [rel]
        assert result["regex"] is not None
        assert result["schema"] is None and result["consistent"] is None

    def test_one_file_types_have_no_schema_to_compare(self, root):
        geojson = DcDraft(
            tag="areas",
            type="geojson",
            mode="single",
            path="regions/areas.geojson",
            props=GeoJSONProps(),
        )
        tree = DcDraft(
            tag="tree",
            type="phylogeny",
            mode="single",
            path="trees/tree.nwk",
            props=PhylogenyProps(),
        )
        for dc in (geojson, tree):
            result = _match(root, dc)
            assert result["count"] == 1
            assert (result["schema"], result["consistent"], result["mismatches"]) == (
                None,
                None,
                [],
            )

    def test_an_image_collection_reads_its_table(self, root):
        dc = DcDraft(
            tag="imgs",
            type="image",
            mode="single",
            path="images.csv",
            props=ImageProps(image_column="img"),
        )
        result = _match(root, dc)
        assert result["schema"] == {"sample": "String", "img": "String"}
        assert result["consistent"] is True


# ── a recursive scan ─────────────────────────────────────────────────────────


class TestRecursive:
    def test_the_scan_regex_picks_the_files_sorted(self, root):
        result = _match(root, scan_dc(regex=r"^quant\.tsv$"))
        assert result["regex"] == r"^quant\.tsv$"
        assert result["files"] == ["star/S1/quant.tsv", "star/S2/quant.tsv", "star/S3/quant.tsv"]
        assert result["count"] == 3
        assert result["warnings"] == []
        assert result["schema"] == {"gene": "String", "count": "Int64"}
        assert result["consistent"] is True
        assert result["mismatches"] == []

    def test_a_regex_over_the_path_picks_by_folder(self, root):
        result = _match(root, scan_dc(regex=r"^star/S[12]/quant\.tsv$"))
        assert result["files"] == ["star/S1/quant.tsv", "star/S2/quant.tsv"]

    def test_the_scan_is_the_same_walk_the_preview_and_ingest_make(self, root, run_dir):
        from depictio.cli.cli.utils.template_preview import scan_dc_hits
        from depictio.project_builder.assemble import dc_config

        dc = scan_dc(regex=r"^quant\.tsv$", max_depth=2, ignore=["S3"])
        assert _match(root, dc)["files"] == sorted(scan_dc_hits(dc_config(dc), root, []) or [])

    def test_a_rule_that_matches_nothing(self, root):
        result = _match(root, scan_dc(regex=r"^nothing\.tsv$"))
        assert result["files"] == [] and result["count"] == 0
        assert result["warnings"] == ["No file matches yet."]
        assert result["schema"] is None and result["consistent"] is None

    def test_a_recursive_scan_given_only_a_path_matches_that_path(self, root):
        dc = DcDraft(
            tag="q",
            type="table",
            mode="recursive",
            path="star/S1/quant.tsv",
            props=TableProps(format="tsv", separator="\t"),
        )
        assert _match(root, dc)["files"] == ["star/S1/quant.tsv"]

    def test_an_invalid_regex_is_a_400(self, root):
        with pytest.raises(BuilderRefused) as exc:
            _match(root, scan_dc(regex="("))
        assert (exc.value.status, exc.value.code) == (400, "regex_invalid")
        assert exc.value.detail.startswith("Invalid regex:")


class TestBounds:
    @pytest.fixture
    def bounded(self, tmp_path):
        return LocalDataRoot(str(write_tree(tmp_path / "results", BOUNDS_TREE)))

    @pytest.mark.parametrize(
        ("bounds", "expected"),
        [
            ({}, set(BOUNDS_TREE)),
            ({"max_depth": 0}, {"quant.tsv"}),
            (
                {"max_depth": 1},
                {"quant.tsv", "run_1/quant.tsv", "run_2/quant.tsv", "logs/quant.tsv"},
            ),
            (
                {"max_depth": 2},
                {
                    "quant.tsv",
                    "run_1/quant.tsv",
                    "run_2/quant.tsv",
                    "logs/quant.tsv",
                    "star/S1/quant.tsv",
                    "run_1/star/S1/quant.tsv",
                }
                - {"run_1/star/S1/quant.tsv"},
            ),
            ({"ignore": ["work"]}, set(BOUNDS_TREE) - {"work/ab/cd/quant.tsv"}),
            (
                {"ignore": ["work", "logs"]},
                set(BOUNDS_TREE) - {"work/ab/cd/quant.tsv", "logs/quant.tsv"},
            ),
            (
                {"max_depth": 1, "ignore": ["logs"]},
                {"quant.tsv", "run_1/quant.tsv", "run_2/quant.tsv"},
            ),
        ],
    )
    def test_a_local_scan_applies_its_bounds(self, bounded, bounds, expected):
        result = _match(bounded, scan_dc(**bounds))
        assert set(result["files"]) == expected
        assert result["warnings"] == []

    def test_sequencing_runs_are_scanned_one_run_at_a_time(self, bounded):
        result = _match(bounded, scan_dc(), "sequencing-runs", r"^run_\d$")
        assert result["runs"] == ["run_1", "run_2"]
        assert result["files"] == [
            "run_1/quant.tsv",
            "run_1/star/S1/quant.tsv",
            "run_2/quant.tsv",
        ]

    def test_a_depth_bound_counts_from_each_run_folder(self, bounded):
        result = _match(bounded, scan_dc(max_depth=0), "sequencing-runs", r"^run_\d$")
        assert result["files"] == ["run_1/quant.tsv", "run_2/quant.tsv"]

    def test_a_runs_regex_matching_no_folder_finds_no_runs(self, bounded):
        assert _match(bounded, scan_dc(), "sequencing-runs", r"^batch_")["runs"] == []

    def test_a_runs_regex_matching_no_folder_lists_no_file(self, bounded):
        result = _match(bounded, scan_dc(), "sequencing-runs", r"^batch_")
        assert result["files"] == [] and result["count"] == 0

    def test_flat_ignores_a_runs_regex_it_was_handed(self, bounded):
        result = _match(bounded, scan_dc(), "flat", r"^run_")
        assert result["runs"] == [] and result["count"] == len(BOUNDS_TREE)

    def test_sequencing_runs_need_a_runs_regex(self, bounded):
        for runs_regex in (None, ""):
            with pytest.raises(BuilderRefused) as exc:
                _match(bounded, scan_dc(), "sequencing-runs", runs_regex)
            assert (exc.value.status, exc.value.code) == (400, "runs_regex_missing")

    def test_the_runs_regex_must_compile(self, bounded):
        with pytest.raises(BuilderRefused) as exc:
            _match(bounded, scan_dc(), "sequencing-runs", "run_(")
        assert (exc.value.status, exc.value.code) == (400, "runs_regex_invalid")


class TestBuilderOwnFolder:
    def test_a_rule_that_reaches_into_the_bundle_folder_says_so(self, tmp_path):
        base = write_tree(
            tmp_path / "results",
            {"data/a.tsv": QUANT, ".depictio/template/a.tsv": QUANT},
        )
        result = _match(LocalDataRoot(str(base)), scan_dc(regex=r".*\.tsv$"))
        assert ".depictio/template/a.tsv" in result["files"]
        assert result["warnings"] == [
            "The rule also matches files under .depictio/, where the builder writes its template."
        ]

    def test_a_rule_that_stays_out_of_it_has_no_such_warning(self, root):
        assert _match(root, scan_dc())["warnings"] == []


# ── schemas ──────────────────────────────────────────────────────────────────


class TestSchemas:
    @pytest.fixture
    def drifting(self, tmp_path):
        """Four tables: a reference, one missing a column, one with an extra one, one retyped."""
        base = write_tree(
            tmp_path / "tables",
            {
                "s/a.tsv": b"gene\tcount\nA\t1\n",
                "s/b.tsv": b"gene\nA\n",
                "s/c.tsv": b"gene\tcount\textra\nA\t1\tx\n",
                "s/d.tsv": b"gene\tcount\nA\t1.5\n",
            },
        )
        return LocalDataRoot(str(base))

    def test_the_first_file_is_the_reference_and_each_difference_is_named(self, drifting):
        result = _match(drifting, scan_dc(regex=r".*\.tsv$"))
        assert result["files"] == ["s/a.tsv", "s/b.tsv", "s/c.tsv", "s/d.tsv"]
        assert result["schema"] == {"gene": "String", "count": "Int64"}
        assert result["consistent"] is False
        assert result["mismatches"] == [
            {"file": "s/b.tsv", "missing": ["count"], "extra": [], "changed": {}},
            {"file": "s/c.tsv", "missing": [], "extra": ["extra"], "changed": {}},
            {
                "file": "s/d.tsv",
                "missing": [],
                "extra": [],
                "changed": {"count": ["Int64", "Float64"]},
            },
        ]

    def test_a_file_that_differs_in_all_three_ways_is_one_mismatch(self, tmp_path):
        base = write_tree(
            tmp_path / "t",
            {"a.tsv": b"gene\tcount\tkeep\nA\t1\t2\n", "b.tsv": b"gene\tother\tkeep\nA\tx\t2.5\n"},
        )
        (mismatch,) = _match(LocalDataRoot(str(base)), scan_dc(regex=r".*\.tsv$"))["mismatches"]
        assert mismatch == {
            "file": "b.tsv",
            "missing": ["count"],
            "extra": ["other"],
            "changed": {"keep": ["Int64", "Float64"]},
        }

    def test_the_same_columns_in_another_order_agree(self, tmp_path):
        base = write_tree(tmp_path / "t", {"a.tsv": b"x\ty\n1\t2\n", "b.tsv": b"y\tx\n2\t1\n"})
        result = _match(LocalDataRoot(str(base)), scan_dc(regex=r".*\.tsv$"))
        assert (result["consistent"], result["mismatches"]) == (True, [])

    def test_agreeing_tables_are_consistent(self, root):
        result = _match(root, scan_dc())
        assert (result["consistent"], result["mismatches"]) == (True, [])

    def test_a_long_set_is_compared_on_a_sample_and_says_so(self, root, monkeypatch):
        monkeypatch.setattr(match, "SCHEMA_SAMPLE_LOCAL", 2)
        result = _match(root, scan_dc())
        assert result["count"] == 3
        assert result["warnings"] == ["Schemas compared on the first 2 of 3 files."]

    def test_a_set_within_the_sample_has_no_such_warning(self, root, monkeypatch):
        monkeypatch.setattr(match, "SCHEMA_SAMPLE_LOCAL", 3)
        assert _match(root, scan_dc())["warnings"] == []

    def test_a_file_that_cannot_be_read_is_left_out_of_the_comparison(self, tmp_path, monkeypatch):
        base = write_tree(
            tmp_path / "t", {"a.tsv": b"gene\tcount\nA\t1\n", "b.tsv": b"gene\tcount\nA\t2\n"}
        )
        root = LocalDataRoot(str(base))
        # Gone between the listing and the read.
        original = match.preview_root_file

        def vanishing(root_, rel, **kwargs):
            if rel == "b.tsv":
                raise FileNotFoundError(rel)
            return original(root_, rel, **kwargs)

        monkeypatch.setattr(match, "preview_root_file", vanishing)
        result = _match(root, scan_dc(regex=r".*\.tsv$"))
        assert result["count"] == 2
        assert result["schema"] == {"gene": "String", "count": "Int64"}
        assert (result["consistent"], result["mismatches"]) == (True, [])

    def test_when_nothing_can_be_read_there_is_no_schema_and_no_verdict(self, root, monkeypatch):
        def vanishing(*args, **kwargs):
            raise FileNotFoundError("gone")

        monkeypatch.setattr(match, "preview_root_file", vanishing)
        result = _match(root, scan_dc())
        assert result["count"] == 3
        assert (result["schema"], result["consistent"], result["mismatches"]) == (None, None, [])

    def test_a_file_the_server_may_not_read_is_left_out_too(self, root, monkeypatch):
        from depictio.models.local_access import LocalPathRefused

        def refused(*args, **kwargs):
            raise LocalPathRefused("outside", "local_path_outside")

        monkeypatch.setattr(match, "preview_root_file", refused)
        result = _match(root, table_dc())
        assert (result["schema"], result["consistent"]) == (None, None)


class TestListing:
    def test_files_are_listed_up_to_a_cap_but_all_counted(self, root, monkeypatch):
        monkeypatch.setattr(match, "MAX_LISTED", 2)
        result = _match(root, scan_dc())
        assert result["files"] == ["star/S1/quant.tsv", "star/S2/quant.tsv"]
        assert result["count"] == 3
        assert result["truncated"] is True

    def test_exactly_at_the_cap_is_not_truncated(self, root, monkeypatch):
        monkeypatch.setattr(match, "MAX_LISTED", 3)
        result = _match(root, scan_dc())
        assert (len(result["files"]), result["truncated"]) == (3, False)


# ── indexed files ────────────────────────────────────────────────────────────


def _indexed(**props) -> DcDraft:
    return DcDraft(
        tag="vcf",
        type="indexed_file",
        mode="recursive",
        regex=r".*\.vcf\.gz$",
        props=IndexedFileProps(**props),
    )


class TestIndexedFiles:
    def test_a_file_without_its_index_is_named(self, root):
        result = _match(root, _indexed())
        assert result["files"] == ["variants/S1.vcf.gz", "variants/S2.vcf.gz"]
        assert result["missing_indexes"] == ["variants/S2.vcf.gz"]
        # Not a table: no schema to compare.
        assert (result["schema"], result["consistent"]) == (None, None)

    def test_the_index_suffix_is_the_formats_default_unless_set(self, root):
        assert _match(root, _indexed(index_suffix=".csi"))["missing_indexes"] == [
            "variants/S1.vcf.gz",
            "variants/S2.vcf.gz",
        ]

    def test_an_empty_suffix_means_there_is_no_index_to_miss(self, root):
        assert _match(root, _indexed(index_suffix=""))["missing_indexes"] == []

    def test_a_self_indexed_format_has_none_to_miss(self, tmp_path):
        base = write_tree(tmp_path / "t", {"cov/S1.bw": b"x", "cov/S2.bw": b"x"})
        dc = DcDraft(
            tag="cov",
            type="indexed_file",
            mode="recursive",
            regex=r".*\.bw$",
            props=IndexedFileProps(format="bigwig"),
        )
        result = _match(LocalDataRoot(str(base)), dc)
        assert result["count"] == 2 and result["missing_indexes"] == []

    def test_the_default_for_bam_is_bai(self, tmp_path):
        base = write_tree(tmp_path / "t", {"a.bam": b"x", "a.bam.bai": b"x", "b.bam": b"x"})
        dc = DcDraft(
            tag="bam",
            type="indexed_file",
            mode="recursive",
            regex=r".*\.bam$",
            props=IndexedFileProps(format="bam"),
        )
        assert _match(LocalDataRoot(str(base)), dc)["missing_indexes"] == ["b.bam"]

    def test_the_other_types_never_report_indexes(self, root):
        assert _match(root, scan_dc())["missing_indexes"] == []


# ── an s3:// root ────────────────────────────────────────────────────────────


class TestS3Root:
    def test_the_listing_answers_like_a_folder(self, root, s3_root):
        for dc in (scan_dc(), table_dc(), _indexed()):
            assert _match(s3_root, dc) == _match(root, dc)

    def test_bounds_are_not_applied_and_a_warning_says_so(self, s3_root):
        bounded = _match(s3_root, scan_dc(max_depth=0))
        unbounded = _match(s3_root, scan_dc())
        assert bounded["files"] == unbounded["files"]
        assert bounded["count"] == 3
        assert bounded["warnings"] == [
            "max_depth and ignore apply to local folders only: an S3 prefix is listed whole."
        ]
        assert unbounded["warnings"] == []

    def test_ignore_is_not_applied_either(self, s3_root):
        result = _match(s3_root, scan_dc(ignore=["S1"]))
        assert "star/S1/quant.tsv" in result["files"]
        assert len(result["warnings"]) == 1

    def test_the_deep_files_a_depth_bound_would_hide_are_found(self, monkeypatch):
        install_s3_listing(monkeypatch, BOUNDS_TREE, key_prefix=S3_KEY_PREFIX)
        root = data_root_for(S3_ROOT, s3_cli_config())
        result = _match(root, scan_dc(max_depth=0))
        assert set(result["files"]) == set(BOUNDS_TREE)

    def test_the_schema_sample_is_smaller_over_the_network(self, s3_root, monkeypatch):
        monkeypatch.setattr(match, "SCHEMA_SAMPLE_REMOTE", 1)
        monkeypatch.setattr(match, "SCHEMA_SAMPLE_LOCAL", 50)
        result = _match(s3_root, scan_dc())
        assert result["warnings"] == ["Schemas compared on the first 1 of 3 files."]

    def test_sequencing_runs_over_a_prefix(self, monkeypatch):
        install_s3_listing(monkeypatch, BOUNDS_TREE, key_prefix=S3_KEY_PREFIX)
        root = data_root_for(S3_ROOT, s3_cli_config())
        result = _match(root, scan_dc(), "sequencing-runs", r"^run_\d$")
        assert result["runs"] == ["run_1", "run_2"]
        assert result["files"] == [
            "run_1/quant.tsv",
            "run_1/star/S1/quant.tsv",
            "run_2/quant.tsv",
        ]

    def test_a_missing_single_file_on_a_prefix(self, s3_root):
        result = _match(s3_root, table_dc(path="nope.csv"))
        assert result["warnings"] == ["No file matches yet."]

    def test_every_tree_file_is_there_to_begin_with(self, s3_root):
        assert _match(s3_root, scan_dc(regex=r".*"))["count"] == len(RUN_TREE)
