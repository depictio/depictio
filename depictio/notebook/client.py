"""The HTTP client behind ``depictio.notebook``.

Pure client code: ``httpx`` + ``polars`` (+ ``plotly`` for figures), no
server imports, so it ships in the ``depictio-cli`` distribution and runs in
any notebook environment.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from .components import DepictioComponent, component_for, pin_body

API_PREFIX = "/depictio/api/v1"
DEFAULT_CLI_CONFIG = "~/.depictio/CLI.yaml"


class DepictioClientError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"Depictio API returned {status}: {detail}")
        self.status = status
        self.detail = detail


def _read_cli_config(path: str = DEFAULT_CLI_CONFIG) -> tuple[str | None, str | None]:
    """``(api_base_url, access_token)`` from a ``depictio-cli`` config, if present."""
    p = Path(os.path.expanduser(path))
    if not p.exists():
        return None, None
    try:
        import yaml

        doc = yaml.safe_load(p.read_text()) or {}
        url = doc.get("api_base_url")
        token = ((doc.get("user") or {}).get("token") or {}).get("access_token")
        return (str(url) if url else None), (str(token) if token else None)
    except Exception:
        return None, None


class DepictioClient:
    """Talk to a Depictio instance from a notebook.

    Credentials resolve in this order: explicit arguments, the environment
    (``DEPICTIO_API_URL`` / ``DEPICTIO_API_TOKEN``), then ``~/.depictio/CLI.yaml``
    written by ``depictio-cli``. ``DEPICTIO_DATA_DIR`` switches :meth:`data` to
    local Parquet files (``<dc_id>.parquet``) so a notebook can run offline;
    everything rendered by the server still needs the API.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = 600.0,
        transport: httpx.BaseTransport | None = None,
        data_dir: str | None = None,
    ) -> None:
        cfg_url, cfg_token = (None, None)
        if base_url is None or token is None:
            cfg_url, cfg_token = _read_cli_config()
        self.base_url = (base_url or os.environ.get("DEPICTIO_API_URL") or cfg_url or "").rstrip(
            "/"
        )
        self.token = token or os.environ.get("DEPICTIO_API_TOKEN") or cfg_token
        self.data_dir = data_dir or os.environ.get("DEPICTIO_DATA_DIR")
        self.timeout = timeout
        self._http = httpx.Client(
            base_url=self.base_url or "http://depictio.invalid",
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
        )
        self._dashboards: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ http
    def _require_api(self) -> None:
        if not self.base_url:
            raise DepictioClientError(
                0,
                "no API configured: set DEPICTIO_API_URL and DEPICTIO_API_TOKEN, pass "
                "base_url=/token=, or log in once with depictio-cli",
            )

    def _raise(self, resp: httpx.Response) -> None:
        detail: str
        try:
            body = resp.json()
            detail = str(body.get("detail", body)) if isinstance(body, dict) else str(body)
        except Exception:
            detail = resp.text[:500]
        raise DepictioClientError(resp.status_code, detail)

    def get(self, path: str, **params: Any) -> Any:
        self._require_api()
        resp = self._http.get(f"{API_PREFIX}{path}", params=params or None)
        if resp.status_code >= 400:
            self._raise(resp)
        return resp.json()

    def get_bytes(self, path: str, **params: Any) -> bytes:
        self._require_api()
        resp = self._http.get(f"{API_PREFIX}{path}", params=params or None)
        if resp.status_code >= 400:
            self._raise(resp)
        return resp.content

    def post(self, path: str, body: Any = None, *, raw: bool = False) -> Any:
        self._require_api()
        resp = self._http.post(f"{API_PREFIX}{path}", json=body if body is not None else {})
        if resp.status_code >= 400:
            self._raise(resp)
        if raw:
            return resp
        return resp.json()

    def poll(
        self,
        dispatch_path: str,
        body: dict[str, Any],
        poll_path: str,
        *,
        ready: str = "ready",
        interval: float = 1.0,
        max_wait: float = 300.0,
        retries: int = 1,
    ) -> dict[str, Any]:
        """Dispatch a server job and wait for its result.

        A job that comes back *failed* is dispatched once more. These jobs run a
        real browser on the server, and one that drops its connection while
        closing is a flake rather than an answer — a notebook that asks for
        fifty figures in a row otherwise stops on the first unlucky one. A job
        the server calls ``unsupported`` is an answer, and is not retried.
        """
        for attempt in range(retries + 1):
            failure = self._poll_once(
                dispatch_path, body, poll_path, ready=ready, interval=interval, max_wait=max_wait
            )
            if not isinstance(failure, DepictioClientError):
                return failure
            if attempt == retries or getattr(failure, "final", False):
                raise failure
        raise AssertionError("unreachable")  # pragma: no cover

    def _poll_once(
        self,
        dispatch_path: str,
        body: dict[str, Any],
        poll_path: str,
        *,
        ready: str,
        interval: float,
        max_wait: float,
    ) -> dict[str, Any] | DepictioClientError:
        """One dispatch-and-wait: the result, or the error to raise for it."""
        first = self.post(dispatch_path, body)
        if first.get("status") in (ready, "completed", "SUCCESS") or first.get("job_id") is None:
            return first
        job_id = first["job_id"]
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            time.sleep(interval)
            result = self.get(poll_path.format(job_id=job_id))
            status = str(result.get("status") or "")
            if status in (ready, "completed", "SUCCESS"):
                return result
            if status in ("error", "failed", "FAILURE", "unsupported"):
                err = DepictioClientError(500, str(result.get("reason") or result))
                err.final = status == "unsupported"  # type: ignore[attr-defined]
                return err
        return DepictioClientError(504, f"job {job_id} did not finish within {max_wait:.0f}s")

    # ------------------------------------------------------------------ data
    def data(
        self, dc_id: str, columns: list[str] | None = None, *, version: int | None = None
    ) -> pl.DataFrame:
        """A data collection's table, unfiltered.

        ``version`` reads that Delta commit instead of the current table (what
        an export taken under a dashboard version pins). Reads
        ``DEPICTIO_DATA_DIR/<dc_id>.parquet`` when that variable is set
        (offline mode; ``<dc_id>@v<version>.parquet`` for a pinned read, which
        never falls back to the current table), otherwise the API's Parquet
        endpoint.
        """
        if self.data_dir:
            folder = Path(self.data_dir)
            path = folder / f"{dc_id}.parquet"
            if version is not None:
                path = folder / f"{dc_id}@v{version}.parquet"
                if not path.exists():
                    # A pinned read is that commit or nothing: the current table
                    # would be labelled with a version it is not.
                    raise FileNotFoundError(
                        f"{path} is missing: this document reads {dc_id} as of commit "
                        f"{version}, and offline that is the only file it may read"
                    )
            df = pl.read_parquet(path)
            return df.select(columns) if columns else df
        params: dict[str, Any] = {"columns": ",".join(columns)} if columns else {}
        if version is not None:
            params["version"] = int(version)
        return pl.read_parquet(io.BytesIO(self.get_bytes(f"/deltatables/data/{dc_id}", **params)))

    def specs(self, dc_id: str) -> list[dict[str, Any]]:
        return list(self.get(f"/deltatables/specs/{dc_id}") or [])

    def unique_values(self, dc_id: str, column: str, limit: int = 1000) -> list[str]:
        out = self.get(f"/deltatables/unique_values/{dc_id}", column=column, limit=limit)
        return list(out.get("values") or []) if isinstance(out, dict) else list(out or [])

    # ------------------------------------------------------------- dashboard
    def dashboard(self, dashboard_id: str, *, refresh: bool = False) -> dict[str, Any]:
        """The dashboard document (``stored_metadata`` holds its components)."""
        if refresh or dashboard_id not in self._dashboards:
            self._dashboards[dashboard_id] = self.get(f"/dashboards/get/{dashboard_id}")
        return self._dashboards[dashboard_id]

    def category_colors(self, dashboard_id: str) -> dict[str, dict[str, str]]:
        """``{column: {value: colour}}`` the dashboard draws in.

        Its main tab's (``inherited_category_colors``) with its own laid over,
        per column and value: ``effective_category_colors`` on the server. Empty
        when the dashboard cannot be read (offline): colours then fall back to
        the palette, as for a dashboard that pins none.
        """
        try:
            doc = self.dashboard(dashboard_id)
        except Exception:  # noqa: BLE001 - a missing palette only costs the pins
            return {}
        merged: dict[str, dict[str, str]] = {}
        for layer in (doc.get("inherited_category_colors"), doc.get("category_colors")):
            if not isinstance(layer, dict):
                continue
            for column, values in layer.items():
                if isinstance(values, dict) and values:
                    merged.setdefault(str(column), {}).update(
                        {str(k): str(v) for k, v in values.items() if isinstance(v, str) and v}
                    )
        return merged

    def components(self, dashboard_id: str) -> pl.DataFrame:
        """One row per component: index, title, type, kind, section, column."""
        rows = []
        for m in self.dashboard(dashboard_id).get("stored_metadata") or []:
            rows.append(
                {
                    "index": str(m.get("index") or ""),
                    "title": m.get("title"),
                    "component_type": m.get("component_type"),
                    "kind": m.get("viz_kind")
                    or m.get("visu_type")
                    or m.get("aggregation")
                    or m.get("interactive_component_type"),
                    "section": m.get("section"),
                    "column": m.get("column_name"),
                    "dc_id": str(m.get("dc_id") or "") or None,
                }
            )
        return pl.DataFrame(rows)

    def metadata(self, dashboard_id: str, component: str) -> dict[str, Any]:
        """A component's stored metadata, by index or by title."""
        metas = self.dashboard(dashboard_id).get("stored_metadata") or []
        for m in metas:
            if str(m.get("index")) == component:
                return m
        exact = [m for m in metas if str(m.get("title") or "") == component]
        if len(exact) == 1:
            return exact[0]
        loose = [m for m in metas if str(m.get("title") or "").lower() == component.lower()]
        if len(loose) == 1:
            return loose[0]
        if len(exact) > 1 or len(loose) > 1:
            raise KeyError(
                f"several components are titled {component!r}; use the index instead "
                "(see client.components(dashboard_id))"
            )
        raise KeyError(f"no component {component!r} in dashboard {dashboard_id}")

    # ----------------------------------------------------------------- state
    def filter(self, dashboard_id: str, component: str, value: Any) -> dict[str, Any]:
        """A well-formed filter for an interactive component (by index or title)."""
        meta = self.metadata(dashboard_id, component)
        if meta.get("component_type") != "interactive":
            raise ValueError(f"{component!r} is a {meta.get('component_type')}, not a filter")
        return {
            "index": str(meta.get("index")),
            "value": value,
            "column_name": meta.get("column_name"),
            "interactive_component_type": meta.get("interactive_component_type"),
            "metadata": {
                "dc_id": str(meta.get("dc_id") or "") or None,
                "column_name": meta.get("column_name"),
                "interactive_component_type": meta.get("interactive_component_type"),
            },
        }

    def state(
        self,
        dashboard_id: str,
        *,
        filters: list[dict[str, Any]] | None = None,
        groups: list[dict[str, Any]] | None = None,
        stage_order: list[str] | None = None,
        theme: str = "light",
        as_of_version: str | None = None,
        data_versions: dict[str, int | None] | None = None,
    ) -> dict[str, Any]:
        """An ``AnalysisState`` payload, the wire shape the server expects.

        ``as_of_version`` reads the data and the definitions a stored dashboard
        version held (both halves, as the viewer's preview does);
        ``data_versions`` pins single collections.
        """
        pins: dict[str, Any] = {"data_versions": dict(data_versions or {})}
        if as_of_version:
            pins["as_of_version"] = as_of_version
            pins["definition_version"] = as_of_version
        return {
            "version": 1,
            "filters": list(filters or []),
            "groups": list(groups or []),
            "color_by": {"kind": "none"},
            "display_mode": "color",
            "show_other": True,
            "show_overall": True,
            "compare_in_cards": False,
            "funnel": {"enabled": True, "stage_order": list(stage_order or [])},
            "split_panels": [],
            "pins": pins,
            "context": {"dashboard_id": dashboard_id, "theme": theme},
        }

    def text_values(
        self,
        dashboard_id: str,
        index: str,
        state: dict[str, Any] | None = None,
        *,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """A text tile's live values under ``state``: ``{name: v, "param:KEY": v}``.

        The same computation the viewer asks for (``bulk_compute_cards`` with
        the tile's index). ``fallback`` — the values at export time — answers
        when the API is out of reach (offline, ``DEPICTIO_DATA_DIR``), so a
        document still reads rather than printing dashes everywhere.
        """
        state = state or {}
        try:
            payload = self.post(
                f"/dashboards/bulk_compute_cards/{dashboard_id}",
                {
                    "filters": list(state.get("filters") or []),
                    "component_ids": [index],
                    **pin_body(state),
                },
            )
            got = (payload.get("values") or {}).get(index)
            if isinstance(got, dict):
                return got
        except Exception:  # noqa: BLE001 - the export-time values stand in
            pass
        return dict(fallback or {})

    # ------------------------------------------------------------ components
    def component(
        self,
        dashboard_id: str,
        component: str,
        *,
        state: dict[str, Any] | Any | None = None,
        filters: list[dict[str, Any]] | None = None,
        theme: str = "light",
    ) -> DepictioComponent:
        """Any dashboard component, ready to display in a cell.

        ``state`` is an ``AnalysisState`` (dict or model); ``filters`` is the
        shortcut for "just these filters" (see :meth:`filter`).
        """
        meta = self.metadata(dashboard_id, component)
        if state is not None and hasattr(state, "model_dump"):
            state = state.model_dump(mode="json", exclude_none=True)
        if state is None:
            state = self.state(dashboard_id, filters=filters, theme=theme)
        elif filters:
            state = {**state, "filters": [*state.get("filters", []), *filters]}
        return component_for(self, dashboard_id, meta, state, theme)

    def figure(self, dashboard_id: str, component: str, **kwargs: Any):
        """``component(...).figure`` — a ``plotly.graph_objects.Figure``."""
        return self.component(dashboard_id, component, **kwargs).figure

    # ---------------------------------------------------------------- export
    def preflight(self, dashboard_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or self.state(dashboard_id)
        return self.post(f"/dashboards/notebook_export/{dashboard_id}/preflight", {"state": state})

    def notebook(
        self,
        dashboard_id: str,
        state: dict[str, Any] | None = None,
        *,
        save_to: str | os.PathLike[str] | None = None,
    ) -> str:
        """The dashboard as a Quarto document: the ``.qmd`` source."""
        state = state or self.state(dashboard_id)
        resp = self.post(f"/dashboards/notebook_export/{dashboard_id}", {"state": state}, raw=True)
        content = resp.text
        if save_to is not None:
            with open(save_to, "w", encoding="utf-8") as fh:
                fh.write(content)
        return content

    # --------------------------------------------------------- report runtime
    def manifest(self, dashboard_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        """The dashboard's ``BundleManifest``, opening on ``state``.

        The same manifest a static export bundles (producer A, the dashboard's
        whole tab family), with ``initial_filters`` set to the state's filters,
        so the runtime opens on the view the document narrates. Owner-gated,
        like the static export: it carries the data. Built by a worker, as
        long as the export's own build, so this waits for it.
        """
        state = state or self.state(dashboard_id)
        if hasattr(state, "model_dump"):
            state = state.model_dump(mode="json", exclude_none=True)
        job = self.poll(
            f"/serverless/report-manifest/{dashboard_id}",
            {"state": state},
            "/serverless/report-manifest/job/{job_id}",
            interval=2.0,
            max_wait=900.0,
            retries=0,
        )
        return job["manifest"]

    def runtime(self, addons: list[str] | None = None) -> dict[str, Any]:
        """The static runtime: ``{"js", "css", "addons": {name: markup}}``."""
        params = {"addons": ",".join(addons)} if addons else {}
        return self.get("/serverless/report-runtime", **params)

    def report_runtime(
        self,
        dashboard_id: str,
        state: dict[str, Any] | None = None,
        *,
        config: dict[str, Any] | None = None,
    ) -> str:
        """The runtime and the manifest a report embeds, as a raw-HTML block.

        With it, the report's tiles are drawn by the dashboard's own renderers
        and follow an in-page filter panel; without it (this returns ``""``
        when the API is out of reach, the caller is not an owner, or the
        state cannot be reproduced in the page) every tile keeps the output
        this document computed for it. A worker rendering the report embeds the
        runtime itself afterwards (``DEPICTIO_REPORT_RUNTIME_DEFERRED``).
        """
        from .components import static_figures
        from .report_runtime import RUNTIME_DEFERRED_ENV, raw_html_block, runtime_parts

        if static_figures() or os.environ.get(RUNTIME_DEFERRED_ENV):
            # A page with no browser (the PDF) runs no script: the block would
            # only be megabytes of raw HTML for the typst writer to drop. And a
            # worker's render gets the runtime from the worker, once.
            return ""
        try:
            manifest = self.manifest(dashboard_id, state)
            names = [str(a.get("name")) for a in manifest.get("addons") or [] if a.get("name")]
            runtime = self.runtime(names)
        except Exception:  # noqa: BLE001 - the fallbacks stand in
            return ""
        markup = runtime.get("addons") or {}
        data, code = runtime_parts(
            js=str(runtime.get("js") or ""),
            css=str(runtime.get("css") or ""),
            manifest=manifest,
            config=config,
            addons="".join(markup.get(n, "") for n in names),
        )
        return raw_html_block(data + code)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DepictioClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
