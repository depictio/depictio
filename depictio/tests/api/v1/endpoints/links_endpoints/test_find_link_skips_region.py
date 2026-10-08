"""``_find_link_for_resolution`` on a pair of collections that carries both a
direct link and a ``region`` link.

sarek declares a ``stage`` link and the locus region link between
``mosdepth_windows`` and ``mosdepth_targets``. A value lookup that returned the
region link ended in ``Unknown resolver type: region`` from the resolver
registry (SK-D15, 2026-09-23): a region link renames coordinates, it never
resolves values, so it must only match when asked for by name.
"""

import pytest

from depictio.api.v1.endpoints.links_endpoints.routes import _find_link_for_resolution

pytestmark = pytest.mark.no_db

WINDOWS_DC = "6a19541470f089f587c39c64"
TARGETS_DC = "6a1954189fa2f2d1ffc39c76"


def _link(link_id: str, resolver: str, source_column: str, **config) -> dict:
    return {
        "id": link_id,
        "enabled": True,
        "source_dc_id": WINDOWS_DC,
        "source_column": source_column,
        "target_dc_id": TARGETS_DC,
        "target_type": "table",
        "link_config": {"resolver": resolver, **config},
    }


REGION = _link(
    "6a19541e70f089f587c39c6a", "region", "chrom", columns={"chrom": "chrom", "pos": "pos"}
)
STAGE = _link("6a19541e70f089f587c39c6b", "direct", "stage", target_field="stage")


def test_value_lookup_skips_the_region_link_declared_first():
    project = {"links": [REGION, STAGE]}
    link = _find_link_for_resolution(project, WINDOWS_DC, TARGETS_DC)
    assert link is not None
    assert str(link.id) == STAGE["id"]


def test_value_lookup_finds_nothing_when_only_a_region_link_exists():
    project = {"links": [REGION]}
    assert _find_link_for_resolution(project, WINDOWS_DC, TARGETS_DC) is None


def test_region_link_still_matches_when_asked_for_by_name():
    project = {"links": [STAGE, REGION]}
    link = _find_link_for_resolution(project, WINDOWS_DC, TARGETS_DC, resolver="region")
    assert link is not None
    assert str(link.id) == REGION["id"]
