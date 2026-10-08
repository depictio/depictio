"""Shared fixtures for the CLI tests."""

import pytest
import typer.rich_utils

from depictio.cli.cli.utils import common


@pytest.fixture(autouse=True)
def _announce_servers_afresh():
    """Each test is a fresh command: load_depictio_config announces its server again."""
    common._announced.clear()
    yield
    common._announced.clear()


@pytest.fixture(autouse=True)
def _no_real_local_home(tmp_path, monkeypatch):
    """A local home of the test's own: commands look for a running local server to
    mention it, and the developer's ~/.depictio/local must not answer for it."""
    monkeypatch.setenv("DEPICTIO_LOCAL_HOME", str(tmp_path / "local-home"))


@pytest.fixture(autouse=True)
def _help_in_plain_text(monkeypatch):
    """Typer colours help and usage errors when GITHUB_ACTIONS, FORCE_COLOR or PY_COLORS
    is set, which splits an option name into styled pieces; the tests read plain text."""
    monkeypatch.setattr(typer.rich_utils, "FORCE_TERMINAL", None)
