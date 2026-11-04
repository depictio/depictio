"""MigrationConfig: the push targets and inbound sources read from the environment (#1303)."""

import json

import pytest
from pydantic import ValidationError

from depictio.api.v1.configs.settings_models import MigrationConfig

KEY = "k" * 32


def test_both_directions_are_off_by_default(monkeypatch) -> None:
    for name in ("TARGETS", "INBOUND_SOURCES", "INBOUND_ENABLED", "ALLOW_UI_TARGETS"):
        monkeypatch.delenv(f"DEPICTIO_MIGRATION_{name}", raising=False)
    config = MigrationConfig()

    assert config.targets == [] and config.inbound_sources == []
    assert config.inbound_enabled is False and config.allow_ui_targets is False
    assert config.lock_imported_default is True


def test_lists_are_read_as_json(monkeypatch) -> None:
    monkeypatch.setenv(
        "DEPICTIO_MIGRATION_TARGETS",
        json.dumps([{"name": "public", "url": "https://p.example.org", "pairing_key": KEY}]),
    )
    monkeypatch.setenv(
        "DEPICTIO_MIGRATION_INBOUND_SOURCES",
        json.dumps([{"name": "lab", "pairing_key": KEY, "allowed_source_buckets": ["lab"]}]),
    )
    config = MigrationConfig()

    assert config.targets[0].pairing_key.get_secret_value() == KEY
    assert config.targets[0].credential_type == "pairing_key"
    assert config.inbound_sources[0].allowed_source_buckets == ["lab"]
    # A SecretStr: the key never shows in a repr or a log line.
    assert KEY not in repr(config)


def test_a_short_pairing_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        MigrationConfig(inbound_sources=[{"name": "lab", "pairing_key": "short"}])
    with pytest.raises(ValidationError, match="at least 32"):
        MigrationConfig(targets=[{"name": "t", "url": "https://x", "pairing_key": "short"}])


@pytest.mark.parametrize("prefix", ["", "/", "a" * 24, "0123456789abcdef01234567", "a/b"])
def test_a_staging_prefix_the_orphan_sweep_could_delete_is_refused(prefix) -> None:
    with pytest.raises(ValidationError):
        MigrationConfig(staging_prefix=prefix)


def test_names_and_keys_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="names must be unique"):
        MigrationConfig(
            inbound_sources=[
                {"name": "lab", "pairing_key": KEY},
                {"name": "lab", "pairing_key": "j" * 32},
            ]
        )
    # Two sources with one key: the key could not tell them apart.
    with pytest.raises(ValidationError, match="keys must be unique"):
        MigrationConfig(
            inbound_sources=[{"name": "a", "pairing_key": KEY}, {"name": "b", "pairing_key": KEY}]
        )
