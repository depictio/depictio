"""Smoke tests for the MultiQC pre-render disk store."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

from depictio.api.v1.services import multiqc_prerender_store


@pytest.fixture
def isolated_store(monkeypatch):
    """Point the store at a fresh tmpdir so tests don't touch the real cache."""
    tmp = tempfile.mkdtemp(prefix="depictio_prerender_test_")
    # Patch the settings reader directly — the helper calls
    # ``settings.multiqc_prerender.prerender_dir`` each invocation.
    with patch("depictio.api.v1.services.multiqc_prerender_store.settings") as mock_settings:
        mock_settings.multiqc_prerender.prerender_dir = tmp
        yield tmp
    # Best-effort cleanup; ignore if the dir was already removed by a test.
    if os.path.exists(tmp):
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


class TestPrerenderStore:
    def test_write_read_roundtrip(self, isolated_store):
        dc_id = "65a000000000000000000001"
        key = "multiqc:figure:dc=65a000000000000000000001:abcdef1234567890"
        fig_dict = {"data": [{"x": [1, 2, 3], "y": [4, 5, 6]}], "layout": {"title": "t"}}

        multiqc_prerender_store.write_figure(dc_id, key, fig_dict)
        result = multiqc_prerender_store.read_figure(dc_id, key)
        assert result == fig_dict

    def test_read_missing_returns_none(self, isolated_store):
        result = multiqc_prerender_store.read_figure(
            "65a000000000000000000002", "multiqc:figure:dc=x:deadbeef"
        )
        assert result is None

    def test_delete_dc_dir_removes_files(self, isolated_store):
        dc_id = "65a000000000000000000003"
        keys = [f"multiqc:figure:dc={dc_id}:hash{i:08x}" for i in range(3)]
        for k in keys:
            multiqc_prerender_store.write_figure(dc_id, k, {"k": k})

        # All three are on disk.
        for k in keys:
            assert multiqc_prerender_store.read_figure(dc_id, k) is not None

        count = multiqc_prerender_store.delete_dc_dir(dc_id)
        assert count == 3

        # Reads now return None.
        for k in keys:
            assert multiqc_prerender_store.read_figure(dc_id, k) is None

    def test_delete_missing_dir_returns_zero(self, isolated_store):
        assert multiqc_prerender_store.delete_dc_dir("non-existent-dc") == 0

    def test_figure_path_strips_key_prefix(self, isolated_store):
        # The on-disk filename should be the trailing hash, not the full key.
        path = multiqc_prerender_store.figure_path("dc1", "multiqc:figure:dc=dc1:cafebabecafebabe")
        assert path.name == "cafebabecafebabe.json.gz"

    def test_atomic_write_no_partial_file_on_failure(self, isolated_store, monkeypatch):
        dc_id = "65a000000000000000000004"
        key = "multiqc:figure:dc=x:abc123"

        # Force the json.dump to raise — the atomic rename should never run,
        # and no .json.gz file should remain in the DC dir.
        with patch(
            "depictio.api.v1.services.multiqc_prerender_store.json.dump",
            side_effect=RuntimeError("disk full"),
        ):
            with pytest.raises(RuntimeError):
                multiqc_prerender_store.write_figure(dc_id, key, {"x": 1})

        target = multiqc_prerender_store.figure_path(dc_id, key)
        assert not target.exists()
        # And no leftover tmp files.
        leftovers = list(target.parent.glob(".tmp.*"))
        assert leftovers == []

    def test_corrupt_file_returns_none(self, isolated_store):
        dc_id = "65a000000000000000000005"
        key = "multiqc:figure:dc=x:dead"
        target = multiqc_prerender_store.figure_path(dc_id, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write non-gzip bytes so read_figure hits the OSError branch.
        target.write_bytes(b"not-a-gzip-file")
        assert multiqc_prerender_store.read_figure(dc_id, key) is None
