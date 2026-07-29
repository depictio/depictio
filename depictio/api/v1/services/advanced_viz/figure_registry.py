"""Registry of Python builders that turn tidy data into an advanced-viz Plotly spec.

Each advanced-viz kind has a TypeScript renderer that builds its traces in the
browser. That is the right design for the live dashboard — threshold sliders and
top-N pickers re-render locally with no round-trip — but it means no server-side
figure exists to export as JSON.

This registry is the server-side counterpart, filled in one kind at a time. A kind
with no builder is not an error: ``capabilities.formats_for`` drops JSON from its
supported formats and the export route answers 501 pointing at ``format=html``,
which renders through the real TypeScript renderer offline. Adding a module under
``kinds/`` is the only change needed to make a kind JSON-exportable.

Builders are pure functions of ``(rows, config, controls, theme)``:

* ``rows`` — column-oriented data from ``services/advanced_viz/data.load_tidy_columns``
* ``config`` — the persisted component config (the same dict the TS renderer reads)
* ``controls`` — intra-viz control state. The TS renderers seed these from ``config``
  and then keep live tweaks in browser state; a server-side build necessarily renders
  at the persisted/default state unless a caller pins them explicitly.
* ``theme`` — ``"light"`` or ``"dark"``

Purity is what makes the golden-JSON parity tests possible.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.services.advanced_viz.theme import apply_theme


class FigureBuilder(Protocol):
    """Signature every registered builder implements."""

    def __call__(
        self,
        *,
        rows: dict[str, list[Any]],
        config: dict[str, Any],
        controls: dict[str, Any],
        theme: str,
    ) -> dict[str, Any]:
        """Return ``{"data": [...], "layout": {...}}``."""
        ...


class ColumnResolver(Protocol):
    """Returns the DC columns a kind needs, given its config.

    May include ``None`` for optional bindings the config leaves unset — listing
    them unconditionally keeps the resolvers readable. :func:`required_columns`
    drops them.
    """

    def __call__(self, config: dict[str, Any]) -> list[str | None]: ...


_BUILDERS: dict[str, FigureBuilder] = {}
_COLUMNS: dict[str, ColumnResolver] = {}
_BUILDERS_LOADED = False


def register(kind: str, *, columns: ColumnResolver) -> Callable[[FigureBuilder], FigureBuilder]:
    """Register a builder for ``kind``.

    Args:
        kind: Canonical ``viz_kind`` (aliases are resolved before lookup).
        columns: Callable mapping the component config to the DC columns to project.
    """

    def decorator(fn: FigureBuilder) -> FigureBuilder:
        if kind in _BUILDERS:
            raise RuntimeError(f"advanced_viz builder for {kind!r} is already registered")
        _BUILDERS[kind] = fn
        _COLUMNS[kind] = columns
        return fn

    return decorator


def _ensure_loaded() -> None:
    """Import the builder modules so their ``@register`` decorators run.

    Import failures are logged and swallowed: one broken builder should degrade
    that kind to ``format=html`` rather than take down the export API.
    """
    global _BUILDERS_LOADED
    if _BUILDERS_LOADED:
        return
    try:
        from depictio.api.v1.services.advanced_viz import kinds  # noqa: F401
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("advanced_viz: builder package failed to import: %s", exc, exc_info=True)
    _BUILDERS_LOADED = True


def supported_kinds() -> frozenset[str]:
    """Kinds with a registered Python builder."""
    _ensure_loaded()
    return frozenset(_BUILDERS)


def required_columns(kind: str, config: dict[str, Any]) -> list[str]:
    """Columns this kind needs projected from its data collection."""
    _ensure_loaded()
    resolver = _COLUMNS.get(kind)
    if resolver is None:
        raise HTTPException(status_code=501, detail=f"No Python builder for {kind!r}.")
    # Drop unset optional bindings and de-duplicate while preserving order.
    return list(dict.fromkeys(c for c in resolver(config) if c))


def build(
    kind: str,
    *,
    config: dict[str, Any],
    rows: dict[str, list[Any]],
    theme: str = "light",
    controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a themed ``{data, layout}`` spec for ``kind``.

    Raises:
        HTTPException: 501 if no builder is registered, 500 if the builder fails.
    """
    _ensure_loaded()
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise HTTPException(status_code=501, detail=f"No Python builder for {kind!r}.")

    try:
        spec = builder(rows=rows, config=config, controls=controls or {}, theme=theme)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("advanced_viz: %s builder failed: %s", kind, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{kind} figure build failed: {exc}")

    return apply_theme(spec, theme)
