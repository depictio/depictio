"""Conditional runtime add-ons for serverless bundles (RFC §13.4).

The base runtime (``viewer/dist-static/static.html``) stays inside its byte
budget by leaving heavy, rarely needed libraries out. An add-on is a script the
producer appends to one bundle's HTML only when one of its components needs it,
and records in ``BundleManifest.addons`` so the tier table and the runtime can
say what was embedded and why.

* ``3dmol`` — 3Dmol.js (the package's own minified UMD build, BSD-3), for
  ``molecule_3d``. Built next to the template by
  ``viewer/scripts/build-static-addons.mjs`` into ``dist-static/addons/``, which
  ships in the wheel with the template. The runtime's ``3dmol`` module
  (``static-runtime/threeDmolAddon.ts``) reads the global the script defines and
  falls back to the stub's message when it is absent.

* ``pyodide`` — the optional Python runtime (Pyodide, pinned in
  ``serverless/pyodide/pin.json``): the core, the packages the bundle's Python
  jobs need, and the server modules they run, all inlined as data blocks
  (``<script type="application/octet-stream" data-pya=…>``) plus one JSON meta
  block. Never in the wheel: the producer fetches and verifies the files at
  export (``pyodide/assets.py``). The runtime boots it lazily, on the first
  tile that asks (``static-runtime/pyodide/runtime.ts``).

The add-ons are inserted before ``</body>``: 3Dmol's classic ``<script>`` runs
while the document parses, before the deferred module script of the runtime,
so its global is in place when the runtime first imports ``3dmol``; the
Pyodide blocks are inert data until a tile boots the runtime.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from depictio.models.models.serverless import RuntimeAddon

ADDONS_DIR_ENV = "DEPICTIO_SERVERLESS_ADDONS_DIR"
REGISTRY_NAME = "addons.json"


class AddonError(RuntimeError):
    """An add-on a bundle needs is not available next to the template."""


def addons_dir() -> Path:
    """``dist-static/addons`` beside the template in use (or the env override)."""
    override = os.environ.get(ADDONS_DIR_ENV)
    if override:
        return Path(override)
    from depictio.serverless.producer_b import _template_path

    return _template_path().parent / "addons"


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
    return f'<script data-depictio-addon="{name}">{body}</script>'


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
    blob = json.dumps(meta, separators=(",", ":")).replace("</", "<\\/")
    blocks = [f'<script type="application/json" id="{PYODIDE_META_ID}">{blob}</script>']
    for f in assets.files:
        blocks.append(
            f'<script type="application/octet-stream" data-pya="{f.name}" '
            f'data-gz="{int(f.gzip)}">{f.embedded()}</script>'
        )
    return "".join(blocks)


def addons_html(names: list[str], packages: list[str] | None = None) -> str:
    """The add-ons' elements, in order: what both hosts of the runtime embed
    (the bundle before its ``</body>``, a report beside its runtime)."""
    return "".join(
        pyodide_html(list(packages or [])) if n == "pyodide" else addon_script(n) for n in names
    )


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
