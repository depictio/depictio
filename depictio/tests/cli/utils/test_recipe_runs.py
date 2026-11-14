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


# ── recomputed over every run ───────────────────────────────────────────────

from depictio.cli.cli.utils.recipe_runs import (  # noqa: E402
    combine_runs,
    execute_aggregate,
    merge_wide,
)
from depictio.cli.cli.utils.recipe_scopes import REGISTRY, RecipeScope, recipe_scope  # noqa: E402


def test_wide_tables_join_on_their_shared_columns_and_absent_features_count_zero():
    athens = pl.DataFrame({"ID": ["asv1", "asv2"], "Phylum": ["p", "q"], "a1": [0.5, 0.5]})
    naples = pl.DataFrame({"ID": ["asv1", "asv3"], "Phylum": ["p", "r"], "n1": [0.2, 0.8]})
    out = merge_wide([athens, naples]).sort("ID")
    assert out.columns == ["ID", "Phylum", "a1", "n1"]
    assert out.rows() == [("asv1", "p", 0.5, 0.2), ("asv2", "q", 0.5, 0.0), ("asv3", "r", 0.0, 0.8)]


def test_string_typed_wide_tables_fill_with_a_string_zero():
    a = pl.DataFrame({"ID": ["x"], "a1": ["1"]})
    n = pl.DataFrame({"ID": ["y"], "n1": ["2"]})
    assert merge_wide([a, n]).sort("ID").rows() == [("x", "1", "0"), ("y", "0", "2")]


def test_one_run_is_never_reshaped():
    frame = pl.DataFrame({"ID": ["x"], "a1": [None]}, schema_overrides={"a1": pl.Float64})
    assert combine_runs([frame], "wide") is frame
    assert combine_runs([frame], "rows") is frame


def test_unique_drops_what_every_run_repeats():
    t = pl.DataFrame({"Feature ID": ["a", "b"], "Taxon": ["x", "y"]})
    assert combine_runs([t, t], "unique").height == 2


def _resolve_by_run(tables):
    def resolve(run):
        if run.tag not in tables:
            raise Missing(f"no file in {run.tag}")
        return {"asv": tables[run.tag]}

    return resolve


def test_an_aggregate_sees_every_run_and_tags_rows_by_their_sample():
    seen = {}

    def execute(recipe_name, root, extra_sources=None, params=None, sources=None, **kw):
        seen["sources"], seen["extra"] = sources, extra_sources
        samples = [c for c in sources["asv"].columns if c != "ID"]
        return pl.DataFrame({"sample": samples, "n": [len(samples)] * len(samples)})

    tables = {
        "run_athens": pl.DataFrame({"ID": ["x"], "a1": [1.0]}),
        "run_naples": pl.DataFrame({"ID": ["y"], "n1": [2.0]}),
    }
    meta = pl.DataFrame({"ID": ["a1", "n1"], "depictio_run_id": ["run_athens", "run_naples"]})
    result = execute_aggregate(
        execute,
        _resolve_by_run(tables),
        "r.py",
        [_run("run_athens"), _run("run_naples"), _run("run_missing")],
        {"meta": RefFrame(meta)},
        None,
        RecipeScope("aggregate", "sample", {"asv": "wide"}),
        Missing,
    )
    assert result.frame.rows() == [("a1", 2, "run_athens"), ("n1", 2, "run_naples")]
    assert result.ran == ["run_athens", "run_naples"]
    assert "run_missing" in result.skipped
    # dc_ref inputs are not narrowed: every run's rows.
    assert seen["extra"]["meta"].height == 2


def test_an_aggregate_takes_its_declared_sample_column_even_outside_the_usual_names():
    # quantms names a sample by run_id, which is no global sample column.
    def execute(recipe_name, root, extra_sources=None, params=None, sources=None, **kw):
        return pl.DataFrame({"run_id": ["ms1", "ms2"], "dim_1": [0.1, 0.2]})

    proteins = pl.DataFrame(
        {
            "run_id": ["ms1", "ms2"],
            "protein_group": ["P1", "P1"],
            "depictio_run_id": ["run_athens", "run_naples"],
        }
    )
    result = execute_aggregate(
        execute,
        lambda run: {},
        "r.py",
        [_run("run_athens"), _run("run_naples")],
        {"proteins": RefFrame(proteins)},
        None,
        RecipeScope("aggregate", "run_id"),
        Missing,
    )
    assert result.frame["depictio_run_id"].to_list() == ["run_athens", "run_naples"]


def test_an_aggregate_row_of_several_samples_has_no_run():
    def execute(recipe_name, root, extra_sources=None, params=None, sources=None, **kw):
        return pl.DataFrame({"taxon": ["t"], "n_groups": [2]})

    tables = {t: pl.DataFrame({"ID": ["x"], t: [1.0]}) for t in ("run_athens", "run_naples")}
    result = execute_aggregate(
        execute,
        _resolve_by_run(tables),
        "r.py",
        [_run("run_athens"), _run("run_naples")],
        {},
        None,
        RecipeScope("aggregate"),
        Missing,
    )
    assert result.frame["depictio_run_id"].to_list() == [None]


def test_a_wide_recipe_output_input_is_merged_back_per_run():
    heat = pl.DataFrame(
        {
            "Phylum": ["p1", "p2", "p1"],
            "a1": [1.0, 2.0, None],
            "n1": [None, None, 5.0],
            "depictio_run_id": ["run_athens", "run_athens", "run_naples"],
        }
    )
    seen = {}

    def execute(recipe_name, root, extra_sources=None, params=None, sources=None, **kw):
        seen["heat"] = extra_sources["heat"]
        return pl.DataFrame({"sample_id": ["a1"]})

    execute_aggregate(
        execute,
        lambda run: {},
        "r.py",
        [_run("run_athens"), _run("run_naples")],
        {"heat": RefFrame(heat, from_recipe=True)},
        None,
        RecipeScope("aggregate", "sample_id", {"heat": "wide"}),
        Missing,
    )
    assert seen["heat"].sort("Phylum").rows() == [("p1", 1.0, 5.0), ("p2", 2.0, 0.0)]


def test_declared_scope_wins_over_the_registry():
    assert recipe_scope("nf-core/ampliseq/bray_curtis_canonical.py").scope == "aggregate"
    assert recipe_scope("nf-core/ampliseq/bray_curtis_canonical.py", "run").scope == "run"
    assert recipe_scope("qiime2/alpha_rarefaction.py").scope == "run"


def _registered_version(name: str) -> tuple[bool, str | None]:
    """Whether a registry id names a recipe, and the template version it is under."""
    from pathlib import Path

    from depictio.recipes import PROJECTS_DIR, RecipeError, resolve_recipe_path

    parts = name.split("/")
    versions: list[str | None] = [None]
    if parts[0] == "nf-core":
        versions += [p.name for p in Path(PROJECTS_DIR, *parts[:2]).iterdir() if p.is_dir()]
    for version in versions:
        try:
            if resolve_recipe_path(f"{name}.py", version).is_file():
                return True, version
        except RecipeError:
            continue
    return False, None


def test_every_registered_recipe_exists():
    """A typo in the registry would silently leave a recipe per run."""
    missing = [name for name in REGISTRY if not _registered_version(name)[0]]
    assert missing == []


@pytest.mark.parametrize("name", sorted(n for n, s in REGISTRY.items() if s.scope == "aggregate"))
def test_an_aggregate_entry_matches_its_recipe(name):
    """``combine`` names the recipe's own sources, and ``sample_column`` one of
    its output columns: a wrong name silently stacks a wide table, or leaves
    every recomputed row without a run."""
    from depictio.recipes import load_recipe

    _, version = _registered_version(name)
    module = load_recipe(f"{name}.py", version)
    scope = REGISTRY[name]
    refs = {source.ref for source in module.SOURCES}
    assert set(scope.combine) <= refs
    if scope.sample_column:
        outputs = {**module.OUTPUT_SCHEMA, **getattr(module, "OPTIONAL_OUTPUT_SCHEMA", {})}
        assert scope.sample_column in outputs


def test_a_wrapper_recipe_shares_the_scope_of_the_recipe_it_wraps():
    assert REGISTRY["nf-core/riboseq/sample_pca"] == REGISTRY["salmon/sample_pca"]


def test_a_run_folder_missing_on_this_host_is_unreachable(tmp_path):
    # An aggregate recomputes every run: one whose folder is not mounted here
    # would silently drop out of the rewritten table. A folder that exists but
    # lacks the recipe's input is a run the pipeline step skipped, not this.
    from depictio.cli.cli.utils.data_root import LocalDataRoot
    from depictio.cli.cli.utils.recipe_runs import unreachable_runs
    from depictio.cli.cli.utils.run_roots import RunRoot

    present = tmp_path / "run_B"
    present.mkdir()
    gone = tmp_path / "run_A"
    runs = [
        RunRoot("run_A", LocalDataRoot(str(gone)), str(gone)),
        RunRoot("run_B", LocalDataRoot(str(present)), str(present)),
    ]
    assert [r.tag for r in unreachable_runs(runs)] == ["run_A"]
