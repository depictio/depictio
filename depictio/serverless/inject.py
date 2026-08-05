"""Payload → HTML injection shared by the serverless producers and the catalog
preview.

Extracted from ``depictio/catalog/payload.py`` so both single-file bundle
builders (catalog preview and serverless producer B) share one JSON-safety and
token-injection implementation instead of drifting apart.
"""

from __future__ import annotations

import json
import math
from typing import Any


def json_safe(o: Any) -> Any:
    """Replace non-finite floats (NaN / ±Infinity) with ``None``.

    Plotly figures and computed stats can carry NaN/Inf; Python's ``json`` emits
    them as bare ``NaN``/``Infinity`` tokens, which are valid for ``json.loads``
    but make the browser's ``JSON.parse`` throw — blanking the embedded bundle.
    """
    if isinstance(o, dict):
        return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [json_safe(v) for v in o]
    # numpy arrays / scalars — Plotly UI-mode figures (px.* on a pandas frame)
    # keep numpy in their traces; json.dumps(default=str) would stringify an
    # ndarray into a useless "['a' 'b']" blob. Convert to plain Python first.
    if hasattr(o, "dtype") and hasattr(o, "tolist"):
        return json_safe(o.tolist())
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    return o


def inject(template: str, token: str, payload: Any) -> str:
    """Embed a computed payload into a prebuilt single-file HTML template.

    Every occurrence of ``token`` is replaced by the JSON-serialized payload.
    The blob is passed through :func:`json_safe` (so ``JSON.parse`` never sees
    a bare ``NaN``/``Infinity`` token) and ``</`` is escaped to ``<\\/`` so the
    payload can never close the ``<script>`` tag it is embedded in.
    """
    blob = json.dumps(json_safe(payload), default=str).replace("</", "<\\/")
    return template.replace(token, blob)
