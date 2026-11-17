"""A reader with no bearer token resolves a Delta location from the deltatables collection.

``jbrowse_calls`` reads its collections through ``load_deltatable_lite`` without an
``init_data`` hint or a token. The loader then called its own ``GET /deltatables/get/{dc}``
unauthenticated, got a 401 for an anonymous visitor on a public dashboard, and failed the
whole read as ``Error loading deltatable`` (a 500 on the endpoint).
"""

import pytest

from depictio.api.v1 import deltatables_utils

DC_ID = "6ae7927da012044fe09dadf4"
WF_ID = "6ae7927da012044fe09dade3"


def _forbid_http(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the loader called the API instead of reading the collection")

    monkeypatch.setattr(deltatables_utils.httpx, "get", refuse)


def test_location_comes_from_the_collection_without_an_http_call(monkeypatch):
    _forbid_http(monkeypatch)
    monkeypatch.setattr(
        "depictio.api.v1.services.export.delta_location.delta_location_for",
        lambda dc_id, dc_config=None: f"s3://bucket/{dc_id}",
    )
    assert deltatables_utils._get_delta_location(DC_ID, WF_ID, None, None) == f"s3://bucket/{DC_ID}"


def test_init_data_still_wins(monkeypatch):
    _forbid_http(monkeypatch)
    init = {DC_ID: {"delta_location": "s3://bucket/from-init"}}
    assert (
        deltatables_utils._get_delta_location(DC_ID, WF_ID, init, None) == "s3://bucket/from-init"
    )


def test_falls_back_to_the_api_when_the_collection_has_no_entry(monkeypatch):
    monkeypatch.setattr(
        "depictio.api.v1.services.export.delta_location.delta_location_for",
        lambda dc_id, dc_config=None: None,
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"delta_table_location": "s3://bucket/from-api"}

    monkeypatch.setattr(deltatables_utils.httpx, "get", lambda *a, **k: Response())
    with pytest.warns(DeprecationWarning):
        assert (
            deltatables_utils._get_delta_location(DC_ID, WF_ID, None, None)
            == "s3://bucket/from-api"
        )
