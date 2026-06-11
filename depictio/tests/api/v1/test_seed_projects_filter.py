"""Tests for the reference-dataset seed allowlist (DEPICTIO_SEED_PROJECTS).

Two seed controls exist on startup:

* ``DEPICTIO_DISABLE_EXAMPLE_DASHBOARDS`` (bool) — skip *all* seeding.
* ``DEPICTIO_SEED_PROJECTS`` (CSV) — seed *only* the named reference projects
  (default empty = seed all). This file covers the parsing of that CSV into a
  filter set and the name → dataset mapping used to gate dashboard creation.
"""

from __future__ import annotations

import pytest

from depictio.api.v1.configs.settings_models import Settings
from depictio.api.v1.db_init import _dataset_of_dashboard


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", None),
        ("   ", None),
        ("iris", {"iris"}),
        ("iris,penguins", {"iris", "penguins"}),
        (" iris , penguins ", {"iris", "penguins"}),
        ("iris,,viralrecon,", {"iris", "viralrecon"}),
    ],
)
def test_seed_projects_filter_parsing(monkeypatch, raw, expected):
    # client context skips the server-secret enforcement validator.
    monkeypatch.setenv("DEPICTIO_CONTEXT", "client")
    monkeypatch.setenv("DEPICTIO_SEED_PROJECTS", raw)
    assert Settings().seed_projects_filter == expected


def test_seed_projects_default_is_all(monkeypatch):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "client")
    monkeypatch.delenv("DEPICTIO_SEED_PROJECTS", raising=False)
    settings = Settings()
    assert settings.seed_projects == ""
    assert settings.seed_projects_filter is None  # None => seed everything


@pytest.mark.parametrize(
    "dashboard_name,dataset",
    [
        ("iris", "iris"),
        ("penguins", "penguins"),
        ("ampliseq_multiqc", "ampliseq"),
        ("ampliseq_phylogeny", "ampliseq"),
        ("advanced_viz_volcano", "advanced_viz_showcase"),
        ("advanced_viz_upset", "advanced_viz_showcase"),
        ("viralrecon_variants", "viralrecon"),
    ],
)
def test_dataset_of_dashboard_mapping(dashboard_name, dataset):
    assert _dataset_of_dashboard(dashboard_name) == dataset


def test_only_iris_keeps_only_iris_dashboards():
    """A filter of {'iris'} should keep exactly the iris dashboard."""
    names = [
        "iris",
        "penguins",
        "ampliseq_multiqc",
        "advanced_viz_volcano",
        "viralrecon_variants",
    ]
    only = {"iris"}
    kept = [n for n in names if _dataset_of_dashboard(n) in only]
    assert kept == ["iris"]
