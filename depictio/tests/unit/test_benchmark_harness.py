"""Unit tests for the ``benchmark/`` performance-harness config generation.

These assert the *generated* project/dashboard configs parse against the real
Pydantic models, so a broken template is caught in CI without needing a live
stack. Data generation (Polars) is exercised at a tiny size and skipped if
Polars is unavailable.
"""

import sys
import time
from pathlib import Path

import pytest

# The harness lives at the repo root (``benchmark/``), which is not part of the
# installed ``depictio`` package — make sure it is importable from the tests.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.configgen import (  # noqa: E402
    bindable_tags,
    build_dashboard,
    build_project,
    write_configs,
)
from benchmark.matrix import (  # noqa: E402
    Cell,
    ConnectMode,
    MatrixSpec,
    VisuType,
)

pytestmark = pytest.mark.no_db


def _cell(connect=ConnectMode.JOINS, n_dcs=2, n_components=4):
    return Cell(
        size="10mb",
        n_components=n_components,
        n_dcs=n_dcs,
        connect=connect,
        visu=(VisuType.FIGURE, VisuType.TABLE),
    )


def test_matrix_expand_skips_adversarial_links_with_one_dc():
    spec = MatrixSpec(
        sizes=["10mb"],
        n_components=[5],
        n_dcs=[1, 2],
        connect=[ConnectMode.INDEPENDENT, ConnectMode.LINKS_ADVERSARIAL],
        visu=[VisuType.FIGURE],
    )
    cells = spec.expand()
    # independent allows 1 or 2 DCs; the adversarial links mode needs >= 2 DCs
    # (there must be something to link to) -> only the n_dcs=2 case.
    adversarial = [c for c in cells if c.connect is ConnectMode.LINKS_ADVERSARIAL]
    assert adversarial
    assert all(c.n_dcs >= 2 for c in adversarial)
    assert any(c.connect is ConnectMode.INDEPENDENT and c.n_dcs == 1 for c in cells)


def test_matrix_pins_realistic_links_to_three_dcs():
    """``links`` is a fixed three-collection topology, whatever --dcs says."""
    from benchmark.matrix import LINKED_N_DCS

    cells = MatrixSpec(
        sizes=["10mb"],
        n_components=[5],
        n_dcs=[1, 2, 5],
        connect=[ConnectMode.LINKS],
        visu=[VisuType.FIGURE],
    ).expand()
    assert len(cells) == 1, "the --dcs values must collapse to one linked cell"
    assert cells[0].n_dcs == LINKED_N_DCS


def test_matrix_rejects_unknown_size():
    with pytest.raises(ValueError):
        MatrixSpec(sizes=["999tb"])


def test_bindable_tags_joins_vs_raw():
    joins = bindable_tags(_cell(ConnectMode.JOINS, n_dcs=3))
    assert joins == ["joined_join_0_1", "joined_join_0_2"]
    raw = bindable_tags(_cell(ConnectMode.INDEPENDENT, n_dcs=3))
    assert raw == ["dc_0", "dc_1", "dc_2"]


def test_project_has_joins_block():
    project = build_project(_cell(ConnectMode.JOINS, n_dcs=2), dataset_dir="/tmp/x")
    assert project["project_type"] == "advanced"
    assert len(project["joins"]) == 1
    assert project["joins"][0]["left_dc"] == "dc_0"
    assert project["joins"][0]["right_dc"] == "dc_1"
    # every DC carries a stable id so link references resolve without templates
    dcs = project["workflows"][0]["data_collections"]
    assert all(len(dc["id"]) == 24 for dc in dcs)


def test_adversarial_project_has_links_block():
    project = build_project(_cell(ConnectMode.LINKS_ADVERSARIAL, n_dcs=3), dataset_dir="/tmp/x")
    assert len(project["links"]) == 2
    link = project["links"][0]
    assert link["source_column"] == "individual_id"
    assert link["target_type"] == "table"
    assert len(link["source_dc_id"]) == 24 and len(link["target_dc_id"]) == 24


def test_generated_dashboard_parses_with_pydantic():
    """The generated dashboard YAML must validate against DashboardDataLite."""
    from depictio.models.models.dashboards import DashboardDataLite

    cell = _cell(ConnectMode.LINKS_ADVERSARIAL, n_dcs=2, n_components=4)
    project = build_project(cell, dataset_dir="/tmp/x")
    dashboard = build_dashboard(cell, project)

    import yaml

    lite = DashboardDataLite.from_yaml(yaml.safe_dump(dashboard))
    # figure+table components (4) + the top strip: 2 interactive filters and
    # 2 metric cards, both added on every connect mode.
    assert len(lite.components) == 8
    types = {c.component_type for c in lite.components}
    assert "interactive" in types
    # Cards must be present: they were previously absent from the matrix, which
    # hid the filtered-card path (the one that can't use precomputed specs)
    # from every benchmark number.
    assert "card" in types
    assert sum(c.component_type == "card" for c in lite.components) == 2


def test_filters_added_in_joins_mode_bind_to_joined_table():
    """Filters are added on all connect modes (not just links); in joins mode
    they must bind to the joined table so cross-filtering actually narrows the
    same frame the figures/tables render from."""
    cell = _cell(ConnectMode.JOINS, n_dcs=2, n_components=4)
    dashboard = build_dashboard(cell, build_project(cell, dataset_dir="/tmp/x"))
    filters = [c for c in dashboard["components"] if c["component_type"] == "interactive"]
    assert len(filters) == 2
    assert {f["column_name"] for f in filters} == {"species", "body_mass_g"}
    assert all(f["data_collection_tag"] == "joined_join_0_1" for f in filters)


def test_readable_title_decodes_axes():
    from benchmark.configgen import readable_title

    cell = Cell(
        size="1gb",
        n_components=5,
        n_dcs=2,
        connect=ConnectMode.JOINS,
        visu=(VisuType.FIGURE, VisuType.TABLE, VisuType.ADVANCED_VIZ),
    )
    assert readable_title(cell) == "1 GB · 5 comp · 2 DC · joins · figure+table+adv-viz"


def test_advanced_viz_config_parses():
    from depictio.models.models.dashboards import DashboardDataLite

    cell = Cell(
        size="10mb",
        n_components=2,
        n_dcs=2,
        connect=ConnectMode.JOINS,
        visu=(VisuType.ADVANCED_VIZ,),
    )
    project = build_project(cell, dataset_dir="/tmp/x")
    dashboard = build_dashboard(cell, project)

    import yaml

    lite = DashboardDataLite.from_yaml(yaml.safe_dump(dashboard))
    viz_kinds = {getattr(c, "viz_kind", None) for c in lite.components}
    assert "volcano" in viz_kinds


def test_write_configs_roundtrip(tmp_path):
    cell = _cell(ConnectMode.JOINS, n_dcs=2)
    gen = write_configs(cell, dataset_dir=str(tmp_path / "data"), out_dir=str(tmp_path / "cfg"))
    assert Path(gen.project_path).exists()
    assert Path(gen.dashboard_path).exists()
    assert gen.workflow_tag.startswith("python/")


def test_datagen_tiny(tmp_path):
    pytest.importorskip("polars")
    pytest.importorskip("numpy")
    from benchmark.datagen import generate_dataset

    manifest = generate_dataset(64 * 1024, n_dcs=2, dataset_dir=tmp_path / "d")
    assert manifest.rows_total > 0
    # each run dir has one csv per DC, sharing the same individual_ids
    run_dirs = sorted((tmp_path / "d").glob("run_*"))
    assert run_dirs
    assert (run_dirs[0] / "dc_0.csv").exists()
    assert (run_dirs[0] / "dc_1.csv").exists()


# ---------------------------------------------------------------------------
# Filter rounds: one filter change on a warm dashboard, timed the way the
# viewer actually issues it (bounded concurrency).
# ---------------------------------------------------------------------------


def test_filter_payload_carries_the_origin_dc():
    """The payload must name the DC the filter comes from.

    ``_resolve_link_filters`` groups filters by their source DC and only walks
    the link graph for filters belonging to another DC than the component being
    rendered. Without ``metadata.dc_id`` the filter is treated as native, and on
    a linked topology (where the column exists only on the source collection) it
    is then dropped as an unknown column — the render comes back unfiltered.
    """
    from benchmark.configgen import filter_plans
    from benchmark.runner import _filter_payload

    plan = filter_plans(_cell(ConnectMode.JOINS))[0]
    payload = _filter_payload(plan, ("Gentoo", "Adelie"), dc_id="abc123")
    assert payload[0]["value"] == ["Gentoo", "Adelie"]
    assert payload[0]["column_name"] == plan.column
    assert payload[0]["metadata"]["dc_id"] == "abc123"
    assert payload[0]["metadata"]["column_name"] == plan.column


def test_filter_round_values_are_all_distinct():
    """Successive rounds must not repeat a value.

    Re-applying a value already used would be answered by the filtered frame
    cache, so the round would time the cache instead of the filter.
    """
    from benchmark.configgen import filter_plans

    for connect in ConnectMode:
        for plan in filter_plans(_cell(connect, n_dcs=2)):
            assert len(set(plan.values)) == len(plan.values), plan.label


def test_filter_round_bounds_concurrency_and_times_first_and_last(monkeypatch):
    """The round must never exceed the viewer's in-flight limit."""
    import threading

    from benchmark import runner

    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def fake_render(client, base, headers, dashboard_id, comp, filters):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.02)
        with lock:
            in_flight -= 1
        # Passive components return {} and must be excluded from the window.
        if comp.get("component_type") == "text":
            return {}
        return {"ok": True, "wall_ms": 20.0}

    monkeypatch.setattr(runner, "_render_component", fake_render)

    components = [{"component_type": "figure", "index": str(i)} for i in range(10)]
    components.append({"component_type": "text", "index": "passive"})

    rows, first_ms, last_ms = runner._filter_round(
        None, "http://x", {}, "dash1", components, filters=[], concurrency=4
    )

    assert peak <= 4, f"fired {peak} concurrently, viewer caps at 4"
    assert len(rows) == 11
    assert sum(1 for _, m, _ in rows if m) == 10  # the text component is untimed
    assert 0 < first_ms <= last_ms
    # 10 timed components through a pool of 4 means at least 3 waves.
    assert last_ms >= 3 * 20.0


def test_filter_round_result_catch_up_and_serialization():
    from benchmark.metrics import FilterRoundResult

    r = FilterRoundResult(
        cell_slug="c",
        size="1gb",
        size_bytes=1 << 30,
        n_components=25,
        n_dcs=2,
        connect="links",
        time_to_first_ms=120.0,
        time_to_last_ms=3400.0,
    )
    assert r.catch_up_ms == 3280.0
    d = r.to_dict()
    assert d["time_to_last_ms"] == 3400.0
    assert d["filter_values"] == []


def test_dashboard_load_rows_separate_cold_from_warm():
    """A cold open and a warm one must be distinguishable after the fact.

    They are the same request set at the same concurrency; only the server's
    cache state differs. Pooling them would average a first visit with a
    revisit and describe neither.
    """
    from benchmark import runner
    from benchmark.matrix import Cell, ConnectMode, VisuType

    cell = Cell(
        size="1gb",
        n_components=8,
        n_dcs=3,
        connect=ConnectMode.LINKS,
        visu=(VisuType.FIGURE,),
    )
    loaded = [
        # (component, metrics, when it landed relative to the shared t0)
        ({"component_type": "figure", "index": "0"}, {"ok": True, "wall_ms": 900.0}, 900.0),
        ({"component_type": "card", "index": "1"}, {"ok": True, "wall_ms": 120.0}, 120.0),
        ({"component_type": "table", "index": "2"}, {"ok": True, "wall_ms": 700.0}, 700.0),
        # A failure returns fast and must not be credited as the first paint.
        ({"component_type": "card", "index": "3"}, {"ok": False, "wall_ms": 5.0}, 5.0),
        # Passive components are untimed and must not count as requested.
        ({"component_type": "text", "index": "4"}, {}, 3.0),
    ]

    cold = runner._dashboard_load_rows(
        cell, loaded, 1200.0, server_mode="celery_on", profile_label="hw", cache_state="cold"
    )
    warm = runner._dashboard_load_rows(
        cell, loaded, 400.0, server_mode="celery_on", profile_label="hw", cache_state="warm"
    )

    cold_summary = cold[-1]
    warm_summary = warm[-1]
    assert cold_summary["kind"] == warm_summary["kind"] == "dashboard_load"
    assert cold_summary["cache_state"] == "cold"
    assert warm_summary["cache_state"] == "warm"
    assert cold_summary["wall_ms"] == 1200.0
    assert warm_summary["wall_ms"] == 400.0
    # The untimed component is excluded from the count; the failed one is not.
    assert cold_summary["n_requested"] == 4
    assert cold_summary["n_rendered"] == 3
    assert cold_summary["ok"] is False

    assert [r["phase"] for r in cold[:-1]] == ["dashboard_load_cold"] * 4
    assert [r["phase"] for r in warm[:-1]] == ["dashboard_load"] * 4


def test_dashboard_load_reports_first_paint_and_first_chart():
    """First component, first *chart* and last component are three moments.

    On a dense dashboard they are far apart, and a single wall-clock number
    hides both of the earlier two.
    """
    from benchmark import runner
    from benchmark.matrix import Cell, ConnectMode, VisuType

    cell = Cell(
        size="1gb", n_components=8, n_dcs=3, connect=ConnectMode.LINKS, visu=(VisuType.FIGURE,)
    )
    loaded = [
        ({"component_type": "figure", "index": "0"}, {"ok": True, "wall_ms": 900.0}, 900.0),
        ({"component_type": "card", "index": "1"}, {"ok": True, "wall_ms": 120.0}, 120.0),
        ({"component_type": "advanced_viz", "index": "2"}, {"ok": True}, 640.0),
        # An interactive component isn't data-bearing and can't claim first paint.
        ({"component_type": "interactive", "index": "3"}, {"ok": True}, 30.0),
        # A failed render returns fast; crediting it would report a paint that
        # never happened.
        ({"component_type": "card", "index": "4"}, {"ok": False}, 5.0),
    ]

    summary = runner._dashboard_load_rows(
        cell, loaded, 900.0, server_mode="celery_on", profile_label="hw", cache_state="cold"
    )[-1]

    assert summary["time_to_first_ms"] == 120.0  # the card, not the interactive or the failure
    assert summary["time_to_first_figure_ms"] == 640.0  # the advanced viz beat the figure
    assert summary["wall_ms"] == 900.0


def test_report_buckets_every_render_phase():
    """``report`` must not silently drop a phase it doesn't recognise."""
    from benchmark.report import _phase_of

    assert _phase_of({"phase": "dashboard_load_cold"}) == "dashboard_load_cold"
    # Rows written before ``phase`` existed still resolve to a known bucket.
    assert _phase_of({"concurrent": True, "filtered": False}) == "dashboard_load"
    assert _phase_of({"concurrent": True, "filtered": True}) == "filter_round"
    assert _phase_of({}) == "sequential"
