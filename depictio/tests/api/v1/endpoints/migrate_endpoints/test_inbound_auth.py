"""Who may push here (#1303): the pairing key names the source, and nothing else does."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import MigrationInboundSource
from depictio.api.v1.endpoints.migrate_endpoints import inbound_auth

K1, K2 = "a" * 40, "b" * 40


@pytest.fixture
def two_sources(monkeypatch):
    monkeypatch.setattr(settings.migration, "inbound_enabled", True)
    monkeypatch.setattr(
        settings.migration,
        "inbound_sources",
        [
            MigrationInboundSource(name="one", pairing_key=K1),
            MigrationInboundSource(name="two", pairing_key=K2),
        ],
    )


def test_disabled_inbound_is_a_404_even_with_a_valid_key(two_sources, monkeypatch):
    monkeypatch.setattr(settings.migration, "inbound_enabled", False)
    with pytest.raises(HTTPException) as exc:
        inbound_auth.require_inbound_source(K1)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("key", [None, "", "wrong" * 10])
def test_a_missing_or_wrong_key_is_a_403(two_sources, key):
    with pytest.raises(HTTPException) as exc:
        inbound_auth.require_inbound_source(key)
    assert exc.value.status_code == 403


def test_the_source_name_comes_from_the_key(two_sources):
    assert inbound_auth.require_inbound_source(K2).name == "two"
    assert inbound_auth.require_inbound_source(K1).name == "one"


def test_every_entry_is_compared_even_after_a_match(two_sources):
    """Constant time: the work does not reveal which entry matched."""
    real = inbound_auth.hmac.compare_digest
    with patch.object(inbound_auth.hmac, "compare_digest", side_effect=real) as spy:
        assert inbound_auth.match_inbound_source(K1).name == "one"
    assert spy.call_count == 2
