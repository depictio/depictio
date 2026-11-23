"""Where the built static runtime lives, for every serverless module that reads it.

``cd depictio/viewer && pnpm run build:static`` writes ``dist-static/``: the
runtime (``combined-runtime.js`` and its stylesheet ``combined-runtime.css``),
its add-ons (``addons/``) and the gene tables a genome tile may carry
(``assets/genomes/``). The runtime is shipped once, for both of its hosts: a
report embeds it as is, and a single-file bundle is composed from it
(``serverless.bundle_html``). Official images do not carry it (it is gitignored
and needs a Node build), so a container that mounts it elsewhere points
``DEPICTIO_SERVERLESS_TEMPLATE_PATH`` at the script, and everything beside it
moves with it. The variable also accepts a legacy ``.html`` template carrying
the ``__BUNDLE_MANIFEST__`` token. Resolved per call, not at import time, so
the variable can be set after the module loads.

Standard library only: producer B runs on the CLI-only install.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The in-tree build output.
RUNTIME_PATH = (
    Path(__file__).resolve().parent.parent / "viewer" / "dist-static" / "combined-runtime.js"
)
TEMPLATE_PATH_ENV = "DEPICTIO_SERVERLESS_TEMPLATE_PATH"


def runtime_path() -> Path:
    """The runtime script this process composes bundles from.

    A ``.js`` file (its stylesheet is the ``.css`` beside it), or a legacy
    ``.html`` template when the override points at one.
    """
    override = os.environ.get(TEMPLATE_PATH_ENV)
    return Path(override) if override else RUNTIME_PATH


def is_legacy_template(path: Path) -> bool:
    """Whether ``path`` is a prebuilt ``.html`` template (token injection)."""
    return path.suffix.lower() == ".html"


def runtime_css_path(js: Path) -> Path:
    """The stylesheet that goes with a runtime script: the ``.css`` beside it."""
    return js.with_suffix(".css")


def runtime_bytes() -> int:
    """The size of the runtime in use (script + stylesheet, or the template).

    Raises ``OSError`` when it is not there.
    """
    path = runtime_path()
    if is_legacy_template(path):
        return path.stat().st_size
    return path.stat().st_size + runtime_css_path(path).stat().st_size


def dist_static_dir() -> Path:
    """The ``dist-static`` directory in use: the runtime's own directory."""
    return runtime_path().parent
