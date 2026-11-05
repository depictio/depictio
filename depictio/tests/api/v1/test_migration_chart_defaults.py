"""Helm chart defaults for project migration (#1303): on in the chart, off in the code."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from depictio.api.v1.configs.settings_models import MigrationConfig

ROOT = Path(__file__).resolve().parents[4]
CHART = ROOT / "helm-charts" / "depictio"
SECRET_CARRYING = ("DEPICTIO_MIGRATION_TARGETS", "DEPICTIO_MIGRATION_INBOUND_SOURCES")


@pytest.fixture(scope="module")
def backend_env() -> dict:
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    return values["backend"]["env"]


@pytest.fixture(scope="module")
def configmap() -> str:
    return (CHART / "templates" / "configmaps.yaml").read_text()


def test_the_chart_receives_projects_and_shows_the_ui_by_default(backend_env):
    assert backend_env["DEPICTIO_MIGRATION_INBOUND_ENABLED"] == "true"
    assert backend_env["DEPICTIO_MIGRATION_UI_ENABLED"] == "true"


def test_values_never_carry_pairing_keys(backend_env):
    for name in SECRET_CARRYING:
        assert name not in backend_env
    raw = (CHART / "values.yaml").read_text()
    for name in SECRET_CARRYING:
        # A comment may name them; an assignment may not.
        assert not re.search(rf"^\s*{name}\s*:", raw, re.MULTILINE)


def test_every_migration_value_is_a_string(backend_env):
    """A bare YAML true would render as a bool in the configmap, not "true"."""
    for key, value in backend_env.items():
        if key.startswith("DEPICTIO_MIGRATION_"):
            assert isinstance(value, str), key


def test_the_configmap_forwards_migration_values_by_prefix_without_the_secret_ones(configmap):
    match = re.search(
        r"range \$key, \$value := \.Values\.backend\.env.*?\{\{- end \}\}\s*\{\{- end \}\}",
        configmap[configmap.index("Project migration") :],
        re.DOTALL,
    )
    assert match, "the migration range block is missing"
    block = match.group(0)
    assert 'hasPrefix "DEPICTIO_MIGRATION_" $key' in block
    for name in SECRET_CARRYING:
        assert f'(ne $key "{name}")' in block
    assert '(ne (toString $value) "")' in block, "empty values are not forwarded"
    assert "| quote" in block, "values are quoted into the configmap"


def test_the_configmap_is_the_backend_one_only(configmap):
    """Migration env is forwarded once; the worker's configmap needs none."""
    assert configmap.count('hasPrefix "DEPICTIO_MIGRATION_"') == 1


def test_the_code_defaults_stay_off(monkeypatch):
    for name in ("INBOUND_ENABLED", "UI_ENABLED", "INBOUND_SOURCES", "TARGETS"):
        monkeypatch.delenv(f"DEPICTIO_MIGRATION_{name}", raising=False)
    config = MigrationConfig()
    assert config.inbound_enabled is False and config.ui_enabled is False
    assert config.inbound_sources == [] and config.targets == []
    assert config.destination_domains == []


def test_the_chart_env_names_are_read_by_the_config(monkeypatch, backend_env):
    for name in ("INBOUND_ENABLED", "UI_ENABLED"):
        monkeypatch.setenv(f"DEPICTIO_MIGRATION_{name}", backend_env[f"DEPICTIO_MIGRATION_{name}"])
    config = MigrationConfig()
    assert config.inbound_enabled is True and config.ui_enabled is True
    # Receiving with no source and no invite still accepts nothing.
    assert config.inbound_sources == []


def test_new_slice_two_settings_have_safe_defaults(monkeypatch):
    for name in (
        "INVITE_TTL_DAYS",
        "INVITE_MAX_TTL_DAYS",
        "INTERRUPTED_AFTER_MINUTES",
        "DESTINATION_DOMAINS",
    ):
        monkeypatch.delenv(f"DEPICTIO_MIGRATION_{name}", raising=False)
    config = MigrationConfig()
    assert config.invite_ttl_days == 30
    for removed in ("invite_single_use_ttl_hours", "invite_lineage_ttl_days"):
        assert removed not in MigrationConfig.model_fields
        assert not hasattr(config, removed)
    assert config.invite_max_ttl_days == 365
    assert config.interrupted_after_minutes == 60
    for field in (
        "invite_ttl_days",
        "invite_max_ttl_days",
        "interrupted_after_minutes",
    ):
        with pytest.raises(ValueError):
            MigrationConfig(**{field: 0})


def test_destination_domains_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("DEPICTIO_MIGRATION_DESTINATION_DOMAINS", '[" .Serve.Example.org. ", ""]')
    assert MigrationConfig().destination_domains == ["serve.example.org"]
