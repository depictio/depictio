"""Where the built static runtime lives, for every serverless module that reads it.

``cd depictio/viewer && pnpm run build:static`` writes ``dist-static/``: the
single-file template (``static.html``) every bundle is injected into, its
add-ons (``addons/``) and the gene tables a genome tile may carry
(``assets/genomes/``). Official images do not carry it (it is gitignored and
needs a Node build), so a container that mounts it elsewhere points
``DEPICTIO_SERVERLESS_TEMPLATE_PATH`` at the template, and everything beside it
moves with it. Resolved per call, not at import time, so the variable can be
set after the module loads.

Standard library only: producer B runs on the CLI-only install.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The in-tree build output.
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "viewer" / "dist-static" / "static.html"
TEMPLATE_PATH_ENV = "DEPICTIO_SERVERLESS_TEMPLATE_PATH"


def template_path() -> Path:
    """The static-runtime template this process injects bundles into."""
    override = os.environ.get(TEMPLATE_PATH_ENV)
    return Path(override) if override else TEMPLATE_PATH


def dist_static_dir() -> Path:
    """The ``dist-static`` directory in use: the template's own directory."""
    return template_path().parent
