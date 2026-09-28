"""Ingestion agent tools: flag-gated wrappers over the /projects/from_run flow."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1 import db
from depictio.api.v1.agents import ratelimit
from depictio.api.v1.agents.context import ToolContext
from depictio.api.v1.agents.registry import invoke, tools_for
from depictio.api.v1.agents.tools import ingestion as tools
from depictio.api.v1.endpoints.projects_endpoints import from_run, manifest_ingest
from depictio.api.v1.endpoints.projects_endpoints.from_run import FromRunReport
from depictio.api.v1.endpoints.projects_endpoints.manifest_ingest import ManifestRefreshReport
from depictio.api.v1.endpoints.projects_endpoints.templates_catalog import (
    TemplateCatalog,
    TemplateInfo,
)
from depictio.models.models.users import effective_scopes

INGEST_TOOLS = {"list_templates", "preview_run", "create_project_from_run", "get_ingestion_status"}
RUN = {"data_root": "s3://bucket/run1", "template_id": "nf-core/ampliseq/2.14.0"}


def run(coro):
    return asyncio.run(coro)


def _ctx(scopes=None):
    return ToolContext(
        user=SimpleNamespace(id=ObjectId(), email="a@b.c", is_admin=False),  # type: ignore[arg-type]
        scopes=effective_scopes(scopes),
        token_id=str(ObjectId()),
    )


@pytest.fixture
def audit():
    ratelimit.reset_local()
    with (
        patch.object(
            db, "agent_tool_calls_collection", mongomock.MongoClient()["t"]["agent_tool_calls"]
        ),
        patch.object(ratelimit, "_redis_client", return_value=None),
    ):
        yield
    ratelimit.reset_local()


@pytest.fixture
def ingest_on(audit):
    from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils

    with (
        patch.object(tools.settings.mcp, "enable_ingest", True),
        patch.object(tools, "_reject_in_public_mode"),
        patch.object(dc_utils, "_ensure_user_cli_token", new=AsyncMock()) as token,
    ):
        yield token


def _report(**kwargs):
    return FromRunReport(
        project_name="ampliseq",
        template_id=RUN["template_id"],
        data_root=RUN["data_root"],
        **kwargs,
    )


def test_flag_off_hides_every_ingestion_tool(audit):
    with patch.object(tools.settings.mcp, "enable_ingest", False):
        assert not INGEST_TOOLS & {s.name for s in tools_for(effective_scopes(None))}
        result = run(invoke("preview_run", _ctx(), RUN))
        assert result.error == "Unknown tool: preview_run"
    with patch.object(tools.settings.mcp, "enable_ingest", True):
        assert INGEST_TOOLS <= {s.name for s in tools_for(effective_scopes(None))}
        read_only = {s.name for s in tools_for(effective_scopes(["read"]))}
        assert {"list_templates", "get_ingestion_status"} <= read_only
        assert not {"preview_run", "create_project_from_run"} & read_only


def test_list_templates(ingest_on):
    catalog = TemplateCatalog(
        templates=[TemplateInfo(template_id="t/1", name="T", dashboards=["a.yaml", "b.yaml"])]
    )
    with patch.object(tools, "list_templates_catalog", return_value=catalog):
        result = run(invoke("list_templates", _ctx(["read"]), {}))
    assert result.ok and result.data["templates"][0]["dashboards"] == 2


def test_preview_run_is_a_dry_run(ingest_on):
    # A dry run creates nothing, so it mints no token either (as the route).
    with patch.object(
        from_run, "_create_project_from_run", return_value=_report(dry_run=True, success=True)
    ) as core:
        result = run(invoke("preview_run", _ctx(["ingest"]), {**RUN, "variables": {"A": "b"}}))
    assert result.ok, result.error
    assert result.data["dry_run"] is True and result.data["project_id"] is None
    kwargs = core.call_args.kwargs
    assert kwargs["dry_run"] is True and kwargs["variables"] == {"A": "b"}
    assert kwargs["data_root"] == RUN["data_root"] and ingest_on.await_count == 0


def test_create_project_mints_the_cli_token_then_runs_for_real(ingest_on):
    report = _report(project_id=str(ObjectId()), run_id="r1", success=True)
    with patch.object(from_run, "_create_project_from_run", return_value=report) as core:
        result = run(invoke("create_project_from_run", _ctx(["ingest"]), RUN))
    assert result.ok and result.data["run_id"] == "r1"
    assert core.call_args.kwargs["dry_run"] is False and ingest_on.await_count == 1


def test_local_paths_are_refused_like_the_rest_route(ingest_on):
    result = run(invoke("preview_run", _ctx(["ingest"]), {**RUN, "data_root": "/app/data/run1"}))
    assert not result.ok and result.error.startswith("data_root must be an s3:// prefix")


def test_rest_errors_scope_and_validation_are_mapped(ingest_on):
    with patch.object(
        from_run,
        "_create_project_from_run",
        side_effect=HTTPException(status_code=409, detail="A project named 'x' already exists"),
    ):
        result = run(invoke("create_project_from_run", _ctx(["ingest"]), RUN))
    assert not result.ok and "already exists" in result.error

    result = run(invoke("preview_run", _ctx(["read", "annotate"]), RUN))
    assert not result.ok and "'ingest' scope" in result.error

    result = run(invoke("preview_run", _ctx(["ingest"]), {**RUN, "template_id": "../etc"}))
    assert not result.ok and result.error.startswith("Invalid arguments")


def test_public_mode_gate_runs_first(audit):
    denied = HTTPException(status_code=403, detail="Project creation is disabled in public mode")
    with (
        patch.object(tools.settings.mcp, "enable_ingest", True),
        patch.object(tools, "_reject_in_public_mode", side_effect=denied),
        patch.object(from_run, "_create_project_from_run") as core,
    ):
        result = run(invoke("create_project_from_run", _ctx(["ingest"]), RUN))
    assert result.error == "Project creation is disabled in public mode"
    core.assert_not_called()


def test_ingestion_status(ingest_on):
    from depictio.api.v1.monitoring import store

    report = ManifestRefreshReport(project_id="p", run_id="r1")
    with (
        patch.object(manifest_ingest, "_get_refresh_run_report", return_value=report),
        patch.object(store, "get_ingestion_run", return_value={"status": "running"}),
    ):
        result = run(invoke("get_ingestion_status", _ctx(["read"]), {"run_id": "r1"}))
    assert result.ok and result.data["status"] == "running" and not result.data["finished"]

    other = HTTPException(status_code=403, detail="This refresh run belongs to another user.")
    with patch.object(manifest_ingest, "_get_refresh_run_report", side_effect=other):
        result = run(invoke("get_ingestion_status", _ctx(["read"]), {"run_id": "r1"}))
    assert result.error == "This refresh run belongs to another user."

    both = run(invoke("get_ingestion_status", _ctx(), {"run_id": "r1", "project_id": "p"}))
    assert not both.ok and "exactly one" in both.error
