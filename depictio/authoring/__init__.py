"""Depictio Studio — host-side, service-free authoring backend.

``depictio studio <dir>`` launches a standalone uvicorn app (no Mongo/Redis/
Celery/S3) that serves the studio SPA plus the ``/studio/*`` authoring API. The
central gesture is *pick file(s) → see the data → design a viz*, feeding two
outputs from the same UI:

- **Dashboard** — picked files become Data Collections; visus attach to them →
  ``project.yaml`` + ``dashboard.yaml`` (importable via ``depictio run`` /
  ``dashboard import``).
- **Catalogue** — deferred in this pass (see :mod:`depictio.authoring.export_catalog`).

Everything here reuses depictio's existing Dash-free, service-free primitives:
``build_payload`` (preview), ``match_run_dir`` (recognition), ``suggest_viz_kinds``
(suggestions) and ``DashboardDataLite`` / ``auto_generate_layout`` (export). No
module in this package may import ``depictio.api.main`` (it pulls Beanie/Mongo).
"""

from depictio.authoring.paths import safe_resolve

__all__ = ["safe_resolve"]
