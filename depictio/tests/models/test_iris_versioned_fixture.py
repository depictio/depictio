"""The iris_versioned demo fixture must actually demonstrate versioning.

This fixture exists to give both version dimensions something real to show, and
every way it can fail is silent: the dashboards still render, the project still
seeds, the numbers just never move. So the properties that make it a *demo*
rather than four copies of the same thing are asserted here.

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
    "batch_01_setosa_only",
    "batch_02_versicolor_added",
    "batch_03_setosa_recalibrated",
    "batch_04_virginica_added",
]
DASHBOARD_ORDER = [
    "v1_survey.yaml",
    "v2_extended.yaml",
    "v3_recalibrated.yaml",
    "v4_complete.yaml",
]

MEASUREMENTS = ["sepal.length", "sepal.width", "petal.length", "petal.width"]

#: Fields whose change is visible on screen. Two consecutive versions of the
#: same component must differ in at least one, or its history shows two
#: identical renders and the feature reads as broken.
VISIBLE_FIELDS = (
    "component_type",
    "aggregation",
    "column_name",
    "visu_type",
    "dict_kwargs",
    "interactive_component_type",
    "title",
    "body",
    "layout",
)


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


def test_the_four_batches_tell_the_documented_story(batches) -> None:
    b1, b2, b3, b4 = (batches[n] for n in BATCH_ORDER)

    assert [b1.height, b2.height, b3.height, b4.height] == [50, 100, 100, 150]
    assert set(b1["variety"].unique()) == {"Setosa"}
    assert set(b2["variety"].unique()) == {"Setosa", "Versicolor"}
    assert set(b3["variety"].unique()) == {"Setosa", "Versicolor"}
    assert set(b4["variety"].unique()) == {"Setosa", "Versicolor", "Virginica"}


def test_batch_two_is_purely_additive(batches) -> None:
    """v0 -> v1 must add Versicolor without disturbing what was already there."""
    b1, b2 = batches[BATCH_ORDER[0]], batches[BATCH_ORDER[1]]
    kept_1 = b1.sort(MEASUREMENTS)
    kept_2 = b2.filter(pl.col("variety") != "Versicolor").sort(MEASUREMENTS)
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
    assert set(b2["variety"].unique()) == set(b3["variety"].unique())
    assert not b2.sort(MEASUREMENTS).equals(b3.sort(MEASUREMENTS)), (
        "batch 2 and 3 are identical — the fixture demonstrates nothing"
    )

    mean_2 = b2.filter(pl.col("variety") == "Setosa")["petal.length"].mean()
    mean_3 = b3.filter(pl.col("variety") == "Setosa")["petal.length"].mean()
    assert abs(mean_2 - mean_3) > 0.3, (
        "the recalibration must be visible on a chart, not lost in noise"
    )

    untouched_2 = b2.filter(pl.col("variety") != "Setosa").sort(MEASUREMENTS)
    untouched_3 = b3.filter(pl.col("variety") != "Setosa").sort(MEASUREMENTS)
    assert untouched_2.equals(untouched_3), "batch 3 must touch Setosa only"


def test_the_recalibration_lands_on_a_variety_that_already_existed(batches) -> None:
    """Setosa, not the newest arrival.

    Correcting a variety that arrived with its own batch would be
    indistinguishable from that batch simply adding rows. Changing one that the
    *earlier* versions already held is what makes time travel to those versions
    show something different — the hard half.
    """
    b1, b3 = batches[BATCH_ORDER[0]], batches[BATCH_ORDER[2]]

    assert "Setosa" in set(b1["variety"].unique())
    mean_first = b1["petal.length"].mean()
    mean_after = b3.filter(pl.col("variety") == "Setosa")["petal.length"].mean()
    assert abs(mean_first - mean_after) > 0.3


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


def _components(filename: str) -> dict[str, dict]:
    raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
    return {component["tag"]: component for component in raw["components"]}


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


def test_versions_are_not_a_chain_of_supersets() -> None:
    """A diff that only appends never exercises removal.

    The earlier fixture was a strict superset chain, which let the component
    history modal look correct while only pinning data: nothing was ever
    removed, and no existing component ever changed meaning.
    """
    sets = [set(_components(f)) for f in DASHBOARD_ORDER]

    removals = [
        (DASHBOARD_ORDER[i], sorted(sets[i] - sets[i + 1]))
        for i in range(len(sets) - 1)
        if sets[i] - sets[i + 1]
    ]
    assert removals, "no version ever removes a component; restore is untested"

    returning = sets[0].union(*sets)
    assert any(
        tag not in sets[i] and tag in sets[i + 1] and any(tag in s for s in sets[:i])
        for tag in returning
        for i in range(len(sets) - 1)
    ), "no component is removed and later restored, which is the hardest restore case"


def test_every_surviving_component_changes_between_versions() -> None:
    """Otherwise its history shows two identical renders.

    The failure this prevents is not an error: the modal renders both versions
    perfectly and they look the same, which reads as the feature being broken
    rather than as nothing having happened.

    ``regenerate_dashboards.py`` enforces this when writing the YAMLs; this
    asserts the files on disk still hold it.
    """
    previous: dict[str, dict] | None = None
    previous_name = ""

    for filename in DASHBOARD_ORDER:
        current = _components(filename)
        if previous is not None:
            for tag in sorted(set(previous) & set(current)):
                before = {k: previous[tag].get(k) for k in VISIBLE_FIELDS}
                after = {k: current[tag].get(k) for k in VISIBLE_FIELDS}
                assert before != after, (
                    f"{tag} is identical in {previous_name} and {filename} — "
                    "its component history would show two identical renders"
                )
        previous, previous_name = current, filename


def test_a_component_changes_what_it_measures_not_just_where_it_sits() -> None:
    """Layout churn alone would be a weak demo.

    At least one component has to change the *question it asks* between
    versions, since that is the case proving component history pins the stored
    definition rather than recomputing with today's.
    """
    versions = [_components(f) for f in DASHBOARD_ORDER]
    shared = set(versions[0]).intersection(*[set(v) for v in versions[1:]])

    retyped = [
        tag
        for tag in shared
        if len({(v[tag].get("aggregation"), v[tag].get("column_name")) for v in versions}) > 1
    ]
    assert retyped, (
        "no component that exists in every version ever changes its aggregation "
        "or column, so nothing proves the definition is pinned"
    )


def test_dashboard_components_bind_to_this_project() -> None:
    """A component pointing at the wrong collection renders empty, not broken."""
    for filename in DASHBOARD_ORDER:
        raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
        for component in raw["components"]:
            if component["component_type"] == "text":
                continue
            assert component["data_collection_tag"] == "iris_versioned_table"
            assert component["workflow_tag"] == "python/iris_versioned_workflow"


def test_figure_sequences_are_real_lists() -> None:
    """A quoted list degrades the chart silently.

    Plotly Express reads a string `color_discrete_sequence` as a sequence of
    single characters, which knocks a histogram down to a scatter. It renders,
    so nothing reports an error — this was a real bug in v1.
    """
    for filename in DASHBOARD_ORDER:
        raw = yaml.safe_load((DASHBOARDS_DIR / filename).read_text())
        for component in raw["components"]:
            kwargs = component.get("dict_kwargs") or {}
            sequence = kwargs.get("color_discrete_sequence")
            if sequence is None:
                continue
            assert isinstance(sequence, list), (
                f"{filename}:{component['tag']} has a quoted "
                "color_discrete_sequence; Plotly would read it character by character"
            )


# ── the documented sequence, executed ───────────────────────────────────────


def test_the_documented_ingest_sequence_produces_four_versions(tmp_path) -> None:
    """Run the README's sequence against a real Delta table.

    Everything above validates the fixture's *inputs*. This validates the claim
    the README actually makes: stage a batch, ingest, repeat, and end up with
    four Delta versions you can time-travel between.

    Uses the same `write_delta_table_versioned` the CLI calls, against a local
    path — no Mongo, no S3, no API — so the claim is executed rather than
    reasoned about.

    The last assertion is the one that matters for the dataset-version picker:
    two versions with identical row counts and identical varieties must still be
    distinguishable by value, or a time-travel read that silently returned
    current data would look correct.
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

    assert len(DeltaTable(table_path).history()) == 4

    heights = [pl.read_delta(table_path, version=v).height for v in range(4)]
    assert heights == [50, 100, 100, 150]

    at_v1 = pl.read_delta(table_path, version=1)
    at_v2 = pl.read_delta(table_path, version=2)

    mean_v1 = at_v1.filter(pl.col("variety") == "Setosa")["petal.length"].mean()
    mean_v2 = at_v2.filter(pl.col("variety") == "Setosa")["petal.length"].mean()
    assert abs(mean_v1 - mean_v2) > 0.3, (
        "two versions of the same shape must differ by value, or a time-travel "
        "read that returned current data would be indistinguishable from a correct one"
    )
