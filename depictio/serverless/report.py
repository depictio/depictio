"""The report host of the static runtime: producer A's manifest, in a Quarto report.

The common trunk of Depictio's two offline outputs (RFC serverless §14, RFC
notebook export §3.9). A serverless bundle and a rendered report embed the same
thing — one ``BundleManifest`` built by producer A, one static runtime — and
differ only in the host page:

* the bundle (``producer_a.export_static``) injects the manifest into
  ``static.html``, which mounts the viewer App over the whole page;
* the report (this module) inlines the manifest, once, beside the report
  runtime (``dist-static/report-runtime.{js,css}``, ``vite.report.config.ts``),
  which mounts each tile into the placeholder the notebook generator wrote for
  it, and the dashboard's controls into the report's "Filters" part.

The manifest is producer A's own (``export_manifest``), so a report is exactly
as live as the bundle of the same dashboard would be and is refused on the same
grounds: building one needs *owner* on the dashboard's project (RFC §8, a
manifest carries the data), and the same size ceilings apply. The one addition
is ``initial_filters``: the exported analysis state's filters, so the runtime
opens on the view the document narrates.

A state the runtime cannot reproduce in the page is not embedded at all
(:func:`ineligibility`): pinned data or definitions (the manifest holds current
data), and selection groups / colour-by / split panels (the report runtime has
no group store). Those reports keep every tile's own output, as before.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from depictio.models.models.analysis_state import AnalysisState
from depictio.models.models.serverless import BundleManifest
from depictio.notebook.report_runtime import compose_report_runtime

logger = logging.getLogger(__name__)

RUNTIME_DIR_ENV = "DEPICTIO_REPORT_RUNTIME_DIR"
RUNTIME_JS = "report-runtime.js"
RUNTIME_CSS = "report-runtime.css"


class ReportRuntimeUnavailable(RuntimeError):
    """The report runtime is not built next to the static template."""


class ReportRuntimeRefused(RuntimeError):
    """This state (or this caller) cannot have the runtime embedded."""


def runtime_dir() -> Path:
    """``dist-static/`` beside the static template in use (or the env override)."""
    override = os.environ.get(RUNTIME_DIR_ENV)
    if override:
        return Path(override)
    from depictio.serverless.producer_b import _template_path

    return _template_path().parent


def runtime_available() -> bool:
    folder = runtime_dir()
    return (folder / RUNTIME_JS).is_file() and (folder / RUNTIME_CSS).is_file()


@dataclass(frozen=True)
class RuntimeAssets:
    js: str
    css: str

    @property
    def bytes(self) -> int:
        return len(self.js.encode()) + len(self.css.encode())


def runtime_assets() -> RuntimeAssets:
    """The built runtime's script and stylesheet."""
    folder = runtime_dir()
    try:
        return RuntimeAssets(
            js=(folder / RUNTIME_JS).read_text(encoding="utf-8"),
            css=(folder / RUNTIME_CSS).read_text(encoding="utf-8"),
        )
    except OSError as exc:
        raise ReportRuntimeUnavailable(
            f"report runtime not built: {folder / RUNTIME_JS} is missing — run "
            "`cd depictio/viewer && pnpm run build:static`, or point "
            f"{RUNTIME_DIR_ENV} at a folder holding {RUNTIME_JS} and {RUNTIME_CSS}"
        ) from exc


def ineligibility(state: AnalysisState) -> str | None:
    """Why the runtime cannot open on ``state``, or ``None`` when it can."""
    if state.pins.active:
        return (
            "the export reads pinned data or definitions; the in-page runtime carries the "
            "current data only"
        )
    if state.color_by.kind != "none" or state.split_panels:
        return "the view is coloured or split by selection groups, which the in-page runtime does not draw"
    if any(g.filter_active for g in state.groups) or any(
        f.source == "group_filter" for f in state.filters
    ):
        return "a selection group filters the view, which the in-page runtime does not apply"
    return None


def initial_filters(state: AnalysisState) -> list[dict[str, Any]]:
    """The state's filters, in the wire shape the viewer's filter store holds."""
    return [f for f in state.filters_as_payload() if f.get("source") != "group_filter"]


def build_report_manifest(
    dashboard_id: str,
    user: Any,
    state: AnalysisState,
    *,
    python_runtime: str = "off",
) -> BundleManifest:
    """Producer A's manifest for ``dashboard_id``'s family, opening on ``state``.

    Raises :class:`ReportRuntimeRefused` for a state the runtime cannot
    reproduce, and lets producer A's own errors through (permission —
    ``ProducerAError`` — and size — ``BundleTooLargeError``).
    """
    reason = ineligibility(state)
    if reason:
        raise ReportRuntimeRefused(reason)
    if user is None:
        # producer A reads ``None`` as "the instance's admin" (operator-run
        # exports); a report is always somebody's, and gets only their rights.
        raise ReportRuntimeRefused("a report's manifest is built with its requester's rights")
    from depictio.serverless import producer_a

    result = producer_a.export_manifest(
        str(dashboard_id), producer_a.resolve_user(user), python_runtime=python_runtime
    )
    assert result.manifest is not None
    return result.manifest.model_copy(update={"initial_filters": initial_filters(state)})


def addon_markup(manifest: BundleManifest) -> str:
    from depictio.serverless.addons import addons_html

    pyodide = next((a for a in manifest.addons if a.name == "pyodide"), None)
    return addons_html(
        [a.name for a in manifest.addons], list(pyodide.packages) if pyodide else None
    )


def report_runtime_html(manifest: BundleManifest, *, config: dict[str, Any] | None = None) -> str:
    """The block a report inlines once: runtime CSS, config, manifest, add-ons, script.

    ``config`` is the report's look (``NotebookBuilder.runtime_config``).
    """
    assets = runtime_assets()
    return compose_report_runtime(
        js=assets.js,
        css=assets.css,
        manifest=manifest.model_dump(mode="json"),
        config=config,
        addons=addon_markup(manifest),
    )


def build_report_runtime(
    dashboard_id: str,
    user: Any,
    state: AnalysisState,
    *,
    config: dict[str, Any] | None = None,
    python_runtime: str = "off",
) -> str:
    """Everything a report needs to mount its tiles, as one HTML block."""
    if not runtime_available():
        raise ReportRuntimeUnavailable(f"report runtime not built in {runtime_dir()}")
    manifest = build_report_manifest(dashboard_id, user, state, python_runtime=python_runtime)
    return report_runtime_html(manifest, config=config)
