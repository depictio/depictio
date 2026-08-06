"""Tests for the s3_prefix scan mode (remote counterpart of `recursive`).

Listing is exercised against a stubbed boto3 paginator: the S3 wire protocol is
not what can break here, the key filtering and pagination handling are.
"""

import pytest

from depictio.cli.cli.utils import scan as scan_module
from depictio.models.models.data_collections import Scan, ScanS3Prefix


class _StubPaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **_kwargs):
        return self._pages


class _StubClient:
    def __init__(self, keys):
        # Mimic list_objects_v2 splitting results across pages.
        self._pages = [
            {"Contents": [{"Key": k, "Size": 10, "ETag": f'"{k}-etag"'} for k in chunk]}
            for chunk in (keys[:2], keys[2:])
            if chunk
        ]

    def get_paginator(self, _name):
        return _StubPaginator(self._pages)


@pytest.fixture
def stub_s3(monkeypatch):
    def _install(keys):
        monkeypatch.setattr(scan_module, "_s3_read_client", lambda _cfg: _StubClient(keys))

    return _install


KEYS = [
    "run42/sample_A.samples.csv",
    "run42/sample_B.samples.csv",
    "run42/sample_A.measurements.csv",
    "run42/nested/sample_D.samples.csv",
    "run42/notes/",  # console-created "folder" placeholder
]


class TestScanS3PrefixModel:
    def test_accepts_a_prefix_and_glob(self):
        scan = Scan(
            mode="s3_prefix",
            scan_parameters={"prefix": "s3://b/run42/", "pattern": "*.csv"},
        )
        assert scan.scan_parameters.pattern == "*.csv"

    def test_https_prefix_rejected_with_a_pointer_to_the_alternatives(self):
        """HTTPS cannot be listed; the error has to say what to use instead."""
        with pytest.raises(ValueError, match="url.*manifest|manifest"):
            ScanS3Prefix(prefix="https://host/dir/")

    def test_prefix_without_bucket_rejected(self):
        with pytest.raises(ValueError, match="bucket"):
            ScanS3Prefix(prefix="s3://")

    def test_id_regex_must_have_exactly_one_group(self):
        with pytest.raises(ValueError, match="one capture group"):
            ScanS3Prefix(prefix="s3://b/x", id_regex=r"(a)(b)")

    def test_invalid_id_regex_rejected(self):
        with pytest.raises(ValueError, match="Invalid id_regex"):
            ScanS3Prefix(prefix="s3://b/x", id_regex="(")

    def test_empty_pattern_rejected(self):
        with pytest.raises(ValueError, match="pattern cannot be empty"):
            ScanS3Prefix(prefix="s3://b/x", pattern="   ")

    def test_defaults_match_everything_under_the_prefix(self):
        assert ScanS3Prefix(prefix="s3://b/x").pattern == "*"


class TestListS3Prefix:
    def test_glob_filters_by_role_and_recurses(self, stub_s3):
        """`*` spans `/` on purpose, so a role glob reaches nested keys — this
        is what makes the mode the remote twin of a recursive walk."""
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.samples.csv", 10_000, None)
        assert [o["relative"] for o in found] == [
            "sample_A.samples.csv",
            "sample_B.samples.csv",
            "nested/sample_D.samples.csv",
        ]

    def test_directory_placeholder_keys_are_skipped(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*", 10_000, None)
        assert all(not o["key"].endswith("/") for o in found)

    def test_results_span_pages(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*", 10_000, None)
        assert len(found) == 4

    def test_etag_is_unquoted_for_the_identity_hash(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.samples.csv", 10_000, None)
        assert not found[0]["etag"].startswith('"')

    def test_max_files_caps_and_warns(self, stub_s3, monkeypatch):
        """A silent cap would read as 'that is all there is'."""
        stub_s3(KEYS)
        messages = []
        monkeypatch.setattr(
            scan_module,
            "rich_print_checked_statement",
            lambda msg, level="info": messages.append((level, msg)),
        )
        found = scan_module.list_s3_prefix("s3://b/run42/", "*", 2, None)
        assert len(found) == 2
        assert any(level == "warning" and "truncated" in msg for level, msg in messages)

    def test_non_s3_prefix_rejected(self, stub_s3):
        stub_s3(KEYS)
        with pytest.raises(ValueError, match="s3:// prefix"):
            scan_module.list_s3_prefix("https://host/d/", "*", 10, None)

    def test_full_urls_are_reconstructed(self, stub_s3):
        stub_s3(KEYS)
        found = scan_module.list_s3_prefix("s3://b/run42/", "*.measurements.csv", 10_000, None)
        assert found[0]["url"] == "s3://b/run42/sample_A.measurements.csv"
