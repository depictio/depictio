"""The static runtime in a rendered report: the report alone, or the report AND
the dashboard in one HTML file.

``depictio/serverless/combined.py`` embeds the one runtime in a rendered
report: Quarto's plotly.js out (the runtime's Plotly draws the report's
figures), the runtime in once — where plotly.js was — with the manifest, its
add-ons (or the report's own 3Dmol, lent to the dashboard) and its stylesheet
as inert text. The two outputs differ only by the config's ``combined``
section, so a report-only file becomes the combined one by flipping it. These
tests hold the composition to that on a page shaped like a Quarto report, then
the endpoint's gate, the worker's path to it and the CLI.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.models.models.analysis_state import AnalysisState, NotebookExportRequest
from depictio.notebook.components import public_reason
from depictio.notebook.report_runtime import CONFIG_ID, MANIFEST_ID
from depictio.serverless import combined

PLOTLY = "/**\n* plotly.js v3.7.0\n* Copyright 2012-2026, Plotly, Inc.\n*/\nwindow.Plotly = {};"
THREEDMOL = (
    "/*! For license information please see 3Dmol-min.js.LICENSE.txt */\n"
    'var root,factory;root=this;root["3Dmol"]={};'
)
FIGURE = '<script>window.PLOTLYENV={};Plotly.newPlot("f1",[],{});</script>'
JS = "window.__combined=1;var s='</script>';/*<!-- -->*/"
CSS = ":root{--x:1}body{margin:0}.depictio-tile{display:block}"
MANIFEST = {"dashboard": {"id": "d1", "title": "T", "doc": {}}, "built_at": "now", "addons": []}


def _report(*, plotly: bool = True, threedmol: bool = False) -> str:
    parts = [
        "<!DOCTYPE html><html><head><title>R</title></head><body class='quarto-light'>",
        "<h1>Report</h1>",
        "<script>window.PlotlyConfig = {MathJaxConfig: 'local'};</script>",
    ]
    if plotly:
        parts.append(f"<script>{PLOTLY}</script>")
    parts.append(FIGURE)
    if threedmol:
        parts.append(
            "<script>window.__dpxDefine=window.define;window.define=undefined;</script>"
            f"<script>{THREEDMOL}</script>"
        )
    parts.append(
        '<div class="depictio-tile" data-depictio-tile="d1:c1"><div class="depictio-fallback">'
        "<b>X</b></div></div>"
    )
    parts.append("</body></html>")
    return "".join(parts)


def _compose(html: str, **kw: Any) -> combined.ComposedReport:
    return combined.compose_report(html, MANIFEST, js=JS, css=CSS, **kw)


def _runtime_script_bodies(html: str) -> list[str]:
    return re.findall(r'<script data-depictio-runtime="js">(.*?)</script>', html, re.DOTALL)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_the_runtime_takes_the_place_of_quartos_plotly():
    out = _compose(_report())
    html = out.html
    assert "plotly.js v3.7.0" not in html
    assert out.plotly_dropped == len(f"<script>{PLOTLY}</script>")
    # Where plotly.js was: before the figures that call window.Plotly.
    assert html.index('data-depictio-runtime="js"') < html.index("Plotly.newPlot")
    assert html.index("PlotlyConfig") < html.index('data-depictio-runtime="js"')
    assert len(_runtime_script_bodies(html)) == 1


def test_without_quartos_plotly_the_runtime_closes_the_page():
    html = _compose(_report(plotly=False)).html
    assert html.index(f'id="{MANIFEST_ID}"') < html.index('data-depictio-runtime="js"')
    assert html.index('data-depictio-runtime="js"') < html.index("</body>")


def test_one_manifest_one_config_one_stylesheet_and_nothing_closes_early():
    html = _compose(_report()).html
    assert html.count(f'id="{MANIFEST_ID}"') == 1
    assert html.count(f'id="{CONFIG_ID}"') == 1
    assert html.count('data-depictio-runtime="css"') == 1
    # The stylesheet is inert text: never applied to the report as written.
    assert '<script type="text/plain" data-depictio-runtime="css">' in html
    assert "<style data-depictio-runtime" not in html
    body = _runtime_script_bodies(html)[0]
    assert "</script" not in body and "<!--" not in body
    assert "window.__combined=1" in body


def test_the_two_outputs_differ_by_the_combined_section_only():
    look = {"brand": {"primary": "#159090"}}
    alone = _compose(_report(), config=look).html
    both = _compose(_report(), config=look, output="combined", default_view="dashboard").html
    assert combined.embedded_config(alone) == look
    assert combined.embedded_config(both) == {**look, "combined": {"default_view": "dashboard"}}
    config_re = rf'<script type="application/json" id="{CONFIG_ID}">.*?</script>'
    assert re.sub(config_re, "", alone) == re.sub(config_re, "", both)
    # And a report-only file becomes the combined one by flipping that section.
    assert combined.set_output(alone, "combined", "dashboard") == both
    assert combined.set_output(both, "report") == alone


def test_flipping_needs_an_embedded_runtime():
    with pytest.raises(ValueError, match="does not embed"):
        combined.set_output(_report(), "combined")


def test_the_reports_own_3dmol_is_lent_to_the_dashboard():
    out = _compose(
        _report(threedmol=True), addons={"3dmol": '<script data-depictio-addon="3dmol">x</script>'}
    )
    assert out.addons_shared == ("3dmol",)
    assert out.html.count("3Dmol-min.js.LICENSE") == 1
    assert out.html.count('data-depictio-addon="3dmol"') == 1
    tagged = out.html.index('data-depictio-addon="3dmol"')
    assert out.html.index("3Dmol-min.js.LICENSE") > tagged


def test_an_addon_the_report_lacks_goes_in_before_the_runtime():
    out = _compose(
        _report(), addons={"jbrowse": '<script data-depictio-addon="jbrowse">jb</script>'}
    )
    assert out.addons_shared == ()
    assert out.html.count('data-depictio-addon="jbrowse"') == 1
    assert out.html.index('data-depictio-addon="jbrowse"') < out.html.index(
        'data-depictio-runtime="js"'
    )


def test_the_default_view_and_the_output_are_checked():
    with pytest.raises(ValueError):
        _compose(_report(), output="combined", default_view="both")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _compose(_report(), output="both")  # type: ignore[arg-type]


def test_the_runtime_floor_is_the_runtime_and_nothing_else():
    """What every report that embeds the runtime pays for it (CI's budget floor,
    written by build-demo.mjs), on top of its report and manifest."""
    page = "<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>"
    floor = combined.compose_report(page, "null", js="a" * 1000, css="b" * 100).html
    assert floor.count("a" * 1000) == 1 and floor.count("b" * 100) == 1
    assert len(floor) < 1000 + 100 + 1000


def test_the_body_end_is_found_in_either_case():
    html = _compose(_report(plotly=False).replace("</body>", "</BODY>")).html
    assert html.index('data-depictio-runtime="js"') < html.index("</BODY>")


# ---------------------------------------------------------------------------
# What an exported error may say
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Depictio API returned 500: Executable doesn't exist at /opt/pw-browsers/x/chrome\n"
            "╔══╗\n║ banner ║",
            "Depictio API returned 500: Executable doesn't exist at <path>",
        ),
        ("C:\\Users\\me\\data.parquet missing", "<path> missing"),
        ("fetch https://example.org/a/b failed", "fetch https://example.org/a/b failed"),
        ("ratio 1/2 and a/b", "ratio 1/2 and a/b"),
        ("", "unavailable"),
    ],
)
def test_public_reason(raw: str, expected: str):
    assert public_reason(raw) == expected


def test_public_reason_is_bounded():
    assert len(public_reason("x" * 1000)) == 300


# ---------------------------------------------------------------------------
# The built runtime
# ---------------------------------------------------------------------------


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from depictio.serverless import report

    (tmp_path / combined.RUNTIME_JS).write_text(JS)
    (tmp_path / combined.RUNTIME_CSS).write_text(CSS)
    monkeypatch.setenv(report.RUNTIME_DIR_ENV, str(tmp_path))
    addons = tmp_path / "addons"
    addons.mkdir()
    (addons / "jbrowse.js").write_text("window.__jb=1;")
    (addons / "addons.json").write_text(
        json.dumps({"jbrowse": {"version": "4", "file": "jbrowse.js", "bytes": 14}})
    )
    monkeypatch.setenv("DEPICTIO_SERVERLESS_ADDONS_DIR", str(addons))
    return tmp_path


def test_embed_runtime_reads_the_built_runtime_and_addons(built):
    entries = [{"name": "jbrowse", "version": "4", "bytes": 14}]
    out = combined.embed_runtime(_report(), {**MANIFEST, "addons": entries}, entries)
    assert "window.__combined=1" in out.html
    assert 'data-depictio-addon="jbrowse">window.__jb=1;</script>' in out.html


def test_a_missing_runtime_is_a_named_error(tmp_path, monkeypatch):
    from depictio.serverless import report

    monkeypatch.setenv(report.RUNTIME_DIR_ENV, str(tmp_path))
    assert not combined.runtime_available()
    with pytest.raises(combined.RuntimeUnavailable, match="build:static"):
        combined.runtime_assets()


def test_addon_markup_is_one_builder_for_every_path(built):
    from depictio.serverless.addons import AddonError, addon_markup

    markup = addon_markup([{"name": "jbrowse"}, {"name": "jbrowse"}])
    assert list(markup) == ["jbrowse"] and "window.__jb=1;" in markup["jbrowse"]
    with pytest.raises(AddonError):
        addon_markup([{"name": "3dmol"}])
    assert addon_markup([{"name": "3dmol"}, {"name": "jbrowse"}], skip_missing=True).keys() == {
        "jbrowse"
    }


# ---------------------------------------------------------------------------
# The endpoint's gate
# ---------------------------------------------------------------------------


def _state() -> AnalysisState:
    return AnalysisState.model_validate({"filters": [], "context": {"dashboard_id": "d1"}})


def test_combined_needs_rendering_a_built_runtime_and_the_runtime_rules(built):
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as ep

    user = type("U", (), {"id": ObjectId()})()
    with patch.object(ep.settings.notebook_export, "render_enabled", False):
        assert "does not render" in (ep._combined_refusal("d1", _state(), user) or "")  # type: ignore[arg-type]
    with (
        patch.object(ep.settings.notebook_export, "render_enabled", True),
        patch.object(ep, "_owner_refusal", lambda *a: "limited to its owners"),
    ):
        assert ep._combined_refusal("d1", _state(), user) == "limited to its owners"  # type: ignore[arg-type]
    with (
        patch.object(ep.settings.notebook_export, "render_enabled", True),
        patch.object(ep, "_owner_refusal", lambda *a: None),
    ):
        assert ep._combined_refusal("d1", _state(), user) is None  # type: ignore[arg-type]
        (built / combined.RUNTIME_JS).unlink()
        assert "not built" in (ep._combined_refusal("d1", _state(), user) or "")  # type: ignore[arg-type]


def test_a_refused_combined_render_is_an_error_not_a_downgrade():
    from depictio.api.v1.endpoints.dashboards_endpoints import notebook_export as ep

    user = type("U", (), {"id": ObjectId(), "email": "a@b.c"})()
    with (
        patch.object(ep.settings.notebook_export, "render_enabled", True),
        patch.object(ep, "_combined_refusal", lambda *a: "limited to its owners"),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                ep.notebook_export_render(
                    dashboard_id="d1",  # type: ignore[arg-type]
                    request=NotebookExportRequest(state=_state(), output="combined"),
                    current_user=user,  # type: ignore[arg-type]
                    access_token=None,
                )
            )
    assert exc.value.status_code == 409
    assert "limited to its owners" in exc.value.detail


def test_the_request_defaults_to_the_report_alone():
    req = NotebookExportRequest(state=_state())
    assert req.output == "report" and req.default_view == "report"


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------


class _Token:
    access_token = "tok"

    async def delete(self) -> None:
        return None


class _Mongo:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    def __getitem__(self, name: str) -> Any:
        return object()

    async def close(self) -> None:
        return None


async def _noop(*a: Any, **k: Any) -> None:
    return None


async def _token(*a: Any, **k: Any) -> _Token:
    return _Token()


def _run_task(monkeypatch: pytest.MonkeyPatch, **kw: Any) -> tuple[dict, dict, dict]:
    from depictio.api import celery_app as worker
    from depictio.api.v1.services.notebook_export import render as render_mod
    from depictio.api.v1.services.notebook_export import store

    stored: dict[str, bytes] = {}
    seen: dict[str, Any] = {}

    def fake_render(qmd: bytes, **opts: Any) -> bytes:
        seen["deferred"] = opts["extra_env"].get("DEPICTIO_REPORT_RUNTIME_DEFERRED")
        return _report().encode()

    monkeypatch.setattr("pymongo.AsyncMongoClient", _Mongo)
    monkeypatch.setattr("beanie.init_beanie", _noop)
    monkeypatch.setattr("depictio.models.models.users.TokenBeanie.get", _token)
    monkeypatch.setattr(store, "get", lambda key: b"---\ntitle: x\n---\n")
    monkeypatch.setattr(store, "put", lambda key, body, ct: stored.__setitem__(key, body))
    monkeypatch.setattr(store, "delete", lambda key: None)
    monkeypatch.setattr(render_mod, "render_quarto_html", fake_render)
    monkeypatch.setattr(worker.render_notebook_report, "update_state", lambda **k: None)
    result = worker.render_notebook_report.run(
        job_id="job1",
        user_id="u1",
        notebook_key="k.qmd",
        stem="report",
        api_url="http://api",
        token_id=str(ObjectId()),
        **kw,
    )
    return result, stored, seen


RUNTIME = {
    "dashboard_id": "d1",
    "state": {"filters": []},
    "user": {"id": str(ObjectId()), "email": "", "is_admin": False, "is_anonymous": False},
    "config": {"brand": {"primary": "#123456"}},
}


class _Manifest:
    """What the worker reads of producer A's manifest."""

    addons: list[Any] = []

    def model_dump_json(self) -> str:
        return json.dumps(MANIFEST)


def _manifest(*a: Any) -> Any:
    return _Manifest()


def test_the_worker_embeds_the_combined_file_after_rendering(monkeypatch, built):
    from depictio.api import celery_app as worker

    monkeypatch.setattr(worker, "_report_manifest", _manifest)
    result, stored, seen = _run_task(
        monkeypatch,
        runtime=RUNTIME,
        combined={"default_view": "dashboard"},
        filename="report-report-dashboard.html",
    )
    assert seen["deferred"] == "1"  # the document printed no runtime of its own
    assert result["filename"] == "report-report-dashboard.html"
    html = stored[result["key"]].decode()
    assert result["key"].endswith("/report-report-dashboard.html")
    assert "window.__combined=1" in html and "plotly.js v3" not in html
    config = combined.embedded_config(html)
    assert config["combined"] == {"default_view": "dashboard"}
    assert config["brand"] == {"primary": "#123456"}


def test_a_report_job_embeds_the_same_runtime_without_the_switch(monkeypatch, built):
    from depictio.api import celery_app as worker

    monkeypatch.setattr(worker, "_report_manifest", _manifest)
    result, stored, seen = _run_task(monkeypatch, runtime=RUNTIME)
    assert seen["deferred"] == "1"
    assert result["filename"] == "report.html"
    html = stored[result["key"]].decode()
    assert "window.__combined=1" in html and "plotly.js v3" not in html
    assert combined.embedded_config(html) == {"brand": {"primary": "#123456"}}


def test_a_combined_job_whose_manifest_fails_fails(monkeypatch, built):
    from depictio.api import celery_app as worker
    from depictio.serverless.producer_a import ProducerAError

    def boom(runtime: dict) -> dict:
        raise ProducerAError("permission denied")

    monkeypatch.setattr(worker, "_report_manifest", boom)
    with pytest.raises(ProducerAError):
        _run_task(monkeypatch, runtime=RUNTIME, combined={"default_view": "report"})


def test_a_report_job_whose_manifest_fails_keeps_its_fallbacks(monkeypatch, built):
    from depictio.api import celery_app as worker
    from depictio.serverless.producer_a import ProducerAError

    def boom(runtime: dict) -> dict:
        raise ProducerAError("permission denied")

    monkeypatch.setattr(worker, "_report_manifest", boom)
    result, stored, seen = _run_task(monkeypatch, runtime=RUNTIME)
    # Still deferred: the document must not ask the API for what failed here.
    assert seen["deferred"] == "1"
    html = stored[result["key"]].decode()
    assert "window.__combined" not in html and "plotly.js v3" in html


def test_a_time_limit_during_the_manifest_is_the_tasks(monkeypatch, built):
    from celery.exceptions import SoftTimeLimitExceeded

    from depictio.api import celery_app as worker

    def slow(runtime: dict) -> dict:
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(worker, "_report_manifest", slow)
    with pytest.raises(SoftTimeLimitExceeded):
        _run_task(monkeypatch, runtime=RUNTIME)


def test_the_task_limits_count_the_manifest_build():
    from depictio.api import celery_app as worker

    render = worker.settings.notebook_export.render_timeout_s
    task = worker.render_notebook_report
    assert task.soft_time_limit >= worker.MANIFEST_BUILD_S + 2 * render
    assert task.time_limit > task.soft_time_limit


def test_a_plain_report_job_is_unchanged(monkeypatch, built):
    result, stored, seen = _run_task(monkeypatch)
    assert seen["deferred"] is None
    assert result["filename"] == "report.html"
    assert "window.__combined" not in stored[result["key"]].decode()


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def test_the_cli_turns_a_report_only_file_into_the_combined_one(tmp_path):
    """Offline and from the file alone: no built runtime is needed."""
    from typer.testing import CliRunner

    from depictio.cli.cli.commands.dashboard import app

    alone = _compose(_report(), config={"brand": {"primary": "#159090"}}).html
    src = tmp_path / "penguins.html"
    src.write_text(alone)
    res = CliRunner().invoke(app, ["combine-report", str(src), "--default-view", "dashboard"])
    assert res.exit_code == 0, res.output
    out = tmp_path / "penguins-report-dashboard.html"
    html = out.read_text()
    assert html.count("window.__combined=1") == 1
    assert combined.embedded_config(html) == {
        "brand": {"primary": "#159090"},
        "combined": {"default_view": "dashboard"},
    }
    assert combined.embedded_manifest(html) == MANIFEST


def test_the_cli_refuses_a_report_without_the_runtime(tmp_path):
    from typer.testing import CliRunner

    from depictio.cli.cli.commands.dashboard import app

    src = tmp_path / "plain.html"
    src.write_text(_report())
    res = CliRunner().invoke(app, ["combine-report", str(src)])
    assert res.exit_code == 1
    assert "does not embed" in res.output
    bad = CliRunner().invoke(app, ["combine-report", str(src), "--default-view", "both"])
    assert bad.exit_code == 2
