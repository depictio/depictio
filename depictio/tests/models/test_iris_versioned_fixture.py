"""The iris_versioned demo fixture must actually demonstrate versioning.

This fixture exists to give both version dimensions something real to show, and
every way it can fail is silent: the dashboards still render, the project still
seeds, the numbers just never move. So the properties that make it a *demo*
rather than three copies of the same thing are asserted here.

Deliberately not marked ``integration``: this reads bundled files and validates
them against the same models the loader uses. No database, no S3, no CLI.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import polars as pl
import pytest
import yaml

os.environ.setdefault("DEPICTIO_CONTEXT", "server")

# tests/models/<this file> -> tests/ -> depictio/
PROJECT_DIR = Path(__file__).resolve().parents[2] / "projects" / "init" / "iris_versioned"
BATCHES_DIR = PROJECT_DIR / "batches"
DASHBOARDS_DIR = PROJECT_DIR / "dashboards"

BATCH_ORDER = [
    "batch_01_initial_survey",
    "batch_02_virginica_added",
    "batch_03_virginica_recalibrated",
]
DASHBOARD_ORDER = ["v1_survey.yaml", "v2_extended.yaml", "v3_recalibrated.yaml"]

MEASUREMENTS = ["sepal.length", "sepal.width", "petal.length", "petal.width"]


@pytest.fixture(scope="module")
def batches() -> dict[str, pl.DataFrame]:
    return {name: pl.read_csv(BATCHES_DIR / name / "iris.csv") for name in BATCH_ORDER}


# ── the data dimension ──────────────────────────────────────────────────────


def test_measurements_are_numeric(batches) -> None:
    """Quoted numerics would land in Delta as text and break every aggregation.

    The generator writes with QUOTE_MINIMAL for exactly this reason; a switch to
    QUOTE_NONNUMERIC would quote everything, since the rows are all `str` by the
    time they are written.
    """
    for name, frame in batches.items():
        for column in MEASUREMENTS:
            assert frame.schema[column] == pl.Float64, f"{name}:{column} is not numeric"


def test_the_three_batches_tell_the_documented_story(batches) -> None:
    b1, b2, b3 = (batches[n] for n in BATCH_ORDER)

    assert b1.height == 100 and b2.height == 150 and b3.height == 150
    assert set(b1["variety"].unique()) == {"Setosa", "Versicolor"}
    assert set(b2["variety"].unique()) == {"Setosa", "Versicolor", "Virginica"}
    assert set(b3["variety"].unique()) == {"Setosa", "Versicolor", "Virginica"}


def test_batch_two_is_purely_additive(batches) -> None:
    """v0 -> v1 must add Virginica without disturbing what was already there."""
    b1, b2 = batches[BATCH_ORDER[0]], batches[BATCH_ORDER[1]]
    kept_1 = b1.sort(MEASUREMENTS)
    kept_2 = b2.filter(pl.col("variety") != "Virginica").sort(MEASUREMENTS)
    assert kept_1.equals(kept_2)


def test_batch_three_differs_only_in_values(batches) -> None:
    """The whole point of the fixture.

    Batch 3 has the same row count and the same varieties as batch 2, so a
    dashboard cannot distinguish them by shape — only the data version can. If
    these two ever became equivalent, a time-travel read that silently returned
    current data would look correct.
    """
    b2, b3 = batches[BATCH_ORDER[1]], batches[BATCH_ORDER[2]]

    assert b2.height == b3.height
    assert not b2.sort(MEASUREMENTS).equals(b3.sort(MEASUREMENTS)), (
        "batch 2 and 3 are identical — the fixture demonstrates nothing"
    )

    median_2 = b2.filter(pl.col("variety") == "Virginica")["petal.length"].median()
    median_3 = b3.filter(pl.col("variety") == "Virginica")["petal.length"].median()
    assert abs(median_2 - median_3) > 0.3, (
        "the recalibration must be visible on a chart, not lost in noise"
    )

    untouched_2 = b2.filter(pl.col("variety") != "Virginica").sort(MEASUREMENTS)
    untouched_3 = b3.filter(pl.col("variety") != "Virginica").sort(MEASUREMENTS)
    assert untouched_2.equals(untouched_3), "batch 3 must touch Virginica only"


# ── the project config ──────────────────────────────────────────────────────


def _load_project() -> dict:
    raw = yaml.safe_load((PROJECT_DIR / "project.yaml").read_text())
    # Injected by the loader from the calling user; no bundled project.yaml
    # carries it.
    raw["permissions"] = {"owners": [{"id": "646b0f3c1e4a2d7f8e5b0000", "email": "a@b.c"}]}
    return raw


def test_project_config_validates() -> None:
    from depictio.models.models.projects import Project

    project = Project.model_validate(_load_project())
    assert project.workflows[0].data_location.structure == "sequencing-runs", (
        "flat structure gives batches no run tag, so there is nothing to version"
    )


def test_every_batch_is_seen_as_its_own_run() -> None:
    """`runs_regex` is the mechanism: no match, no run tag, no versioning."""
    from depictio.models.models.projects import Project

    project = Project.model_validate(_load_project())
    pattern = re.compile(project.workflows[0].data_location.runs_regex)

    for name in BATCH_ORDER:
        assert pattern.match(name), f"{name} would not be picked up as a run"


# ── the dashboard dimension ─────────────────────────────────────────────────


def _dashboard_tags(filename: str) -> set[str]:
    raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
    return {component["tag"] for component in raw["components"]}


def test_dashboards_validate() -> None:
    from depictio.models.models.dashboards import DashboardDataLite

    for filename in DASHBOARD_ORDER:
        raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
        DashboardDataLite.model_validate(raw)


def test_dashboard_validation_is_not_vacuous() -> None:
    """Every component must resolve to a *typed* Lite model, not the dict arm.

    ``components`` is ``list[LiteComponent | dict[str, Any]]`` and pydantic
    resolves unions left to right, so a component with a bad field falls through
    to ``dict`` — which always succeeds. `test_dashboards_validate` would then
    pass having checked nothing at all.

    This is what makes these fixtures trustworthy as a reference for what a
    valid dashboard YAML looks like.
    """
    from depictio.models.models.dashboards import DashboardDataLite

    for filename in DASHBOARD_ORDER:
        raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
        dashboard = DashboardDataLite.model_validate(raw)

        untyped = [
            component.get("tag", "<untagged>")
            for component in dashboard.components
            if isinstance(component, dict)
        ]
        assert not untyped, (
            f"{filename}: {untyped} fell back to the dict union arm, so their "
            "fields were never validated"
        )


def test_each_dashboard_version_extends_the_last() -> None:
    """Restoring an earlier version must be a visible change.

    Supersets rather than variations, so a restore removes components the user
    can count — and the timeline's "N components" moves between rows, which is
    the field that read 0 for every version before it was fixed.
    """
    v1, v2, v3 = (_dashboard_tags(f) for f in DASHBOARD_ORDER)

    assert v1 < v2 < v3, "each version must be a strict superset of the previous"
    assert len(v1) < len(v2) < len(v3)


def test_dashboard_components_bind_to_this_project() -> None:
    """A component pointing at the wrong collection renders empty, not broken."""
    for filename in DASHBOARD_ORDER:
        raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
        for component in raw["components"]:
            if component["component_type"] == "text":
                continue
            assert component["data_collection_tag"] == "iris_versioned_table"
            assert component["workflow_tag"] == "python/iris_versioned_workflow"


def test_v3_virginica_filter_selects_real_rows(batches) -> None:
    """The tile that separates data version 1 from 2 must not be empty.

    Model validation only checks `filter_expr` *syntax*. An expression that
    parses but matches nothing renders a card showing zero — a broken demo that
    looks like a working one, and precisely the tile whose value is supposed to
    reveal the recalibration.
    """
    from depictio.models.components.filter_expr import apply_filter_expr

    raw = yaml.safe_load((DASHBOARDS_DIR / "v3_recalibrated.yaml").read_text())
    component = next(c for c in raw["components"] if c["tag"] == "virginica-petal-median")

    selected = apply_filter_expr(batches[BATCH_ORDER[2]], component["filter_expr"])

    assert selected.height == 50, f"expected the 50 Virginica rows, got {selected.height}"
    assert set(selected["variety"].unique()) == {"Virginica"}

    # And the value it reports must differ from the previous data version, or
    # the tile cannot do the job it was added for.
    previous = apply_filter_expr(batches[BATCH_ORDER[1]], component["filter_expr"])
    assert abs(previous["petal.length"].median() - selected["petal.length"].median()) > 0.3


# ── the documented sequence, executed ───────────────────────────────────────


def test_the_documented_ingest_sequence_produces_three_versions(tmp_path) -> None:
    """Run the README's sequence against a real Delta table.

    Everything above validates the fixture's *inputs*. This validates the claim
    the README actually makes: stage a batch, ingest, repeat, and end up with
    three Delta versions you can time-travel between.

    Uses the same `write_delta_table_versioned` the CLI calls, against a local
    path — no Mongo, no S3, no API — so the claim is executed rather than
    reasoned about.

    The last assertion is the one that matters for any future dataset-version
    picker: two versions with identical row counts and identical varieties must
    still be distinguishable by value, or a time-travel read that silently
    returned current data would look correct.
    """
    from deltalake import DeltaTable

    from depictio.cli.cli.utils.delta_versioning import write_delta_table_versioned

    class _NoStorageOptions:
        """The writer calls `.model_dump()`; a local path needs no credentials."""

        def model_dump(self) -> dict:
            return {}

    table_path = str(tmp_path / "iris_versioned_delta")

    for expected_version, name in enumerate(BATCH_ORDER):
        frame = pl.read_csv(BATCHES_DIR / name / "iris.csv").with_columns(
            pl.lit(name).alias("depictio_run_id")
        )
        result = write_delta_table_versioned(
            frame,
            table_path,
            _NoStorageOptions(),  # type: ignore[arg-type]
            write_mode="overwrite",
            commit_metadata={"depictio.run_tags": name},
        )
        assert result.delta_version == expected_version

    assert len(DeltaTable(table_path).history()) == 3

    at_v0 = pl.read_delta(table_path, version=0)
    at_v1 = pl.read_delta(table_path, version=1)
    at_v2 = pl.read_delta(table_path, version=2)

    assert at_v0.height == 100
    assert set(at_v0["variety"].unique()) == {"Setosa", "Versicolor"}
    assert at_v1.height == at_v2.height == 150

    median_v1 = at_v1.filter(pl.col("variety") == "Virginica")["petal.length"].median()
    median_v2 = at_v2.filter(pl.col("variety") == "Virginica")["petal.length"].median()
    assert abs(median_v1 - median_v2) > 0.3, (
        "two versions of the same shape must differ by value, or a time-travel "
        "read that returned current data would be indistinguishable from a correct one"
    )
