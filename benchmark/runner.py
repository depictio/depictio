"""Drive the benchmark matrix against a live Depictio stack and collect timings.

Per cell: generate data -> write configs -> ingest (``depictio run``) -> import
the dashboard -> discover its components -> render each one, timing the HTTP
round-trip and reading the ``X-Celery-Path`` header. Results are appended to
``results.jsonl`` (one row per rendered component).

Celery on/off is a *server* setting that cannot be flipped mid-process, so the
harness runs the whole matrix once per server config. Each row is stamped with
the ``server_mode`` label you pass and the authoritative per-render
``celery_path`` header, so the two halves can be compared after the fact.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from benchmark.configgen import GeneratedConfigs, write_configs
from benchmark.datagen import generate_dataset
from benchmark.matrix import Cell, ConnectMode, VisuType
from benchmark.metrics import IngestResult, RenderResult

# Columns projected for advanced_viz (/advanced_viz/data) — a superset that
# satisfies both volcano and ma bindings.
_ADVANCED_VIZ_COLUMNS = [
    "individual_id",
    "effect_size",
    "neg_log10_p",
    "mean_expression",
    "species",
]

# Representative cross-filter payload (React filter shape) for links cells.
_CROSS_FILTER = [
    {
        "column_name": "species",
        "value": ["Adelie"],
        "interactive_component_type": "MultiSelect",
    }
]


def _api(base: str) -> str:
    return f"{base.rstrip('/')}/depictio/api/v1"


def _ingest(cell: Cell, cli_config_path: str, gen: GeneratedConfigs, depictio_bin: str) -> float:
    """Run ``depictio run`` for the generated project. Returns wall-clock ms.

    Raises ``subprocess.CalledProcessError`` on failure so the caller can record
    an error row and move on.
    """
    t0 = time.perf_counter()
    subprocess.run(
        [
            depictio_bin,
            "run",
            "--CLI-config-path",
            cli_config_path,
            "--project-config-path",
            gen.project_path,
            "--overwrite",
            "--update-config",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return (time.perf_counter() - t0) * 1000.0


def _dir_csv_bytes(dataset_dir: Path) -> int:
    """Total on-disk bytes of the generated CSV shards (the ingest input)."""
    return sum(p.stat().st_size for p in Path(dataset_dir).rglob("*.csv"))


def _project_delta_bytes(client, base: str, headers: dict, dashboard_id: str) -> int:
    """Best-effort materialized Delta size for a dashboard's project.

    Sums ``flexible_metadata.deltatable_size_bytes`` (written by the CLI at
    ingest) across every data collection of the project's workflows. Returns 0
    on any failure — compression is then omitted from the report, not guessed.
    """
    try:
        resp = client.get(
            f"{_api(base)}/projects/get/from_dashboard_id/{dashboard_id}", headers=headers
        )
        if resp.status_code != 200:
            return 0
        body = resp.json()
        # Endpoint wraps the project: {"project": {...}, "delta_locations": {...}}.
        project = body.get("project", body)
    except Exception:
        return 0
    total = 0
    # In joins mode the materialized size lands on the joined DC (source DCs
    # carry empty flexible_metadata); in links/independent mode it's on each
    # source DC. Summing all workflow DCs captures the right total either way.
    for wf in project.get("workflows") or []:
        for dc in wf.get("data_collections") or []:
            fm = dc.get("flexible_metadata") or {}
            try:
                total += int(fm.get("deltatable_size_bytes") or 0)
            except (TypeError, ValueError):
                continue
    return total


def _import_dashboard(client, base: str, headers: dict, gen: GeneratedConfigs) -> tuple[str, float]:
    """POST the dashboard YAML to the import endpoint. Returns (dashboard_id, ms)."""
    yaml_content = Path(gen.dashboard_path).read_text(encoding="utf-8")
    t0 = time.perf_counter()
    resp = client.post(
        f"{_api(base)}/dashboards/import/yaml",
        params={"overwrite": True},
        content=yaml_content,
        headers={**headers, "Content-Type": "text/plain"},
    )
    ms = (time.perf_counter() - t0) * 1000.0
    resp.raise_for_status()
    return str(resp.json().get("dashboard_id")), ms


def _get_components(client, base: str, headers: dict, dashboard_id: str) -> list[dict]:
    resp = client.get(f"{_api(base)}/dashboards/get/{dashboard_id}", headers=headers)
    resp.raise_for_status()
    return resp.json().get("stored_metadata") or []


def _render_component(
    client, base: str, headers: dict, dashboard_id: str, comp: dict, filters: list[dict]
) -> dict:
    """Dispatch one component to its render endpoint. Returns a metrics dict."""
    ctype = comp.get("component_type")
    index = str(comp.get("index"))
    api = _api(base)
    t0 = time.perf_counter()

    if ctype == "figure":
        resp = client.post(
            f"{api}/dashboards/render_figure/{dashboard_id}/{index}",
            json={"filters": filters, "theme": "light"},
            headers=headers,
        )
        celery_path = resp.headers.get("X-Celery-Path", "inline")
    elif ctype == "table":
        resp = client.post(
            f"{api}/dashboards/render_table/{dashboard_id}/{index}",
            json={"filters": filters, "start": 0, "limit": 100},
            headers=headers,
        )
        celery_path = resp.headers.get("X-Celery-Path", "n/a")
    elif ctype == "advanced_viz":
        resp = client.post(
            f"{api}/advanced_viz/data",
            json={
                "wf_id": str(comp.get("wf_id")),
                "dc_id": str(comp.get("dc_id")),
                "columns": _ADVANCED_VIZ_COLUMNS,
                "filter_metadata": filters,
                "limit_rows": 100_000,
            },
            headers=headers,
        )
        celery_path = resp.headers.get("X-Celery-Path", "n/a")
    else:
        return {}  # interactive/card/text — not a timed render

    wall_ms = (time.perf_counter() - t0) * 1000.0

    def _hdr_float(name: str):
        raw = resp.headers.get(name)
        try:
            return float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "wall_ms": wall_ms,
        "celery_path": celery_path,
        "http_status": resp.status_code,
        "ok": resp.status_code == 200,
        # Server-side per-stage split (additive X-* headers; None if absent).
        "load_ms": _hdr_float("X-Load-Ms"),
        "build_ms": _hdr_float("X-Build-Ms"),
        "server_total_ms": _hdr_float("X-Total-Ms"),
        "error": "" if resp.status_code == 200 else resp.text[:300],
    }


def _get_celery_health(client, base: str, headers: dict) -> dict:
    try:
        resp = client.get(f"{_api(base)}/celery/health", headers=headers)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


def run_matrix(
    cells: list[Cell],
    *,
    cli_config_path: str,
    output_root: str | Path,
    server_mode: str,
    cross_filter: bool = False,
    force_datagen: bool = False,
    depictio_bin: str = "depictio",
) -> Path:
    """Run every cell and append results to ``<output_root>/results.jsonl``.

    Returns the results path. Datasets are cached by ``(size, n_dcs)`` so
    connect/visu variants of the same size reuse the generated CSVs.
    """
    # Lazy imports: keep this module importable without the full depictio stack.
    from depictio.cli.cli.utils.common import (
        generate_api_headers,
        get_http_client,
        load_depictio_config,
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"

    cli_config = load_depictio_config(cli_config_path)
    base = str(cli_config.api_base_url)
    headers = generate_api_headers(cli_config)
    client = get_http_client()

    celery_health = _get_celery_health(client, base, headers)

    with results_path.open("a", encoding="utf-8") as sink:

        def emit(row: dict) -> None:
            sink.write(json.dumps(row) + "\n")
            sink.flush()

        for cell in cells:
            dataset_dir = output_root / "data" / f"{cell.size}_dc{cell.n_dcs}"
            manifest = generate_dataset(
                cell.size_bytes, cell.n_dcs, dataset_dir, force=force_datagen
            )
            gen = write_configs(cell, dataset_dir, output_root / "configs" / cell.slug)
            input_bytes = _dir_csv_bytes(dataset_dir)

            # ── Ingest + import ──────────────────────────────────────────────
            try:
                ingest_ms = _ingest(cell, cli_config_path, gen, depictio_bin)
                dashboard_id, import_ms = _import_dashboard(client, base, headers, gen)
            except subprocess.CalledProcessError as exc:
                emit(_ingest_error_row(cell, server_mode, f"ingest failed: {exc.stderr[:300]}"))
                continue
            except Exception as exc:  # import/network failure
                emit(_ingest_error_row(cell, server_mode, f"import failed: {exc}"))
                continue

            # ── Render each component ────────────────────────────────────────
            components = _get_components(client, base, headers, dashboard_id)
            ingest_res = IngestResult(
                cell_slug=cell.slug,
                ingest_wall_ms=ingest_ms,
                import_wall_ms=import_ms,
                ok=True,
                dashboard_id=dashboard_id,
                n_dcs=cell.n_dcs,
                rows_per_dc=manifest.rows_total,
                rows_total=manifest.rows_total * cell.n_dcs,
                input_bytes=input_bytes,
                delta_bytes=_project_delta_bytes(client, base, headers, dashboard_id),
            )
            emit({"kind": "ingest", "server_mode": server_mode, **vars(ingest_res)})
            passes: list[tuple[bool, list[dict]]] = [(False, [])]
            if cross_filter and cell.connect is ConnectMode.LINKS:
                passes.append((True, _CROSS_FILTER))

            for filtered, filt in passes:
                for comp in components:
                    m = _render_component(client, base, headers, dashboard_id, comp, filt)
                    if not m:
                        continue
                    row = RenderResult(
                        cell_slug=cell.slug,
                        size=cell.size,
                        size_bytes=cell.size_bytes,
                        n_components=cell.n_components,
                        n_dcs=cell.n_dcs,
                        connect=cell.connect.value,
                        component_type=comp.get("component_type", ""),
                        component_index=str(comp.get("index")),
                        visu=str(comp.get("visu_type") or comp.get("viz_kind") or ""),
                        dc_tag=str(comp.get("dc_config", {}).get("data_collection_tag", "")),
                        server_mode=server_mode,
                        filtered=filtered,
                        **m,
                    )
                    emit({"kind": "render", **row.to_dict()})

    client.close()
    _stamp_run_meta(output_root, server_mode, celery_health)
    return results_path


def _ingest_error_row(cell: Cell, server_mode: str, error: str) -> dict:
    return {
        "kind": "ingest",
        "cell_slug": cell.slug,
        "server_mode": server_mode,
        "ok": False,
        "error": error,
        "ingest_wall_ms": 0.0,
        "import_wall_ms": 0.0,
        "dashboard_id": "",
    }


def _stamp_run_meta(output_root: Path, server_mode: str, celery_health: dict) -> None:
    """Record the server config active for this matrix half (best-effort)."""
    meta_path = output_root / "run_meta.jsonl"
    with meta_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"server_mode": server_mode, "celery_health": celery_health}) + "\n")


# Convenience re-export used by the pytest so it doesn't import the runner's
# depictio dependencies transitively.
__all__ = ["run_matrix", "VisuType"]
