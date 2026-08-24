"""GitHub links back to depictio's own source.

Several surfaces want to point at the file behind something they are showing:
the ingestion report links a data collection's recipe, the catalog picker links
the module YAML that declares an output. Both are the same operation, "make this
repo file clickable", so it lives once here.

Links are anchored on the default branch: nothing in the codebase pins source
links to a tag, and a released tag would go stale against a dev checkout.
"""

from __future__ import annotations

from pathlib import Path

REPO_BLOB_BASE = "https://github.com/depictio/depictio/blob/main/"

# depictio/api/v1/source_links.py -> the repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


def github_blob_url(path: str | Path | None) -> str | None:
    """Blob URL for a file inside the depictio repo, or None.

    Best-effort by design: an installed (non-checkout) deployment, or a path that
    resolves outside the repo, yields None and the caller simply shows no link.
    """
    if not path:
        return None
    try:
        return REPO_BLOB_BASE + str(Path(path).resolve().relative_to(_REPO_ROOT))
    except Exception:
        return None
