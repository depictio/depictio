"""The render service: what it refuses, and what it checks before believing Quarto."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from depictio.api.v1.services.notebook_export import render, store


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _quarto(monkeypatch, *, log: str, returncode: int = 0, write_output: bool = True):
    """Stand in for the Quarto binary, writing whatever report it claims to."""
    monkeypatch.setattr(render, "quarto_binary", lambda: "/usr/bin/quarto")
    monkeypatch.setitem(__import__("sys").modules, "nbclient", object())
    monkeypatch.setitem(__import__("sys").modules, "ipykernel", object())
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["env"] = kwargs.get("env") or {}
        if write_output:
            out = Path(kwargs["cwd"]) / f"{cmd[2].removesuffix('.quarto.ipynb')}.quarto.html"
            out.write_bytes(b"<html>report</html>")
        return FakeProc(returncode=returncode, stdout=log)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_render_needs_quarto(monkeypatch):
    monkeypatch.setattr(render, "quarto_binary", lambda: None)
    with pytest.raises(render.RenderUnavailable, match="Quarto is not installed"):
        render.render_quarto_html(b"{}", stem="x", api_url="http://api", api_token="t")


def test_render_returns_the_report_and_passes_the_caller_through(monkeypatch):
    seen = _quarto(monkeypatch, log="Executing 'x.quarto.ipynb'\n  Cell 1/2: ''...Done\n")
    html = render.render_quarto_html(b"{}", stem="x", api_url="http://api:8058", api_token="tok")
    assert html == b"<html>report</html>"
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
    _quarto(monkeypatch, log="pandoc\n  to: html\nOutput created: x.quarto.html\n")
    with pytest.raises(render.RenderUnavailable, match="without executing"):
        render.render_quarto_html(b"{}", stem="x", api_url="http://api", api_token="t")


def test_a_failed_render_carries_quarto_s_own_message(monkeypatch):
    _quarto(monkeypatch, log="An error occurred: cell 4 raised", returncode=1, write_output=False)
    with pytest.raises(render.RenderUnavailable, match="cell 4 raised"):
        render.render_quarto_html(b"{}", stem="x", api_url="http://api", api_token="t")


def test_job_keys_are_namespaced_by_user():
    """A download endpoint builds this from the *caller*, so it can only reach their own."""
    key = store.job_key("user1", "job1", "report.html")
    assert key.endswith("/user1/job1/report.html")
    assert store.job_key("user2", "job1", "report.html") != key
