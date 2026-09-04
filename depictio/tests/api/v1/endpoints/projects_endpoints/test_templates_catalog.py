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
