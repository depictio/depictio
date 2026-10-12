"""Depictio Project Builder — host-side, service-free authoring backend.

``depictio project-builder <dir>`` launches a standalone uvicorn app (no Mongo/Redis/
Celery/S3) that serves the Project Builder SPA plus the ``/project-builder/*`` authoring API. The
gesture is *point at a folder → associate file(s) to Data Collections → create a
project*: picked files become Data Collections whose scan glob/regex is inferred
by config-by-example, producing a validated ``project.yaml`` importable via
``depictio run``.

Scope stops at the data setup — dashboards are authored later, in the editor of a
real deployment, after ``depictio run`` imports the project.

Everything here reuses depictio's existing Dash-free, service-free primitives:
``preview_file`` (polars preview), ``match_run_dir`` (recognition) and the real
``DataCollection`` model (per-DC validation). No module in this package may import
``depictio.api.main`` (it pulls Beanie/Mongo).
"""

from depictio.project_builder.paths import safe_resolve

__all__ = ["safe_resolve"]
