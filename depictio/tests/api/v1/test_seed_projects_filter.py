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


def test_bioimage_examples_is_an_optional_dataset():
    """The bioimage examples ship images, so they are opt-in like the fixture."""
    from depictio.api.v1.db_init_reference_datasets import (
        OPTIONAL_DATASETS,
        STATIC_IDS,
        ReferenceDatasetRegistry,
    )

    assert "bioimage_examples" in OPTIONAL_DATASETS
    assert "bioimage_examples" in STATIC_IDS
    assert ReferenceDatasetRegistry.resolve_dataset_rel_path("bioimage_examples").endswith(
        "bioimage_examples"
    )


@pytest.mark.parametrize(
    "dashboard_name,dataset",
    [
        ("iris", "iris"),
        # Child tabs are dashboards in their own right and must map to their
        # parent dataset. An equality test mapped them to themselves, so
        # DEPICTIO_SEED_PROJECTS=iris seeded the overview and dropped the tab
        # hanging off it — a half-seeded family, silently.
        ("iris_petal", "iris"),
        ("penguins", "penguins"),
        ("penguins_island_season", "penguins"),
        ("ampliseq_multiqc", "ampliseq"),
        ("ampliseq_phylogeny", "ampliseq"),
        ("advanced_viz_volcano", "advanced_viz_showcase"),
        ("advanced_viz_upset", "advanced_viz_showcase"),
        ("viralrecon_variants", "viralrecon"),
        ("catalog_conformance_overview", "catalog_conformance"),
        ("bioimage_fluorescence", "bioimage_examples"),
        ("bioimage_multi_sample", "bioimage_examples"),
        ("bioimage_ome_tiff", "bioimage_examples"),
        ("bioimage_spatialdata", "bioimage_examples"),
        ("bioimage_ngff05", "bioimage_examples"),
    ],
)
def test_dataset_of_dashboard_mapping(dashboard_name, dataset):
    assert _dataset_of_dashboard(dashboard_name) == dataset


def test_only_iris_keeps_only_iris_dashboards():
    """A filter of {'iris'} should keep exactly the iris dashboard."""
    names = [
        "iris",
        "iris_petal",
        "penguins",
        "penguins_island_season",
        "ampliseq_multiqc",
        "advanced_viz_volcano",
        "viralrecon_variants",
    ]
    only = {"iris"}
    kept = [n for n in names if _dataset_of_dashboard(n) in only]
    assert kept == ["iris", "iris_petal"]


def test_extra_widens_the_allowlist_without_replacing_it():
    """`only` narrows the default set; `extra` adds to whatever survived."""
    names = ["iris", "penguins", "viralrecon_variants", "catalog_conformance_overview"]
    only, extra = {"iris"}, {"catalog_conformance"}
    kept = [n for n in names if _dataset_of_dashboard(n) in only | extra]
    assert kept == ["iris", "catalog_conformance_overview"]


def test_bioimage_dashboards_follow_the_static_id_table():
    """Every seeded bioimage tab maps back to the project and has a pinned id.

    `create_initial_dashboards` names them `bioimage_<slug>`; a slug missing
    from STATIC_IDS would make `reseed_project --dashboards-only` skip the tab.
    """
    from depictio.api.v1.db_init_reference_datasets import STATIC_IDS

    dashboards = STATIC_IDS["bioimage_examples"]["dashboards"]
    assert set(dashboards) == {
        "bioimage_fluorescence",
        "bioimage_spatial",
        "bioimage_volume",
        "bioimage_multi_sample",
        "bioimage_ome_tiff",
        "bioimage_spatialdata",
        "bioimage_ngff05",
    }
    assert all(_dataset_of_dashboard(name) == "bioimage_examples" for name in dashboards)
    # The main tab carries the project id, as in the other multi-tab projects.
    assert dashboards["bioimage_fluorescence"] == STATIC_IDS["bioimage_examples"]["project"]


@pytest.mark.parametrize(
    "only,extra,expected",
    [
        # `depictio local up --examples bioimage_examples`: the allowlist holds
        # nothing but an optional project, and that project alone is seeded.
        ({"bioimage_examples"}, set(), ["bioimage_examples"]),
        ({"iris", "bioimage_examples"}, set(), ["iris", "bioimage_examples"]),
        ({"iris"}, {"bioimage_examples"}, ["iris", "bioimage_examples"]),
        ({"iris"}, set(), ["iris"]),
    ],
)
def test_optional_dataset_is_seeded_when_named(monkeypatch, only, extra, expected):
    import asyncio

    from depictio.api.v1 import db_init_reference_datasets as mod

    seen: list[str] = []

    async def record(cls, dataset_name, admin_user, token_payload):
        seen.append(dataset_name)
        # Seeding is best-effort per dataset, so raising here just moves on.
        raise RuntimeError("recorded")

    monkeypatch.setattr(
        mod.ReferenceDatasetRegistry, "create_reference_project", classmethod(record)
    )
    asyncio.run(
        mod.create_reference_datasets(admin_user=None, token_payload={}, only=only, extra=extra)
    )
    assert seen == expected


@pytest.mark.parametrize(
    "only,extra,kept",
    [
        ({"bioimage_examples"}, set(), True),
        (None, {"bioimage_examples"}, True),
        (None, set(), False),
        ({"iris"}, set(), False),
    ],
)
def test_bioimage_dashboards_follow_the_seed_request(monkeypatch, only, extra, kept):
    import asyncio

    from depictio.api.v1 import db_init

    created: list[str] = []

    async def record(admin_user, dashboard_json_path, static_dc_id):
        created.append(dashboard_json_path)
        return None

    monkeypatch.setattr(db_init, "create_dashboard_from_json", record)
    asyncio.run(db_init.create_initial_dashboards(admin_user=None, only=only, extra=extra))

    bio = [p for p in created if "bioimage_examples" in p]
    assert len(bio) == (7 if kept else 0)
