"""The report and PDF of a public project's visitors' copy (#1480).

Rendered on a worker after the family's public bundle, under the same content
key (``public_bundle.build_report``), and held to the same rules as that bundle:

* as the project's owner, without their email: the cover's "exported by" stays
  empty and the token the notebook runs with is minted for this render and
  revoked when it ends, whichever way it ends;
* at the dashboard's default state, as the bundle is (a report layer's own
  state is not applied: a visitor gets what the dashboard opens on);
* without running an author's Python (``author_code=False``: a code-mode figure
  is drawn by the API's sandbox, as the dashboard draws it) and without its
  source in the document;
* with the public manifest (code-mode figures frozen, no Python runtime).

The output is the combined report + dashboard file (the report first, its
switch to the dashboard on) and its PDF; a failed PDF leaves the report.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger


@dataclass
class _Owner:
    """The project's owner as the export plan reads a user, without an email."""

    id: Any
    email: str = ""
    is_admin: bool = False
    is_anonymous: bool = False


def strip_author_code(tabs: list[dict[str, Any]]) -> int:
    """Drop the source of every code-mode figure of ``tabs``; the count dropped.

    With ``author_code`` off the report asks the API for these figures, which
    reads the stored definition: the document needs no source, and a visitor's
    copy carries none.
    """
    dropped = 0
    for tab in tabs:
        for meta in tab.get("stored_metadata") or []:
            if (
                isinstance(meta, dict)
                and meta.get("component_type") == "figure"
                and meta.get("mode") == "code"
            ):
                meta["code_content"] = None
                dropped += 1
    return dropped


def public_plan(main_id: str, owner: Any, access_token: str | None) -> Any:
    """The export plan of a visitor's report: default state, no exporter, no
    author code."""
    from depictio.api.v1.endpoints.dashboards_endpoints.notebook_export import build_export_plan
    from depictio.models.models.analysis_state import AnalysisContext, AnalysisState
    from depictio.models.models.base import PyObjectId

    state = AnalysisState(context=AnalysisContext(dashboard_id=str(main_id)))
    plan = build_export_plan(
        PyObjectId(str(main_id)), state, owner, access_token, embed_runtime=True, pdf=True
    )
    plan.exported_by = None
    plan.author_code = False
    strip_author_code(plan.tabs)
    return plan


def public_manifest(main_id: str, owner_id: Any) -> Any:
    """The public manifest the combined file embeds (producer A, ``public=True``)."""
    from depictio.serverless import producer_a

    result = producer_a.export_manifest(
        str(main_id),
        producer_a.ExportUser(id=owner_id, email="", is_admin=False, is_anonymous=False),
        python_runtime="off",
        state=None,
        public=True,
    )
    assert result.manifest is not None
    return result.manifest.model_copy(update={"initial_filters": []})


async def _with_beanie(action: Any) -> Any:
    from beanie import init_beanie
    from pymongo import AsyncMongoClient

    from depictio.api.v1.configs.config import MONGODB_URL
    from depictio.models.models.users import TokenBeanie, UserBeanie

    client: AsyncMongoClient = AsyncMongoClient(MONGODB_URL)
    try:
        await init_beanie(
            database=client[settings.mongodb.db_name], document_models=[TokenBeanie, UserBeanie]
        )
        return await action()
    finally:
        await client.close()


def _mint(owner_id: Any, name: str, lifetime_s: int) -> Any:
    from depictio.api.v1.services.task_tokens import mint_task_token

    return asyncio.run(_with_beanie(lambda: mint_task_token(str(owner_id), name, lifetime_s)))


def _revoke(token: Any) -> None:
    from depictio.api.v1.services.task_tokens import revoke

    asyncio.run(_with_beanie(lambda: revoke(token)))


def render_public_report(main_id: str, owner_id: Any) -> tuple[bytes, bytes | None, str]:
    """``(combined report + dashboard HTML, PDF or None, file stem)``."""
    from depictio.api.v1.services.notebook_export.generator import NotebookBuilder
    from depictio.api.v1.services.notebook_export.render import (
        render_quarto_html_files,
        render_quarto_pdf,
    )
    from depictio.notebook.report_runtime import RUNTIME_DEFERRED_ENV
    from depictio.serverless.combined import embed_runtime
    from depictio.serverless.report import manifest_json

    timeout = settings.notebook_export.render_timeout_s
    token = _mint(owner_id, f"public-report-{main_id}", 2 * timeout + 900)
    try:
        plan = public_plan(main_id, _Owner(id=owner_id), token.access_token)
        builder = NotebookBuilder(plan)
        qmd = builder.build().encode("utf-8")
        manifest = public_manifest(main_id, owner_id)
        env = {RUNTIME_DEFERRED_ENV: "1"}
        html, _files = render_quarto_html_files(
            qmd,
            stem=plan.stem,
            api_url=settings.fastapi.internal_url,
            api_token=token.access_token,
            timeout_s=timeout,
            extra_env=env,
        )
        combined = embed_runtime(
            html.decode("utf-8"),
            manifest_json(manifest),
            list(manifest.addons),
            config=builder.runtime_config(),
            output="combined",
            default_view="report",
        )
        pdf: bytes | None
        try:
            pdf = render_quarto_pdf(
                qmd,
                stem=plan.stem,
                api_url=settings.fastapi.internal_url,
                api_token=token.access_token,
                timeout_s=timeout,
                extra_env=env,
            )
        except Exception as exc:  # noqa: BLE001 - the report stands on its own
            logger.warning(f"public report: PDF of {main_id} failed: {exc}")
            pdf = None
        return combined.html.encode("utf-8"), pdf, plan.stem
    finally:
        try:
            _revoke(token)
        except Exception as exc:  # noqa: BLE001 - never mask the render's own error
            logger.warning(f"public report: could not revoke the token of {main_id}: {exc}")
