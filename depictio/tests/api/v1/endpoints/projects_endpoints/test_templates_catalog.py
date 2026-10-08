"""Tests for GET /projects/templates (`list_templates_catalog`).

The catalog is filesystem-derived from the templates shipped in
``depictio/projects/`` — these assertions double as a continuous validation
of the shipped template metadata (same philosophy as the from_manifest tests
exercising the real reference template).
"""

from depictio.api.v1.endpoints.projects_endpoints.templates_catalog import (
    list_templates_catalog,
)


def test_catalog_lists_shipped_templates():
    catalog = list_templates_catalog()
    by_id = {t.template_id: t for t in catalog.templates}
    # The manifest reference template and at least one nf-core template ship.
    assert "generic/manifest-tables/1" in by_id
    assert any(tid.startswith("nf-core/") for tid in by_id)


def test_manifest_reference_template_metadata():
    catalog = list_templates_catalog()
    info = next(t for t in catalog.templates if t.template_id == "generic/manifest-tables/1")
    assert info.manifest_capable is True
    assert info.name == "Manifest Tables"
    assert info.version == "1.0.0"
    assert info.dashboards == ["dashboards/base.yaml"]
    manifest_var = next(v for v in info.variables if v.name == "MANIFEST_URL")
    assert manifest_var.required is True


def test_data_root_templates_are_not_manifest_capable():
    catalog = list_templates_catalog()
    for info in catalog.templates:
        if info.template_id.startswith("nf-core/"):
            assert info.manifest_capable is False


def _one_template_root(tmp_path, name: str):
    """A projects root holding a copy of the manifest reference template."""
    from pathlib import Path

    from depictio.cli.cli.utils import templates

    source = (
        Path(templates.__file__).resolve().parents[4]
        / "depictio"
        / "projects"
        / "generic"
        / "manifest-tables"
        / "1"
        / "template.yaml"
    )
    target = tmp_path / "projects" / "generic" / "manifest-tables" / "1" / "template.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text().replace('name: "Manifest Tables"', f'name: "{name}"'))
    return tmp_path / "projects", target


def test_catalog_walks_only_the_bundled_roots_and_is_reused_until_a_template_changes(
    tmp_path, monkeypatch
):
    """Every request used to rglob the whole repository (or site-packages) and
    parse every template. Only the bundled roots are walked now, and the
    parsed catalog is reused while no template file changed."""
    from depictio.cli.cli.utils import templates

    root, template_file = _one_template_root(tmp_path, "First")
    monkeypatch.setattr(templates, "_projects_roots", lambda: [root, root])
    listed: list = []
    real_list = templates._list_available_templates

    def _recording_list(projects_dir):
        listed.append(projects_dir)
        return real_list(projects_dir)

    monkeypatch.setattr(templates, "_list_available_templates", _recording_list)

    first = list_templates_catalog()
    assert [t.template_id for t in first.templates] == ["generic/manifest-tables/1"]
    assert first.templates[0].name == "First"
    assert listed == [root.resolve()]  # the one root, once, even listed twice

    assert list_templates_catalog() is first  # nothing changed: not parsed again
    assert len(listed) == 1

    template_file.write_text(template_file.read_text().replace('"First"', '"Second one"'))
    assert list_templates_catalog().templates[0].name == "Second one"
