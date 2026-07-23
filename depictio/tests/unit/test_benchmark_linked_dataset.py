"""The realistic three-collection benchmark topology.

The symmetric generator gives every data collection a join key that is unique
per row, so translating a filter through a link yields millions of values —
a pathological case that must not be what ``--connect links`` measures. These
tests pin the properties that make the linked dataset realistic instead:

- ``sample_id`` has hundreds of distinct values, and that count does NOT follow
  the size tier (rows scale through the per-sample fan-out);
- all three routes exist and resolve, including the two-hop chain and the two
  competing routes to ``features``;
- successive filter rounds never repeat a value (a repeat would be answered by
  the filtered frame cache and would time the cache, not the filter).
"""

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.configgen import (  # noqa: E402
    bindable_tags,
    build_dashboard,
    build_project,
    filter_plans,
    linked_dc_ids,
)
from benchmark.datagen_linked import (  # noqa: E402
    FEATURES_TAG,
    METADATA_TAG,
    METRICS_PER_SAMPLE,
    METRICS_TAG,
    generate_linked_dataset,
)
from benchmark.matrix import Cell, ConnectMode, VisuType  # noqa: E402

pytestmark = pytest.mark.no_db


def _cell(size="10mb", n_components=6):
    return Cell(
        size=size,
        n_components=n_components,
        n_dcs=3,
        connect=ConnectMode.LINKS,
        visu=(VisuType.FIGURE, VisuType.TABLE, VisuType.ADVANCED_VIZ),
    )


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------


def test_generates_three_collections_per_run(tmp_path):
    pytest.importorskip("polars")
    pytest.importorskip("numpy")

    manifest = generate_linked_dataset(200 * 1024, tmp_path / "d", n_samples=10)
    run_dirs = sorted((tmp_path / "d").glob("run_*"))
    assert run_dirs
    for tag in (METADATA_TAG, METRICS_TAG, FEATURES_TAG):
        assert (run_dirs[0] / f"{tag}.csv").exists()

    assert manifest.n_samples == 10
    assert manifest.rows_by_dc[METADATA_TAG] == 10
    assert manifest.rows_by_dc[METRICS_TAG] == 10 * METRICS_PER_SAMPLE
    assert manifest.rows_by_dc[FEATURES_TAG] == 10 * manifest.features_per_sample


def test_join_key_cardinality_is_the_sample_count(tmp_path):
    """The whole point: ``sample_id`` is bounded by the sample count.

    Not by the row count — otherwise a filter translates into as many values as
    there are rows, which is the pathology this dataset exists to avoid.
    """
    pl = pytest.importorskip("polars")
    pytest.importorskip("numpy")

    generate_linked_dataset(200 * 1024, tmp_path / "d", n_samples=10)
    for tag in (METADATA_TAG, METRICS_TAG, FEATURES_TAG):
        frame = pl.concat(
            [pl.read_csv(shard) for shard in sorted((tmp_path / "d").rglob(f"{tag}.csv"))]
        )
        assert frame["sample_id"].n_unique() == 10, tag
        assert frame.height >= 10


def test_rows_scale_with_the_tier_but_the_join_key_does_not(tmp_path):
    pytest.importorskip("polars")
    pytest.importorskip("numpy")

    small = generate_linked_dataset(100 * 1024, tmp_path / "small", n_samples=10)
    large = generate_linked_dataset(400 * 1024, tmp_path / "large", n_samples=10)

    assert large.rows_by_dc[FEATURES_TAG] > small.rows_by_dc[FEATURES_TAG]
    assert large.n_samples == small.n_samples == 10


def test_generation_is_idempotent(tmp_path):
    pytest.importorskip("polars")
    pytest.importorskip("numpy")

    first = generate_linked_dataset(100 * 1024, tmp_path / "d", n_samples=8)
    again = generate_linked_dataset(100 * 1024, tmp_path / "d", n_samples=8)
    assert again.rows_by_dc == first.rows_by_dc
    assert again.features_per_sample == first.features_per_sample


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------


def test_project_declares_the_three_routes():
    project = build_project(_cell(), dataset_dir="/tmp/x")
    ids = linked_dc_ids(_cell())
    by_route = {(link["source_dc_id"], link["target_dc_id"]): link for link in project["links"]}
    assert set(by_route) == {
        (ids[METADATA_TAG], ids[METRICS_TAG]),
        (ids[METADATA_TAG], ids[FEATURES_TAG]),
        (ids[METRICS_TAG], ids[FEATURES_TAG]),
    }
    assert all(link["source_column"] == "sample_id" for link in project["links"])
    # Each collection carries its own schema description — they are not the same
    # three columns under different names.
    dcs = project["workflows"][0]["data_collections"]
    described = [set(dc["config"]["dc_specific_properties"]["columns_description"]) for dc in dcs]
    assert described[0] != described[2]


def test_all_three_link_routes_resolve_including_the_chain():
    """Star, chain, and two routes to one target — the definition of done.

    Uses the real graph walker so the generated project is validated against the
    code that will traverse it at render time, not against a re-implementation.
    """
    from depictio.api.v1 import filter_links

    project = build_project(_cell(), dataset_dir="/tmp/x")
    ids = linked_dc_ids(_cell())
    links = project["links"]

    to_metrics = filter_links._link_paths(links, ids[METADATA_TAG], ids[METRICS_TAG])
    assert [len(p) for p in to_metrics] == [1]

    to_features = filter_links._link_paths(links, ids[METADATA_TAG], ids[FEATURES_TAG])
    # One direct route and one through metrics; breadth-first, so direct first.
    assert sorted(len(p) for p in to_features) == [1, 2]

    chain = next(p for p in to_features if len(p) == 2)
    assert [link["source_dc_id"] for link in chain] == [ids[METADATA_TAG], ids[METRICS_TAG]]


def test_dashboard_mixes_component_types_over_the_right_collections():
    import yaml

    from depictio.models.models.dashboards import DashboardDataLite

    cell = _cell(n_components=6)
    dashboard = build_dashboard(cell, build_project(cell, dataset_dir="/tmp/x"))
    lite = DashboardDataLite.from_yaml(yaml.safe_dump(dashboard))

    by_type: dict[str, list] = {}
    for comp in lite.components:
        by_type.setdefault(comp.component_type, []).append(comp)

    # Filters on metadata: the filter origin is deliberately NOT the collection
    # the components read, so every round crosses a link.
    filters = {c.column_name for c in by_type["interactive"]}
    assert filters == {"condition", "batch", "age"}
    assert all(c.data_collection_tag == METADATA_TAG for c in by_type["interactive"])
    assert all(c.data_collection_tag == METRICS_TAG for c in by_type["card"])
    assert all(
        c.data_collection_tag == FEATURES_TAG
        for t in ("figure", "table", "advanced_viz")
        for c in by_type.get(t, [])
    )
    # Every render path is covered.
    assert {"figure", "table", "advanced_viz", "card", "interactive"} <= set(by_type)


def test_components_bind_to_the_heavy_collection():
    assert bindable_tags(_cell()) == [FEATURES_TAG]


# ---------------------------------------------------------------------------
# Filter plans
# ---------------------------------------------------------------------------


def test_linked_filter_plans_cover_both_origins():
    plans = filter_plans(_cell())
    by_tag = {p.dc_tag: p for p in plans}
    assert set(by_tag) == {METADATA_TAG, FEATURES_TAG}
    # metadata -> metrics -> features is the deepest path a filter travels.
    assert by_tag[METADATA_TAG].hops == 2
    assert by_tag[METADATA_TAG].column == "condition"
    # A filter on the collection being rendered propagates nowhere.
    assert by_tag[FEATURES_TAG].hops == 0


def test_linked_filter_rounds_never_repeat_a_value():
    for plan in filter_plans(_cell()):
        assert len(set(plan.values)) == len(plan.values), plan.label


# ---------------------------------------------------------------------------
# Hardware profile
# ---------------------------------------------------------------------------


def test_profile_records_the_limits_the_stack_was_booted_with(monkeypatch):
    """The BENCH_* variables compose reads are what the profile must report."""
    from benchmark import profile as profile_mod

    monkeypatch.setenv("BENCH_API_CPUS", "2")
    monkeypatch.setenv("BENCH_CELERY_CPUS", "2")
    monkeypatch.delenv("BENCH_MONGO_CPUS", raising=False)
    prof = profile_mod.collect_profile("mbp-2cpu")
    assert prof["label"] == "mbp-2cpu"
    assert prof["service_limits"]["api_cpus"] == "2"
    assert prof["service_limits"]["celery_cpus"] == "2"
    assert prof["service_limits"]["mongo_cpus"] == "2"  # compose default


def test_profile_reads_colima_vm_sizing(tmp_path):
    from benchmark import profile as profile_mod

    config = tmp_path / "colima.yaml"
    config.write_text("cpu: 8\nmemory: 20\ndisk: 100\nvmType: vz\n")
    vm = profile_mod._colima(config)
    assert vm == {"vcpu": 8, "memory_gb": 20, "disk_gb": 100, "vm_type": "vz"}


def test_profile_round_trips_and_describes(tmp_path):
    from benchmark import profile as profile_mod

    prof = profile_mod.collect_profile("mbp-m1max-4cpu")
    profile_mod.write_profile(tmp_path, prof)
    assert profile_mod.read_profile(tmp_path)["label"] == "mbp-m1max-4cpu"
    assert any("mbp-m1max-4cpu" in line for line in profile_mod.describe(prof))
    # A run without a profile must say so rather than invent one.
    assert profile_mod.describe({}) == ["_No hardware profile recorded for this run._"]


# ---------------------------------------------------------------------------
# Reusing an already-ingested project
# ---------------------------------------------------------------------------


def test_reused_ingest_row_reports_no_throughput():
    """A reused project ingested nothing, so its timing must not be read as one.

    ``ingest_wall_ms`` is 0 for such a row; publishing it as throughput would
    divide the row count by zero seconds and claim an infinite rate.
    """
    from benchmark.blog_metrics import _ingest
    from benchmark.metrics import IngestResult

    reused = IngestResult(
        cell_slug="c",
        ingest_wall_ms=0.0,
        import_wall_ms=5.0,
        ok=True,
        reused=True,
        rows_total=17_221_500,
    )
    assert _ingest([vars(reused)]) == {}

    measured = IngestResult(
        cell_slug="c",
        ingest_wall_ms=30_000.0,
        import_wall_ms=5.0,
        ok=True,
        rows_total=17_221_500,
        input_bytes=1024**3,
    )
    stats = _ingest([vars(measured), vars(reused)])
    assert stats["wall_s"] == 30.0
    assert stats["rows_per_s"] == 574_050
