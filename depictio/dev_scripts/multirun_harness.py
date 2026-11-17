"""Non-regression harness for multi-run template ingestion (epic #1399).

Black box: it drives the real ``depictio`` CLI against an isolated
``depictio local up`` stack, then reads back every data collection of the
ingested project and records, per collection tag:

* the ordered columns with their dtypes, row count and a content digest, all
  computed WITHOUT ``depictio_run_id`` and ``aggregation_time``;
* separately, the ``depictio_run_id`` values and the column's position;
* the Delta version count, so a no-op commit shows up;
* for MultiQC, a digest of every report parquet; for geojson/phylogeny, the
  sha256 of the stored blob.

``compare`` then demands that a single-run ingestion is unchanged except for
``depictio_run_id`` (added, re-valued or moved), which it lists apart.

Usage (from the repository root, in an env with the ``local`` extra)::

    H=/tmp/depictio-harness
    python depictio/dev_scripts/multirun_harness.py up --local-home $H
    python depictio/dev_scripts/multirun_harness.py record ampliseq-trec \\
        --local-home $H --out $H/baseline
    python depictio/dev_scripts/multirun_harness.py compare \\
        $H/baseline/ampliseq-trec.json $H/current/ampliseq-trec.json
    python depictio/dev_scripts/multirun_harness.py multirun ampliseq-trec \\
        --local-home $H --out $H/multirun
    python depictio/dev_scripts/multirun_harness.py down --local-home $H

The stack is started with telemetry off and no example projects.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

RUN_ID_COLUMN = "depictio_run_id"
VOLATILE_COLUMNS = {RUN_ID_COLUMN, "aggregation_time"}
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = Path(__file__).with_name("multirun_harness_cases.yaml")
BUCKET = "depictio-bucket"


# ---------------------------------------------------------------------------
# Stack and CLI
# ---------------------------------------------------------------------------


def _env(local_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["DEPICTIO_LOCAL_HOME"] = str(local_home)
    env["DO_NOT_TRACK"] = "1"
    env["DEPICTIO_TELEMETRY_ENABLED"] = "false"
    return env


def _depictio(args: list[str], local_home: Path, log: Path | None = None) -> int:
    entry = (
        "import sys; from depictio.cli.depictio_cli import main; sys.argv[0] = 'depictio'; main()"
    )
    cmd = [sys.executable, "-c", entry, *args]
    print(f"$ depictio {' '.join(args)}", flush=True)
    if log is None:
        return subprocess.call(cmd, env=_env(local_home), cwd=REPO_ROOT)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        fh.write(f"\n$ depictio {' '.join(args)}\n")
        fh.flush()
        return subprocess.call(
            cmd, env=_env(local_home), cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT
        )


def _port_busy(port: int) -> bool:
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True
    )
    return bool(out.stdout.strip())


def _state(local_home: Path) -> dict[str, Any]:
    path = local_home / "state.json"
    if not path.is_file():
        sys.exit(f"No running stack under {local_home}: run `up` first.")
    return json.loads(path.read_text())


def _cli_config_path(local_home: Path) -> Path:
    found = sorted((local_home / "cli").glob("*_config.yaml"))
    if not found:
        sys.exit(f"No CLI configuration under {local_home / 'cli'}.")
    return found[0]


def cmd_up(ns: argparse.Namespace) -> int:
    home: Path = ns.local_home
    if ns.fresh and home.exists():
        if (home / "state.json").is_file():
            _depictio(["local", "down"], home)
        shutil.rmtree(home)
    if ns.port is not None and _port_busy(ns.port):
        sys.exit(f"Port {ns.port} is already in use (lsof).")
    args = ["local", "up", "--no-open", "--examples", "none", "--no-screenshots"]
    if ns.port is not None:
        args += ["--port", str(ns.port)]
    for root in ns.data_root_allow or []:
        args += ["--data-root-allow", str(root)]
    return _depictio(args, home)


def cmd_down(ns: argparse.Namespace) -> int:
    return _depictio(["local", "down"], ns.local_home)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _load_case(path: Path, name: str) -> dict[str, Any]:
    cases = (yaml.safe_load(path.read_text()) or {}).get("cases", {})
    if name not in cases:
        sys.exit(f"Unknown case {name!r}; known: {', '.join(sorted(cases))}")
    case = dict(cases[name])
    runs = []
    for raw in case.get("runs", []):
        p = Path(os.path.expanduser(raw))
        runs.append(p if p.is_absolute() else (REPO_ROOT / p))
    case["runs"] = runs
    return case


def _ingest(
    case: dict[str, Any],
    data_root: Path,
    project: str,
    local_home: Path,
    log: Path,
    extra: list[str],
) -> dict[str, Any]:
    if not data_root.exists():
        sys.exit(f"Data root {data_root} does not exist.")
    result = log.with_suffix(f".{int(time.time() * 1000)}.result.json")
    args = [
        "ingest",
        str(data_root),
        "--template",
        case["template"],
        "--project",
        project,
        "--server",
        str(_cli_config_path(local_home)),
        "--result-json",
        str(result),
    ]
    for key, value in (case.get("vars") or {}).items():
        args += ["--var", f"{key}={value}"]
    args += extra
    code = _depictio(args, local_home, log)
    outcome = json.loads(result.read_text()) if result.is_file() else {}
    outcome["exit_code"] = code
    if code != 0:
        print(f"  ingest exited {code}; log: {log}", file=sys.stderr)
    return outcome


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _storage(local_home: Path) -> tuple[dict[str, str], dict[str, Any]]:
    config = yaml.safe_load(_cli_config_path(local_home).read_text()) or {}
    s3 = config.get("s3_storage") or config.get("s3") or config.get("minio") or {}
    port = _state(local_home)["ports"]["s3"]
    endpoint = f"http://127.0.0.1:{port}"
    key = s3.get("root_user") or s3.get("access_key") or s3.get("aws_access_key_id")
    secret = s3.get("root_password") or s3.get("secret_key") or s3.get("aws_secret_access_key")
    opts = {
        "AWS_ENDPOINT_URL": endpoint,
        "AWS_ACCESS_KEY_ID": str(key),
        "AWS_SECRET_ACCESS_KEY": str(secret),
        "AWS_REGION": "us-east-1",
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }
    boto = {
        "endpoint_url": endpoint,
        "aws_access_key_id": str(key),
        "aws_secret_access_key": str(secret),
        "region_name": "us-east-1",
    }
    return opts, boto


def frame_digest(df: Any) -> str:
    """Order-insensitive digest of a frame without the volatile columns.

    Mirrors ``content_digest`` of #1398: sorted columns, floats rounded to 10
    significant figures, row hashes sorted. Nested dtypes fall back to a JSON
    rendering of each row.
    """
    import polars as pl

    cols = sorted(c for c in df.columns if c not in VOLATILE_COLUMNS)
    if not cols:
        return hashlib.sha256(f"rows:{df.height}".encode()).hexdigest()
    projected = df.select(
        pl.col(c).round_sig_figs(10) if df.schema[c].is_float() else pl.col(c) for c in cols
    )
    schema = "|".join(f"{c}:{df.schema[c]}" for c in cols)
    try:
        rows = projected.hash_rows(seed=0).sort().to_numpy().tobytes()
    except Exception:
        lines = sorted(
            json.dumps(r, default=str, sort_keys=True) for r in projected.iter_rows(named=True)
        )
        rows = "\n".join(lines).encode()
    return hashlib.sha256(schema.encode() + rows).hexdigest()


def _delta_record(uri: str, opts: dict[str, str]) -> dict[str, Any]:
    import polars as pl
    from deltalake import DeltaTable

    table = DeltaTable(uri, storage_options=opts)
    df = pl.from_arrow(table.to_pyarrow_table())
    assert isinstance(df, pl.DataFrame)
    columns = [f"{c}:{df.schema[c]}" for c in df.columns if c not in VOLATILE_COLUMNS]
    record: dict[str, Any] = {
        "storage": "delta",
        "columns": columns,
        "rows": df.height,
        "digest": frame_digest(df),
        "delta_version": table.version(),
        "partition_columns": list(table.metadata().partition_columns),
    }
    if RUN_ID_COLUMN in df.columns:
        record["run_ids"] = sorted(str(v) for v in df.get_column(RUN_ID_COLUMN).unique().to_list())
        record["run_id_position"] = df.columns.index(RUN_ID_COLUMN)
        record["rows_per_run"] = {
            str(r[RUN_ID_COLUMN]): r["len"]
            for r in df.group_by(RUN_ID_COLUMN).len().iter_rows(named=True)
        }
    return record


def _s3_client(boto: dict[str, Any]) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client("s3", config=Config(s3={"addressing_style": "path"}), **boto)


def _blob_record(boto: dict[str, Any], key: str) -> dict[str, Any]:
    client = _s3_client(boto)
    try:
        body = client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001 - recorded, compared as a value
        return {"storage": "blob", "key": key, "error": type(exc).__name__}
    return {"storage": "blob", "key": key, "sha256": hashlib.sha256(body).hexdigest()}


def _multiqc_record(db: Any, dc_id: str, boto: dict[str, Any]) -> dict[str, Any]:
    import polars as pl

    client = _s3_client(boto)
    digests = []
    for report in db["multiqc"].find({"data_collection_id": dc_id}):
        location = str(report.get("s3_location") or "")
        if not location.startswith("s3://"):
            digests.append(f"unreadable:{location}")
            continue
        bucket, _, key = location[len("s3://") :].partition("/")
        try:
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            digests.append(frame_digest(pl.read_parquet(io.BytesIO(body))))
        except Exception as exc:  # noqa: BLE001
            digests.append(f"error:{type(exc).__name__}")
    return {"storage": "multiqc", "reports": len(digests), "digests": sorted(digests)}


def snapshot(project: str, local_home: Path) -> dict[str, Any]:
    from pymongo import MongoClient

    state = _state(local_home)
    opts, boto = _storage(local_home)
    client = MongoClient(f"mongodb://127.0.0.1:{state['ports']['mongo']}")
    db = client[os.environ.get("DEPICTIO_MONGODB_DB_NAME", "depictioDB")]
    doc = db["projects"].find_one({"name": project})
    if doc is None:
        sys.exit(f"Project {project!r} not found.")
    dcs: dict[str, Any] = {}
    for wf in doc.get("workflows", []):
        for dc in wf.get("data_collections", []):
            dc_id = str(dc.get("_id") or dc.get("id"))
            tag = dc.get("data_collection_tag")
            kind = str((dc.get("config") or {}).get("type", "")).lower()
            key = tag if tag not in dcs else f"{wf.get('name')}/{tag}"
            try:
                if kind == "multiqc":
                    rec = _multiqc_record(db, dc_id, boto)
                elif kind == "geojson":
                    rec = _blob_record(boto, f"{dc_id}/geojson_data.geojson")
                elif kind == "phylogeny":
                    rec = _blob_record(boto, f"phylogeny/{dc_id}/tree.nwk")
                else:
                    rec = _delta_record(f"s3://{BUCKET}/{dc_id}", opts)
            except Exception as exc:  # noqa: BLE001 - a missing table is a result too
                rec = {"storage": "missing", "error": f"{type(exc).__name__}: {exc}"[:300]}
            rec["kind"] = kind
            dcs[key] = rec
    origin = doc.get("template_origin") or {}
    return {
        "project": project,
        "template": origin.get("template_id"),
        "locations": [
            loc
            for wf in doc.get("workflows", [])
            for loc in ((wf.get("data_location") or {}).get("locations") or [])
        ],
        "data_collections": dict(sorted(dcs.items())),
    }


def cmd_snapshot(ns: argparse.Namespace) -> int:
    snap = snapshot(ns.project, ns.local_home)
    Path(ns.output).write_text(json.dumps(snap, indent=2, sort_keys=True))
    print(f"Recorded {len(snap['data_collections'])} collections to {ns.output}")
    return 0


def cmd_record(ns: argparse.Namespace) -> int:
    case = _load_case(ns.cases, ns.case)
    data_root = Path(ns.data_root) if ns.data_root else case["runs"][0]
    project = ns.project or f"harness-{ns.case}-{int(time.time())}"
    out: Path = ns.out
    out.mkdir(parents=True, exist_ok=True)
    outcome = _ingest(case, data_root, project, ns.local_home, out / f"{ns.case}.log", ns.extra)
    snap = snapshot(project, ns.local_home)
    snap["ingest"] = {"exit_code": outcome.get("exit_code"), "status": outcome.get("status")}
    target = out / f"{ns.case}.json"
    target.write_text(json.dumps(snap, indent=2, sort_keys=True))
    print(f"Recorded {len(snap['data_collections'])} collections to {target}")
    return 0 if outcome.get("exit_code") == 0 else 1


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

STRICT_KEYS = ("storage", "kind", "columns", "rows", "digest", "sha256", "reports", "digests")


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    allowed: list[str] = []
    base_dcs = baseline["data_collections"]
    cur_dcs = current["data_collections"]
    for tag in sorted(set(base_dcs) - set(cur_dcs)):
        failures.append(f"{tag}: missing from current")
    for tag in sorted(set(cur_dcs) - set(base_dcs)):
        failures.append(f"{tag}: new in current")
    for tag in sorted(set(base_dcs) & set(cur_dcs)):
        b, c = base_dcs[tag], cur_dcs[tag]
        for key in STRICT_KEYS:
            if b.get(key) != c.get(key):
                failures.append(f"{tag}: {key} {b.get(key)!r} -> {c.get(key)!r}")
        if b.get("run_ids") != c.get("run_ids"):
            allowed.append(f"{tag}: {RUN_ID_COLUMN} {b.get('run_ids')} -> {c.get('run_ids')}")
        elif b.get("run_id_position") != c.get("run_id_position"):
            allowed.append(
                f"{tag}: {RUN_ID_COLUMN} position "
                f"{b.get('run_id_position')} -> {c.get('run_id_position')}"
            )
    return failures, allowed


def cmd_compare(ns: argparse.Namespace) -> int:
    baseline = json.loads(Path(ns.baseline).read_text())
    current = json.loads(Path(ns.current).read_text())
    failures, allowed = compare(baseline, current)
    for line in allowed:
        print(f"  allowed  {line}")
    for line in failures:
        print(f"  FAIL     {line}")
    n = len(baseline["data_collections"])
    print(f"{n} collections, {len(failures)} failures, {len(allowed)} allowed run-id changes")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Multi-run
# ---------------------------------------------------------------------------


def cmd_multirun(ns: argparse.Namespace) -> int:
    case = _load_case(ns.cases, ns.case)
    runs: list[Path] = case["runs"]
    if len(runs) < 2:
        sys.exit(f"Case {ns.case} lists fewer than two runs.")
    project = ns.project or f"harness-multi-{ns.case}-{int(time.time())}"
    out: Path = ns.out
    out.mkdir(parents=True, exist_ok=True)
    log = out / f"{ns.case}.multirun.log"
    snaps = []
    for i, run in enumerate(runs):
        extra = list(ns.extra)
        if i > 0:
            extra.append("--attach-run")
        outcome = _ingest(case, run, project, ns.local_home, log, extra)
        snap = snapshot(project, ns.local_home)
        snap["ingest"] = {"exit_code": outcome.get("exit_code"), "run": run.name}
        (out / f"{ns.case}.step{i}.json").write_text(json.dumps(snap, indent=2, sort_keys=True))
        snaps.append(snap)
        if outcome.get("exit_code") != 0:
            print(f"Ingest of {run.name} failed; stopping.", file=sys.stderr)
            return 1

    expected = sorted(r.name for r in runs)
    final = snaps[-1]["data_collections"]
    failures = []
    print(f"\nRun coverage after {len(runs)} runs (expected {expected}):")
    for tag, rec in final.items():
        if rec.get("storage") != "delta":
            print(f"  {tag:45s} {rec.get('storage')}")
            continue
        versions = [s["data_collections"].get(tag, {}).get("delta_version") for s in snaps]
        print(f"  {tag:45s} runs={rec.get('rows_per_run')} versions={versions}")
    for tag in case.get("expect_all_runs", []):
        got = final.get(tag, {}).get("run_ids")
        if got != expected:
            failures.append(f"{tag}: run ids {got}, expected {expected}")
    for line in failures:
        print(f"  FAIL     {line}")
    return 1 if failures else 0


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--local-home", type=Path, required=True, help="DEPICTIO_LOCAL_HOME")

    p = sub.add_parser("up", help="Start an isolated local stack")
    common(p)
    p.add_argument("--port", type=int, help="API port (checked free with lsof)")
    p.add_argument("--fresh", action="store_true", help="Delete the local home first")
    p.add_argument("--data-root-allow", type=Path, action="append")
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("down", help="Stop the stack")
    common(p)
    p.set_defaults(func=cmd_down)

    for name, func, helptext in (
        ("record", cmd_record, "Ingest the first run of a case and snapshot it"),
        ("multirun", cmd_multirun, "Ingest every run of a case with --attach-run"),
    ):
        p = sub.add_parser(name, help=helptext)
        common(p)
        p.add_argument("case")
        p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--project", help="Project name (default: a fresh one)")
        if name == "record":
            p.add_argument("--data-root", help="Override the case's first run")
        p.add_argument(
            "--extra", action="append", default=[], help="Extra ingest argument (repeatable)"
        )
        p.set_defaults(func=func)

    p = sub.add_parser("snapshot", help="Snapshot an existing project")
    common(p)
    p.add_argument("project")
    p.add_argument("output")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("compare", help="Compare two snapshots of a single-run case")
    p.add_argument("baseline")
    p.add_argument("current")
    p.set_defaults(func=cmd_compare)

    ns = parser.parse_args()
    return ns.func(ns)


if __name__ == "__main__":
    raise SystemExit(main())
