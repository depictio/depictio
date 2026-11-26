"""The dry run of a sequencing-runs template counts what ingestion reads.

Ingestion runs a recipe once per run folder (``run_roots.iter_run_roots``) and
walks only run folders when it scans (``scan.describe_unmatched_run_scan``).
The preview used to look for recipe sources at the data root, so a correct
layout (``results/run_1/...``) reported them missing, and to scan the root
when no run folder matched, so a data root one level too deep looked clean.
"""

from types import ModuleType
from unittest.mock import MagicMock

import pytest

import depictio.recipes
from depictio.cli.cli.utils.data_root import LocalDataRoot
from depictio.cli.cli.utils.template_preview import (
    _unmatched_run_layout,
    preview_data_collections,
)
from depictio.models.models.transforms import RecipeSource


@pytest.fixture()
def recipe(monkeypatch):
    """A recipe reading one CSV, found by glob, and a summary found by path."""
    module = MagicMock(spec=ModuleType)
    module.SOURCES = [
        RecipeSource(ref="calls", format="csv", glob_pattern="variants/*/calls.csv"),
        RecipeSource(ref="summary", format="csv", path="multiqc/summary.csv"),
    ]
    module.__doc__ = "Test recipe."
    monkeypatch.setattr(depictio.recipes, "load_recipe", lambda *args, **kwargs: module)
    return module


def _config() -> dict:
    return {
        "workflows": [
            {
                "data_location": {
                    "structure": "sequencing-runs",
                    "runs_regex": "run_.*",
                    "locations": ["{DATA_ROOT}"],
                },
                "data_collections": [
                    {
                        "data_collection_tag": "calls",
                        "config": {
                            "source": "transformed",
                            "transform": {"recipe": "test/calls.py"},
                        },
                    },
                    {
                        "data_collection_tag": "coverage",
                        "config": {
                            "type": "Table",
                            "scan": {
                                "mode": "recursive",
                                "scan_parameters": {
                                    "regex_config": {"pattern": "mosdepth/coverage.tsv"}
                                },
                            },
                        },
                    },
                    {
                        "data_collection_tag": "multiqc_data",
                        "config": {
                            "type": "MultiQC",
                            "scan": {
                                "mode": "recursive",
                                "scan_parameters": {
                                    "regex_config": {
                                        "pattern": "multiqc/multiqc_data/multiqc.parquet"
                                    }
                                },
                            },
                        },
                    },
                ],
            }
        ]
    }


def _run(folder) -> None:
    for relative in (
        "variants/ivar/calls.csv",
        "multiqc/summary.csv",
        "mosdepth/coverage.tsv",
        "multiqc/multiqc_data/multiqc.parquet",
    ):
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")


def _rows(root) -> dict[str, tuple[str, int]]:
    rows, _runs = preview_data_collections(_config(), LocalDataRoot(str(root)))
    return {row.tag: (row.status, row.matched) for row in rows}


def test_recipe_sources_are_found_inside_each_run_folder(tmp_path, recipe):
    for run in ("run_1", "run_2"):
        _run(tmp_path / run)

    rows = _rows(tmp_path)

    # Two sources in each of two runs.
    assert rows["calls"] == ("ok", 4)
    assert rows["coverage"] == ("ok", 2)
    assert _unmatched_run_layout(_config(), LocalDataRoot(str(tmp_path))) is None


def test_a_source_missing_from_every_run_is_still_missing(tmp_path, recipe):
    (tmp_path / "run_1" / "variants" / "ivar").mkdir(parents=True)
    (tmp_path / "run_1" / "variants" / "ivar" / "calls.csv").write_text("x\n")

    rows, _runs = preview_data_collections(_config(), LocalDataRoot(str(tmp_path)))
    calls = next(row for row in rows if row.tag == "calls")

    assert calls.status == "missing"
    assert calls.missing_sources == ["multiqc/summary.csv"]


def test_a_root_without_run_folders_scans_nothing_but_runs_recipes(tmp_path, recipe):
    # The data root is a run folder itself: one level too deep.
    _run(tmp_path)

    rows = _rows(tmp_path)

    # Recipes read the root as one run, as ingestion does.
    assert rows["calls"] == ("ok", 2)
    # The scan walks run folders only, and there are none.
    assert rows["coverage"] == ("empty", 0)
    # MultiQC falls back to globbing the local folder at ingest.
    assert rows["multiqc_data"] == ("ok", 1)
    message = _unmatched_run_layout(_config(), LocalDataRoot(str(tmp_path)))
    assert message is not None
    assert "matched the pattern 'run_.*'" in message
    assert "mosdepth, multiqc, variants" in message
