"""Tests for the reference-dataset seed allowlist (DEPICTIO_SEED_PROJECTS).

Two seed controls exist on startup:

* ``DEPICTIO_DISABLE_EXAMPLE_DASHBOARDS`` (bool) — skip *all* seeding.
* ``DEPICTIO_SEED_PROJECTS`` (CSV) — seed *only* the named reference projects
  (default empty = seed all). This file covers the parsing of that CSV into a
  filter set and the name → dataset mapping used to gate dashboard creation.
* ``DEPICTIO_SEED_EXTRA_PROJECTS`` (CSV) — seed the named *optional* projects
  in addition. Additive rather than restrictive: an optional project is a test
  fixture, so asking for one must not cost you the default set.
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
    "raw,expected",
    [
        ("", set()),
        ("   ", set()),
        ("catalog_conformance", {"catalog_conformance"}),
        (" catalog_conformance , other ", {"catalog_conformance", "other"}),
    ],
)
def test_seed_extra_projects_filter_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("DEPICTIO_CONTEXT", "client")
    monkeypatch.setenv("DEPICTIO_SEED_EXTRA_PROJECTS", raw)
    assert Settings().seed_extra_projects_filter == expected


def test_seed_extra_projects_default_is_none(monkeypatch):
    """Optional projects stay out of a deployment nobody configured."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "client")
    monkeypatch.delenv("DEPICTIO_SEED_EXTRA_PROJECTS", raising=False)
    assert Settings().seed_extra_projects_filter == set()


def test_optional_datasets_are_not_in_the_default_set():
    """The default seed set and the optional set must not overlap.

    An optional dataset that also sits in `all_datasets` would seed everywhere,
    which is exactly what opting in is meant to prevent.
    """
    from depictio.api.v1.db_init_reference_datasets import OPTIONAL_DATASETS

    default_set = {"iris", "penguins", "ampliseq", "advanced_viz_showcase", "viralrecon"}
    assert set(OPTIONAL_DATASETS).isdisjoint(default_set)


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
        ("catalog_conformance_overview", "catalog_conformance"),
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


def test_extra_widens_the_allowlist_without_replacing_it():
    """`only` narrows the default set; `extra` adds to whatever survived."""
    names = ["iris", "penguins", "viralrecon_variants", "catalog_conformance_overview"]
    only, extra = {"iris"}, {"catalog_conformance"}
    kept = [n for n in names if _dataset_of_dashboard(n) in only | extra]
    assert kept == ["iris", "catalog_conformance_overview"]
