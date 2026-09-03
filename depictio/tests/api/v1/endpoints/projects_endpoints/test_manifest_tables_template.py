"""The shipped ``generic/manifest-tables/1`` reference template, parsed through
the models the server uses when it instantiates a template.

``template.yaml`` must validate as ``TemplateMetadata`` and, once the manifest
variable is substituted, as ``Project`` (what ``POST /projects/from_manifest``
does). ``dashboards/base.yaml`` must parse as ``DashboardDataLite``, the format
``import_dashboard_yaml_content`` accepts, and every tile must bind to a
workflow and data collection the template actually declares. No database is
involved: the point is catching a template edit that would only fail once
someone instantiates it.
"""

import json

import pytest
import yaml
from bson import ObjectId

from depictio.cli.cli.utils.templates import locate_template, substitute_template_variables
from depictio.models.models.dashboards import DashboardDataLite
from depictio.models.models.projects import Project
from depictio.models.models.templates import TemplateMetadata

TEMPLATE_ID = "generic/manifest-tables/1"
MANIFEST_VAR = "MANIFEST_URL"
MANIFEST_URL = "https://data.example.org/run42/manifest.json"
# The only column the manifest contract guarantees on every ingested table.
JOIN_COLUMN = "depictio_manifest_id"


@pytest.fixture(scope="module")
def template_dir():
    return locate_template(TEMPLATE_ID).parent


@pytest.fixture(scope="module")
def template_cfg(template_dir) -> dict:
    return yaml.safe_load((template_dir / "template.yaml").read_text())


@pytest.fixture(scope="module")
def meta(template_cfg) -> TemplateMetadata:
    return TemplateMetadata(**template_cfg["template"])


@pytest.fixture(scope="module")
def project(template_cfg) -> Project:
    """The config as the from_manifest endpoint validates it."""
    cfg = {key: value for key, value in template_cfg.items() if key != "template"}
    cfg = substitute_template_variables(cfg, {MANIFEST_VAR: MANIFEST_URL})
    cfg["permissions"] = {"owners": [{"_id": ObjectId(), "email": "owner@example.com"}]}
    return Project(**cfg)


@pytest.fixture(scope="module")
def dashboards(template_dir, meta) -> dict[str, DashboardDataLite]:
    return {
        rel_path: DashboardDataLite.from_yaml((template_dir / rel_path).read_text())
        for rel_path in meta.dashboards
    }


def _components(dashboard: DashboardDataLite) -> list[dict]:
    """Components as plain dicts, whether they parsed as typed Lite models or
    fell through to the dict fallback."""
    return [c if isinstance(c, dict) else c.model_dump() for c in dashboard.components]


def test_metadata_binds_one_required_manifest_variable_and_no_data_root(meta):
    assert meta.template_id == TEMPLATE_ID
    assert meta.get_required_variable_names() == [MANIFEST_VAR]
    # Manifest-driven: no local layout to declare and nothing conditional.
    assert meta.structure is None
    assert meta.runs_regex is None
    assert meta.conditional == []


def test_declared_dashboards_match_the_files_on_disk(template_dir, meta):
    declared = set(meta.dashboards)
    on_disk = {
        str(path.relative_to(template_dir)) for path in (template_dir / "dashboards").glob("*.yaml")
    }
    assert declared
    assert declared == on_disk


def test_config_instantiates_as_a_manifest_driven_project(project):
    assert len(project.workflows) == 1
    workflow = project.workflows[0]
    assert workflow.data_location.locations == [MANIFEST_URL]
    for dc in workflow.data_collections:
        scan = dc.config.scan
        assert str(scan.mode).lower() == "manifest"
        assert scan.scan_parameters.manifest_url == MANIFEST_URL
        # The manifest `type` a row carries is the DC tag it lands in.
        assert scan.scan_parameters.manifest_type == dc.data_collection_tag
    # Substitution left no placeholder behind anywhere in the document.
    assert "{" + MANIFEST_VAR + "}" not in json.dumps(project.model_dump(), default=str)


def test_base_dashboard_parses_and_targets_the_template_project(dashboards, template_cfg):
    base = dashboards["dashboards/base.yaml"]
    assert base.project_tag == template_cfg["name"]
    assert base.is_main_tab
    assert base.title
    components = _components(base)
    assert components
    assert len({c["tag"] for c in components}) == len(components), "component tags must be unique"


def test_components_bind_only_to_declared_workflow_and_collections(dashboards, project):
    """Mirrors ``_resolve_workflow_tags`` in the dashboards routes: a component
    tag is ``[engine/]name``; the name part must match a workflow's ``name``
    or ``workflow_tag``, and an engine prefix must be that workflow's engine
    (the ``engine/name`` form the exporter writes back)."""
    workflows = {wf.name: wf for wf in project.workflows}
    by_tag = {wf.workflow_tag: wf for wf in project.workflows}
    dc_tags = {dc.data_collection_tag for wf in project.workflows for dc in wf.data_collections}
    bound = [c for d in dashboards.values() for c in _components(d) if c.get("data_collection_tag")]
    assert bound
    resolved: set[str] = set()
    for comp in bound:
        engine, _, name = comp["workflow_tag"].rpartition("/")
        workflow = workflows.get(name) or by_tag.get(name)
        assert workflow is not None, (
            f"{comp['tag']} binds unknown workflow {comp['workflow_tag']!r}"
        )
        if engine:
            assert engine == workflow.engine.name, f"{comp['tag']} names the wrong engine"
        resolved.add(workflow.name)
    assert resolved == set(workflows)
    # Every collection the template declares gets at least one tile.
    assert {c["data_collection_tag"] for c in bound} == dc_tags


def test_column_bound_components_use_only_the_injected_join_column(dashboards):
    """The template is schema-agnostic: nothing but the injected id column may
    be referenced, since it is the only column every manifest table carries."""
    columns = {
        c["column_name"]
        for d in dashboards.values()
        for c in _components(d)
        if c.get("column_name")
    }
    assert columns == {JOIN_COLUMN}


def test_component_sections_are_declared_in_the_matching_panel(dashboards):
    for dashboard in dashboards.values():
        filter_names = {s.name for s in dashboard.filter_sections}
        grid_names = {s.name for s in dashboard.grid_sections}
        for comp in _components(dashboard):
            section = comp.get("section")
            if not section:
                continue
            declared = filter_names if comp["component_type"] == "interactive" else grid_names
            assert section in declared, f"{comp['tag']} names undeclared section {section!r}"


def test_filters_only_bind_to_required_collections(dashboards, project):
    """A filter on an optional collection would vanish with it when the
    self-adapting import drops empty optional DCs, taking the panel with it."""
    required = {
        dc.data_collection_tag
        for wf in project.workflows
        for dc in wf.data_collections
        if not getattr(dc, "optional", False)
    }
    filters = [
        c
        for d in dashboards.values()
        for c in _components(d)
        if c["component_type"] == "interactive"
    ]
    assert filters
    assert {c["data_collection_tag"] for c in filters} <= required
