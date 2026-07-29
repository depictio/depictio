"""Cache validation and version pinning on the export routes.

The behaviours here are what let an embedding site stay current cheaply, so each
one is pinned against the specific way it could silently regress: an ETag that
ignores theme would serve a light figure to a dark request, and a pin that
compares loosely would let a caller drift onto a different dashboard without
noticing.
"""

from __future__ import annotations

from datetime import datetime

from depictio.api.v1.services.export.revision import (
    EXPORT_CONTRACT_VERSION,
    build_etag,
    dashboard_revision,
    etag_matches,
)

DOC = {
    "dashboard_id": "646b0f3c1e4a2d7f8e5b8cb3",
    "version": 7,
    "last_saved_ts": datetime(2026, 7, 29, 14, 11, 40),
}


def _etag(**overrides) -> str:
    kwargs = {
        "dashboard_doc": DOC,
        "component_id": "c1",
        "export_format": "json",
        "theme": "light",
        "filters": [],
    }
    kwargs.update(overrides)
    return build_etag(**kwargs)


def test_etag_is_stable_for_identical_inputs() -> None:
    assert _etag() == _etag()


def test_etag_is_weak() -> None:
    """meta.generated_at differs on every build, so a strong validator would lie."""
    assert _etag().startswith('W/"')


def test_etag_varies_with_every_input_that_changes_the_body() -> None:
    baseline = _etag()
    assert _etag(theme="dark") != baseline, "theme changes the colours"
    assert _etag(export_format="html") != baseline, "format changes the whole body"
    assert _etag(component_id="c2") != baseline, "different component"
    assert _etag(filters=[{"column": "x", "value": 1}]) != baseline, "filters change the data"
    assert _etag(dashboard_doc={**DOC, "version": 8}) != baseline, "dashboard was saved"


def test_etag_ignores_filter_key_order() -> None:
    """Two equivalent filter sets must not defeat the cache over key ordering."""
    a = _etag(filters=[{"column": "habitat", "value": "soil"}])
    b = _etag(filters=[{"value": "soil", "column": "habitat"}])
    assert a == b


def test_etag_matching_follows_weak_comparison() -> None:
    tag = 'W/"abc123"'
    assert etag_matches(tag, tag)
    assert etag_matches('"abc123"', tag), "W/ prefix must not break the match"
    assert etag_matches('W/"other", W/"abc123"', tag), "client may send a list"
    assert etag_matches("*", tag)
    assert not etag_matches('W/"different"', tag)
    assert not etag_matches(None, tag)
    assert not etag_matches("", tag)


def test_revision_reports_provenance() -> None:
    revision = dashboard_revision(DOC)
    assert revision["dashboard_version"] == 7
    assert revision["last_saved_ts"].startswith("2026-07-29")
    assert revision["export_contract"] == EXPORT_CONTRACT_VERSION


def test_revision_survives_a_missing_timestamp() -> None:
    """A dashboard that has never been saved must not blow up the export."""
    revision = dashboard_revision({"version": 1})
    assert revision["last_saved_ts"] == ""
    assert revision["dashboard_version"] == 1
