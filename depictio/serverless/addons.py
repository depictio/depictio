"""Conditional runtime add-ons for serverless bundles (RFC §13.4).

The base runtime (``viewer/dist-static/combined-runtime.js``) stays inside its byte
budget by leaving heavy, rarely needed libraries out. An add-on is a script the
producer appends to one bundle's HTML only when one of its components needs it,
and records in ``BundleManifest.addons`` so the tier table and the runtime can
say what was embedded and why.

* ``3dmol`` — 3Dmol.js (the package's own minified UMD build, BSD-3), for
  ``molecule_3d``. Built next to the runtime by
  ``viewer/scripts/build-static-addons.mjs`` into ``dist-static/addons/``, which
  ships in the wheel with the runtime. The runtime's ``3dmol`` module
  (``static-runtime/threeDmolAddon.ts``) reads the global the script defines and
  falls back to the stub's message when it is absent.

* ``jbrowse`` — JBrowse 2 with MUI and mobx (Apache-2.0 / MIT), for genome
  browser tiles whose files producer A shipped (``jbrowse_bundle.py``). Built
  by ``viewer/vite.static-jbrowse.config.ts`` into an IIFE with React external,
  wrapped by ``build-static-addons.mjs`` in a factory the runtime calls with
  its own React (``static-runtime/jbrowse/vendor.ts``); the base runtime keeps
  the depictio half of the renderer and forwards every JBrowse import to it.

* ``pyodide`` — the optional Python runtime (Pyodide, pinned in
  ``serverless/pyodide/pin.json``): the core, the packages the bundle's Python
  jobs need, and the server modules they run, all inlined as data blocks
  (``<script type="application/octet-stream" data-pya=…>``) plus one JSON meta
  block. Never in the wheel: the producer fetches and verifies the files at
  export (``pyodide/assets.py``). The runtime boots it lazily, on the first
  tile that asks (``static-runtime/pyodide/runtime.ts``).

A bundle places the add-ons before the runtime's own ``<script>``
(``serverless.bundle_html``), and a legacy template gets them before its
``</body>``: 3Dmol's classic ``<script>`` runs while the document parses, before
the runtime, so its global is in place when the runtime first imports ``3dmol``;
the Pyodide blocks are inert data until a tile boots the runtime.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from depictio.models.models.serverless import RuntimeAddon

logger = logging.getLogger(__name__)

ADDONS_DIR_ENV = "DEPICTIO_SERVERLESS_ADDONS_DIR"
REGISTRY_NAME = "addons.json"


class AddonError(RuntimeError):
    """An add-on a bundle needs is not available next to the runtime."""


def addons_dir() -> Path:
    """``dist-static/addons`` beside the runtime in use (or the env override)."""
    override = os.environ.get(ADDONS_DIR_ENV)
    if override:
        return Path(override)
    from depictio.serverless.dist import dist_static_dir

    return dist_static_dir() / "addons"


def registry() -> dict[str, Any]:
    """``addons.json``: ``{name: {version, file, bytes, sha256}}``; empty when not built."""
    path = addons_dir() / REGISTRY_NAME
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def addon_entry(name: str, reason: str) -> RuntimeAddon | None:
    """The manifest entry for a built add-on, or ``None`` when it was not built."""
    info = registry().get(name)
    if not info:
        return None
    return RuntimeAddon(
        name=name,  # type: ignore[arg-type]
        version=str(info.get("version", "")),
        bytes=int(info.get("bytes", 0)),
        reason=reason,
    )


def addon_script(name: str) -> str:
    """The ``<script>`` element embedding one add-on."""
    info = registry().get(name)
    if not info:
        raise AddonError(
            f"runtime add-on {name!r} is not built: run `cd depictio/viewer && pnpm run "
            f"build:static` (it writes {addons_dir() / REGISTRY_NAME})"
        )
    body = (addons_dir() / str(info["file"])).read_text(encoding="utf-8")
    if "</script" in body.lower():  # pragma: no cover - guarded at build time too
        raise AddonError(f"runtime add-on {name!r} contains '</script' and cannot be inlined")
    # A Quarto report loads RequireJS (Jupyter's widget and Plotly outputs), and
    # an add-on's UMD wrapper then registers itself as an anonymous AMD module
    # ("Mismatched anonymous define()") instead of setting its global. AMD is
    # hidden while the add-on runs and given back after; a page without it is
    # unchanged.
    return (
        "<script>window.__dpxDefine=window.define;window.define=undefined;</script>"
        f'<script data-depictio-addon="{name}">{body}</script>'
        "<script>window.define=window.__dpxDefine;delete window.__dpxDefine;</script>"
    )


PYODIDE_META_ID = "depictio-pyodide-meta"


def pyodide_html(packages: list[str]) -> str:
    """The Pyodide add-on's data blocks for ``packages`` (+ extras), verified."""
    from depictio.serverless.pyodide.assets import load_assets_named
    from depictio.serverless.pyodide.modules import bundle_python_sources

    assets = load_assets_named(packages)
    meta = {
        "version": assets.version,
        "packages": assets.packages,
        "extras": [f"{n}.zip" for n in assets.extras],
        "lock": assets.lock,
        "modules": bundle_python_sources(),
    }
    from depictio.notebook.report_runtime import json_script

    blocks = [json_script(PYODIDE_META_ID, meta)]
    for f in assets.files:
        blocks.append(
            f'<script type="application/octet-stream" data-pya="{f.name}" '
            f'data-gz="{int(f.gzip)}">{f.embedded()}</script>'
        )
    return "".join(blocks)


def addons_html(names: list[str], packages: list[str] | None = None) -> str:
    """The add-ons' elements, in order, as the bundle embeds them before its
    ``</body>``."""
    return "".join(
        pyodide_html(list(packages or [])) if n == "pyodide" else addon_script(n) for n in names
    )


def addon_markup(entries: Iterable[Any], *, skip_missing: bool = False) -> dict[str, str]:
    """Each add-on ``entries`` names (``BundleManifest.addons``: models or their
    JSON dicts), as its embedding markup, in order: what a report embeds beside
    the runtime. Pyodide's data blocks are built from the entry's packages.

    ``skip_missing`` leaves out an add-on that is not built (logged) instead of
    raising :class:`AddonError`.
    """
    out: dict[str, str] = {}
    for entry in entries:
        data = entry if isinstance(entry, dict) else entry.model_dump()
        name = str(data.get("name") or "")
        if not name or name in out:
            continue
        try:
            if name == "pyodide":
                out[name] = pyodide_html(list(data.get("packages") or []))
            else:
                out[name] = addon_script(name)
        except AddonError as exc:
            if not skip_missing:
                raise
            logger.warning("runtime add-on %r unavailable: %s", name, exc)
    return out


def apply_addons(template: str, names: list[str], packages: list[str] | None = None) -> str:
    """Insert the add-ons' scripts before the template's closing ``</body>``.

    ``packages`` is the Pyodide add-on's package list (``RuntimeAddon.packages``).
    """
    if not names:
        return template
    scripts = addons_html(names, packages)
    at = template.rfind("</body>")
    if at < 0:
        return template + scripts
    return template[:at] + scripts + template[at:]
