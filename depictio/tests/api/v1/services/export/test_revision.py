"""Cache validation and revision pinning on the export routes.

The behaviours here are what let an embedding site stay current cheaply, so each
one is pinned against the specific way it could silently regress: an ETag that
ignores theme would serve a light figure to a dark request, one that ignores the
data would answer 304 after a re-ingest, and one keyed on the document's
`version` counter would never move on a UI edit (that counter counts imports).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from depictio.api.v1.services.export.revision import (
    EXPORT_CONTRACT_VERSION,
    build_etag,
    component_dc_ids,
    dashboard_revision,
    etag_matches,
)

DOC = {
    "dashboard_id": "646b0f3c1e4a2d7f8e5b8cb3",
    "is_main_tab": True,
    "version": 7,
    "last_saved_ts": datetime(2026, 7, 29, 14, 11, 40),
    "stored_metadata": [{"index": "c1", "component_type": "figure", "dc_id": "dc1"}],
}
COMPONENT = DOC["stored_metadata"][0]

_LATEST = "depictio.api.v1.endpoints.dashboards_endpoints.version_store.latest_version"
_AGG_HASH = "depictio.api.v1.deltatables_utils._get_aggregation_hash"


def _revision(*, ledger=None, data_hash="h1", doc=DOC, component=COMPONENT) -> dict:
    with patch(_LATEST, return_value=ledger), patch(_AGG_HASH, return_value=data_hash):
        return dashboard_revision(doc, component)


def _etag(**overrides) -> str:
    kwargs = {
        "revision": "r1",
        "component_id": "c1",
        "export_format": "json",
        "theme": "light",
        "filters": [],
        "controls": None,
    }
    kwargs.update(overrides)
    return build_etag(**kwargs)


class TestRevision:
    def test_follows_the_version_ledger(self) -> None:
        a = _revision(ledger={"version_id": "v1", "seq": 3, "content_hash": "aaa"})
        b = _revision(ledger={"version_id": "v2", "seq": 4, "content_hash": "bbb"})
        assert a["revision"] != b["revision"], "a content edit moves the revision"
        assert a["dashboard_version_id"] == "v1" and a["dashboard_version_seq"] == 3

    def test_ignores_what_is_not_content(self) -> None:
        """`version` counts imports and `last_saved_ts` moves with screenshots."""
        ledger = {"version_id": "v1", "seq": 3, "content_hash": "aaa"}
        base = _revision(ledger=ledger)
        touched = _revision(
            ledger=ledger,
            doc={**DOC, "version": 8, "last_saved_ts": datetime(2026, 8, 1)},
        )
        assert base["revision"] == touched["revision"]

    def test_moves_when_the_data_is_reingested(self) -> None:
        ledger = {"version_id": "v1", "seq": 3, "content_hash": "aaa"}
        assert _revision(ledger=ledger, data_hash="h1")["revision"] != (
            _revision(ledger=ledger, data_hash="h2")["revision"]
        )

    def test_a_family_without_a_ledger_entry_hashes_its_stored_content(self) -> None:
        base = _revision(ledger=None)
        assert base["dashboard_version_id"] is None
        edited = _revision(
            ledger=None,
            doc={**DOC, "stored_metadata": [{**COMPONENT, "title": "renamed"}]},
        )
        assert base["revision"] != edited["revision"]
        resaved = _revision(ledger=None, doc={**DOC, "last_saved_ts": datetime(2026, 8, 1)})
        assert base["revision"] == resaved["revision"]

    def test_reports_provenance(self) -> None:
        revision = _revision(ledger={"version_id": "v1", "seq": 3, "content_hash": "aaa"})
        assert revision["last_saved_ts"].startswith("2026-07-29")
        assert revision["export_contract"] == EXPORT_CONTRACT_VERSION

    def test_survives_a_missing_timestamp(self) -> None:
        revision = _revision(doc={"dashboard_id": "d", "version": 1})
        assert revision["last_saved_ts"] == ""


@pytest.mark.parametrize(
    ("component", "expected"),
    [
        ({"dc_id": "a"}, ["a"]),
        ({"dc_id": "a", "config": {"ma_dc_id": "b", "tree_dc_id": "c"}}, ["a", "b", "c"]),
        ({"values": {"n": {"dc_id": "x"}, "m": {"dc_id": "y"}}}, ["x", "y"]),
        (None, []),
    ],
)
def test_component_dc_ids(component, expected) -> None:
    assert component_dc_ids(component) == expected


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
    assert _etag(revision="r2") != baseline, "definition or data moved"


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


def test_etag_varies_with_intra_viz_controls() -> None:
    """A ROC and a PR curve come from the same component at the same revision.
    Leaving controls out of the tag would serve one from cache when the caller
    asked for the other."""
    pr = _etag(controls={"mode": "pr"})
    roc = _etag(controls={"mode": "roc"})
    threshold = _etag(controls={"mode": "threshold"})
    assert len({pr, roc, threshold}) == 3


def test_etag_ignores_control_key_order() -> None:
    a = _etag(controls={"mode": "roc", "show_auc": True})
    b = _etag(controls={"show_auc": True, "mode": "roc"})
    assert a == b


def test_absent_controls_match_empty_controls() -> None:
    """Omitting the parameter and passing {} are the same request, so they must
    not split the cache."""
    assert _etag() == _etag(controls={})
