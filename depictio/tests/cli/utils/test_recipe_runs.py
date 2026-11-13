"""A recipe runs once per run, its dc_ref inputs narrowed to that run (epic #1399)."""

from __future__ import annotations

import polars as pl
import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli.utils.recipe_runs import RefFrame, execute_per_run, ref_frames_for_run
from depictio.cli.cli.utils.run_roots import RunRoot


class Missing(Exception):
    pass


def _run(tag: str) -> RunRoot:
    return RunRoot(tag, LocalDataRoot(f"/data/{tag}"), f"/data/{tag}")


def _fake_execute(seen: list):
    def execute(recipe_name, root, extra_sources=None, params=None, **kwargs):
        seen.append((root.name, extra_sources, params))
        if root.name == "run_missing":
            raise Missing("file not found: x.tsv")
        if root.name == "run_broken":
            raise ValueError("schema mismatch")
        meta = (extra_sources or {}).get("meta")
        n = meta.height if meta is not None else 0
        return pl.DataFrame({"sample": [f"{root.name}_s"], "n_meta": [n]})

    return execute


def test_single_run_output_is_the_recipe_output_plus_the_run_column():
    seen: list = []
    result = execute_per_run(
        _fake_execute(seen), "r.py", [_run("run_athens")], {}, lambda run: None, Missing
    )
    assert result.frame.columns == ["sample", "n_meta", "depictio_run_id"]
    assert result.frame["depictio_run_id"].to_list() == ["run_athens"]
    assert seen[0][1] is None


def test_every_run_is_stacked_with_its_tag_and_its_params():
    seen: list = []
    params = {"run_athens": {"G": "a"}, "run_naples": {"G": "n"}}
    result = execute_per_run(
        _fake_execute(seen),
        "r.py",
        [_run("run_athens"), _run("run_naples")],
        {},
        lambda run: params[run.tag],
        Missing,
    )
    assert result.frame["depictio_run_id"].to_list() == ["run_athens", "run_naples"]
    assert [p for _, _, p in seen] == [{"G": "a"}, {"G": "n"}]
    assert result.ran == ["run_athens", "run_naples"]


def test_dc_ref_rows_are_narrowed_to_the_run_and_shared_rows_kept():
    meta = pl.DataFrame(
        {
            "sample": ["a1", "a2", "n1", "shared"],
            "depictio_run_id": ["run_athens", "run_athens", "run_naples", "meta-single-file-scan"],
        }
    )
    seen: list = []
    result = execute_per_run(
        _fake_execute(seen),
        "r.py",
        [_run("run_athens"), _run("run_naples")],
        {"meta": RefFrame(meta)},
        lambda run: None,
        Missing,
    )
    assert result.frame["n_meta"].to_list() == [3, 2]
    athens_meta = seen[0][1]["meta"]
    assert athens_meta["sample"].to_list() == ["a1", "a2", "shared"]
    # A file-backed input keeps its run column, as it always had.
    assert "depictio_run_id" in athens_meta.columns


def test_recipe_output_input_loses_its_run_column():
    upstream = pl.DataFrame({"x": [1.0, 2.0], "depictio_run_id": ["run_athens", "run_naples"]})
    out = ref_frames_for_run(
        {"up": RefFrame(upstream, from_recipe=True), "none": RefFrame(None)},
        "run_athens",
        {"run_athens", "run_naples"},
    )
    assert out["up"].columns == ["x"]
    assert out["up"]["x"].to_list() == [1.0]
    assert out["none"] is None


def test_a_run_without_the_input_files_is_skipped_when_others_have_them():
    seen: list = []
    result = execute_per_run(
        _fake_execute(seen),
        "r.py",
        [_run("run_athens"), _run("run_missing")],
        {},
        lambda run: None,
        Missing,
    )
    assert result.ran == ["run_athens"]
    assert "run_missing" in result.skipped


def test_a_single_run_without_its_inputs_still_fails():
    with pytest.raises(Missing):
        execute_per_run(
            _fake_execute([]), "r.py", [_run("run_missing")], {}, lambda run: None, Missing
        )


def test_any_other_failure_fails_the_collection():
    with pytest.raises(ValueError, match="schema mismatch"):
        execute_per_run(
            _fake_execute([]),
            "r.py",
            [_run("run_athens"), _run("run_broken")],
            {},
            lambda run: None,
            Missing,
        )


def test_no_run_with_inputs_fails_with_every_reason():
    with pytest.raises(Missing, match="run_missing"):
        execute_per_run(
            _fake_execute([]),
            "r.py",
            [_run("run_missing"), _run("run_missing")],
            {},
            lambda run: None,
            Missing,
        )


def test_wide_input_keeps_only_this_run_columns():
    # A wide table stacked per run: one column per sample, null in other runs' rows.
    wide = pl.DataFrame(
        {
            "Phylum": ["p1", "p2", "p1"],
            "a1": [1.0, 2.0, None],
            "n1": [None, None, 5.0],
            "depictio_run_id": ["run_athens", "run_athens", "run_naples"],
        }
    )
    out = ref_frames_for_run(
        {"heat": RefFrame(wide, from_recipe=True)}, "run_athens", {"run_athens", "run_naples"}
    )
    assert out["heat"].columns == ["Phylum", "a1"]


def test_null_column_of_every_run_is_kept():
    frame = pl.DataFrame(
        {
            "sample": ["a", "n"],
            "note": [None, None],
            "depictio_run_id": ["run_athens", "run_naples"],
        },
        schema_overrides={"note": pl.String},
    )
    out = ref_frames_for_run({"m": RefFrame(frame)}, "run_athens", {"run_athens", "run_naples"})
    assert out["m"].columns == ["sample", "note", "depictio_run_id"]


def test_single_run_input_is_never_narrowed():
    frame = pl.DataFrame({"a1": [1.0], "empty": [None], "depictio_run_id": ["run_athens"]})
    out = ref_frames_for_run({"m": RefFrame(frame)}, "run_athens", {"run_athens"})
    assert out["m"].columns == ["a1", "empty", "depictio_run_id"]
