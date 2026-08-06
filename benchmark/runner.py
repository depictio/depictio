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
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

from benchmark.configgen import (
    FilterPlan,
    GeneratedConfigs,
    dataset_slug,
    filter_plans,
    write_configs,
    write_ingest_config,
)
from benchmark.datagen import (
    generate_dataset,
    generate_image_dataset,
    generate_multiqc_dataset,
)
from benchmark.datagen_linked import (
    DEFAULT_N_SAMPLES,
    FEATURES_TAG,
    JOIN_COLUMN,
    METADATA_TAG,
    METRICS_TAG,
    generate_linked_dataset,
)
from benchmark.matrix import Cell, ConnectMode, DCKind, IngestCell, VisuType
from benchmark.metrics import (
    FilterRoundResult,
    IngestResult,
    LinkResolutionResult,
    RenderResult,
)
from benchmark.profile import write_profile

# The worktree root — ``benchmark/`` sits directly under it. Every CLI subprocess
# is run from here so the worktree wins on ``sys.path`` (see ``_cli_argv``).
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _cli_argv(interpreter: str) -> list[str]:
    """The command prefix for a depictio CLI subprocess: ``<py> -m depictio.cli``.

    Never a console-script path. ``<venv>/bin/depictio`` puts the venv's ``bin/``
    on ``sys.path[0]``, so ``import depictio`` inside it resolves to whatever
    checkout the venv installed — the *main* checkout, not this worktree — and a
    CLI edit under test is run against the wrong source with no error at all
    (this already produced one false 2.9× result). Running ``-m`` with
    ``cwd=_REPO_ROOT`` (see the call sites) prepends the worktree to ``sys.path``
    instead, so the code under test is the code that runs.
    """
    return [interpreter, "-m", "depictio.cli"]


def _verify_cli_source(interpreter: str) -> str:
    """Resolve the ``depictio.cli`` the benchmark will actually execute; hard-fail
    if it is not inside this worktree.

    Runs the same interpreter + ``cwd`` the real ingests use, so the path it
    reports is the path they will import. Returns it (recorded into
    ``run_meta.jsonl`` as proof of provenance). Raising here aborts the whole run
    before a single number is produced — a measurement against the wrong source
    is worse than no measurement, so the trap is a stop, not a warning.
    """
    proc = subprocess.run(
        [interpreter, "-c", "import depictio.cli, sys; sys.stdout.write(depictio.cli.__file__)"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    source = (proc.stdout or "").strip()
    if proc.returncode != 0 or not source:
        raise RuntimeError(
            f"benchmark: could not import depictio.cli via {interpreter!r} "
            f"(rc={proc.returncode}). --depictio-bin must be a Python interpreter "
            f"whose depictio is this worktree, not a bin/depictio console script.\n"
            f"  stderr: {(proc.stderr or '').strip()[-300:]}"
        )
    resolved = Path(source).resolve()
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        raise RuntimeError(
            "benchmark: depictio.cli resolves OUTSIDE this worktree — CLI changes "
            "would be silently ignored, so the run is aborted.\n"
            f"  resolved: {resolved}\n"
            f"  worktree: {_REPO_ROOT}\n"
            "Point --depictio-bin at an interpreter whose depictio is installed "
            "editable from this worktree (or run the benchmark from its venv)."
        )
    return str(resolved)


def _advanced_viz_columns(comp: dict) -> list[str]:
    """Columns to project for ``/advanced_viz/data``, read off the component.

    Taken from the component's own ``*_col`` bindings rather than a constant: the
    two generators name their feature identifier and categorical differently
    (``individual_id``/``species`` vs ``feature_id``/``feature_class``), and a
    hardcoded list quietly asks a collection for columns it doesn't have — the
    request still succeeds, so the projection ends up describing a payload the
    component never binds to.
    """
    config = comp.get("config") or {}
    columns: list[str] = []
    for k, v in config.items():
        if not v:
            continue
        # Multi-column roles (sunburst ``rank_cols``, sankey ``step_cols``) are
        # lists, not single ``*_col`` strings — miss them and the projection
        # drops the very columns those kinds hierarchy/flow on.
        if k.endswith("_cols") and isinstance(v, list):
            columns.extend(str(x) for x in v if x)
        elif k.endswith("_col") and isinstance(v, str):
            columns.append(v)
    # Keep the union volcano/ma bind to, so the payload size stays comparable
    # across viz kinds within a cell.
    for extra in ("mean_expression", "neg_log10_p", "effect_size"):
        if extra not in columns:
            columns.append(extra)
    # Dedupe, preserving first-seen order (a column can play two roles).
    return list(dict.fromkeys(columns))


def _advanced_viz_policy(comp: dict) -> dict:
    """The kind + role + threshold fields a renderer sends with its data request.

    ``/advanced_viz/data`` picks its reduction from these, so a harness that
    omitted them would time a path the viewer no longer takes: a uniform sample
    where the volcano/MA/manhattan components get a tail-preserving one. Mirrors
    what the corresponding renderers put in the body, built from the same
    component config the dashboard was generated with.

    Every kind gets ``viz_kind`` — that alone lets the server pick the ``hash``
    (qq/lollipop) or ``none`` (da_barplot/sunburst/sankey/stacked_taxonomy/
    dot_plot) policy. Only the three ``tail`` kinds additionally need
    ``roles``/``tail`` so the server knows which column's significant end to
    keep; a tail kind with no branch here would fall back to a uniform sample,
    which is a different measurement from the one its renderer produces.
    """
    config = comp.get("config") or {}
    viz_kind = str(comp.get("viz_kind") or config.get("viz_kind") or "")
    if not viz_kind:
        return {}

    payload: dict = {"viz_kind": viz_kind}
    if viz_kind == "volcano":
        sig = config.get("significance_col")
        payload["roles"] = {
            "feature_id": config.get("feature_id_col"),
            "effect_size": config.get("effect_size_col"),
            "significance": sig,
        }
        if sig:
            neg_log10 = bool(config.get("significance_is_neg_log10"))
            cutoff = float(config.get("significance_threshold") or 0.05)
            payload["tail"] = {
                "column": sig,
                "direction": "high" if neg_log10 else "low",
                "threshold": -math.log10(cutoff) if neg_log10 else cutoff,
            }
    elif viz_kind == "ma":
        fc = config.get("log2_fold_change_col")
        payload["roles"] = {
            "feature_id": config.get("feature_id_col"),
            "avg_log_intensity": config.get("avg_log_intensity_col"),
            "log2_fold_change": fc,
        }
        if fc:
            payload["tail"] = {
                "column": fc,
                "direction": "both",
                "threshold": float(config.get("fold_change_threshold") or 1.0),
            }
    elif viz_kind == "manhattan":
        score = config.get("score_col")
        payload["roles"] = {"score": score, "chr": config.get("chr_col")}
        if score:
            # The generator's score column is a −log10(p) (large = significant),
            # so the tail is the high end, at the conventional −log10(0.05) line.
            payload["tail"] = {
                "column": score,
                "direction": "high",
                "threshold": -math.log10(float(config.get("significance_threshold") or 0.05)),
            }
    return payload


# A heavy render is the *subject* of this benchmark, not an anomaly: at 1 GB/DC a
# cold table read is minutes, not seconds. The CLI's shared client defaults to
# httpx's 5 s, which turns every measurement above that into a ReadTimeout that
# aborts the whole matrix — so the harness owns its own client with a ceiling
# high enough that a timeout means "genuinely stuck", not "slow but interesting".
_BENCH_TIMEOUT = httpx.Timeout(900.0, connect=10.0)

# A resolved translation is materialised as a list and sent over HTTP before any
# data is touched, so its *size* is a property of the topology rather than of the
# machine. Past this many values the topology is the finding — the row is flagged
# so the report can label it instead of averaging it in with realistic ones.
_PATHOLOGICAL_VALUE_COUNT = 10_000

# ``fetchQueue.ts``'s DEFAULT_CONCURRENCY. The viewer never has more render
# fetches in flight than this, so a filter round fired with unbounded
# parallelism would measure a client that doesn't exist.
_VIEWER_FETCH_CONCURRENCY = 4

# Components whose render actually reads the filtered data. A MultiSelect's
# option list is served from the *unfiltered* source collection, so it answers
# almost instantly and says nothing about how long the filter took.
_DATA_BEARING_COMPONENTS = frozenset({"figure", "table", "advanced_viz", "card"})

# Successive filter rounds must apply *different* values (see
# ``configgen.FilterPlan``): re-applying one is answered by the filtered frame
# cache (``filtered_cache_key`` in deltatables_utils), which would measure the
# cache rather than the filter.


def _filter_payload(plan: FilterPlan, values: tuple[str, ...], dc_id: str) -> list[dict]:
    """One MultiSelect filter in the React payload shape.

    ``metadata.dc_id`` is what makes cross-DC resolution happen at all:
    ``_resolve_link_filters`` groups the incoming filters by their source DC and
    only walks the link graph for filters that belong to a *different* DC than
    the component being rendered. A filter sent without it is applied natively —
    and on the linked topology, where ``condition`` exists only on ``metadata``,
    it would then be dropped as an unknown column and the render would come back
    unfiltered.
    """
    return [
        {
            "index": f"bench-{plan.dc_tag}-{plan.column}",
            "column_name": plan.column,
            "value": list(values),
            "interactive_component_type": "MultiSelect",
            "metadata": {
                "dc_id": dc_id,
                "column_name": plan.column,
                "interactive_component_type": "MultiSelect",
            },
        }
    ]


def _dc_tag(comp: dict) -> str:
    """The data-collection tag a component renders from."""
    return str((comp.get("dc_config") or {}).get("data_collection_tag", ""))


def _dc_ids_by_tag(components: list[dict]) -> dict[str, str]:
    """Map data-collection tag -> DC id, read off the imported components."""
    out: dict[str, str] = {}
    for comp in components:
        tag = _dc_tag(comp)
        dc_id = str(comp.get("dc_id") or "")
        if tag and dc_id:
            out.setdefault(tag, dc_id)
    return out


def _render_row(
    cell: Cell,
    comp: dict,
    measurements: dict,
    *,
    server_mode: str,
    profile_label: str,
    **extra,
) -> dict:
    """One ``render`` result row: cell identity + component identity + measurements.

    Every render phase (sequential, cold open, filter round) emits the same
    shape and differs only in ``extra`` (``filtered``, ``concurrent``,
    ``iteration``, ``dc_first_touch``).
    """
    return {
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
            dc_tag=_dc_tag(comp),
            server_mode=server_mode,
            profile_label=profile_label,
            **extra,
            **measurements,
        ).to_dict(),
    }


def _api(base: str) -> str:
    return f"{base.rstrip('/')}/depictio/api/v1"


def _ingest(
    cell: Cell, cli_config_path: str, gen: GeneratedConfigs, interpreter: str
) -> tuple[float, str]:
    """Run ``depictio run`` for the generated project.

    Returns ``(wall_clock_ms, stdout)``. The stdout carries the CLI's
    ``DEPICTIO_INGEST_TIMINGS`` markers — without them an ingest row can only
    report one opaque wall-clock number, and a slow run cannot be attributed to
    parse / collect / write / upsert. See ``_aggregate_markers``.

    Raises ``subprocess.CalledProcessError`` on failure so the caller can record
    an error row and move on.
    """
    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            *_cli_argv(interpreter),
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
        cwd=_REPO_ROOT,
        # Opt into the per-phase marker lines `_aggregate_markers` parses.
        env={**os.environ, "DEPICTIO_INGEST_TIMINGS": "1"},
    )
    return (time.perf_counter() - t0) * 1000.0, proc.stdout or ""


def _project_id_by_name(client, base: str, headers: dict, project_name: str) -> str:
    """The project's id, or ``""`` if it doesn't exist / can't be read.

    ``get/from_name`` serialises the id as ``id``; other project endpoints return
    raw Mongo documents with ``_id``. Accept either so a response-shape change
    can't silently turn this into a no-op.
    """
    try:
        resp = client.get(
            f"{_api(base)}/projects/get/from_name/{quote(project_name, safe='')}",
            headers=headers,
        )
        if resp.status_code != 200:
            return ""
        body = resp.json() or {}
        return str(body.get("id") or body.get("_id") or "")
    except Exception as exc:
        print(f"  ! project lookup failed for {project_name!r}: {exc}")
        return ""


def _reset_project(client, base: str, headers: dict, project_name: str) -> bool:
    """Delete ``project_name`` if it exists, so the cell ingests from scratch.

    ``depictio run --overwrite`` overwrites the *config*, not the data: runs are
    upserted, so re-running a cell against a project that already exists ADDS its
    runs to the ones already there. A second pass over a 1 GB cell silently
    becomes a 2 GB one — the ingest then times out, and any measurement that did
    survive would describe a dataset twice the size the report claims.

    That failure is invisible without this: nothing errors, the row count just
    doubles. So the reset is unconditional rather than opt-in.

    Returns True if a project was deleted. Failures are logged and swallowed —
    a benchmark run must not be blocked by cleanup, and a missing project is the
    normal case on a first run.
    """
    project_id = _project_id_by_name(client, base, headers, project_name)
    if not project_id:
        return False
    try:
        # Cascade delete: dashboards, DCs, files, runs, deltatables + S3 objects.
        deleted = client.delete(
            f"{_api(base)}/projects/delete",
            params={"project_id": project_id},
            headers=headers,
        )
        if deleted.status_code != 200:
            print(f"  ! could not delete existing project {project_name!r}: {deleted.status_code}")
            return False
        print(f"  · removed existing project {project_name!r} so the cell starts clean")
        return True
    except Exception as exc:
        print(f"  ! project reset failed for {project_name!r}: {exc}")
        return False


@dataclass
class DatasetFacts:
    """What a cell's dataset contains, whichever generator produced it."""

    rows_per_dc: int
    rows_total: int
    # Distinct values of the join key. On the linked topology this is the sample
    # count (hundreds); on the symmetric one the key is unique per row, so it
    # equals the row count — which is what makes that dataset adversarial.
    join_key_cardinality: int
    rows_by_dc: dict[str, int] = field(default_factory=dict)
    summary: str = ""


def prepare_dataset(
    cell: Cell,
    output_root: Path,
    *,
    n_samples: int = DEFAULT_N_SAMPLES,
    force: bool = False,
) -> tuple[Path, DatasetFacts]:
    """Generate (or reuse) the dataset for a cell. Returns its dir and its facts.

    The single place that decides *which* generator a cell uses and *where* its
    data lives. ``bench generate`` and ``bench run`` both go through it: spelling
    the directory layout twice means a change to one makes the other regenerate
    tens of GB instead of reusing what is already on disk, silently.
    """
    if cell.connect is ConnectMode.LINKS:
        # Three collections at three grains, sharing a join key with hundreds of
        # distinct values.
        dataset_dir = output_root / "data" / f"linked_{cell.size}_s{n_samples}"
        linked = generate_linked_dataset(
            cell.size_bytes, dataset_dir, n_samples=n_samples, force=force
        )
        return dataset_dir, DatasetFacts(
            rows_per_dc=linked.rows_by_dc.get(FEATURES_TAG, 0),
            rows_total=linked.rows_total,
            join_key_cardinality=linked.n_samples,
            rows_by_dc=dict(linked.rows_by_dc),
            summary=(
                f"{linked.n_runs} runs, {linked.n_samples} samples "
                f"x {linked.features_per_sample} features"
            ),
        )

    dataset_dir = output_root / "data" / f"{cell.size}_dc{cell.n_dcs}"
    manifest = generate_dataset(cell.size_bytes, cell.n_dcs, dataset_dir, force=force)
    return dataset_dir, DatasetFacts(
        rows_per_dc=manifest.rows_total,
        rows_total=manifest.rows_total * cell.n_dcs,
        join_key_cardinality=manifest.rows_total,
        summary=f"{manifest.n_runs} runs, {manifest.rows_total} rows/DC",
    )


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
                # Deliberately no ``limit_rows``: an explicit cap puts the
                # endpoint on its "caller asked for exactly N rows" branch, which
                # skips sampling entirely. The React renderers don't send one
                # (``fetchAdvancedVizData`` leaves it undefined), so passing
                # 100_000 here measured a code path no user ever hits — and hid
                # the endpoint's actual reduction behaviour from the benchmark.
                json={
                    "wf_id": str(comp.get("wf_id")),
                    "dc_id": str(comp.get("dc_id")),
                    "columns": _advanced_viz_columns(comp),
                    "filter_metadata": filters,
                    # Same reasoning as the omitted ``limit_rows``: the kind
                    # selects the server's reduction policy, so a payload
                    # without one measures the uniform-sample path that no
                    # renderer takes any more.
                    **_advanced_viz_policy(comp),
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
        "sampling_policy": resp.headers.get("X-Sampling-Policy", ""),
        "cache": resp.headers.get("X-Cache", ""),
        "peak_rss_mb": _hdr_float("X-Peak-RSS-MB"),
        # How much cross-DC translation this render carried (absent on endpoints
        # that don't resolve links, and on unfiltered renders).
        "link_values": _hdr_int("X-Link-Values"),
        "link_hops": _hdr_int("X-Link-Hops"),
        "error": "" if resp.status_code == 200 else resp.text[:300],
    }


def _dashboard_load(
    client, base: str, headers: dict, dashboard_id: str, components: list[dict]
) -> tuple[list[tuple[dict, dict, float]], float]:
    """Fire every component at once, as opening the dashboard does.

    Sequential rendering measures one component on an idle server; a real cold
    open puts all of them in flight together, so the answer to "does a heavy
    dashboard hold up" lives in the contention this creates — worker-pool
    saturation, connection-pool queueing, memory pressure from concurrent Delta
    reads. Returns the per-component metrics plus the wall-clock to the *last*
    one, which is what the user actually waits for.

    Each row also carries when that component *landed*, measured from the same
    ``t0`` every request was fired at. The last one is the wait; the first one
    is when the page stops being empty, and the two are far apart on a dense
    dashboard. Without the offsets neither can be recovered afterwards — a
    component's own duration says how long it took, not when it finished.
    """
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.perf_counter()

    def _one(comp: dict) -> tuple[dict, dict, float]:
        m = _render_component(client, base, headers, dashboard_id, comp, [])
        return comp, m, (time.perf_counter() - t0) * 1000.0

    with ThreadPoolExecutor(max_workers=max(1, len(components))) as pool:
        results = list(pool.map(_one, components))
    return results, (time.perf_counter() - t0) * 1000.0


def _dashboard_load_rows(
    cell,
    loaded: list[tuple[dict, dict, float]],
    total_ms: float,
    *,
    server_mode: str,
    profile_label: str,
    cache_state: str,
    dataset_first_open: bool = True,
) -> list[dict]:
    """The per-component rows plus the summary row for one concurrent open.

    ``cache_state`` is ``"cold"`` (first open, server caches empty for this
    dashboard) or ``"warm"`` (every DC already touched). Both are emitted under
    the same ``kind`` so a reader compares like with like; the phase carries
    the distinction.

    ``dataset_first_open`` is ``False`` when an earlier cell in the same run
    already opened this dataset — its caches are then populated and the "cold"
    number is really a warm one. Recorded rather than suppressed so the reader
    can see which cold figures to trust.
    """
    phase = "dashboard_load_cold" if cache_state == "cold" else "dashboard_load"
    # Passive components (text, …) return no metrics; counting them as
    # "requested" would report a complete load as partial.
    n_timed = sum(1 for _, m, _ in loaded if m)
    n_ok = 0
    rows: list[dict] = []
    for comp, m, offset in loaded:
        if not m:
            continue
        n_ok += bool(m.get("ok"))
        row = _render_row(
            cell,
            comp,
            m,
            server_mode=server_mode,
            profile_label=profile_label,
            concurrent=True,
            phase=phase,
        )
        # When this component landed, from the instant every request was fired.
        # Distinct from its own ``wall_ms``, which is a duration.
        row["completed_at_ms"] = offset
        rows.append(row)

    # Only components that actually succeeded count as "rendered": a failure
    # returns fast and would otherwise take the crown for first paint.
    landed = [
        (comp, offset) for comp, m, offset in loaded if m and m.get("ok") and offset is not None
    ]
    first_any = min(
        (off for comp, off in landed if comp.get("component_type") in _DATA_BEARING_COMPONENTS),
        default=None,
    )
    # "First figure" is the first *plot* — a Plotly figure or an advanced viz.
    # Cards and tables land far sooner and are not what a reader pictures when
    # they hear that a chart appeared.
    first_figure = min(
        (off for comp, off in landed if comp.get("component_type") in ("figure", "advanced_viz")),
        default=None,
    )
    rows.append(
        {
            "kind": "dashboard_load",
            "cell_slug": cell.slug,
            "size": cell.size,
            "n_components": cell.n_components,
            "n_dcs": cell.n_dcs,
            "connect": cell.connect.value,
            "server_mode": server_mode,
            # Without this the row is dropped by the report's profile scoping,
            # which silently removed the whole dashboard-open table.
            "profile_label": profile_label,
            "cache_state": cache_state,
            "dataset_first_open": dataset_first_open,
            # The three moments a reader cares about: when the page stops being
            # empty, when the first chart is there, and when it is all done.
            "time_to_first_ms": first_any,
            "time_to_first_figure_ms": first_figure,
            "wall_ms": total_ms,
            "n_rendered": n_ok,
            "n_requested": n_timed,
            "ok": n_ok == n_timed,
        }
    )
    return rows


def _filter_round(
    client,
    base: str,
    headers: dict,
    dashboard_id: str,
    components: list[dict],
    filters: list[dict],
    concurrency: int = _VIEWER_FETCH_CONCURRENCY,
) -> tuple[list[tuple[dict, dict, float]], float, float]:
    """Apply one filter change and time every component catching up.

    Models the viewer's behaviour rather than the server's capacity: the React
    client bounds in-flight render fetches to ``fetchQueue.ts``'s limit, so this
    fires the components through a pool of the same width. Firing all N at once
    would measure a client that doesn't exist and would understate the queueing
    that makes a filter change feel slow.

    Returns ``(rows, time_to_first_ms, time_to_last_ms)`` where each row is
    ``(component, metrics, completed_at_ms)``. Components that aren't timed
    renders (text, RangeSliders) return empty metrics and are excluded from the
    first/last window — counting them would report a round as complete before
    the components the user is looking at had answered.

    The window covers **data-bearing** renders only. A MultiSelect's option list
    (``/deltatables/unique_values``) ignores filters entirely and, on a small
    source collection, always returns in a few milliseconds — it would set
    ``time_to_first_ms`` every single round, and the number would describe an
    unfiltered option fetch rather than the dashboard starting to answer.
    """
    from concurrent.futures import ThreadPoolExecutor

    t0 = time.perf_counter()

    def _one(comp: dict) -> tuple[dict, dict, float]:
        m = _render_component(client, base, headers, dashboard_id, comp, filters)
        return comp, m, (time.perf_counter() - t0) * 1000.0

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        rows = list(pool.map(_one, components))

    offsets = [
        off for comp, m, off in rows if m and comp.get("component_type") in _DATA_BEARING_COMPONENTS
    ]
    if not offsets:
        return rows, 0.0, 0.0
    return rows, min(offsets), max(offsets)


def _resolve_once(
    client,
    base: str,
    headers: dict,
    project_id: str,
    source_dc_id: str,
    source_column: str,
    values: list,
    target_dc_id: str,
) -> tuple[list, float, str]:
    """One hop through ``POST /links/{project}/resolve``. Returns (values, ms, error)."""
    t0 = time.perf_counter()
    try:
        resp = client.post(
            f"{_api(base)}/links/{project_id}/resolve",
            json={
                "source_dc_id": source_dc_id,
                "source_column": source_column,
                "filter_values": values,
                "target_dc_id": target_dc_id,
            },
            headers=headers,
        )
    except httpx.HTTPError as exc:
        return [], (time.perf_counter() - t0) * 1000.0, f"{type(exc).__name__}: {exc}"[:200]
    ms = (time.perf_counter() - t0) * 1000.0
    if resp.status_code != 200:
        return [], ms, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return list(resp.json().get("resolved_values") or []), ms, ""


def _probe_links(
    client,
    base: str,
    headers: dict,
    cell: Cell,
    project_id: str,
    dc_ids: dict[str, str],
    plan: FilterPlan,
    values: tuple[str, ...],
    pathological_above: int = _PATHOLOGICAL_VALUE_COUNT,
) -> list[LinkResolutionResult]:
    """Measure how many values each link translation produces, route by route.

    This is the check the whole realistic-dataset exercise exists for. On a
    topology whose join key has hundreds of distinct values, translating a
    filter yields hundreds; on the adversarial dataset (join key unique per row)
    the same translation yields millions, which is then serialised into an HTTP
    payload. Recording the count per route is what tells the two apart in the
    report instead of leaving it to be inferred from a latency figure.

    Routes probed on the linked topology: both of ``metadata``'s links (1 hop)
    plus the ``metadata -> metrics -> features`` chain, walked hop by hop the way
    ``filter_links._walk_link_path`` walks it — the second hop's input is the
    first hop's output. On the adversarial topology there is one route per
    linked DC, and measuring it is the point: that is where the millions show up.
    """
    results: list[LinkResolutionResult] = []
    if not cell.connect.is_links or plan.dc_tag not in (METADATA_TAG, "dc_0"):
        return results

    def _record(source: str, target: str, hops: int, sent: list, got: list, ms: float, err: str):
        results.append(
            LinkResolutionResult(
                cell_slug=cell.slug,
                connect=cell.connect.value,
                source_tag=source,
                target_tag=target,
                hops=hops,
                filter_column=plan.column,
                filter_values=list(values),
                n_source_values=len(sent),
                n_resolved_values=len(got),
                wall_ms=ms,
                ok=not err,
                pathological=len(got) > pathological_above,
                error=err,
            )
        )

    if cell.connect is ConnectMode.LINKS_ADVERSARIAL:
        # One route per linked DC, all from dc_0. No chain: the adversarial
        # project declares a star, and the interesting number is the size of a
        # single translation.
        for target in [f"dc_{i}" for i in range(1, cell.n_dcs)]:
            # A DC no component binds to has no id here (ids are read off the
            # imported dashboard) — nothing to probe, and inventing one would
            # measure a route the dashboard never uses.
            if target not in dc_ids or plan.dc_tag not in dc_ids:
                continue
            got, ms, err = _resolve_once(
                client,
                base,
                headers,
                project_id,
                dc_ids[plan.dc_tag],
                plan.column,
                list(values),
                dc_ids[target],
            )
            _record(plan.dc_tag, target, 1, list(values), got, ms, err)
        return results

    # One hop from metadata to each of its two targets. The source column is the
    # user's filter column; the endpoint translates it to the join column against
    # the source DC. metrics is also the first leg of the 2-hop chain below.
    if METADATA_TAG not in dc_ids:
        return results
    one_hop: dict[str, tuple[list, float, str]] = {}
    for target in (METRICS_TAG, FEATURES_TAG):
        if target not in dc_ids:
            continue
        one_hop[target] = _resolve_once(
            client,
            base,
            headers,
            project_id,
            dc_ids[METADATA_TAG],
            plan.column,
            list(values),
            dc_ids[target],
        )
        got, ms, err = one_hop[target]
        _record(METADATA_TAG, target, 1, list(values), got, ms, err)

    # Hop 2: metrics -> features, fed by the metadata -> metrics output — the
    # chain, walked the way filter_links._walk_link_path walks it.
    if METRICS_TAG not in one_hop or FEATURES_TAG not in dc_ids:
        return results
    hop1, ms1, err1 = one_hop[METRICS_TAG]
    if err1:
        return results
    chained, ms2, err2 = _resolve_once(
        client,
        base,
        headers,
        project_id,
        dc_ids[METRICS_TAG],
        JOIN_COLUMN,
        hop1,
        dc_ids[FEATURES_TAG],
    )
    # Recorded as metadata -> features so it lines up with the direct route to
    # the same target: same origin, same destination, one hop more. ``in`` stays
    # the user's filter values (what the chain started from) and the wall covers
    # both hops.
    _record(METADATA_TAG, FEATURES_TAG, 2, list(values), chained, ms1 + ms2, err2)
    return results


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
    filter_rounds: int = 0,
    depictio_bin: str = "",
    n_samples: int = DEFAULT_N_SAMPLES,
    profile: dict | None = None,
    reuse_ingest: bool = False,
) -> Path:
    """Run every cell and append results to ``<output_root>/results.jsonl``.

    Returns the results path. Datasets are cached by ``(size, n_dcs)`` so
    connect/visu variants of the same size reuse the generated CSVs.

    ``n_samples`` is the join-key cardinality of the linked topology — the axis
    that must NOT scale with the size tier. ``profile`` is the hardware profile
    every emitted row is stamped with (see :mod:`benchmark.profile`).

    ``reuse_ingest`` re-imports the dashboard against the project already in the
    database and skips both the reset and the ingest — for iterating on the
    dashboard (layout, component mix, filter origins) without paying to rebuild
    data that hasn't changed. It is opt-in because the reset is what stops a
    re-run from ingesting on top of itself; when the project is absent the cell
    falls back to a full ingest rather than measuring an empty dashboard.
    """
    # Lazy imports: keep this module importable without the full depictio stack.
    from depictio.cli.cli.utils.common import (
        generate_api_headers,
        load_depictio_config,
    )

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"

    # Resolve + verify the CLI *before* any ingest: a mis-resolved CLI silently
    # measures the wrong source (see _cli_argv / _verify_cli_source). Empty means
    # "the interpreter running this benchmark", which is the worktree venv.
    interpreter = depictio_bin or sys.executable
    cli_source = _verify_cli_source(interpreter)
    print(f"  · depictio CLI: {cli_source}")

    cli_config = load_depictio_config(cli_config_path)
    base = str(cli_config.api_base_url)
    headers = generate_api_headers(cli_config)
    # Own client, not the CLI's shared singleton: see _BENCH_TIMEOUT.
    client = httpx.Client(timeout=_BENCH_TIMEOUT)

    celery_health = _get_celery_health(client, base, headers)
    profile = profile or {}
    profile_label = str(profile.get("label") or "")
    if profile:
        write_profile(output_root, profile)

    with results_path.open("a", encoding="utf-8") as sink:

        def emit(row: dict) -> None:
            sink.write(json.dumps(row) + "\n")
            sink.flush()

        # Which datasets some earlier cell in this run has already opened. Cells
        # that differ only in component count share one ingested project (see
        # ``dataset_slug``), so the second one's "cold" open finds every
        # server-side cache already populated by the first. Recording it is what
        # keeps the cold column readable instead of quietly wrong.
        opened_datasets: set[str] = set()

        for cell in cells:
            dataset_dir, facts = prepare_dataset(
                cell, output_root, n_samples=n_samples, force=force_datagen
            )
            # n_samples is part of the project identity for the linked topology:
            # a different join-key cardinality is a different dataset.
            gen = write_configs(
                cell, dataset_dir, output_root / "configs" / cell.slug, n_samples=n_samples
            )
            input_bytes = _dir_csv_bytes(dataset_dir)

            # ── Ingest + import ──────────────────────────────────────────────
            # Wipe any project left by an earlier pass over this cell first:
            # runs are upserted, not replaced, so re-running would ingest on top
            # of the previous data and quietly double the dataset.
            reused = reuse_ingest and bool(
                _project_id_by_name(client, base, headers, gen.project_name)
            )
            if reuse_ingest and not reused:
                print(
                    f"  ! --reuse-ingest asked for, but project {gen.project_name!r} "
                    "does not exist yet — ingesting it once"
                )
            if not reused:
                _reset_project(client, base, headers, gen.project_name)
            try:
                if reused:
                    ingest_ms, ingest_stdout = 0.0, ""
                else:
                    ingest_ms, ingest_stdout = _ingest(cell, cli_config_path, gen, interpreter)
                if reused:
                    print(f"  · reusing the ingested data of {gen.project_name!r}")
                dashboard_id, import_ms = _import_dashboard(client, base, headers, gen)
            except subprocess.CalledProcessError as exc:
                emit(_ingest_error_row(cell, server_mode, f"ingest failed: {exc.stderr[:300]}"))
                continue
            except Exception as exc:  # import/network failure
                emit(_ingest_error_row(cell, server_mode, f"import failed: {exc}"))
                continue

            # ── Render each component ────────────────────────────────────────
            components = _get_components(client, base, headers, dashboard_id)

            # Per-phase attribution from the CLI's timing markers. Without it an
            # ingest row is a single wall-clock number that cannot be split into
            # parse / collect / write / upsert.
            #
            # ``delta_bytes`` is dropped: the markers only see the DCs this
            # process wrote, while ``_project_delta_bytes`` below asks the API
            # for the whole project, which is the figure the throughput columns
            # are computed from.
            ingest_markers = _aggregate_markers(ingest_stdout) if ingest_stdout else {}
            ingest_markers.pop("delta_bytes", None)

            ingest_res = IngestResult(
                cell_slug=cell.slug,
                ingest_wall_ms=ingest_ms,
                import_wall_ms=import_ms,
                ok=True,
                dashboard_id=dashboard_id,
                n_dcs=cell.n_dcs,
                rows_per_dc=facts.rows_per_dc,
                rows_total=facts.rows_total,
                input_bytes=input_bytes,
                delta_bytes=_project_delta_bytes(client, base, headers, dashboard_id),
                profile_label=profile_label,
                join_key_cardinality=facts.join_key_cardinality,
                rows_by_dc=facts.rows_by_dc,
                # When reused, nothing was ingested, so there is no ingest timing
                # to report — the row still carries the dataset shape the renders
                # ran against.
                reused=reused,
                **ingest_markers,
            )
            emit({"kind": "ingest", "server_mode": server_mode, **vars(ingest_res)})

            dc_ids = _dc_ids_by_tag(components)

            # Cold open — *before* anything else touches these DCs. The
            # sequential passes below populate every server-side cache
            # (row counts, aggregation results, link resolution), so the
            # existing dashboard_load at the end of the cell can only ever
            # report a warm number. Running the same concurrent open here too
            # is what makes "first visit" and "revisit" comparable: same work,
            # same concurrency, only the cache state differs.
            #
            # Cold means *server process caches are empty for this dashboard*.
            # The Delta files may still sit in the OS page cache or MinIO's,
            # so this is a lower bound on a truly cold machine.
            if dashboard_load:
                slug = dataset_slug(cell, n_samples)
                first_open = slug not in opened_datasets
                opened_datasets.add(slug)
                cold_loaded, cold_ms = _dashboard_load(
                    client, base, headers, dashboard_id, components
                )
                for row in _dashboard_load_rows(
                    cell,
                    cold_loaded,
                    cold_ms,
                    server_mode=server_mode,
                    profile_label=profile_label,
                    cache_state="cold",
                    dataset_first_open=first_open,
                ):
                    emit(row)

            plans = filter_plans(cell)
            passes: list[tuple[bool, list[dict]]] = [(False, [])]
            if cross_filter and cell.connect.is_links:
                # Sequential filtered pass, using the cell's own filter origin
                # (species on the adversarial dataset, condition on the linked
                # one) rather than a hardcoded column that may not exist.
                plan = plans[0]
                origin_id = dc_ids.get(plan.dc_tag, "")
                if origin_id:
                    # A value reserved for this pass. Reusing a round's value
                    # here would leave the filtered frame cache warm for it, and
                    # that round would then time the cache.
                    passes.append((True, _filter_payload(plan, plan.sequential_value, origin_id)))

            touched_dcs: set[str] = set()
            for filtered, filt in passes:
                for iteration in range(max(1, repeats)):
                    for comp in components:
                        m = _render_component(client, base, headers, dashboard_id, comp, filt)
                        if not m:
                            continue
                        dc_tag = _dc_tag(comp)
                        first_touch = dc_tag not in touched_dcs
                        touched_dcs.add(dc_tag)
                        emit(
                            _render_row(
                                cell,
                                comp,
                                m,
                                server_mode=server_mode,
                                profile_label=profile_label,
                                filtered=filtered,
                                dc_first_touch=first_touch,
                                iteration=iteration,
                            )
                        )

            if dashboard_load:
                loaded, total_ms = _dashboard_load(client, base, headers, dashboard_id, components)
                for row in _dashboard_load_rows(
                    cell,
                    loaded,
                    total_ms,
                    server_mode=server_mode,
                    profile_label=profile_label,
                    cache_state="warm",
                ):
                    emit(row)

            # ── Filter rounds ────────────────────────────────────────────────
            # Deliberately last: the passes above have already touched every DC,
            # so this measures a filter change on a *warm, already-open*
            # dashboard — the situation a user is actually in when they move a
            # filter. Running it cold would fold the first Delta read into the
            # number and describe an event that only happens once.
            # One sweep of rounds per filter *origin*: on the linked topology a
            # filter on ``metadata`` must be translated across one or two links
            # before ``features`` can be narrowed, while a filter on ``features``
            # applies natively. They are different mechanisms and are reported
            # apart.
            for plan in plans if filter_rounds > 0 else []:
                origin_dc_id = dc_ids.get(plan.dc_tag, "")
                if not origin_dc_id:
                    print(f"  ! no DC id for filter origin {plan.dc_tag!r} — skipping its rounds")
                    continue
                # Hard cap: each round must apply a value no earlier round used,
                # or the filtered frame cache answers it and the round times the
                # cache instead of the filter.
                # How much of the dashboard this origin can actually narrow.
                # Constant across the sweep, so computed once.
                n_affected = sum(
                    1
                    for comp in components
                    if comp.get("component_type") in _DATA_BEARING_COMPONENTS
                    and _dc_tag(comp) in plan.reachable_tags
                )
                n_rounds = min(filter_rounds, plan.max_rounds)
                if n_rounds < filter_rounds:
                    print(
                        f"  ! {plan.label}: {filter_rounds} rounds requested but only "
                        f"{plan.max_rounds} distinct values exist — running {n_rounds}"
                    )
                for round_index in range(n_rounds):
                    values = plan.values[round_index]
                    filt = _filter_payload(plan, values, origin_dc_id)

                    # What each translation actually costs in *values*, measured
                    # against the resolve endpoint directly. Hundreds is the
                    # realistic topology; millions means the dataset is wrong.
                    for probe in _probe_links(
                        client,
                        base,
                        headers,
                        cell,
                        gen.project_id,
                        dc_ids,
                        plan,
                        values,
                    ):
                        probe.server_mode = server_mode
                        probe.profile_label = profile_label
                        emit({"kind": "link_resolution", **probe.to_dict()})

                    rows, first_ms, last_ms = _filter_round(
                        client, base, headers, dashboard_id, components, filt
                    )
                    n_timed = sum(1 for _, m, _ in rows if m)
                    n_ok = 0
                    for comp, m, _offset in rows:
                        if not m:
                            continue
                        n_ok += bool(m.get("ok"))
                        emit(
                            _render_row(
                                cell,
                                comp,
                                m,
                                server_mode=server_mode,
                                profile_label=profile_label,
                                filtered=True,
                                concurrent=True,
                                phase="filter_round",
                                filter_dc_tag=plan.dc_tag,
                                hops=plan.hops,
                                iteration=round_index,
                            )
                        )
                    emit(
                        {
                            "kind": "filter_round",
                            **FilterRoundResult(
                                cell_slug=cell.slug,
                                size=cell.size,
                                size_bytes=cell.size_bytes,
                                n_components=cell.n_components,
                                n_dcs=cell.n_dcs,
                                connect=cell.connect.value,
                                server_mode=server_mode,
                                round_index=round_index,
                                filter_column=plan.column,
                                filter_values=list(values),
                                concurrency=_VIEWER_FETCH_CONCURRENCY,
                                n_fired=n_timed,
                                n_ok=n_ok,
                                time_to_first_ms=first_ms,
                                time_to_last_ms=last_ms,
                                ok=n_timed > 0 and n_ok == n_timed,
                                filter_dc_tag=plan.dc_tag,
                                hops=plan.hops,
                                n_affected=n_affected,
                                profile_label=profile_label,
                            ).to_dict(),
                        }
                    )

    client.close()
    _stamp_run_meta(output_root, server_mode, celery_health, profile, cli_source=cli_source)
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


def _run_cli_capture(args: list[str], cwd: str | Path | None = None) -> tuple[int, str, str, float]:
    """Run a depictio CLI subprocess, returning (rc, stdout, stderr, wall_ms)."""
    t0 = time.perf_counter()
    # Per-phase markers are opt-in on the CLI side so ordinary runs stay quiet;
    # `_aggregate_markers` below needs them, so turn them on for this subprocess.
    env = {**os.environ, "DEPICTIO_INGEST_TIMINGS": "1"}
    proc = subprocess.run(args, capture_output=True, text=True, cwd=cwd, env=env)
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
    depictio_bin: str = "",
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

    # Same guard as run_matrix: fail before the first ingest if the CLI resolves
    # outside this worktree (see _cli_argv / _verify_cli_source).
    interpreter = depictio_bin or sys.executable
    cli_source = _verify_cli_source(interpreter)
    print(f"  · depictio CLI: {cli_source}")

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
                *_cli_argv(interpreter),
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
            rc, out, err, wall_ms = _run_cli_capture(run_args, cwd=_REPO_ROOT)
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
                        *_cli_argv(interpreter),
                        "images",
                        "push",
                        images_dir,
                        gen.s3_base_folder,
                        "--CLI-config-path",
                        cli_config_path,
                        "--overwrite",
                    ],
                    cwd=_REPO_ROOT,
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


def _stamp_run_meta(
    output_root: Path,
    server_mode: str,
    celery_health: dict,
    profile: dict | None = None,
    cli_source: str = "",
) -> None:
    """Record the server config + hardware profile for this matrix half.

    ``argv`` is recorded too, so a results file says how it was produced. Which
    dimensions a run covered — and in particular whether ``--filter-rounds``
    was non-zero — is otherwise only inferable from which row *kinds* happen to
    be absent, which is exactly the ambiguity that made an earlier baseline
    with no ``filter_round`` rows hard to interpret.

    ``cli_source`` is the verified ``depictio.cli.__file__`` the ingests ran
    against (see ``_verify_cli_source``): proof, in the results file itself, that
    a CLI change under test was actually the code measured — the trap that
    otherwise fails silently.
    """
    meta_path = output_root / "run_meta.jsonl"
    with meta_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "server_mode": server_mode,
                    "celery_health": celery_health,
                    "profile": profile or {},
                    "argv": sys.argv,
                    "cwd": os.getcwd(),
                    "cli_source": cli_source,
                }
            )
            + "\n"
        )


# Convenience re-export used by the pytest so it doesn't import the runner's
# depictio dependencies transitively.
__all__ = ["run_matrix", "VisuType"]
