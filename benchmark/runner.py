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

import httpx

from benchmark.configgen import GeneratedConfigs, write_configs, write_ingest_config
from benchmark.datagen import (
    generate_dataset,
    generate_image_dataset,
    generate_multiqc_dataset,
)
from benchmark.matrix import Cell, ConnectMode, DCKind, IngestCell, VisuType
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

# A heavy render is the *subject* of this benchmark, not an anomaly: at 1 GB/DC a
# cold table read is minutes, not seconds. The CLI's shared client defaults to
# httpx's 5 s, which turns every measurement above that into a ReadTimeout that
# aborts the whole matrix — so the harness owns its own client with a ceiling
# high enough that a timeout means "genuinely stuck", not "slow but interesting".
_BENCH_TIMEOUT = httpx.Timeout(900.0, connect=10.0)

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
    """Dispatch one component to its render endpoint. Returns a metrics dict.

    Never raises: a transport failure is itself a measurement (the size at which
    rendering stops working is the answer we are after), so it is recorded as a
    row with ``ok=False`` rather than propagated to abort the matrix.
    """
    ctype = comp.get("component_type")
    index = str(comp.get("index"))
    api = _api(base)
    t0 = time.perf_counter()

    try:
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
        elif ctype == "card":
            # One bulk call serves every card on the dashboard, so time it for
            # this component and let the report divide by the card count. The
            # filtered variant is the interesting one: it's the case the
            # precomputed-specs fast path can't serve.
            resp = client.post(
                f"{api}/dashboards/bulk_compute_cards/{dashboard_id}",
                json={"filters": filters, "component_ids": [index]},
                headers=headers,
            )
            celery_path = "n/a"
        elif ctype == "interactive":
            # MultiSelect option list — the cost paid on every mount. RangeSliders
            # read precomputed specs and never touch Delta, so they aren't timed.
            if (comp.get("interactive_component_type") or "") != "MultiSelect":
                return {}
            dc_id = str(comp.get("dc_id"))
            column = comp.get("column_name") or ""
            if not dc_id or not column:
                return {}
            resp = client.get(
                f"{api}/deltatables/unique_values/{dc_id}",
                params={"column": column},
                headers=headers,
            )
            celery_path = "n/a"
        else:
            return {}  # text and other passive components — not a timed render
    except httpx.HTTPError as exc:
        return {
            "wall_ms": (time.perf_counter() - t0) * 1000.0,
            "celery_path": "error",
            "http_status": 0,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:300],
        }

    wall_ms = (time.perf_counter() - t0) * 1000.0

    def _hdr_float(name: str):
        raw = resp.headers.get(name)
        try:
            return float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _hdr_int(name: str):
        v = _hdr_float(name)
        return int(v) if v is not None else None

    return {
        "wall_ms": wall_ms,
        "celery_path": celery_path,
        "http_status": resp.status_code,
        "ok": resp.status_code == 200,
        # Server-side per-stage split (additive X-* headers; None if absent).
        "load_ms": _hdr_float("X-Load-Ms"),
        "build_ms": _hdr_float("X-Build-Ms"),
        "server_total_ms": _hdr_float("X-Total-Ms"),
        # What the render had to touch — this is what makes the latency number
        # interpretable. rows_loaded == 0 with aggregated == True means a
        # scan-level reduction served it without materialising anything.
        "rows_loaded": _hdr_int("X-Rows-Loaded"),
        "rows_displayed": _hdr_int("X-Rows-Displayed"),
        "frame_bytes": _hdr_int("X-Frame-Bytes"),
        "aggregated": resp.headers.get("X-Aggregated") == "1",
        "cache": resp.headers.get("X-Cache", ""),
        "peak_rss_mb": _hdr_float("X-Peak-RSS-MB"),
        "error": "" if resp.status_code == 200 else resp.text[:300],
    }


def _dashboard_load(
    client, base: str, headers: dict, dashboard_id: str, components: list[dict]
) -> tuple[list[tuple[dict, dict]], float]:
    """Fire every component at once, as opening the dashboard does.

    Sequential rendering measures one component on an idle server; a real cold
    open puts all of them in flight together, so the answer to "does a heavy
    dashboard hold up" lives in the contention this creates — worker-pool
    saturation, connection-pool queueing, memory pressure from concurrent Delta
    reads. Returns the per-component metrics plus the wall-clock to the *last*
    one, which is what the user actually waits for.
    """
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, len(components))) as pool:
        futures = [
            (comp, pool.submit(_render_component, client, base, headers, dashboard_id, comp, []))
            for comp in components
        ]
        results = [(comp, fut.result()) for comp, fut in futures]
    return results, (time.perf_counter() - t0) * 1000.0


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
    repeats: int = 1,
    dashboard_load: bool = False,
    depictio_bin: str = "depictio",
) -> Path:
    """Run every cell and append results to ``<output_root>/results.jsonl``.

    Returns the results path. Datasets are cached by ``(size, n_dcs)`` so
    connect/visu variants of the same size reuse the generated CSVs.
    """
    # Lazy imports: keep this module importable without the full depictio stack.
    from depictio.cli.cli.utils.common import (
        generate_api_headers,
        load_depictio_config,
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"

    cli_config = load_depictio_config(cli_config_path)
    base = str(cli_config.api_base_url)
    headers = generate_api_headers(cli_config)
    # Own client, not the CLI's shared singleton: see _BENCH_TIMEOUT.
    client = httpx.Client(timeout=_BENCH_TIMEOUT)

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

            touched_dcs: set[str] = set()
            for filtered, filt in passes:
                for iteration in range(max(1, repeats)):
                    for comp in components:
                        m = _render_component(client, base, headers, dashboard_id, comp, filt)
                        if not m:
                            continue
                        dc_tag = str(comp.get("dc_config", {}).get("data_collection_tag", ""))
                        first_touch = dc_tag not in touched_dcs
                        touched_dcs.add(dc_tag)
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
                            dc_tag=dc_tag,
                            server_mode=server_mode,
                            filtered=filtered,
                            dc_first_touch=first_touch,
                            iteration=iteration,
                            **m,
                        )
                        emit({"kind": "render", **row.to_dict()})

            if dashboard_load:
                loaded, total_ms = _dashboard_load(client, base, headers, dashboard_id, components)
                # Passive components (text, …) return no metrics; counting them as
                # "requested" would report a complete load as partial.
                n_timed = sum(1 for _, m in loaded if m)
                n_ok = 0
                for comp, m in loaded:
                    if not m:
                        continue
                    n_ok += bool(m.get("ok"))
                    emit(
                        {
                            "kind": "render",
                            **RenderResult(
                                cell_slug=cell.slug,
                                size=cell.size,
                                size_bytes=cell.size_bytes,
                                n_components=cell.n_components,
                                n_dcs=cell.n_dcs,
                                connect=cell.connect.value,
                                component_type=comp.get("component_type", ""),
                                component_index=str(comp.get("index")),
                                visu=str(comp.get("visu_type") or comp.get("viz_kind") or ""),
                                dc_tag=str(
                                    comp.get("dc_config", {}).get("data_collection_tag", "")
                                ),
                                server_mode=server_mode,
                                concurrent=True,
                                **m,
                            ).to_dict(),
                        }
                    )
                emit(
                    {
                        "kind": "dashboard_load",
                        "cell_slug": cell.slug,
                        "size": cell.size,
                        "n_components": cell.n_components,
                        "n_dcs": cell.n_dcs,
                        "connect": cell.connect.value,
                        "server_mode": server_mode,
                        "wall_ms": total_ms,
                        "n_rendered": n_ok,
                        "n_requested": n_timed,
                        "ok": n_ok == n_timed,
                    }
                )

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


def _run_cli_capture(args: list[str]) -> tuple[int, str, str, float]:
    """Run a depictio CLI subprocess, returning (rc, stdout, stderr, wall_ms)."""
    t0 = time.perf_counter()
    proc = subprocess.run(args, capture_output=True, text=True)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    return proc.returncode, proc.stdout, proc.stderr, wall_ms


def _aggregate_markers(stdout: str) -> dict:
    """Sum per-phase timings + collect counters from ``DEPICTIO_INGEST_TIMINGS`` lines."""
    from depictio.cli.cli.utils.ingest_timing import parse_timing_markers

    phase_ms: dict[str, float] = {}
    peak_rss: float | None = None
    n_units = 0
    delta_bytes = 0
    # Authoritative write path, as taken (a requested stream that hit the
    # fallback reports False) — None when no marker declared one.
    streaming: bool | None = None
    for m in parse_timing_markers(stdout):
        for phase, ms in (m.get("phase_ms") or {}).items():
            phase_ms[phase] = phase_ms.get(phase, 0.0) + float(ms)
        rss = m.get("peak_rss_mb")
        if rss is not None:
            peak_rss = rss if peak_rss is None else max(peak_rss, rss)
        n_units += int(m.get("n_rows") or m.get("n_files") or m.get("n_images") or 0)
        delta_bytes += int(m.get("delta_bytes") or 0)
        if "streaming" in m:
            # Across multiple DCs, only report streaming if every one streamed.
            val = bool(m["streaming"])
            streaming = val if streaming is None else (streaming and val)
    return {
        "phase_ms": phase_ms,
        "peak_rss_mb": peak_rss,
        "n_units": n_units,
        "delta_bytes": delta_bytes,
        "streaming": streaming,
    }


def run_ingest_matrix(
    cells: list[IngestCell],
    *,
    cli_config_path: str,
    output_root: str | Path,
    multiqc_fixture: str = "small",
    force_datagen: bool = False,
    streaming: bool = False,
    run_tag: str = "",
    depictio_bin: str = "depictio",
) -> Path:
    """Ingest each cell (no render) and append ``kind=="ingest"`` rows.

    Dispatches per :class:`~benchmark.matrix.DCKind`: TABLE/MULTIQC run through
    ``depictio run``; IMAGES additionally pushes the PNGs via ``depictio images
    push``. The per-phase ``DEPICTIO_INGEST_TIMINGS`` markers emitted by the CLI
    are parsed out of captured stdout to fill the phase breakdown + peak RSS.

    ``run_tag`` namespaces the generated projects so this invocation ingests into
    fresh data collections; it defaults to a timestamp. Reusing a previous run's
    project would re-aggregate the files it registered on top of this run's own,
    inflating row counts and invalidating before/after comparisons.
    """
    from depictio.cli.cli.utils.common import load_depictio_config

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"
    run_tag = run_tag or time.strftime("%Y%m%d%H%M%S")

    cli_config = load_depictio_config(cli_config_path)
    s3_bucket = getattr(getattr(cli_config, "s3_storage", None), "bucket", "depictio-bucket")

    with results_path.open("a", encoding="utf-8") as sink:

        def emit(row: dict) -> None:
            sink.write(json.dumps(row) + "\n")
            sink.flush()

        for cell in cells:
            data_dir = output_root / "data" / cell.slug
            cfg_dir = output_root / "configs" / cell.slug
            input_bytes = 0
            metadata_csv = images_dir = None

            # ── generate the dataset for this kind ───────────────────────────
            if cell.kind is DCKind.TABLE:
                generate_dataset(cell.size_bytes, cell.n_dcs, data_dir, force=force_datagen)
                input_bytes = _dir_csv_bytes(data_dir)
            elif cell.kind is DCKind.MULTIQC:
                mq = generate_multiqc_dataset(
                    cell.magnitude_int, data_dir, fixture=multiqc_fixture, force=force_datagen
                )
                input_bytes = mq.total_bytes
            else:  # IMAGES
                im = generate_image_dataset(cell.magnitude_int, data_dir, force=force_datagen)
                input_bytes = im.total_bytes
                metadata_csv, images_dir = im.metadata_csv, im.images_dir

            gen = write_ingest_config(
                cell,
                data_dir,
                cfg_dir,
                s3_bucket=s3_bucket,
                metadata_csv=metadata_csv,
                images_dir=images_dir,
                run_tag=run_tag,
            )

            # ── ingest (run) ─────────────────────────────────────────────────
            run_args = [
                depictio_bin,
                "run",
                "--CLI-config-path",
                cli_config_path,
                "--project-config-path",
                gen.project_path,
                "--overwrite",
                "--update-config",
            ]
            # Toggling this per run is how the table before/after is measured:
            # same cell, same data, collect-then-write vs streamed write.
            if streaming:
                run_args.append("--streaming")
            rc, out, err, wall_ms = _run_cli_capture(run_args)
            if rc != 0:
                emit(
                    _ingest_kind_error_row(cell, input_bytes, f"run failed (rc={rc}): {err[-300:]}")
                )
                continue

            combined_stdout = out
            # ── images: push the PNGs to S3 (the real N-HEAD + N-PUT cost) ────
            if cell.kind is DCKind.IMAGES and gen.s3_base_folder:
                prc, pout, perr, pwall = _run_cli_capture(
                    [
                        depictio_bin,
                        "images",
                        "push",
                        images_dir,
                        gen.s3_base_folder,
                        "--CLI-config-path",
                        cli_config_path,
                        "--overwrite",
                    ]
                )
                wall_ms += pwall
                combined_stdout += "\n" + pout
                if prc != 0:
                    emit(
                        _ingest_kind_error_row(
                            cell, input_bytes, f"images push failed (rc={prc}): {perr[-300:]}"
                        )
                    )
                    continue

            agg = _aggregate_markers(combined_stdout)
            res = IngestResult(
                cell_slug=cell.slug,
                ingest_wall_ms=wall_ms,
                import_wall_ms=0.0,
                ok=True,
                n_dcs=cell.n_dcs,
                rows_total=agg["n_units"] if cell.kind is DCKind.TABLE else 0,
                input_bytes=input_bytes,
                delta_bytes=agg["delta_bytes"],
                dc_kind=cell.kind.value,
                magnitude=cell.magnitude,
                n_units=agg["n_units"],
                phase_ms=agg["phase_ms"],
                peak_rss_mb=agg["peak_rss_mb"],
                streaming=agg["streaming"],
            )
            emit({"kind": "ingest", "server_mode": "ingest", **vars(res)})

    return results_path


def _ingest_kind_error_row(cell: IngestCell, input_bytes: int, error: str) -> dict:
    return {
        "kind": "ingest",
        "server_mode": "ingest",
        "cell_slug": cell.slug,
        "dc_kind": cell.kind.value,
        "magnitude": cell.magnitude,
        "ok": False,
        "error": error,
        "ingest_wall_ms": 0.0,
        "import_wall_ms": 0.0,
        "input_bytes": input_bytes,
    }


def _stamp_run_meta(output_root: Path, server_mode: str, celery_health: dict) -> None:
    """Record the server config active for this matrix half (best-effort)."""
    meta_path = output_root / "run_meta.jsonl"
    with meta_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"server_mode": server_mode, "celery_health": celery_health}) + "\n")


# Convenience re-export used by the pytest so it doesn't import the runner's
# depictio dependencies transitively.
__all__ = ["run_matrix", "VisuType"]
