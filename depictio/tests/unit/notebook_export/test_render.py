"""The render service: what it refuses, and what it checks before believing Quarto."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from depictio.api.v1.services.notebook_export import render, store


class FakeProc:
    def __init__(self, cmd, *, returncode: int = 0, stdout: str = "", hang: bool = False):
        self.args = cmd
        self.pid = 4242
        self.returncode = returncode
        self._stdout = stdout
        self._hang = hang

    def communicate(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self._stdout, None

    def wait(self, timeout=None):
        return self.returncode


def _quarto(
    monkeypatch,
    *,
    log: str,
    returncode: int = 0,
    write_output: bool = True,
    hang: bool = False,
    stem: str = "x",
    write_files: dict[str, bytes] | None = None,
):
    """Stand in for the Quarto binary, writing whatever report it claims to."""
    monkeypatch.setattr(render, "quarto_binary", lambda: "/usr/bin/quarto")
    monkeypatch.setitem(__import__("sys").modules, "nbclient", object())
    monkeypatch.setitem(__import__("sys").modules, "ipykernel", object())
    seen: dict[str, object] = {"killed": []}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs.get("env") or {}
        seen["new_session"] = kwargs.get("start_new_session")
        if write_output:
            out = Path(kwargs["cwd"]) / f"{stem}.html"
            out.write_bytes(b"<html>report</html>")
        for rel, body in (write_files or {}).items():
            path = Path(kwargs["cwd"]) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return FakeProc(cmd, returncode=returncode, stdout=log, hang=hang)

    def fake_killpg(pid, sig):
        seen["killed"].append(pid)  # type: ignore[union-attr]

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(render.os, "killpg", fake_killpg)
    return seen


def test_render_needs_quarto(monkeypatch):
    monkeypatch.setattr(render, "quarto_binary", lambda: None)
    with pytest.raises(render.RenderUnavailable, match="Quarto is not installed"):
        render.render_quarto_html(
            b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t"
        )


def test_render_returns_the_report_and_passes_the_caller_through(monkeypatch):
    seen = _quarto(monkeypatch, log="Executing 'x.quarto_ipynb'\n  Cell 1/2: ''...Done\n")
    html = render.render_quarto_html(
        b"---\ntitle: x\n---\n", stem="x", api_url="http://api:8058", api_token="tok"
    )
    assert html == b"<html>report</html>"
    assert seen["cmd"][2] == "x.qmd"
    assert "--execute" in seen["cmd"]
    env = seen["env"]
    # The notebook is a client of this deployment, running as whoever asked.
    assert env["DEPICTIO_API_URL"] == "http://api:8058"
    assert env["DEPICTIO_API_TOKEN"] == "tok"
    assert env["DEPICTIO_CONTEXT"] == "client"
    # And Quarto is pinned to *this* interpreter, the one that has the kernel.
    assert env["QUARTO_PYTHON"].endswith("python3") or "python" in env["QUARTO_PYTHON"]


def test_a_report_quarto_never_executed_is_a_failure(monkeypatch):
    """Quarto skips execution silently and exits 0 — the log is the only tell."""
    _quarto(monkeypatch, log="pandoc\n  to: html\nOutput created: x.html\n")
    with pytest.raises(render.RenderUnavailable, match="without executing"):
        render.render_quarto_html(
            b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t"
        )


def test_a_preview_read_from_quarto_s_cache_is_not_a_failure(monkeypatch, tmp_path):
    """A text-only edit re-renders without executing: the cache hit is the point."""
    monkeypatch.setitem(__import__("sys").modules, "jupyter_cache", object())
    log = "Starting python3 kernel...(Notebook read from cache)\npandoc\n"
    seen = _quarto(monkeypatch, log=log)
    html = render.render_quarto_html(
        b"---\ntitle: x\n---\n",
        stem="x",
        api_url="http://api",
        api_token="t",
        workdir=str(tmp_path / "preview"),
        cache=True,
    )
    assert html == b"<html>report</html>"
    assert "--cache" in seen["cmd"]
    # Without the cache flag the same log is still a render that never ran.
    _quarto(monkeypatch, log=log)
    with pytest.raises(render.RenderUnavailable, match="without executing"):
        render.render_quarto_html(
            b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t"
        )


def test_a_failed_render_keeps_quarto_s_log_for_the_server(monkeypatch):
    """The log can hold worker paths and what the document printed: it goes to
    the worker's log, and the message a user can be shown does not carry it."""
    _quarto(monkeypatch, log="An error occurred: cell 4 raised", returncode=1, write_output=False)
    with pytest.raises(render.RenderUnavailable) as err:
        render.render_quarto_html(
            b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t"
        )
    assert "cell 4" not in str(err.value)
    assert "cell 4 raised" in err.value.log


def test_the_render_sees_none_of_the_worker_s_secrets(monkeypatch):
    monkeypatch.setenv("DEPICTIO_S3_ROOT_PASSWORD", "s3-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("DEPICTIO_MONGODB_URL", "mongodb://u:p@mongo")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("QUARTO_LOG_LEVEL", "INFO")
    seen = _quarto(monkeypatch, log="Executing 'x.quarto_ipynb'\n")
    render.render_quarto_html(
        b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t"
    )
    env = seen["env"]
    assert "s3-secret" not in env.values() and "aws-secret" not in env.values()
    assert not any("MONGO" in k for k in env)
    assert {k for k in env if k.startswith("DEPICTIO_")} <= {
        "DEPICTIO_API_URL",
        "DEPICTIO_API_TOKEN",
        "DEPICTIO_CONTEXT",
        "DEPICTIO_NOTEBOOK_NATIVE",
        render.STATIC_FIGURES_ENV,
    }
    assert env["LC_ALL"] == "C.UTF-8" and env["QUARTO_LOG_LEVEL"] == "INFO"
    assert "PATH" in env


def test_a_timeout_kills_the_whole_process_group(monkeypatch):
    """Quarto's kernel and its children are in Quarto's session: they go with it."""
    seen = _quarto(monkeypatch, log="", hang=True, write_output=False)
    with pytest.raises(render.RenderUnavailable, match="timed out"):
        render.render_quarto_html(
            b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t", timeout_s=1
        )
    assert seen["new_session"] is True
    assert seen["killed"] and set(seen["killed"]) == {4242}


def test_a_non_embedded_render_collects_the_files_beside_the_report(monkeypatch, tmp_path: Path):
    """A preview's document is rendered with ``embed-resources: false``: Quarto
    writes the report beside a ``<stem>_files/`` directory, and the render
    hands both back — the report under its served name, the files keyed as
    they are served."""
    monkeypatch.setitem(__import__("sys").modules, "jupyter_cache", object())
    seen = _quarto(
        monkeypatch,
        log="Executing 'report.quarto_ipynb'\n",
        write_files={
            "report_files/site_libs/quarto.js": b"console.log(1)",
            "report_files/site_libs/quarto.css": b"body{}",
        },
        stem="report",
    )
    html, files = render.render_quarto_html_files(
        b"---\ntitle: x\n---\n",
        stem="report",
        api_url="http://api",
        api_token="t",
        workdir=str(tmp_path / "preview"),
        cache=True,
    )
    assert html == b"<html>report</html>"
    assert files == {
        "report_files/site_libs/quarto.js": b"console.log(1)",
        "report_files/site_libs/quarto.css": b"body{}",
    }
    assert "--cache" in seen["cmd"]


def test_an_embedded_render_collects_no_files(monkeypatch):
    """A self-contained report carries everything in its one file: the plain
    render path is unchanged, and nothing is read from the output directory."""
    _quarto(monkeypatch, log="Executing 'x.quarto_ipynb'\n")
    html, files = render.render_quarto_html_files(
        b"---\ntitle: x\n---\n", stem="x", api_url="http://api", api_token="t"
    )
    assert html == b"<html>report</html>"
    assert files == {}


def test_job_keys_are_namespaced_by_user():
    """A download endpoint builds this from the *caller*, so it can only reach their own."""
    key = store.job_key("user1", "job1", "report.html")
    assert key.endswith("/user1/job1/report.html")
    assert store.job_key("user2", "job1", "report.html") != key


def test_preview_keys_carry_nothing_but_the_token_and_the_path():
    """The capability URL is the whole secret: no user id, no job id in the key."""
    key = store.preview_key("tok", "report_files/site_libs/quarto.js")
    assert key.endswith("/preview/tok/report_files/site_libs/quarto.js")
    assert store.preview_key("tok2", "report.html") != store.preview_key("tok", "report.html")
    assert store.preview_url("tok") == (
        "/depictio/api/v1/dashboards/notebook_export/preview_files/tok/report.html"
    )


def test_preview_content_types_come_from_the_extension():
    assert store.preview_content_type("report.html") == store.HTML_MEDIA_TYPE
    assert store.preview_content_type("report_files/site_libs/quarto.css") == "text/css"
    assert store.preview_content_type("report_files/x.bin") == "application/octet-stream"


def test_the_support_files_keep_the_name_the_report_links_them_by(monkeypatch, tmp_path: Path):
    """A report rendered as ``iris_analysis.html`` links ``iris_analysis_files/…``:
    renamed on the way to the store, every library 404s and the page loads
    without Quarto's scripts and styles."""
    monkeypatch.setitem(__import__("sys").modules, "jupyter_cache", object())
    _quarto(
        monkeypatch,
        log="Executing 'iris_analysis.quarto_ipynb'\n",
        write_files={"iris_analysis_files/libs/quarto-html/quarto.js": b"x"},
        stem="iris_analysis",
    )
    _html, files = render.render_quarto_html_files(
        b"---\ntitle: x\n---\n",
        stem="iris_analysis",
        api_url="http://api",
        api_token="t",
        workdir=str(tmp_path / "preview"),
        cache=True,
    )
    assert list(files) == ["iris_analysis_files/libs/quarto-html/quarto.js"]
