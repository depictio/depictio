"""The builder's first guess for a picked file: type, scan rule, format and catalog matches."""

from __future__ import annotations

import re

import pytest

from depictio.cli.cli.utils.compose import glob_regex
from depictio.project_builder import infer
from depictio.project_builder.errors import BuilderRefused

from ..s3_stubs import write_tree

# ── file type and format ─────────────────────────────────────────────────────


class TestGuessType:
    @pytest.mark.parametrize(
        ("name", "dc_type"),
        [
            ("multiqc.parquet", "multiqc"),
            # Only the parquet is the MultiQC data collection; any other parquet is a table.
            ("data.parquet", "table"),
            ("multiqc_report.html", "table"),
            ("tree.nwk", "phylogeny"),
            ("tree.newick", "phylogeny"),
            ("tree.tree", "phylogeny"),
            ("tree.nex", "phylogeny"),
            ("tree.nexus", "phylogeny"),
            ("areas.geojson", "geojson"),
            ("S1.vcf.gz", "indexed_file"),
            ("calls.bcf", "table"),  # BCF is not a GenomeSpy lazy source
            ("S1.bam", "indexed_file"),
            ("cov.bw", "indexed_file"),
            ("cov.bigwig", "indexed_file"),
            ("peaks.bb", "indexed_file"),
            ("peaks.bigbed", "indexed_file"),
            ("genes.gff3.gz", "indexed_file"),
            ("genes.gff.gz", "indexed_file"),
            ("ref.fa", "indexed_file"),
            ("ref.fasta", "indexed_file"),
            ("regions.bed.gz", "indexed_file"),
            ("samplesheet.csv", "table"),
            ("quant.tsv", "table"),
            ("notes.txt", "table"),
            ("unknown.xyz", "table"),
            # Case never changes what a file is.
            ("TREE.NWK", "phylogeny"),
            ("S1.VCF.GZ", "indexed_file"),
        ],
    )
    def test_by_name(self, name, dc_type):
        assert infer.guess_type(name) == dc_type

    def test_it_guesses_every_type_but_image_which_only_the_user_picks(self):
        names = [
            "multiqc.parquet",
            "t.nwk",
            "a.geojson",
            "a.vcf.gz",
            "a.csv",
            "photo.png",
            "cells.ome.tif",
            "s1.zarr",
        ]
        guessed = {infer.guess_type(n) for n in names}
        # A track file is an indexed file by name; a genomic tracks collection
        # is offered for it only where this Depictio has one (see suggest).
        assert guessed == set(infer.DC_TYPES) - {"image", "genomic_tracks"}


class TestFormats:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("a.csv", ("csv", ",")),
            ("a.tsv", ("tsv", "\t")),
            ("a.tab", ("tsv", "\t")),
            ("a.txt", ("tsv", "\t")),
            ("a.parquet", ("parquet", None)),
            # A gzipped table is read through the suffix under the .gz.
            ("a.tsv.gz", ("tsv", "\t")),
            ("a.csv.gz", ("csv", ",")),
            ("A.CSV", ("csv", ",")),
            ("a.bin", (None, None)),
            ("a.gz", (None, None)),
            ("noextension", (None, None)),
        ],
    )
    def test_table_format(self, name, expected):
        assert infer.table_format(name) == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("S1.vcf.gz", "vcf"),
            ("S1.VCF.GZ", "vcf"),
            ("S1.bam", "bam"),
            ("cov.bw", "bigwig"),
            ("peaks.bigbed", "bigbed"),
            ("genes.gff3.gz", "gff3"),
            ("genes.gff.gz", "gff3"),
            ("ref.fasta", "fasta"),
            ("regions.bed.gz", "tabix"),
            ("samplesheet.csv", None),
            # ".gz" alone says nothing: the longest suffix has to match.
            ("notes.txt.gz", None),
        ],
    )
    def test_indexed_format(self, name, expected):
        assert infer.indexed_format(name) == expected


# ── config by example ────────────────────────────────────────────────────────


class TestAntiUnify:
    def test_nothing_to_generalise_is_an_error(self):
        with pytest.raises(ValueError, match="at least one path"):
            infer.anti_unify([])

    def test_one_example_cannot_say_what_varies_so_the_name_is_kept_at_any_depth(self):
        assert infer.anti_unify(["star/S1/quant.tsv"]) == "**/quant.tsv"
        assert infer.anti_unify(["samplesheet.csv"]) == "**/samplesheet.csv"

    def test_examples_at_one_depth_are_generalised_segment_by_segment(self):
        paths = ["star/S1/quant.tsv", "star/S2/quant.tsv", "star/S3/quant.tsv"]
        assert infer.anti_unify(paths) == "star/S*/quant.tsv"

    def test_segments_that_all_differ_become_a_bare_wildcard(self):
        assert infer.anti_unify(["a/x/1.tsv", "b/y/2.tsv"]) == "*/*/*.tsv"

    def test_identical_examples_stay_literal(self):
        assert infer.anti_unify(["a/b.tsv", "a/b.tsv"]) == "a/b.tsv"

    def test_the_common_prefix_and_suffix_of_a_segment_are_kept(self):
        assert infer.anti_unify(["S1.tsv", "S2.tsv"]) == "S*.tsv"
        assert infer.anti_unify(["x/pre_1_post.txt", "x/pre_22_post.txt"]) == "x/pre_*_post.txt"

    def test_examples_at_mixed_depths_keep_only_the_file_name_at_any_depth(self):
        assert infer.anti_unify(["quant.tsv", "star/S2/quant.tsv"]) == "**/quant.tsv"
        assert infer.anti_unify(["a/S1.tsv", "b/c/S2.tsv"]) == "**/S*.tsv"

    @pytest.mark.parametrize(
        "paths",
        [
            ["star/S1/quant.tsv"],
            ["star/S1/quant.tsv", "star/S2/quant.tsv"],
            ["quant.tsv", "star/S2/quant.tsv"],
            ["a/x/1.tsv", "b/y/2.tsv"],
        ],
    )
    def test_the_glob_matches_every_example_it_was_made_from(self, paths):
        regex = re.compile(glob_regex(infer.anti_unify(paths)))
        assert all(regex.match(path) for path in paths)

    def test_an_overlapping_prefix_and_suffix_keep_the_extension(self):
        glob = infer.anti_unify(["x/S1.tsv", "x/S11.tsv"])
        regex = re.compile(glob_regex(glob))
        assert regex.match("x/S1.tsv") and regex.match("x/S11.tsv")
        assert not regex.match("x/S1.tsv.bak")


# ── suggest ──────────────────────────────────────────────────────────────────

SUGGESTION_KEYS = {
    "path",
    "tag",
    "type",
    "mode",
    "glob",
    "regex",
    "format",
    "separator",
    "catalog",
    "multiqc",
    "store",
    "tracks",
    "path_wildcard",
    "in_run",
    "warnings",
}


class TestSuggest:
    def test_a_table_set_is_a_recursive_scan_over_the_glob_that_fits_all_of_it(self, root):
        suggestion = infer.suggest(
            root, "star/S1/quant.tsv", ["star/S2/quant.tsv", "star/S3/quant.tsv"]
        )
        assert set(suggestion) == SUGGESTION_KEYS
        assert suggestion["path"] == "star/S1/quant.tsv"
        assert suggestion["type"] == "table"
        assert suggestion["mode"] == "recursive"
        assert suggestion["glob"] == "star/S*/quant.tsv"
        assert suggestion["regex"] == glob_regex("star/S*/quant.tsv")
        assert (suggestion["format"], suggestion["separator"]) == ("tsv", "\t")
        assert suggestion["tag"] == "star_quant"
        assert suggestion["multiqc"] is False
        # The suggested regex selects the three files, not the neighbours.
        regex = re.compile(suggestion["regex"])
        assert [p for p in ("star/S1/quant.tsv", "star/S3/quant.tsv") if regex.match(p)]
        assert not regex.match("star/summary.txt")

    def test_a_lone_table_is_a_single_file_with_the_recursive_glob_ready(self, root):
        suggestion = infer.suggest(root, "samplesheet.csv")
        assert suggestion["type"] == "table"
        assert suggestion["mode"] == "single"
        assert suggestion["glob"] == "**/samplesheet.csv"
        assert suggestion["regex"] == glob_regex("**/samplesheet.csv")
        assert (suggestion["format"], suggestion["separator"]) == ("csv", ",")
        assert suggestion["tag"] == "samplesheet"

    def test_a_multiqc_parquet_is_a_recursive_scan_of_that_path(self, root):
        rel = "multiqc/multiqc_data/multiqc.parquet"
        suggestion = infer.suggest(root, rel)
        assert suggestion["type"] == "multiqc"
        assert suggestion["multiqc"] is True
        assert suggestion["mode"] == "recursive"
        assert suggestion["glob"] == rel
        assert suggestion["tag"] == "multiqc"
        assert (suggestion["format"], suggestion["separator"]) == (None, None)
        assert re.match(suggestion["regex"], rel)

    def test_a_newick_tree_is_a_single_phylogeny_file(self, root):
        suggestion = infer.suggest(root, "trees/tree.nwk")
        assert suggestion["type"] == "phylogeny"
        assert suggestion["mode"] == "single"
        assert suggestion["glob"] == "**/tree.nwk"
        assert suggestion["separator"] is None
        assert suggestion["multiqc"] is False

    def test_a_nexus_tree_suggests_its_format(self, tmp_path):
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        write_tree(tmp_path, {"trees/tree.nex": b"#NEXUS\n", "trees/tree.nwk": b"(a,b);"})
        local = LocalDataRoot(str(tmp_path))
        assert infer.suggest(local, "trees/tree.nwk")["format"] == "newick"
        assert infer.suggest(local, "trees/tree.nex")["format"] == "nexus"

    def test_an_indexed_file_is_every_file_of_its_kind_anywhere(self, root):
        suggestion = infer.suggest(root, "variants/S1.vcf.gz")
        assert suggestion["type"] == "indexed_file"
        assert suggestion["mode"] == "recursive"
        assert suggestion["glob"] == "**/*.vcf.gz"
        assert suggestion["format"] == "vcf"
        assert suggestion["separator"] is None
        regex = re.compile(suggestion["regex"])
        assert regex.match("variants/S1.vcf.gz") and regex.match("S9.vcf.gz")
        assert not regex.match("variants/S1.vcf.gz.tbi")

    def test_indexed_files_with_examples_use_the_glob_that_fits_them(self, root):
        suggestion = infer.suggest(root, "variants/S1.vcf.gz", ["variants/S2.vcf.gz"])
        assert (suggestion["mode"], suggestion["glob"]) == ("recursive", "variants/S*.vcf.gz")

    def test_a_geojson_is_a_single_file(self, root):
        suggestion = infer.suggest(root, "regions/areas.geojson")
        assert (suggestion["type"], suggestion["mode"]) == ("geojson", "single")
        assert suggestion["format"] is None

    def test_catalog_matches_have_a_stable_shape(self, root):
        catalog = infer.suggest(root, "multiqc/multiqc_data/multiqc.parquet")["catalog"]
        assert catalog, "the shipped catalog knows MultiQC's parquet"
        for entry in catalog:
            assert set(entry) == {"tool_id", "output_id", "renders"}
            assert isinstance(entry["tool_id"], str) and entry["tool_id"]
            assert isinstance(entry["output_id"], str) and entry["output_id"]
            assert isinstance(entry["renders"], list)
        # One entry per (tool, output), however many ways the output matched.
        keys = [(e["tool_id"], e["output_id"]) for e in catalog]
        assert len(keys) == len(set(keys))
        assert {e["tool_id"] for e in catalog} == {"multiqc"}

    def test_a_file_the_catalog_does_not_know_has_no_matches(self, root):
        assert infer.suggest(root, "star/S1/quant.tsv")["catalog"] == []

    def test_a_blank_example_is_ignored(self, root):
        with_blank = infer.suggest(root, "star/S1/quant.tsv", ["", "star/S2/quant.tsv"])
        assert with_blank["glob"] == "star/S*/quant.tsv"
        assert infer.suggest(root, "star/S1/quant.tsv", [""])["mode"] == "single"

    def test_the_tag_is_a_slug_of_the_file_prefixed_by_its_top_folder(self, tmp_path):
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        write_tree(
            tmp_path,
            {
                "Star Results/My Sample.1.tsv": b"a\n",
                "star/star_counts.csv.gz": b"a\n",
                "S1.tsv": b"a\n",
            },
        )
        local = LocalDataRoot(str(tmp_path))
        # The folder is added unless the file name already says it.
        assert (
            infer.suggest(local, "Star Results/My Sample.1.tsv")["tag"] == "star_results_my_sample"
        )
        assert infer.suggest(local, "star/star_counts.csv.gz")["tag"] == "star_counts"
        assert infer.suggest(local, "S1.tsv")["tag"] == "s1"

    @pytest.mark.parametrize("rel", ["", "nope.csv", "star/S9/quant.tsv"])
    def test_a_file_that_is_not_there_is_a_404(self, root, rel):
        with pytest.raises(BuilderRefused) as exc:
            infer.suggest(root, rel)
        assert (exc.value.status, exc.value.code) == (404, "file_missing")

    @pytest.mark.parametrize("rel", ["../outside.csv", "/etc/passwd", "~/x.csv", "a\x00b.csv"])
    def test_a_path_leaving_the_root_is_refused_before_it_is_looked_up(self, root, rel):
        with pytest.raises(BuilderRefused) as exc:
            infer.suggest(root, rel)
        assert (exc.value.status, exc.value.code) == (400, "builder_path_refused")

    def test_an_example_leaving_the_root_is_refused_too(self, root):
        with pytest.raises(BuilderRefused) as exc:
            infer.suggest(root, "star/S1/quant.tsv", ["../outside/quant.tsv"])
        assert exc.value.code == "builder_path_refused"

    def test_an_s3_prefix_is_suggested_for_like_a_folder(self, s3_root, root):
        for rel, examples in (
            ("star/S1/quant.tsv", ["star/S2/quant.tsv"]),
            ("samplesheet.csv", []),
            ("variants/S1.vcf.gz", []),
        ):
            assert infer.suggest(s3_root, rel, examples) == infer.suggest(root, rel, examples)
        with pytest.raises(BuilderRefused) as exc:
            infer.suggest(s3_root, "star/S9/quant.tsv")
        assert exc.value.code == "file_missing"


class TestTags:
    def test_a_run_folder_is_not_part_of_the_tag(self):
        from depictio.project_builder.infer import _tag_for

        path = "run_7/sample_a/info/labels.tsv"
        assert _tag_for(path, runs=True) == "labels"

    def test_a_top_folder_still_prefixes_a_flat_path(self):
        from depictio.project_builder.infer import _tag_for

        assert _tag_for("star/quant.sf") == "star_quant"

    def test_ticked_files_are_named_after_the_folder_that_does_not_vary(self):
        from depictio.project_builder.infer import _tag_for_glob

        assert (
            _tag_for_glob("*/counts/*.info_raw", "r1/s1/counts/s1.info_raw", runs=True) == "counts"
        )

    def test_a_shared_file_name_stays_the_tag(self):
        from depictio.project_builder.infer import _tag_for_glob

        assert _tag_for_glob("*/info/labels.tsv", "r1/s1/info/labels.tsv", runs=True) == "labels"


class TestSuggestInRuns:
    """A file under a run is suggested as a scan read inside each run."""

    @pytest.fixture
    def runs_root(self, tmp_path):
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        from ..s3_stubs import write_tree

        files = {}
        for run in ("run_1", "run_2"):
            for sample in ("alpha", "bravo"):
                files[f"{run}/{sample}/info/labels.tsv"] = b"id\tv\n1\t2\n"
                files[f"{run}/{sample}/counts/{sample}.dat"] = b"x\ty\n1\t2\n"
        files["sheet.csv"] = b"a,b\n1,2\n"
        return LocalDataRoot(str(write_tree(tmp_path / "root", files)))

    def test_a_file_in_a_run_is_a_scan_without_the_run(self, runs_root):
        answer = infer.suggest(
            runs_root, "run_1/alpha/info/labels.tsv", runs=True, runs_regex=r"^run_\d+$"
        )
        assert answer["mode"] == "recursive"
        assert answer["in_run"] is True
        assert answer["glob"] == "**/labels.tsv"
        assert answer["tag"] == "labels"

    def test_a_sample_named_in_the_file_becomes_a_wildcard(self, runs_root):
        answer = infer.suggest(
            runs_root, "run_1/alpha/counts/alpha.dat", runs=True, runs_regex=r"^run_\d+$"
        )
        assert answer["glob"] == "*/counts/*.dat"
        assert answer["tag"] == "counts"

    @pytest.fixture
    def self_named_root(self, tmp_path):
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        from ..s3_stubs import write_tree

        files = {}
        for run in ("run_1", "run_2"):
            files[f"{run}/counts/counts.tsv"] = b"id\tv\n1\t2\n"
            files[f"{run}/qc/qc.log"] = b"ok\n"
        return LocalDataRoot(str(write_tree(tmp_path / "root", files)))

    @pytest.fixture
    def sample_named_root(self, tmp_path):
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        from ..s3_stubs import write_tree

        files = {
            f"{run}/{sample}/{sample}.tsv": b"id\tv\n1\t2\n"
            for run in ("run_1", "run_2")
            for sample in ("alpha", "bravo")
        }
        return LocalDataRoot(str(write_tree(tmp_path / "root", files)))

    def test_a_file_named_after_a_fixed_folder_stays_literal(self, self_named_root):
        answer = infer.suggest(
            self_named_root, "run_1/counts/counts.tsv", runs=True, runs_regex=r"^run_\d+$"
        )
        assert answer["glob"] == "**/counts.tsv"

    def test_a_file_named_after_its_sample_folder_becomes_a_wildcard(self, sample_named_root):
        answer = infer.suggest(
            sample_named_root, "run_1/alpha/alpha.tsv", runs=True, runs_regex=r"^run_\d+$"
        )
        assert answer["glob"] == "*/*.tsv"

    def test_a_huge_repeat_count_in_the_runs_regex_is_not_a_crash(self, self_named_root):
        answer = infer.suggest(
            self_named_root, "run_1/counts/counts.tsv", runs=True, runs_regex="a{4294967296}"
        )
        assert answer["in_run"] is False

    def test_ticked_files_generalise_inside_the_run(self, runs_root):
        answer = infer.suggest(
            runs_root,
            "run_1/alpha/info/labels.tsv",
            ["run_2/bravo/info/labels.tsv", "run_1/bravo/info/labels.tsv"],
            runs=True,
            runs_regex=r"^run_\d+$",
        )
        assert answer["glob"] == "*/info/labels.tsv"
        assert answer["mode"] == "recursive"

    def test_a_file_outside_the_runs_stays_one_file(self, runs_root):
        answer = infer.suggest(runs_root, "sheet.csv", runs=True, runs_regex=r"^run_\d+$")
        assert answer["mode"] == "single"
        assert answer["in_run"] is False

    def test_without_runs_nothing_changes(self, runs_root):
        answer = infer.suggest(runs_root, "run_1/alpha/info/labels.tsv")
        assert answer["mode"] == "single"
        assert answer["in_run"] is False
