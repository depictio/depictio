"""Shared fixtures for the CLI tests."""

import pytest

from depictio.cli.cli.utils import common


@pytest.fixture(autouse=True)
def _announce_servers_afresh():
    """Each test is a fresh command: load_depictio_config announces its server again."""
    common._announced.clear()
    yield
    common._announced.clear()
