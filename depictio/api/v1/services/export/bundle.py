"""Inject a computed payload into a prebuilt single-file offline bundle.

Shared by the catalog preview (``depictio/catalog/payload.py``) and the component
embed (``services/export/embed.py``). Both work the same way: a Vite
``viteSingleFile`` build produces one HTML file with all JS/CSS inlined and a
sentinel string where the payload goes; we substitute the sentinel with JSON.

The two subtleties worth keeping in one place are the JSON sanitisation
(``json_safe``) and the ``</`` escaping — both are silent-blank-page bugs when
they go wrong, and neither is obvious from the call site.
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Any


class OfflineBundleError(RuntimeError):
    """The prebuilt bundle is missing or unusable."""


def json_safe(o: Any) -> Any:
    """Coerce a payload into something ``JSON.parse`` will accept.

    Two failure modes this exists to prevent:

    * Non-finite floats. Plotly figures and computed stats carry NaN/Inf; Python's
      ``json`` emits bare ``NaN``/``Infinity`` tokens, which ``json.loads`` accepts
      but the browser's ``JSON.parse`` rejects — blanking the whole bundle.
    * numpy arrays. Plotly UI-mode figures (``px.*`` over a pandas frame) keep numpy
      in their traces, and ``json.dumps(default=str)`` would stringify an ndarray
      into a useless ``"['a' 'b']"`` blob.
    """
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    if hasattr(o, "dtype") and hasattr(o, "tolist"):
        return json_safe(o.tolist())
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def encode_payload(payload: dict[str, Any]) -> str:
    """Serialise a payload for embedding inside an HTML ``<script>`` element.

    The ``</`` escape is what makes it safe to sit inside a script element: without
    it, a payload containing the literal ``</script>`` would terminate the element
    early. ``<\\/`` is not special to JSON but the browser's tokenizer stops looking
    for a closing tag, so both parsers stay happy.
    """
    return json.dumps(json_safe(payload), default=str).replace("</", "<\\/")


def svg_data_uris(logos_dir: Path, mapping: dict[str, str]) -> dict[str, str]:
    """Build ``{server_path: data_uri}`` for SVGs that must survive going offline.

    ``mapping`` is ``{server_path: filename}``. Missing files are skipped rather
    than raising: a missing logo degrades to a broken image, not a failed export.
    """
    result: dict[str, str] = {}
    for server_path, filename in mapping.items():
        path = logos_dir / filename
        if path.exists():
            b64 = base64.b64encode(path.read_bytes()).decode()
            result[server_path] = f"data:image/svg+xml;base64,{b64}"
    return result


def inject(
    template_path: Path,
    sentinel: str,
    payload: dict[str, Any],
    *,
    asset_replacements: dict[str, str] | None = None,
    build_hint: str = "",
) -> str:
    """Substitute ``payload`` into the prebuilt bundle at ``template_path``.

    Args:
        template_path: The built single-file HTML.
        sentinel: Placeholder string the build emitted for the payload.
        payload: Data to embed.
        asset_replacements: ``{server_relative_path: data_uri}`` applied after
            injection so server-relative asset URLs resolve offline.
        build_hint: Command to suggest when the bundle is missing.

    Raises:
        OfflineBundleError: The bundle is not built, or the sentinel is absent
            (which means the template and this code have diverged).
    """
    if not template_path.exists():
        raise OfflineBundleError(
            f"offline bundle not built: {template_path} is missing"
            + (f" — run `{build_hint}`" if build_hint else "")
        )

    html = template_path.read_text()
    if sentinel not in html:
        raise OfflineBundleError(
            f"offline bundle at {template_path} does not contain the sentinel "
            f"{sentinel!r} — the bundle and the payload builder have diverged."
        )

    html = html.replace(sentinel, encode_payload(payload))
    for server_path, data_uri in (asset_replacements or {}).items():
        html = html.replace(server_path, data_uri)
    return html
