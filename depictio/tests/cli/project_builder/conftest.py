"""Fixtures of the Project Builder core tests."""

from __future__ import annotations

import pytest

from depictio.cli.cli.utils.data_root import LocalDataRoot, data_root_for

from ..s3_stubs import S3_KEY_PREFIX, S3_ROOT, install_s3_listing, s3_cli_config, write_tree
from ._fixtures import RUN_TREE


@pytest.fixture(autouse=True)
def builder_env(monkeypatch):
    """Server context (the suite's default; importing the CLI app flips the
    process to ``CLI``), with no local-folder policy and no bucket list."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "server")
    for name in (
        "DEPICTIO_LOCAL_DATA_ROOTS",
        "DEPICTIO_AUTH_SINGLE_USER_MODE",
        "DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS",
        "DEPICTIO_REMOTE_CREDENTIALED_S3_BUCKETS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def run_dir(tmp_path):
    """``RUN_TREE`` on disk."""
    return write_tree(tmp_path / "results", RUN_TREE)


@pytest.fixture
def root(run_dir):
    """A local data root over ``RUN_TREE``."""
    return LocalDataRoot(str(run_dir))


@pytest.fixture
def s3_root(monkeypatch):
    """The same tree as an ``s3://`` root, served by the stubbed listing."""
    install_s3_listing(monkeypatch, RUN_TREE, key_prefix=S3_KEY_PREFIX)
    return data_root_for(S3_ROOT, s3_cli_config())
