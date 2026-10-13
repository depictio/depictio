"""A text tile's `logo`: an image drawn in place of its title."""

import pytest
from pydantic import ValidationError

from depictio.models.components.lite import TextLiteComponent
from depictio.models.models.dashboards import DashboardDataLite

YAML = """
title: T
components:
  - component_type: text
    tag: hero
    title: nf-core/ampliseq
    logo: /assets/images/workflows/ampliseq.png
    logo_dark: /assets/images/workflows/ampliseq_dark.png
"""


@pytest.mark.parametrize(
    "path",
    ["/assets/images/workflows/ampliseq.png", "https://example.org/logo.SVG", "/a/b.webp"],
)
def test_image_paths_are_accepted(path):
    assert TextLiteComponent(title="T", logo=path).logo == path


@pytest.mark.parametrize(
    "path", ["mdi:dna", "assets/logo.png", "http://example.org/logo.png", "/assets/logo.txt"]
)
def test_anything_else_is_refused(path):
    with pytest.raises(ValidationError, match="must be an image path"):
        TextLiteComponent(title="T", logo_dark=path)


def test_the_logo_survives_the_round_trip():
    full = DashboardDataLite.from_yaml(YAML).to_full()
    stored = full["stored_metadata"][0]
    assert stored["logo"] == "/assets/images/workflows/ampliseq.png"
    assert stored["logo_dark"] == "/assets/images/workflows/ampliseq_dark.png"
    again = DashboardDataLite.from_yaml(DashboardDataLite.from_full(full).to_yaml()).to_full()
    assert again["stored_metadata"][0]["logo"] == stored["logo"]
    assert again["stored_metadata"][0]["logo_dark"] == stored["logo_dark"]


def test_no_logo_writes_none():
    full = DashboardDataLite.from_yaml(
        "title: T\ncomponents:\n  - {component_type: text, title: T}\n"
    ).to_full()
    assert "logo:" not in DashboardDataLite.from_full(full).to_yaml()
