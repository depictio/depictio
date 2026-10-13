"""Declared template variable defaults (e.g. ``GENOME: hg38``).

A variable declared in ``template.variables`` with a ``default`` must resolve
``{NAME}`` placeholders both in template.yaml and in the dashboard YAMLs (which
``import_dashboards_from_template`` substitutes with the variables returned by
``resolve_template``), while an explicit ``--var`` still wins and a default
never fires an ``if_var_present`` conditional.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from depictio.cli.cli.utils import templates as templates_mod
from depictio.cli.cli.utils.templates import (
    apply_variable_defaults,
    resolve_template,
    substitute_template_variables,
)
from depictio.models.models.templates import TemplateMetadata

TEMPLATE_YAML = """
template:
  template_id: "test/genome/1.0.0"
  description: "Template exercising a defaulted GENOME variable"
  version: "1.0.0"
  variables:
    - name: "DATA_ROOT"
      description: "Run directory"
      required: true
    - name: "GENOME"
      description: "Genome build of the run"
      required: true
      default: "hg38"
  dashboards:
    - "dashboards/main.yaml"
  conditional:
    - if_var_present: "GENOME"
      remove_dc_tags: ["peaks"]
name: "Genome test"
description: "Peaks called against {GENOME}"
workflows:
  - name: "wf"
    engine: {name: "nextflow"}
    data_collections:
      - data_collection_tag: "peaks"
        description: "Peaks on {GENOME}"
        config: {type: "Table"}
"""

DASHBOARD_YAML = """
main_dashboard:
  title: "Locus"
components:
  - tag: "locus-navigator"
    component_type: "advanced_viz"
    viz_kind: "genome_view"
    config:
      assembly: "{GENOME}"
      annotation: "{GENOME}_genes"
"""


@pytest.fixture
def template_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tdir = tmp_path / "template"
    (tdir / "dashboards").mkdir(parents=True)
    (tdir / "template.yaml").write_text(TEMPLATE_YAML)
    (tdir / "dashboards" / "main.yaml").write_text(DASHBOARD_YAML)
    monkeypatch.setattr(templates_mod, "locate_template", lambda _tid: tdir / "template.yaml")
    return tdir


def _dc_tags(config: dict) -> list[str]:
    return [
        dc["data_collection_tag"] for wf in config["workflows"] for dc in wf["data_collections"]
    ]


def test_model_exposes_defaults() -> None:
    meta = TemplateMetadata(
        template_id="t/x/1.0.0",
        description="d",
        version="1.0.0",
        variables=[
            {"name": "DATA_ROOT", "description": "root"},
            {"name": "GENOME", "description": "build", "default": "hg38"},
        ],
    )
    assert meta.get_variable_defaults() == {"GENOME": "hg38"}
    assert apply_variable_defaults({"DATA_ROOT": "/r"}, meta) == {
        "DATA_ROOT": "/r",
        "GENOME": "hg38",
    }
    assert apply_variable_defaults({"GENOME": "mm10"}, meta)["GENOME"] == "mm10"


def test_default_resolves_template_and_dashboard(template_dir: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config, _meta, origin, dashboards, variables = resolve_template(
        "test/genome/1.0.0", str(run_dir)
    )

    # Required GENOME is satisfied by its default, and substituted in template.yaml.
    assert variables["GENOME"] == "hg38"
    assert config["description"] == "Peaks called against hg38"
    assert origin.variables["GENOME"] == "hg38"
    # A default does not count as provided: the if_var_present rule did not fire.
    assert _dc_tags(config) == ["peaks"]
    assert config["workflows"][0]["data_collections"][0]["description"] == "Peaks on hg38"

    # Dashboard YAMLs are substituted with the same variables at import time.
    assert dashboards == [(template_dir / "dashboards" / "main.yaml").resolve()]
    dashboard = substitute_template_variables(yaml.safe_load(dashboards[0].read_text()), variables)
    viz = dashboard["components"][0]["config"]
    assert viz == {"assembly": "hg38", "annotation": "hg38_genes"}


def test_explicit_var_overrides_default(template_dir: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config, _meta, _origin, _dashboards, variables = resolve_template(
        "test/genome/1.0.0", str(run_dir), extra_vars={"GENOME": "mm10"}
    )
    assert variables["GENOME"] == "mm10"
    assert config["description"] == "Peaks called against mm10"
    # An explicit value is "provided": the if_var_present rule fires.
    assert _dc_tags(config) == []


def test_declared_group_col_default_beats_generic_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A template's own GROUP_COL default wins over the CLI's ``__no_group__`` sentinel."""
    tdir = tmp_path / "template"
    (tdir / "dashboards").mkdir(parents=True)
    text = TEMPLATE_YAML.replace(
        "  dashboards:\n",
        '    - name: "GROUP_COL"\n'
        '      description: "Design column"\n'
        '      default: "Condition"\n'
        "  dashboards:\n",
        1,
    )
    (tdir / "template.yaml").write_text(text)
    (tdir / "dashboards" / "main.yaml").write_text(DASHBOARD_YAML)
    monkeypatch.setattr(templates_mod, "locate_template", lambda _tid: tdir / "template.yaml")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    _config, _meta, _origin, _dashboards, variables = resolve_template(
        "test/genome/1.0.0", str(run_dir)
    )
    assert variables["GROUP_COL"] == "Condition"
    # Variables without a declared default still get the generic sentinels.
    assert variables["GROUP_COL_DISPLAY"] == "Group"
