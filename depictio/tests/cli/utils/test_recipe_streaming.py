"""A recipe's table written a batch at a time (#1418).

A recipe that defines ``transform_batches`` is written as its batches come:
validated, tagged with their run and counted on the way, in one Delta commit.
These tests drive ``process_recipe_data_collection`` end to end, with the S3
destination redirected to a local folder and the API stubbed, and check that
the streamed table is the one the whole-table path writes, that a run without
its inputs falls back to that path before anything is committed, and that a
recipe without batches is written as before.
"""

from __future__ import annotations

import os
from types import ModuleType, SimpleNamespace

import polars as pl
import pytest
from deltalake import DeltaTable

import depictio.recipes as recipes
from depictio.cli.cli.utils import deltatables, run_roots
from depictio.cli.cli.utils.data_root import data_root_for
from depictio.cli.cli.utils.delta_versioning import RUN_ID_COLUMN, content_digest
from depictio.cli.cli.utils.run_roots import RunRoot
from depictio.models.models.s3 import PolarsStorageOptions

OUTPUT_SCHEMA = {"name": pl.Utf8, "v": pl.Int64}


def _batches(run: str):
    yield pl.DataFrame({"name": [f"{run}-a", f"{run}-b"], "v": [1, 2]})
    yield pl.DataFrame({"name": [f"{run}-c"], "v": [3]})


def _recipe(*, streams: bool) -> ModuleType:
    module = ModuleType("fake_recipe")
    module.SOURCES = []  # type: ignore[attr-defined]
    module.OUTPUT_SCHEMA = OUTPUT_SCHEMA  # type: ignore[attr-defined]

    def transform(sources, context):
        return pl.concat(list(_batches(os.path.basename(context.root.location))))

    module.transform = transform  # type: ignore[attr-defined]
    if streams:

        def transform_batches(sources, context):
            yield from _batches(os.path.basename(context.root.location))

        module.transform_batches = transform_batches  # type: ignore[attr-defined]
    return module


@pytest.fixture
def env(tmp_path, monkeypatch):
    runs = []
    for tag in ("run_a", "run_b"):
        (tmp_path / tag).mkdir()
        location = str(tmp_path / tag)
        runs.append(RunRoot(tag=tag, root=data_root_for(location, None), location=location))
    table = str(tmp_path / "table")
    state = SimpleNamespace(table=table, runs=runs, writers=[], upserts=[])
    state.module = _recipe(streams=True)

    monkeypatch.setattr(recipes, "load_recipe", lambda name, version=None: state.module)
    monkeypatch.setattr(run_roots, "iter_run_roots", lambda location, config=None: state.runs)
    monkeypatch.setattr(run_roots, "attach_scope", lambda *a, **k: None)
    monkeypatch.setattr(
        deltatables,
        "turn_S3_config_into_polars_storage_options",
        lambda s3: PolarsStorageOptions(
            endpoint_url="http://localhost:9000", aws_access_key_id="k", aws_secret_access_key="s"
        ),
    )
    monkeypatch.setattr(deltatables, "delta_table_stats", lambda *a, **k: (123, None))

    for name in ("write_delta_frames", "write_delta_table"):
        original = getattr(deltatables, name)

        def local(*args, _original=original, _name=name, **kwargs):
            state.writers.append(_name)
            kwargs["destination_file"] = table
            return _original(*args, **kwargs)

        monkeypatch.setattr(deltatables, name, local)

    def upsert(**kwargs):
        state.upserts.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: {"result": "success"})

    monkeypatch.setattr(deltatables, "api_upsert_deltatable", upsert)
    return state


def _process(env):
    data_collection = SimpleNamespace(
        id="64b000000000000000000001",
        data_collection_tag="profile",
        config=SimpleNamespace(
            type="table",
            transform=SimpleNamespace(
                recipe="fake/recipe.py",
                source_overrides=None,
                params=None,
                scope=None,
                run_params=None,
            ),
            dc_specific_properties={},
        ),
    )
    workflow = SimpleNamespace(data_location=object(), data_collections=[], version=None)
    config = SimpleNamespace(s3_storage=SimpleNamespace(bucket="bucket"), user=None)
    return deltatables.process_recipe_data_collection(
        data_collection,  # type: ignore[arg-type]
        config,  # type: ignore[arg-type]
        workflow=workflow,
        command_parameters={},
    )


def _expected(runs: list[str]) -> pl.DataFrame:
    return pl.concat(
        [pl.concat(list(_batches(r))).with_columns(pl.lit(r).alias(RUN_ID_COLUMN)) for r in runs]
    )


def test_a_batched_recipe_is_streamed_into_one_commit(env):
    result = _process(env)

    assert result["result"] == "success"
    assert env.writers == ["write_delta_frames"]
    back = pl.read_delta(env.table).select(_expected(["run_a"]).columns).sort("name")
    assert back.equals(_expected(["run_a", "run_b"]).sort("name"))
    assert [h["version"] for h in DeltaTable(env.table).history()] == [0]

    (upsert,) = env.upserts
    provenance = upsert["delta_provenance"]
    assert provenance["rows_total"] == 6
    assert provenance["run_tags"] == ["run_a", "run_b"]
    assert provenance["computed_from_runs"] == ["run_a", "run_b"]
    # The digest counted on the way is the whole table's.
    assert provenance["content_digest"] == content_digest(_expected(["run_a", "run_b"]))
    # A streamed table has no frame to measure: its size comes from the commit.
    assert upsert["deltatable_size_bytes"] == 123


def test_a_run_without_its_inputs_falls_back_to_the_whole_table(env, monkeypatch):
    # run_b's inputs are missing: found once run_a's batches are being written.
    real_resolve = recipes.resolve_sources

    def resolve(module, data_dir, overrides=None):
        if getattr(data_dir, "location", "").endswith("run_b"):
            raise recipes.RecipeSourceMissing("Source 'x': file not found: run_b/x.tsv")
        return real_resolve(module, data_dir, overrides)

    monkeypatch.setattr(recipes, "resolve_sources", resolve)
    result = _process(env)

    assert result["result"] == "success"
    # The stream stopped before committing; the whole-table path skips run_b.
    assert env.writers == ["write_delta_frames", "write_delta_table"]
    assert [h["version"] for h in DeltaTable(env.table).history()] == [0]
    back = pl.read_delta(env.table).select(_expected(["run_a"]).columns).sort("name")
    assert back.equals(_expected(["run_a"]).sort("name"))


def test_a_recipe_without_batches_is_written_whole(env):
    env.module = _recipe(streams=False)
    result = _process(env)

    assert result["result"] == "success"
    assert env.writers == ["write_delta_table"]
    back = pl.read_delta(env.table).select(_expected(["run_a"]).columns).sort("name")
    assert back.equals(_expected(["run_a", "run_b"]).sort("name"))


def test_a_batch_that_fails_its_schema_fails_the_recipe_and_commits_nothing(env):
    def transform_batches(sources, context):
        yield pl.DataFrame({"name": ["ok"], "v": [1]})
        yield pl.DataFrame({"name": ["bad"], "v": ["not a number"]})

    env.module.transform_batches = transform_batches
    result = _process(env)

    assert result["result"] == "error"
    assert "expected Int64" in result["message"]
    assert not os.path.exists(os.path.join(env.table, "_delta_log", "00000000000000000000.json"))
