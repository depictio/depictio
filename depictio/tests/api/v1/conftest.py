"""Fixtures for the v1 API tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_jbrowse_probe(monkeypatch):
    """Keep the genome browser's opening probe off storage.

    A payload with no filter, no ``location`` and no first call reads the index
    of its first track to find data. These tests fake the manifest, not the
    files, so the probe would dial the real bucket; the ones that exercise it
    patch ``first_region`` themselves (the later patch wins).
    """
    from depictio.api.v1.services.jbrowse import probe

    monkeypatch.setattr(probe, "first_region", lambda *args, **kwargs: None)
