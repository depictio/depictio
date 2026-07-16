"""Unit tests for the ``benchmark/`` performance-harness config generation.

These assert the *generated* project/dashboard configs parse against the real
Pydantic models, so a broken template is caught in CI without needing a live
stack. Data generation (Polars) is exercised at a tiny size and skipped if
Polars is unavailable.
"""

import sys
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


def test_matrix_expand_skips_links_with_one_dc():
    spec = MatrixSpec(
        sizes=["10mb"],
        n_components=[5],
        n_dcs=[1, 2],
        connect=[ConnectMode.INDEPENDENT, ConnectMode.LINKS],
        visu=[VisuType.FIGURE],
    )
    cells = spec.expand()
    # independent allows 1 or 2 DCs; links requires >= 2 -> only the n_dcs=2 case.
    assert any(c.connect is ConnectMode.LINKS for c in cells)
    assert all(c.n_dcs >= 2 for c in cells if c.connect is ConnectMode.LINKS)
    assert any(c.connect is ConnectMode.INDEPENDENT and c.n_dcs == 1 for c in cells)


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


def test_project_has_links_block():
    project = build_project(_cell(ConnectMode.LINKS, n_dcs=3), dataset_dir="/tmp/x")
    assert len(project["links"]) == 2
    link = project["links"][0]
    assert link["source_column"] == "individual_id"
    assert link["target_type"] == "table"
    assert len(link["source_dc_id"]) == 24 and len(link["target_dc_id"]) == 24


def test_generated_dashboard_parses_with_pydantic():
    """The generated dashboard YAML must validate against DashboardDataLite."""
    from depictio.models.models.dashboards import DashboardDataLite

    cell = _cell(ConnectMode.LINKS, n_dcs=2, n_components=4)
    project = build_project(cell, dataset_dir="/tmp/x")
    dashboard = build_dashboard(cell, project)

    import yaml

    lite = DashboardDataLite.from_yaml(yaml.safe_dump(dashboard))
    # figure+table components (4) + 2 interactive filters added for links mode
    assert len(lite.components) == 6
    types = {c.component_type for c in lite.components}
    assert "interactive" in types


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
