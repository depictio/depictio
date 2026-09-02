"""Dashboard components as notebook objects.

A :class:`DepictioComponent` wraps one component of a dashboard, bound to an
analysis state (the filters, groups and funnel order the dashboard applied).
It fetches lazily, caches, and displays itself in Jupyter, Quarto and marimo:

* ``.figure`` — a ``plotly.graph_objects.Figure`` for figures, maps, MultiQC
  plots and every advanced visualisation (the server extracts the Plotly
  figure from its own React renderer for the kinds it does not draw in Python);
* ``.data`` — a ``polars.DataFrame`` (tables, filters, image rows, advanced-viz
  payloads) or a dict (cards);
* ``.html`` — the real React tile, self-contained, as an HTML document.

What a component shows by default is the closest thing to what the dashboard
shows: the figure where there is one, the DataFrame for a table, a small card
for a card, markdown for a text tile, an image grid, a JBrowse iframe.
"""

from __future__ import annotations

import base64
import html as _html
import json
import time
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:  # pragma: no cover
    from .client import DepictioClient

HTML_MIME = "text/html"
MARKDOWN_MIME = "text/markdown"
PLAIN_MIME = "text/plain"
PLOTLY_MIME = "application/vnd.plotly.v1+json"

# Advanced-viz kinds the server renders as Plotly itself; everything else is
# extracted from the React renderer by the ``component_figure`` endpoint.
SERVER_PLOTLY_KINDS = frozenset({"complex_heatmap", "upset_plot", "sankey"})


def _figure_from_dict(fig_dict: dict[str, Any]):
    import plotly.graph_objects as go
    import plotly.io as pio

    try:
        return pio.from_json(json.dumps(fig_dict))
    except Exception:
        return go.Figure(fig_dict)


def figure_bundle(fig) -> dict[str, Any]:
    """A mimebundle Jupyter and Quarto both render.

    Plotly's own ``_repr_mimebundle_`` is empty unless a mimetype renderer is
    active, which is not the case in every kernel; building the bundle here
    keeps the figure interactive wherever ``application/vnd.plotly.v1+json``
    is understood and falls back to inline HTML elsewhere.
    """
    return {
        PLOTLY_MIME: json.loads(fig.to_json()),
        HTML_MIME: fig.to_html(full_html=False, include_plotlyjs="cdn"),
        PLAIN_MIME: "Plotly figure",
    }


def filters_to_metadata(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``filter_metadata`` shape (``clean_filter_payload``) from state filters."""
    out = []
    for f in filters or []:
        meta = f.get("metadata") or {}
        column = f.get("column_name") or meta.get("column_name")
        if not column or f.get("value") in (None, [], ""):
            continue
        entry = {
            "interactive_component_type": f.get("interactive_component_type")
            or meta.get("interactive_component_type"),
            "column_name": column,
            "value": f.get("value"),
        }
        fexpr = f.get("filter_expr") or meta.get("filter_expr")
        if fexpr:
            entry["filter_expr"] = fexpr
        out.append(entry)
    return out


class DepictioComponent:
    """One dashboard component, bound to a client and an analysis state."""

    default_display: str = "html"  # figure | data | html | markdown

    def __init__(
        self,
        client: DepictioClient,
        dashboard_id: str,
        meta: dict[str, Any],
        state: dict[str, Any],
        theme: str = "light",
    ) -> None:
        self.client = client
        self.dashboard_id = dashboard_id
        self.meta = meta
        self.state = state
        self.theme = theme
        self._figure = None
        self._data: Any = None
        self._html: str | None = None

    # ------------------------------------------------------------ identity
    @property
    def index(self) -> str:
        return str(self.meta.get("index") or "")

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.index)

    @property
    def component_type(self) -> str:
        return str(self.meta.get("component_type") or "")

    @property
    def dc_id(self) -> str | None:
        return str(self.meta.get("dc_id") or "") or None

    @property
    def filters(self) -> list[dict[str, Any]]:
        return list(self.state.get("filters") or [])

    def __repr__(self) -> str:
        return f"<DepictioComponent {self.component_type} {self.title!r} ({self.index})>"

    # ------------------------------------------------------------- fetching
    def _fetch_figure(self):
        raise AttributeError(f"a {self.component_type} component has no figure")

    def _fetch_data(self) -> Any:
        raise AttributeError(f"a {self.component_type} component has no data payload")

    def _fetch_html(self) -> str:
        resp = self.client.post(
            f"/dashboards/embed/{self.dashboard_id}/{self.index}",
            {"state": self.state, "theme": self.theme},
            raw=True,
        )
        return resp.text

    @property
    def figure(self):
        if self._figure is None:
            self._figure = self._fetch_figure()
        return self._figure

    @property
    def data(self) -> Any:
        if self._data is None:
            self._data = self._fetch_data()
        return self._data

    @property
    def html(self) -> str:
        if self._html is None:
            self._html = self._fetch_html()
        return self._html

    def refresh(self) -> DepictioComponent:
        self._figure, self._data, self._html = None, None, None
        return self

    # -------------------------------------------------------------- display
    def _iframe(self, doc: str, height: int = 480) -> str:
        return (
            f'<iframe srcdoc="{_html.escape(doc, quote=True)}" '
            f'style="width:100%;height:{height}px;border:0" '
            'sandbox="allow-scripts allow-same-origin" title="Depictio component"></iframe>'
        )

    def _display_html(self) -> str:
        """HTML for the default display; subclasses override for lighter renderings."""
        return self._iframe(self.html)

    def _display_markdown(self) -> str | None:
        return None

    def _repr_mimebundle_(self, include=None, exclude=None, **kwargs):
        """Jupyter and Quarto."""
        mode = self.default_display
        if mode == "figure":
            return figure_bundle(self.figure)
        if mode == "data":
            df = self.data
            if isinstance(df, pl.DataFrame):
                return {HTML_MIME: df._repr_html_(), PLAIN_MIME: repr(df)}
            return {PLAIN_MIME: repr(df)}
        if mode == "markdown":
            return {MARKDOWN_MIME: self._display_markdown() or "", PLAIN_MIME: self.title}
        return {HTML_MIME: self._display_html(), PLAIN_MIME: repr(self)}

    def _mime_(self) -> tuple[str, str]:
        """marimo."""
        mode = self.default_display
        if mode == "figure":
            try:
                import marimo as mo

                return mo.as_html(self.figure)._mime_()
            except Exception:
                return HTML_MIME, self.figure.to_html(full_html=False, include_plotlyjs="cdn")
        if mode == "data":
            df = self.data
            if isinstance(df, pl.DataFrame):
                return HTML_MIME, df._repr_html_()
            return PLAIN_MIME, repr(df)
        if mode == "markdown":
            try:
                import marimo as mo

                return mo.md(self._display_markdown() or "")._mime_()
            except Exception:
                return PLAIN_MIME, self._display_markdown() or ""
        return HTML_MIME, self._display_html()

    def _repr_html_(self) -> str | None:
        mode = self.default_display
        if mode == "figure":
            return self.figure.to_html(full_html=False, include_plotlyjs="cdn")
        if mode == "data" and isinstance(self.data, pl.DataFrame):
            return self.data._repr_html_()
        if mode == "markdown":
            return None
        return self._display_html()

    def show(self) -> Any:
        """Display now (``IPython.display.display`` when available)."""
        try:
            from IPython.display import display

            display(self)
        except Exception:
            print(repr(self))
        return self


# ---------------------------------------------------------------------------
# Figures the server already renders as Plotly
# ---------------------------------------------------------------------------


class FigureComponent(DepictioComponent):
    default_display = "figure"

    def _fetch_figure(self):
        payload = self.client.post(
            f"/dashboards/render_figure/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "theme": self.theme, "full_load": False},
        )
        return _figure_from_dict(payload["figure"])


class MapComponent(FigureComponent):
    def _fetch_figure(self):
        payload = self.client.post(
            f"/dashboards/render_map/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "theme": self.theme},
        )
        return _figure_from_dict(payload["figure"])

    def _fetch_data(self) -> pl.DataFrame:
        payload = self.client.post(
            f"/dashboards/map_data/{self.dashboard_id}/{self.index}",
            {"filters": self.filters},
        )
        return pl.DataFrame(payload.get("rows") or {})


class MultiQCComponent(FigureComponent):
    """A MultiQC plot; the server may answer 202 while its cache warms."""

    def _fetch_figure(self):
        deadline = time.monotonic() + 300
        while True:
            resp = self.client.post(
                f"/dashboards/render_multiqc/{self.dashboard_id}/{self.index}",
                {"filters": self.filters, "theme": self.theme},
                raw=True,
            )
            if resp.status_code == 202:
                if time.monotonic() > deadline:
                    raise TimeoutError("MultiQC figure did not become ready in time")
                time.sleep(2)
                continue
            return _figure_from_dict(resp.json()["figure"])


class MultiQCGeneralStatsComponent(DepictioComponent):
    default_display = "data"

    def _payload(self) -> dict[str, Any]:
        return self.client.post(
            f"/dashboards/render_multiqc_general_stats/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "theme": self.theme},
        )

    def _fetch_data(self) -> pl.DataFrame:
        payload = self._payload()
        modes = payload.get("modes") or {}
        mode = modes.get("all") or modes.get("mean") or next(iter(modes.values()), {})
        return pl.DataFrame(mode.get("table_data") or [])

    def _fetch_figure(self):
        payload = self._payload()
        modes = payload.get("modes") or {}
        mode = modes.get("all") or modes.get("mean") or next(iter(modes.values()), {})
        return _figure_from_dict(mode["violin_figure"])


# ---------------------------------------------------------------------------
# Advanced visualisations
# ---------------------------------------------------------------------------


class AdvancedVizComponent(DepictioComponent):
    default_display = "figure"

    @property
    def kind(self) -> str:
        return str(
            self.meta.get("viz_kind")
            or self.meta.get("kind")
            or self.meta.get("advanced_viz_kind")
            or ""
        )

    def _fetch_figure(self):
        result = self.client.poll(
            f"/dashboards/component_figure/{self.dashboard_id}/{self.index}",
            {"state": self.state, "theme": self.theme},
            "/dashboards/component_figure/jobs/{job_id}",
        )
        if result.get("status") == "unsupported" or not result.get("figure"):
            raise RuntimeError(
                f"no figure for {self.title!r}: {result.get('reason') or 'unsupported'}"
            )
        return _figure_from_dict(result["figure"])

    def _fetch_data(self) -> pl.DataFrame:
        payload = self.client.post(
            "/advanced_viz/data",
            {
                "dc_id": self.dc_id,
                "filter_metadata": filters_to_metadata(self.filters),
                "viz_kind": self.kind or None,
            },
        )
        rows = payload.get("rows") or {}
        return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# Data-shaped components
# ---------------------------------------------------------------------------


class TableComponent(DepictioComponent):
    default_display = "data"

    def _fetch_data(self) -> pl.DataFrame:
        return self.page(all_rows=True)

    def page(
        self,
        start: int = 0,
        limit: int = 500,
        *,
        sort_by: str | None = None,
        sort_dir: str = "asc",
        all_rows: bool = False,
    ) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        offset = start
        while True:
            payload = self.client.post(
                f"/dashboards/render_table/{self.dashboard_id}/{self.index}",
                {
                    "filters": self.filters,
                    "start": offset,
                    "limit": min(limit, 500),
                    "sort_by": sort_by,
                    "sort_dir": sort_dir,
                },
            )
            rows = payload.get("rows") or []
            frames.append(pl.DataFrame(rows))
            total = int(payload.get("total") or 0)
            offset += len(rows)
            if not all_rows or not rows or offset >= total:
                break
        return (
            pl.concat([f for f in frames if f.width], how="vertical_relaxed")
            if any(f.width for f in frames)
            else pl.DataFrame()
        )


class CardComponent(DepictioComponent):
    default_display = "html"

    def _fetch_data(self) -> dict[str, Any]:
        payload = self.client.post(
            f"/dashboards/bulk_compute_cards/{self.dashboard_id}",
            {"filters": self.filters, "component_ids": [self.index]},
        )
        return {
            "value": (payload.get("values") or {}).get(self.index),
            "secondary": (payload.get("secondary_values") or {}).get(self.index),
            "aggregations": (payload.get("aggregations") or {}).get(self.index),
            "filter_applied": payload.get("filter_applied"),
        }

    @property
    def value(self) -> Any:
        return self.data.get("value")

    @staticmethod
    def _fmt(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:,.4g}" if abs(value) < 1e6 else f"{value:,.0f}"
        return "–" if value is None else _html.escape(str(value))

    def _display_html(self) -> str:
        agg = _html.escape(str(self.meta.get("aggregation") or ""))
        column = _html.escape(str(self.meta.get("column_name") or ""))
        return (
            '<div style="display:inline-block;min-width:180px;padding:12px 16px;border:1px solid '
            '#dee2e6;border-radius:8px;font-family:system-ui,sans-serif">'
            f'<div style="font-size:12px;color:#868e96">{_html.escape(self.title)}</div>'
            f'<div style="font-size:28px;font-weight:600;line-height:1.2">{self._fmt(self.value)}</div>'
            f'<div style="font-size:11px;color:#adb5bd">{agg} · {column}</div>'
            f"{self._secondary_html()}</div>"
        )

    def _bar(self, label: str, fraction: float, note: str = "") -> str:
        pct = max(0.0, min(1.0, fraction)) * 100
        return (
            '<div style="margin:4px 0 0;font-size:11px;color:#495057">'
            f'<div style="display:flex;justify-content:space-between">'
            f"<span>{_html.escape(label)}</span><span>{_html.escape(note)}</span></div>"
            '<div style="background:#f1f3f5;border-radius:3px;height:6px;margin-top:2px">'
            f'<div style="background:#4c6ef5;border-radius:3px;height:6px;width:{pct:.1f}%"></div>'
            "</div></div>"
        )

    def _secondary_html(self) -> str:
        """The card's secondary visualization, from the same numbers the React
        renderer draws (``bulk_compute_cards``' ``secondary_values``), not a
        reconstruction: a top-N breakdown, a box plot's five-number summary, a
        histogram, a pass/warn/fail count, a trend sparkline... The exact
        chrome differs from the dashboard's chart, but every number in it is
        the one Depictio computed, keyed by ``secondary_layout``.
        """
        layout = str(self.meta.get("secondary_layout") or "")
        sec = self.data.get("secondary") or {}
        if layout in ("top_n", "concentration", "composition", "donut"):
            breakdown = sec.get("__breakdown__")
            if not breakdown:
                return ""
            rows = "".join(
                self._bar(
                    item["name"], item["percent"], f"{item['count']:,} ({item['percent']:.0%})"
                )
                for item in breakdown.get("top") or []
            )
            return rows
        if layout == "box_plot":
            s = sec.get("box_plot_stats")
            if not s:
                return ""
            tail = f" · {s['outlier_count']:,} outlier(s)" if s.get("outlier_count") else ""
            return (
                '<div style="margin-top:4px;font-size:11px;color:#495057">'
                f"min {self._fmt(s['min'])} · q1 {self._fmt(s['q1'])} · "
                f"median {self._fmt(s['median'])} · q3 {self._fmt(s['q3'])} · "
                f"max {self._fmt(s['max'])}{tail}</div>"
            )
        if layout == "histogram":
            h = sec.get("__histogram__")
            bins = (h or {}).get("bins") or []
            if not bins:
                return ""
            peak = max(bins) or 1
            bars = "".join(
                f'<div style="flex:1;background:#4c6ef5;height:{c / peak * 24:.0f}px;'
                f'align-self:flex-end;margin:0 1px" title="{c:,}"></div>'
                for c in bins
            )
            return (
                '<div style="margin-top:6px;display:flex;align-items:flex-end;height:24px">'
                f"{bars}</div>"
                f'<div style="font-size:10px;color:#adb5bd">'
                f"{self._fmt(h['min'])} – {self._fmt(h['max'])}</div>"
            )
        if layout == "trend":
            t = sec.get("__trend__")
            points = (t or {}).get("points") or []
            values = [p["value"] for p in points]
            if len(values) < 2:
                return ""
            lo, hi = min(values), max(values)
            span = (hi - lo) or 1
            width, height = 120, 28
            step = width / (len(values) - 1)
            poly = " ".join(
                f"{i * step:.1f},{height - (v - lo) / span * height:.1f}"
                for i, v in enumerate(values)
            )
            change = t.get("change")
            note = f"{change:+.0%}" if change is not None else ""
            return (
                f'<div style="margin-top:6px"><svg width="{width}" height="{height}">'
                f'<polyline points="{poly}" fill="none" stroke="#4c6ef5" stroke-width="1.5"/></svg>'
                f'<div style="font-size:10px;color:#adb5bd">{_html.escape(note)}</div></div>'
            )
        if layout == "threshold":
            th = sec.get("__threshold__")
            if not th:
                return ""
            warn = (
                f' · <span style="color:#f08c00">{th["warning"]:,} warn</span>'
                if th.get("warning")
                else ""
            )
            return (
                '<div style="margin-top:4px;font-size:11px">'
                f'<span style="color:#2f9e44">{th["passing"]:,} pass</span>{warn} · '
                f'<span style="color:#e03131">{th["failing"]:,} fail</span></div>'
            )
        if layout == "completeness":
            c = sec.get("__completeness__")
            if not c:
                return ""
            return self._bar("Filled", c["fill_rate"], f"{c['filled']:,}/{c['total']:,}")
        if layout == "uniqueness":
            u = sec.get("__uniqueness__")
            if not u:
                return ""
            return self._bar("Distinct", u["unique_rate"], f"{u['distinct']:,}/{u['measured']:,}")
        if layout == "attrition":
            a = sec.get("__attrition__")
            if not a:
                return ""
            return "".join(
                self._bar(s["name"], s["share"], f"{s['value']:,.0f}")
                for s in a.get("stages") or []
            )
        if layout in ("coverage", "gauge"):
            cap = self.meta.get("coverage_max")
            value = self.value
            if not isinstance(cap, (int, float)) or not cap or not isinstance(value, (int, float)):
                return ""
            return self._bar(layout.capitalize(), value / cap, f"/{cap:,}")
        if layout in ("vertical", "compact", "grid"):
            names = [n for n in self.meta.get("aggregations") or [] if n in sec]
            if not names:
                return ""
            rows = " · ".join(f"{_html.escape(n)} {self._fmt(sec[n])}" for n in names)
            return f'<div style="margin-top:4px;font-size:11px;color:#495057">{rows}</div>'
        return ""


class InteractiveComponent(DepictioComponent):
    default_display = "html"

    @property
    def column(self) -> str:
        return str(self.meta.get("column_name") or "")

    @property
    def control(self) -> str:
        return str(self.meta.get("interactive_component_type") or "")

    def _fetch_data(self) -> pl.DataFrame:
        if self.control in ("Select", "MultiSelect", "SegmentedControl"):
            values = self.client.unique_values(self.dc_id or "", self.column)
            return pl.DataFrame({self.column: values})
        specs = self.client.specs(self.dc_id or "")
        for spec in specs:
            if spec.get("name") == self.column:
                s = spec.get("specs") or {}
                return pl.DataFrame({"stat": list(s.keys()), "value": [str(v) for v in s.values()]})
        return pl.DataFrame({"stat": [], "value": []})

    def _display_html(self) -> str:
        df = self.data
        preview = (
            ", ".join(str(v) for v in df[df.columns[0]].head(12).to_list()) if df.width else ""
        )
        return (
            '<div style="font-family:system-ui,sans-serif;font-size:13px">'
            f"<b>{_html.escape(self.title)}</b> · {_html.escape(self.control)} on "
            f"<code>{_html.escape(self.column)}</code><br>"
            f'<span style="color:#868e96">{_html.escape(preview)}</span></div>'
        )

    def to_marimo(self):
        """A marimo UI element mirroring this control (``mo.ui.multiselect`` / ``range_slider``)."""
        import marimo as mo

        if self.control in ("Select", "MultiSelect", "SegmentedControl"):
            options = self.data[self.column].to_list()
            if self.control == "Select":
                return mo.ui.dropdown(options=options, label=self.title)
            return mo.ui.multiselect(options=options, label=self.title)
        stats = dict(zip(self.data["stat"].to_list(), self.data["value"].to_list()))
        lo, hi = float(stats.get("min", 0)), float(stats.get("max", 1))
        return mo.ui.range_slider(start=lo, stop=hi, label=self.title)


class TextComponent(DepictioComponent):
    default_display = "markdown"

    def _display_markdown(self) -> str:
        title = str(self.meta.get("title") or "").strip()
        body = str(self.meta.get("body") or "").strip()
        order = self.meta.get("order")
        try:
            level = max(1, min(6, int(order))) if order is not None else 3
        except (TypeError, ValueError):
            level = 3
        parts = [f"{'#' * level} {title}"] if title else []
        if body:
            parts.append(body)
        return "\n\n".join(parts)

    @property
    def markdown(self) -> str:
        return self._display_markdown()


class ImageComponent(DepictioComponent):
    default_display = "html"
    max_images = 50

    def _fetch_data(self) -> pl.DataFrame:
        payload = self.client.post(
            f"/dashboards/render_image_paths/{self.dashboard_id}/{self.index}",
            {"filters": self.filters, "max": self.max_images},
        )
        self._paths = list(payload.get("paths") or [])
        self._base = str((self.meta.get("dc_config") or {}).get("s3_base_folder") or "")
        return pl.DataFrame(payload.get("rows") or [])

    def images(self) -> list[bytes]:
        self.data  # populates paths
        out = []
        for rel in self._paths[: self.max_images]:
            s3_path = f"{self._base}/{rel}" if self._base and not rel.startswith("s3://") else rel
            out.append(self.client.get_bytes("/files/serve/image", s3_path=s3_path))
        return out

    def _display_html(self) -> str:
        tags = []
        for blob in self.images():
            b64 = base64.b64encode(blob).decode()
            tags.append(
                f'<img src="data:image/*;base64,{b64}" style="max-width:220px;margin:4px;'
                'border-radius:4px">'
            )
        return f'<div style="display:flex;flex-wrap:wrap">{"".join(tags)}</div>'


class JBrowseComponent(DepictioComponent):
    default_display = "html"

    def _fetch_data(self) -> dict[str, Any]:
        return self.client.post(
            f"/dashboards/render_jbrowse/{self.dashboard_id}/{self.index}",
            {"filters": self.filters},
        )

    @property
    def iframe_url(self) -> str:
        return str(self.data.get("iframe_url") or "")

    def _display_html(self) -> str:
        return (
            f'<iframe src="{_html.escape(self.iframe_url, quote=True)}" '
            'style="width:100%;height:520px;border:0" title="JBrowse"></iframe>'
        )


def component_for(
    client: DepictioClient,
    dashboard_id: str,
    meta: dict[str, Any],
    state: dict[str, Any],
    theme: str = "light",
) -> DepictioComponent:
    ctype = str(meta.get("component_type") or "")
    cls: type[DepictioComponent]
    if ctype == "figure":
        cls = FigureComponent
    elif ctype == "map":
        cls = MapComponent
    elif ctype == "multiqc":
        cls = (
            MultiQCGeneralStatsComponent
            if str(meta.get("selected_plot") or "").endswith("general_stats")
            or meta.get("selected_module") == "general_stats"
            else MultiQCComponent
        )
    elif ctype == "advanced_viz":
        cls = AdvancedVizComponent
    elif ctype == "table":
        cls = TableComponent
    elif ctype == "card":
        cls = CardComponent
    elif ctype == "interactive":
        cls = InteractiveComponent
    elif ctype == "text":
        cls = TextComponent
    elif ctype == "image":
        cls = ImageComponent
    elif ctype == "jbrowse":
        cls = JBrowseComponent
    else:
        cls = DepictioComponent
    return cls(client, dashboard_id, meta, state, theme)


COMPONENT_CLASSES: dict[str, type[DepictioComponent]] = {
    "figure": FigureComponent,
    "map": MapComponent,
    "multiqc": MultiQCComponent,
    "advanced_viz": AdvancedVizComponent,
    "table": TableComponent,
    "card": CardComponent,
    "interactive": InteractiveComponent,
    "text": TextComponent,
    "image": ImageComponent,
    "jbrowse": JBrowseComponent,
}
