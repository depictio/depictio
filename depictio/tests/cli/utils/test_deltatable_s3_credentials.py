"""The credentials the CLI's Delta reads and writes send to Depictio's S3.

deltalake fills in every option it is not given from the environment, a session token
included, under any spelling of its name. A user's own AWS session token must not ride
along with the keys of Depictio's S3, the local server's included.
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from depictio.cli.cli.utils.deltatables import delta_storage_options, read_delta_table
from depictio.models.models.s3 import PolarsStorageOptions

_TOKEN_VARS = ("AWS_SESSION_TOKEN", "AWS_TOKEN", "SESSION_TOKEN", "TOKEN")
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (*_TOKEN_VARS, *_PROXY_VARS, "AWS_ACCESS_KEY_ID"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)


def _options(endpoint_url: str = "http://127.0.0.1:9000") -> PolarsStorageOptions:
    return PolarsStorageOptions(
        endpoint_url=endpoint_url,
        aws_access_key_id="depictio-key",
        aws_secret_access_key="depictio-secret",
    )


class TestDeltaStorageOptions:
    def test_without_a_token_in_the_environment_the_options_are_the_model(self):
        assert delta_storage_options(_options()) == _options().model_dump()

    @pytest.mark.parametrize("var", [*_TOKEN_VARS, "aws_session_token", "Token"])
    def test_a_token_from_the_environment_is_given_empty(self, monkeypatch, var):
        monkeypatch.setenv(var, "users-own-session-token")

        options = delta_storage_options(_options())

        assert options["aws_session_token"] == ""
        assert options["aws_access_key_id"] == "depictio-key"

    def test_a_token_for_another_access_key_is_given_empty(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "users-own-key")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "users-own-session-token")

        assert delta_storage_options(_options())["aws_session_token"] == ""

    def test_a_token_for_the_same_access_key_is_left_alone(self, monkeypatch):
        """Temporary credentials exported for Depictio's own key: deltalake reads them."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "depictio-key")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "its-session-token")

        assert "aws_session_token" not in delta_storage_options(_options())


class _RecordingS3(BaseHTTPRequestHandler):
    """Answers every request with a 404, after noting its headers."""

    seen: list[dict[str, str]] = []

    def _answer(self):
        type(self).seen.append({k.lower(): v for k, v in self.headers.items()})
        body = b"<Error><Code>NoSuchKey</Code></Error>"
        self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_HEAD = do_PUT = do_POST = _answer

    def log_message(self, *args):
        pass


@pytest.fixture
def s3_endpoint():
    _RecordingS3.seen = []
    server = HTTPServer(("127.0.0.1", 0), _RecordingS3)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", _RecordingS3.seen
    server.shutdown()
    server.server_close()


def test_the_users_session_token_never_reaches_the_endpoint(monkeypatch, s3_endpoint):
    """Real deltalake, against a stand-in for the S3 endpoint."""
    endpoint, seen = s3_endpoint
    monkeypatch.setenv("AWS_SESSION_TOKEN", "users-own-session-token")

    result = read_delta_table("s3://depictio-bucket/some-dc", _options(endpoint))

    assert result["result"] == "error"  # no such table: the endpoint answers 404
    assert seen, "deltalake sent no request"
    assert all(h.get("x-amz-security-token", "") == "" for h in seen)
    assert all("Credential=depictio-key/" in h.get("authorization", "") for h in seen)
