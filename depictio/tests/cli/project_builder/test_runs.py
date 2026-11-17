"""The runs regex read off the first-level folders of a data root."""

from __future__ import annotations

import re

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.project_builder import runs

from ..s3_stubs import write_tree

DATED = [
    "2020-01-05-A1B",
    "2020-02-10-C22D",
    "2020-11-18-E3F",
]


class TestRegexFor:
    def test_dated_runs_with_an_id(self):
        regex, covered = runs.regex_for(DATED)
        assert regex == r"^\d{4}-\d{2}-\d{2}-[A-Z0-9]+$"
        assert covered == DATED

    def test_numbered_runs_keep_their_prefix(self):
        regex, covered = runs.regex_for(["run_1", "run_2", "run_10"])
        assert regex == r"^run_\d+$"
        assert covered == ["run_1", "run_2", "run_10"]

    def test_letters_then_digits_without_a_separator(self):
        regex, _ = runs.regex_for(["set1", "set2", "set3"])
        assert regex == r"^set\d$"

    def test_letters_that_vary_become_a_class(self):
        regex, _ = runs.regex_for(["a1", "b2"])
        assert regex == r"^[a-z]+\d$"

    def test_the_biggest_group_wins_and_the_rest_is_left_out(self):
        names = [*DATED, "notes", "tmp"]
        regex, covered = runs.regex_for(names)
        assert regex == r"^\d{4}-\d{2}-\d{2}-[A-Z0-9]+$"
        assert covered == DATED

    def test_names_that_all_differ_say_nothing(self):
        assert runs.regex_for(["alpha", "beta-1", "gamma_2_x"]) == (None, [])

    def test_two_folders_are_enough_and_one_is_taken_as_it_looks(self):
        assert runs.regex_for(["run_1"])[0] == r"^run_\d$"
        assert runs.regex_for([]) == (None, [])

    @pytest.mark.parametrize(
        "names",
        [DATED, ["run_1", "run_22"], ["S-1.a", "S-2.b"], ["a b", "c d"], ["x+1", "y+2"]],
    )
    def test_the_regex_matches_what_it_was_read_from(self, names):
        regex, covered = runs.regex_for(names)
        assert regex is not None
        assert all(re.match(regex, name) for name in covered)
        assert covered == names


class TestSuggestRunsRegex:
    def test_reads_the_first_level_folders_only(self, tmp_path):
        base = write_tree(
            tmp_path / "root",
            {
                "2020-01-05-A1B/data/a.tsv": b"x",
                "2020-02-10-C22D/data/a.tsv": b"x",
                "notes/readme.txt": b"x",
                "table.xlsx": b"x",
                ".hidden/x.txt": b"x",
            },
        )
        answer = runs.suggest_runs_regex(LocalDataRoot(str(base)))
        assert answer["regex"] == r"^\d{4}-\d{2}-\d{2}-[A-Z0-9]+$"
        assert answer["runs"] == ["2020-01-05-A1B", "2020-02-10-C22D"]
        assert answer["folders"] == 3
        assert answer["skipped"] == ["notes"]
        assert answer["truncated"] is False

    def test_no_folder_no_regex(self, tmp_path):
        base = write_tree(tmp_path / "flat", {"a.tsv": b"x"})
        answer = runs.suggest_runs_regex(LocalDataRoot(str(base)))
        assert answer["regex"] is None
        assert answer["runs"] == []


def _runs_tree(
    count: int, *, drop: dict[str, str] | None = None, extra: dict[str, bytes] | None = None
):
    """``count`` runs of ``<sample>/<kind>/<sample>.<ext>`` files, with optional departures."""
    files: dict[str, bytes] = {}
    for n in range(1, count + 1):
        run = f"run_{n}"
        for sample in (f"s{n}a", f"s{n}b"):
            files[f"{run}/{sample}/table/{sample}.tsv"] = b"x"
            files[f"{run}/{sample}/labels/labels.csv"] = b"x"
        files[f"{run}/summary.txt"] = b"x"
    for gone in drop or {}:
        files.pop(gone, None)
    files.update(extra or {})
    return files


class TestLayoutShapes:
    def test_names_unique_to_a_run_become_wildcards(self):
        per_run = {
            "r1": [("a1", "table", "a1.tsv"), ("a1", "labels", "labels.csv")],
            "r2": [("b2", "table", "b2.tsv"), ("b2", "labels", "labels.csv")],
            "r3": [("c3", "table", "c3.tsv"), ("c3", "labels", "labels.csv")],
        }
        shapes = runs.layout_shapes(per_run)
        expected = {"*/table/*.tsv", "*/labels/labels.csv"}
        assert shapes == {"r1": expected, "r2": expected, "r3": expected}

    def test_a_single_run_keeps_every_name(self):
        shapes = runs.layout_shapes({"r1": [("a", "x.tsv")]})
        assert shapes == {"r1": {"a/x.tsv"}}


class TestOverview:
    def test_a_uniform_layout_is_consistent(self, tmp_path):
        base = write_tree(tmp_path / "root", _runs_tree(4))
        answer = runs.overview(LocalDataRoot(str(base)), r"^run_\d+$")
        assert answer["runs_total"] == 4
        assert answer["consistent"] == 4
        assert answer["deviating"] == []
        shapes = {item["shape"]: item["runs"] for item in answer["layout"]}
        assert shapes == {"*/table/*.tsv": 4, "*/labels/labels.csv": 4, "summary.txt": 4}
        assert answer["files"] == 4 * 5

    def test_a_run_that_departs_is_named_with_what_differs(self, tmp_path):
        tree_ = _runs_tree(
            4,
            drop={"run_3/s3a/labels/labels.csv": "", "run_3/s3b/labels/labels.csv": ""},
            extra={"run_3/odd.bin": b"x"},
        )
        base = write_tree(tmp_path / "root", tree_)
        answer = runs.overview(LocalDataRoot(str(base)), r"^run_\d+$")
        assert answer["consistent"] == 3
        assert answer["deviating_total"] == 1
        [diff] = answer["deviating"]
        assert diff["run"] == "run_3"
        assert diff["missing"] == ["*/labels/labels.csv"]
        assert diff["extra"] == ["*.bin"]

    def test_folders_outside_the_regex_are_reported(self, tmp_path):
        files = {**_runs_tree(2), "notes/readme.txt": b"x"}
        base = write_tree(tmp_path / "root", files)
        answer = runs.overview(LocalDataRoot(str(base)), r"^run_\d+$")
        assert answer["runs"] == ["run_1", "run_2"]
        assert answer["skipped"] == ["notes"]

    def test_a_regex_matching_nothing_has_no_runs(self, tmp_path):
        base = write_tree(tmp_path / "root", _runs_tree(2))
        answer = runs.overview(LocalDataRoot(str(base)), r"^nothing$")
        assert answer["runs_total"] == 0
        assert answer["layout"] == []

    def test_hidden_files_are_not_part_of_the_layout(self, tmp_path):
        files = {**_runs_tree(2), "run_1/.DS_Store": b"x"}
        base = write_tree(tmp_path / "root", files)
        answer = runs.overview(LocalDataRoot(str(base)), r"^run_\d+$")
        assert answer["deviating"] == []

    @pytest.mark.parametrize("regex", [None, "", "  "])
    def test_a_missing_regex_is_refused(self, tmp_path, regex):
        from depictio.project_builder.errors import BuilderRefused

        base = write_tree(tmp_path / "root", _runs_tree(1))
        with pytest.raises(BuilderRefused) as refused:
            runs.overview(LocalDataRoot(str(base)), regex)
        assert refused.value.code == "runs_regex_missing"

    def test_an_invalid_regex_is_refused(self, tmp_path):
        from depictio.project_builder.errors import BuilderRefused

        base = write_tree(tmp_path / "root", _runs_tree(1))
        with pytest.raises(BuilderRefused) as refused:
            runs.overview(LocalDataRoot(str(base)), "(")
        assert refused.value.code == "runs_regex_invalid"
