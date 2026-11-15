"""Advanced visualisations drawn in the document itself, from their data.

Fourteen advanced-viz kinds (and three views of others) are not Plotly in the
live app: SVG, a canvas, WebGL, plain HTML. The server can only hand those
back as a PNG of its own renderer. This package draws them here instead, with
Python libraries, from the same data the React renderer reads, through the
same client and the same exported state (filters reach every fetch, exactly
as the renderer sends them):

* Plotly figures (interactive: hover, zoom) for the genome views, the
  ideogram, the chord, the alignment, the sequence and structure tracks, the
  domain lanes, the PAE matrix and the phylogeny summary;
* py3Dmol for a structure (rotate, zoom), with 3Dmol.js inlined once per
  document so the report stays self-contained;
* SVG or HTML for what is layout rather than plotting: a record card, a
  ranked table, an allele grid, a pedigree, a profile HMM logo.

Each renderer says whether it can run here (``available``, e.g. py3Dmol
installed); a tile whose renderer is missing, fails or finds nothing to draw
falls back on the server's snapshot, so the document never loses a tile to
this. ``use_native(False)`` turns the whole package off.
"""

from __future__ import annotations

import html as _html
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

import polars as pl

if TYPE_CHECKING:  # pragma: no cover
    from ..components import AdvancedVizComponent

HTML_MIME = "text/html"
PLAIN_MIME = "text/plain"

Output = Literal["interactive", "static"]

# On unless the environment says otherwise (``DEPICTIO_NOTEBOOK_NATIVE=0``): a
# deployment that wants the server's snapshots everywhere sets it once.
_STATE = {
    "enabled": os.environ.get("DEPICTIO_NOTEBOOK_NATIVE", "1").strip().lower()
    not in ("0", "false", "no", "off")
}


def use_native(enabled: bool = True) -> None:
    """Draw advanced visualisations here (default), or always ask for snapshots."""
    _STATE["enabled"] = bool(enabled)


def native_enabled() -> bool:
    return bool(_STATE["enabled"])


class NothingToDraw(Exception):
    """The tile's data holds nothing this renderer can draw (an empty frame)."""


@dataclass(frozen=True)
class NativeRenderer:
    kind: str
    output: Output
    how: str  # for the reader: what draws it here
    render: Callable[[Tile], NativeResult]
    available: Callable[[], bool] = lambda: True
    requires: str | None = None  # the package a missing renderer needs


@dataclass
class NativeResult:
    bundle: dict[str, Any]
    figure: Any = None


@dataclass
class Tile:
    """What a native renderer reads: the tile's binding, its config, its data."""

    component: AdvancedVizComponent
    _specs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def meta(self) -> dict[str, Any]:
        return self.component.meta

    @property
    def config(self) -> dict[str, Any]:
        cfg = self.meta.get("config")
        return cfg if isinstance(cfg, dict) else {}

    @property
    def title(self) -> str:
        return self.component.title

    @property
    def dc_id(self) -> str | None:
        return self.component.dc_id

    @property
    def wf_id(self) -> str | None:
        return str(self.meta.get("wf_id") or "") or None

    @property
    def filters(self) -> list[dict[str, Any]]:
        return self.component.filters

    def rows(
        self,
        columns: list[str | None],
        *,
        dc_id: str | None = None,
        wf_id: str | None = None,
        viz_kind: str | None = None,
        roles: dict[str, str] | None = None,
        limit_rows: int | None = None,
        extra_filters: list[dict[str, Any]] | None = None,
        full_load: bool = False,
    ) -> pl.DataFrame:
        """The columns a renderer reads, through ``/advanced_viz/data``.

        The body the React renderer sends (``fetchAdvancedVizData``): the
        state's filters as they are, so link resolution and the server's own
        sampling policy for the kind apply here too.
        """
        cols = list(dict.fromkeys(c for c in columns if c))
        body: dict[str, Any] = {
            "wf_id": wf_id or self.wf_id,
            "dc_id": dc_id or self.dc_id,
            "columns": cols,
            "filter_metadata": [*self.filters, *(extra_filters or [])],
            "viz_kind": viz_kind or self.component.kind or None,
        }
        if roles:
            body["roles"] = roles
        if limit_rows is not None:
            body["limit_rows"] = int(limit_rows)
        if full_load:
            body["full_load"] = True
        payload = self.component.client.post("/advanced_viz/data", body)
        data = payload.get("rows") or {}
        if not data:
            return pl.DataFrame({c: [] for c in cols})
        return pl.DataFrame(data, strict=False)

    def specs(self, dc_id: str | None = None) -> list[dict[str, Any]]:
        """The collection's columns and their descriptions (``/deltatables/specs``)."""
        key = str(dc_id or self.dc_id or "")
        if key not in self._specs:
            try:
                self._specs[key] = list(self.component.client.specs(key))
            except Exception:  # noqa: BLE001 - descriptions are a nicety
                self._specs[key] = []
        return self._specs[key]

    def newick(self, dc_id: str) -> str:
        client = self.component.client
        client._require_api()
        resp = client._http.get(f"/depictio/api/v1/advanced_viz/phylogeny/{dc_id}/newick")
        if resp.status_code >= 400:
            client._raise(resp)
        return resp.text

    def indexed_files(self, dc_id: str) -> list[dict[str, Any]]:
        """An indexed-file collection's objects (structures, PAE matrices), by sample."""
        manifest = self.component.client.get(f"/files/indexed/{dc_id}")
        return list(manifest.get("files") or [])

    def object_text(self, url: str) -> str:
        """An object's text, from the (presigned) URL a manifest gave."""
        import httpx

        client = self.component.client
        if url.startswith("/"):
            resp = client._http.get(url)
        else:
            resp = httpx.get(url, timeout=client.timeout, follow_redirects=True)
        if resp.status_code >= 400:
            raise RuntimeError(f"could not read {url.split('?')[0]}: HTTP {resp.status_code}")
        return resp.text

    @property
    def live_url(self) -> str | None:
        return self.component.live_url


def esc(value: Any) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


def head_html(tile: Tile, sub: str | None = None) -> str:
    """The tile's header row, as the app's tile anatomy draws it: title, then a quiet line."""
    note = sub or ""
    link = tile.live_url
    live = f'<a href="{esc(link)}">live dashboard</a>' if link else "live dashboard"
    note = (note + " · " if note else "") + f"Interactive in the {live}."
    return (
        '<div class="dpx-tile-head">'
        f'<div class="dpx-tile-title" style="font-weight:650">{esc(tile.title)}</div>'
        f'<div class="dpx-tile-sub" style="font-size:12px;color:#868e96">{note}</div>'
        "</div>"
    )


def html_result(tile: Tile, inner: str, *, sub: str | None = None) -> NativeResult:
    kind = esc(tile.component.kind)
    return NativeResult(
        bundle={
            HTML_MIME: (
                f'<div class="dpx-tile dpx-native" data-dpx-native="{kind}">'
                f"{head_html(tile, sub)}{inner}</div>"
            ),
            PLAIN_MIME: f"{tile.title} ({tile.component.kind})",
        }
    )


def figure_result(tile: Tile, fig: Any, *, sub: str | None = None) -> NativeResult:
    from ..components import figure_bundle

    bundle = figure_bundle(fig)
    kind = esc(tile.component.kind)
    bundle[HTML_MIME] = (
        f'<div class="dpx-tile dpx-native" data-dpx-native="{kind}">'
        f"{head_html(tile, sub)}{bundle[HTML_MIME]}</div>"
    )
    return NativeResult(bundle=bundle, figure=fig)


def require(df: pl.DataFrame, *columns: str | None) -> pl.DataFrame:
    """The frame, or ``NothingToDraw`` when it is empty or lacks a bound column."""
    missing = [c for c in columns if c and c not in df.columns]
    if missing:
        raise NothingToDraw(f"the data has no column {', '.join(map(repr, missing))}")
    if df.height == 0:
        raise NothingToDraw("no rows under the exported filters")
    return df


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

_RENDERERS: dict[str, NativeRenderer] = {}


def register(renderer: NativeRenderer) -> NativeRenderer:
    _RENDERERS[renderer.kind] = renderer
    return renderer


def _view(meta: dict[str, Any]) -> str | None:
    cfg = meta.get("config") if isinstance(meta.get("config"), dict) else {}
    return cfg.get("view")


def renderer_key(meta: dict[str, Any]) -> str | None:
    """Which native renderer draws this tile, honouring the view it opens on.

    Only what the live app does not draw with Plotly: a kind whose React
    renderer is Plotly keeps its real figure (the server builds or extracts
    it), and so does a view of a mixed kind that is Plotly.
    """
    _load()
    return _renderer_key(meta)


def _renderer_key(meta: dict[str, Any]) -> str | None:
    """``renderer_key`` once the renderers are registered."""
    kind = str(meta.get("viz_kind") or meta.get("kind") or meta.get("advanced_viz_kind") or "")
    cfg = meta.get("config") if isinstance(meta.get("config"), dict) else {}
    if kind == "phylogenetic":
        return "phylo_summary" if cfg.get("collapse_rank") else None
    if kind == "cnv_profile":
        return "cnv_profile" if _view(meta) == "locus" else None
    if kind == "sashimi":
        return "sashimi" if _view(meta) == "genomespy" else None
    if kind == "genome_view" and str(cfg.get("source") or "table") != "table":
        return None  # indexed files read by range: the snapshot is the ceiling
    return kind if kind in _RENDERERS else None


def renderer_for(meta: dict[str, Any]) -> NativeRenderer | None:
    _load()
    key = _renderer_key(meta)
    return _RENDERERS.get(key) if key else None


def registered() -> dict[str, NativeRenderer]:
    _load()
    return dict(_RENDERERS)


_LOADED = {"done": False}


def _load() -> None:
    if _LOADED["done"]:
        return
    _LOADED["done"] = True
    from . import genome, layout, pedigree, phylo, protein  # noqa: F401
