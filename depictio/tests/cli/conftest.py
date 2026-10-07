"""Shared fixtures for the CLI tests."""

import pytest

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
