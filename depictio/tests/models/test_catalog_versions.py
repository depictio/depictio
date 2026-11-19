"""Finer versions inside a catalog module: optional, and held to the module's.

The module (`module.yaml` `version`) is what the locks hold. An output or a
render may say which module revision it last changed in, and a module may keep a
changelog; see SCHEMA.md "Versions".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from depictio.models.components.advanced_viz.catalog import (
    CatalogEntry,
    load_catalog_entries,
    semver_key,
)


def _entry(module="1.2.0", output=None, render=None, changelog=None) -> CatalogEntry:
    out = {
        "id": "demo_out",
        "name": "Demo",
        "find": {"filename": "demo.tsv"},
        "columns": {"sample": "String", "value": "Float64"},
        "renders_as": [
            {"component": "card", "column": "value", "aggregation": "average"},
        ],
    }
    if output:
        out["version"] = output
    if render:
        out["renders_as"][0]["version"] = render
    tool = {
        "id": "demo",
        "name": "Demo",
        "version": module,
        "description": "A demo tool.",
        "homepage": "https://example.org",
        "biotools_url": None,
        "outputs": [out],
    }
    if changelog is not None:
        tool["changelog"] = changelog
    return CatalogEntry.model_validate(tool)


def test_versions_are_optional_and_fall_back_to_the_module():
    entry = _entry()
    out = entry.outputs[0]
    assert out.version is None and out.renders_as[0].version is None
    assert entry.output_version(out) == "1.2.0"


def test_an_output_and_render_may_say_when_they_last_changed():
    entry = _entry(output="1.1.0", render="1.0.0")
    assert entry.output_version(entry.outputs[0]) == "1.1.0"


@pytest.mark.parametrize(
    ("output", "render"),
    [("1.3.0", None), (None, "2.0.0"), ("1.10.0", None)],
)
def test_no_version_above_the_modules(output, render):
    with pytest.raises(ValidationError, match="above the module"):
        _entry(module="1.2.0", output=output, render=render)


def test_a_render_is_never_newer_than_its_output():
    with pytest.raises(ValidationError, match="newer than its output"):
        _entry(output="1.0.0", render="1.1.0")


def test_versions_compare_as_numbers():
    # "1.10.0" > "1.9.0", which a text comparison gets wrong.
    assert semver_key("1.10.0") > semver_key("1.9.0")
    _entry(module="1.10.0", output="1.9.0")


@pytest.mark.parametrize("bad", ["1.2", "v1.2.0", "1.2.0-beta"])
def test_versions_are_plain_semver(bad):
    with pytest.raises(ValidationError):
        _entry(output=bad)


def test_a_changelog_starts_at_the_module_version_newest_first():
    entry = _entry(
        changelog=[
            {"version": "1.2.0", "date": "2026-11-19", "changes": ["Two."]},
            {"version": "1.0.0", "changes": ["One."]},
        ]
    )
    assert [e.version for e in entry.changelog] == ["1.2.0", "1.0.0"]


@pytest.mark.parametrize(
    ("changelog", "match"),
    [
        # A bump without its line: the history would fall behind the module.
        ([{"version": "1.1.0", "changes": ["x"]}], "add a changelog entry for 1.2.0"),
        (
            [
                {"version": "1.2.0", "changes": ["x"]},
                {"version": "1.2.0", "changes": ["y"]},
            ],
            "newest first",
        ),
        (
            [
                {"version": "1.2.0", "changes": ["x"]},
                {"version": "1.0.0", "changes": ["y"]},
                {"version": "1.1.0", "changes": ["z"]},
            ],
            "newest first",
        ),
        ([{"version": "1.2.0", "changes": []}], "at least 1"),
        ([{"version": "1.2.0", "date": "19/11/2026", "changes": ["x"]}], "pattern"),
    ],
)
def test_a_changelog_that_does_not_match_is_refused(changelog, match):
    with pytest.raises(ValidationError, match=match):
        _entry(changelog=changelog)


def test_bundled_finer_versions_hold():
    """The bundled catalog loads, so every finer version it sets is within bounds;
    at least one module uses them, so the rules above run on real data."""
    entries = load_catalog_entries()
    assert any(e.changelog for e in entries)
    assert any(o.version for e in entries for o in e.outputs)
