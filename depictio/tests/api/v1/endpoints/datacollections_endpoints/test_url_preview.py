"""POST /datacollections/url_preview: the start of a remote file, before a table is made.

The http(s) read is faked at ``open_validated_stream``, the gateway itself is
covered by tests/unit/test_remote_fetch.py; ``s3://`` delegates to the
run-folder preview, covered by test_run_file_preview.py.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from depictio.api.v1.endpoints.datacollections_endpoints import url_preview as up
from depictio.api.v1.endpoints.projects_endpoints.local_dirs import CodedHTTPException
from depictio.api.v1.remote_fetch import RemoteURLRejected


class _Response:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "text/csv"):
        self._body = body
        self.status_code = status
        self.is_success = 200 <= status < 300
        self.headers = {"content-length": str(len(body)), "content-type": content_type}

    def iter_bytes(self, chunk_size: int = 1024):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


def _stream(response):
    @contextmanager
    def fake(url, **_kwargs):
        yield response

    return fake


def _preview(url: str):
    return up.preview_remote_url(up.URLPreviewRequest(url=url), request=None, current_user=None)


def test_https_tsv_shows_first_rows():
    body = b"sample\tgroup\nS1\tA\nS2\tB\n"
    with patch.object(up, "open_validated_stream", _stream(_Response(body))):
        result = _preview("https://example.org/data/meta.tsv")
    assert result.format == "table"
    assert result.columns == ["sample", "group"]
    assert result.rows == [["S1", "A"], ["S2", "B"]]
    assert result.name == "meta.tsv"
    assert result.truncated is False


def test_html_page_is_not_a_data_file():
    page = _Response(b"<html></html>", content_type="text/html")
    with patch.object(up, "open_validated_stream", _stream(page)):
        result = _preview("https://example.org/data.csv")
    assert result.format == "none"
    assert "web page" in result.reason


def test_non_2xx_is_unreachable():
    with patch.object(up, "open_validated_stream", _stream(_Response(b"", status=404))):
        with pytest.raises(CodedHTTPException) as exc:
            _preview("https://example.org/missing.csv")
    assert exc.value.code == up.URL_UNREACHABLE
    assert "404" in exc.value.detail


def test_gateway_refusal_keeps_its_message():
    @contextmanager
    def refused(url, **_kwargs):
        raise RemoteURLRejected("Host 'x' resolves to a non-public address and was rejected.")
        yield  # pragma: no cover

    with patch.object(up, "open_validated_stream", refused):
        with pytest.raises(CodedHTTPException) as exc:
            _preview("https://x/data.csv")
    assert exc.value.code == up.URL_REFUSED
    assert "non-public" in exc.value.detail


def test_parquet_url_is_not_opened():
    with patch.object(up, "open_validated_stream", _stream(_Response(b"PAR1"))):
        result = _preview("https://example.org/t.parquet")
    assert result.format == "none"


@pytest.mark.parametrize("url", ["ftp://example.org/a.csv", "example.org/a.csv"])
def test_other_schemes_refused(url):
    with pytest.raises(CodedHTTPException) as exc:
        _preview(url)
    assert exc.value.code == up.URL_REFUSED


def test_s3_folder_is_not_a_file():
    with pytest.raises(CodedHTTPException) as exc:
        _preview("s3://bucket/some/prefix/")
    assert exc.value.code == up.URL_NOT_A_FILE


def test_s3_file_delegates_with_its_prefix_as_folder():
    with patch.object(up, "preview_run_file") as run_preview:
        _preview("s3://bucket/run/input/meta.tsv")
    payload = run_preview.call_args.args[0]
    assert payload.data_root == "s3://bucket/run/input/"
    assert payload.location == "s3://bucket/run/input/meta.tsv"
