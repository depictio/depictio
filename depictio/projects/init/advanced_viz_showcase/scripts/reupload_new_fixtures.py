"""Reupload the Coverage Track + Sankey showcase fixtures into a running
depictio instance, without restarting the API container.

What it does:

1. Adds the two new data collections (coverage_track_demo + categorical_flow_demo)
   to the showcase project document in Mongo (workflows.0.data_collections).
2. Writes the two TSVs as Delta tables to MinIO at
   ``s3://depictio-bucket/<dc_id>``.
3. Inserts ``deltatables`` records pointing at those locations with column
   specs so ``load_deltatable_lite`` can resolve them.
4. Upserts the two new dashboard documents from the matching ``.db_seeds/*.json``.

Idempotent: re-running skips DCs / dashboards that are already in sync.

Configuration is read from ``.env.instance`` at the worktree root so the
script works on whichever instance the user is currently developing against.

Run from the worktree root:

    ./.venv/bin/python depictio/projects/init/advanced_viz_showcase/scripts/reupload_new_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
from bson import ObjectId, json_util
from pymongo import MongoClient

WORKTREE = Path(__file__).resolve().parents[5]
DATA_DIR = WORKTREE / "depictio" / "projects" / "init" / "advanced_viz_showcase" / "data"
SEEDS_DIR = WORKTREE / "depictio" / "projects" / "init" / "advanced_viz_showcase" / ".db_seeds"

PROJECT_ID = "646b0f3c1e4a2d7f8e5b8d00"
WORKFLOW_ID = "646b0f3c1e4a2d7f8e5b8d01"
ADMIN_USER_ID = "67658ba033c8b59ad489d7c7"
ADMIN_EMAIL = "admin@example.com"
S3_BUCKET = "depictio-bucket"


def _read_env_instance() -> dict[str, str]:
    """Parse .env.instance to discover the current worktree's port mapping."""
    out: dict[str, str] = {}
    env_path = WORKTREE / ".env.instance"
    if not env_path.exists():
        return out
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


# Connection settings — overridden by the worktree's .env.instance when present.
_env = _read_env_instance()
MONGO_PORT = int(_env.get("MONGO_PORT", _env.get("DEPICTIO_MONGODB_PORT", "27018")))
MINIO_PORT = int(_env.get("MINIO_PORT", _env.get("DEPICTIO_MINIO_EXTERNAL_PORT", "9000")))
MONGO_URI = f"mongodb://localhost:{MONGO_PORT}/depictioDB"
S3_ENDPOINT = f"http://localhost:{MINIO_PORT}"
S3_USER = _env.get("DEPICTIO_MINIO_ROOT_USER", "minio")
S3_PASSWORD = _env.get("DEPICTIO_MINIO_ROOT_PASSWORD", "minio123")

# Each new DC: (Mongo id, tag, TSV filename, description, columns_description, container_path).
NEW_DCS: list[dict[str, Any]] = [
    {
        "id": "646b0f3c1e4a2d7f8e5b8d50",
        "tag": "coverage_track_demo",
        "tsv": "coverage_track_demo.tsv",
        "description": (
            "SARS-CoV-2 coverage tracks (200 bp bins) for ~50 samples with "
            "SARS-CoV-2 gene-region annotation; sourced from a "
            "viralrecon-bowtie2-mosdepth run"
        ),
        "columns_description": {
            "chrom": "Reference contig / chromosome (MN908947.3 for SARS-CoV-2)",
            "start": "Bin start position (0-based, half-open)",
            "end": "Bin end position",
            "position": "Bin centre — drives the renderer's x axis",
            "coverage": "Mean read depth in the bin",
            "sample": "Sample identifier (used as the per-track facet key)",
            "gene_region": (
                "SARS-CoV-2 gene-region annotation "
                "(ORF1ab / S / N / … / intergenic) — drives the coverage-track colouring lane"
            ),
        },
    },
    {
        "id": "646b0f3c1e4a2d7f8e5b8d51",
        "tag": "categorical_flow_demo",
        "tsv": "categorical_flow_demo.tsv",
        "description": (
            "Per-sample Pangolin + Nextclade classification: qc_status → "
            "lineage → clade flow across SARS-CoV-2 samples"
        ),
        "columns_description": {
            "sample_id": "Sample identifier",
            "qc_status": "Pangolin QC pass/fail (Sankey step 1)",
            "lineage": "Pangolin lineage assignment (Sankey step 2)",
            "clade": "Nextclade WHO clade assignment (Sankey step 3)",
        },
    },
]

NEW_DASHBOARDS = ["dashboard_coverage_track.json", "dashboard_categorical_flow.json"]


def _admin_block() -> dict[str, Any]:
    return {
        "_id": ObjectId(ADMIN_USER_ID),
        "description": None,
        "flexible_metadata": None,
        "hash": None,
        "email": ADMIN_EMAIL,
        "is_admin": True,
        "is_anonymous": False,
        "is_temporary": False,
        "expiration_time": None,
    }


def _column_specs(df: pl.DataFrame) -> list[dict[str, Any]]:
    """Build the aggregation_columns_specs list mirroring how the CLI process
    pipeline records per-column summary stats. Stats kept minimal — the UI
    only reads `name`/`type`/`description` for advanced_viz binding."""
    rows: list[dict[str, Any]] = []
    for name in df.columns:
        dtype = df.schema[name]
        # Translate polars dtype → the friendly type names existing DCs use
        # ("object" for strings, "int64" / "float64" for numerics).
        if dtype in (pl.Utf8, pl.Categorical):
            type_str = "object"
        elif dtype in (
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
        ):
            type_str = "int64"
        elif dtype in (pl.Float32, pl.Float64):
            type_str = "float64"
        elif dtype == pl.Boolean:
            type_str = "bool"
        else:
            type_str = str(dtype).lower()
        rows.append({"name": name, "type": type_str, "description": None, "specs": {}})
    return rows


def _storage_options() -> dict[str, str]:
    return {
        "AWS_ACCESS_KEY_ID": S3_USER,
        "AWS_SECRET_ACCESS_KEY": S3_PASSWORD,
        "AWS_ENDPOINT_URL": S3_ENDPOINT,
        "AWS_REGION": "us-east-1",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        "AWS_ALLOW_HTTP": "true",
    }


def _ensure_bucket() -> None:
    """Make sure the depictio-bucket exists in the local MinIO. Boto3 is in
    the worktree venv already — depictio depends on it transitively."""
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_USER,
        aws_secret_access_key=S3_PASSWORD,
        region_name="us-east-1",
    )
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)
        print(f"  created bucket s3://{S3_BUCKET}")


def _write_delta(dc: dict[str, Any]) -> tuple[int, pl.DataFrame]:
    tsv_path = DATA_DIR / dc["tsv"]
    df = pl.read_csv(tsv_path, separator="\t")
    target = f"s3://{S3_BUCKET}/{dc['id']}"
    df.write_delta(target, mode="overwrite", storage_options=_storage_options())
    size = sum(p.stat().st_size for p in tsv_path.parent.glob(tsv_path.name))
    print(f"  wrote {df.height} rows → {target}")
    return size, df


def _dc_document(dc: dict[str, Any]) -> dict[str, Any]:
    container_path = f"/app/depictio/projects/init/advanced_viz_showcase/data/{dc['tsv']}"
    return {
        "_id": ObjectId(dc["id"]),
        "description": dc["description"],
        "flexible_metadata": None,
        "hash": None,
        "data_collection_tag": dc["tag"],
        "config": {
            "_id": ObjectId(),
            "description": None,
            "flexible_metadata": None,
            "hash": None,
            "type": "table",
            "source": "native",
            "metatype": "Aggregate",
            "scan": {
                "mode": "single",
                "scan_parameters": {"filename": container_path},
            },
            "dc_specific_properties": {
                "format": "tsv",
                "polars_kwargs": {"separator": "\t"},
                "keep_columns": [],
                "columns_description": dc["columns_description"],
            },
            "join": None,
            "transform": None,
        },
        "optional": False,
    }


def _deltatable_document(dc: dict[str, Any], size_bytes: int, df: pl.DataFrame) -> dict[str, Any]:
    specs = _column_specs(df)
    now = datetime.now(timezone.utc)
    agg_hash = hashlib.sha256(f"{dc['id']}|{now.isoformat()}|{len(specs)}".encode()).hexdigest()
    return {
        "data_collection_id": ObjectId(dc["id"]),
        "delta_table_location": f"s3://{S3_BUCKET}/{dc['id']}",
        "aggregation": [
            {
                "_id": ObjectId(),
                "description": None,
                "flexible_metadata": None,
                "hash": None,
                "aggregation_time": now,
                "aggregation_by": _admin_block(),
                "aggregation_version": 1,
                "aggregation_hash": agg_hash,
                "aggregation_columns_specs": specs,
            }
        ],
        "flexible_metadata": {
            "deltatable_size_bytes": size_bytes,
            "deltatable_size_mb": round(size_bytes / 1_048_576, 2),
            "deltatable_size_updated": now.isoformat(),
        },
    }


def main() -> None:
    client = MongoClient(MONGO_URI)
    db = client.get_database()

    proj = db["projects"].find_one({"_id": ObjectId(PROJECT_ID)})
    if not proj:
        raise SystemExit(
            f"Showcase project {PROJECT_ID} not found in Mongo at {MONGO_URI}. "
            "Make sure the API ran db_init at least once."
        )
    print(f"Found project: {proj['name']}")

    workflow = next((wf for wf in proj["workflows"] if str(wf.get("_id")) == WORKFLOW_ID), None)
    if not workflow:
        raise SystemExit(f"Workflow {WORKFLOW_ID} not on project document")
    existing_dc_ids = {str(dc["_id"]) for dc in workflow.get("data_collections", [])}

    _ensure_bucket()

    for dc in NEW_DCS:
        print(f"\n=== {dc['tag']} ({dc['id']}) ===")
        if dc["id"] in existing_dc_ids:
            print("  DC already on project document — skipping insert")
        else:
            dc_doc = _dc_document(dc)
            db["projects"].update_one(
                {"_id": ObjectId(PROJECT_ID), "workflows._id": ObjectId(WORKFLOW_ID)},
                {"$push": {"workflows.$.data_collections": dc_doc}},
            )
            print("  added DC to project document")

        size_bytes, df = _write_delta(dc)

        delta_doc = _deltatable_document(dc, size_bytes, df)
        db["deltatables"].update_one(
            {"data_collection_id": ObjectId(dc["id"])},
            {"$set": delta_doc},
            upsert=True,
        )
        print("  upserted deltatables record")

    for fname in NEW_DASHBOARDS:
        path = SEEDS_DIR / fname
        with path.open() as fh:
            doc = json.load(fh, object_hook=json_util.object_hook)
        # Make sure the dashboard's owner matches the local admin (the .json
        # template might carry a different admin_user OID across environments).
        doc.setdefault("permissions", {})["owners"] = [_admin_block()]
        db["dashboards"].update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
        print(f"\nUpserted dashboard: {doc.get('title', fname)} (id={doc['_id']})")

    # Wipe any compute_results entries — backend payload shape changed, so
    # stale "pending" / "done" records would otherwise hand back wrong figures.
    wiped = db["compute_results"].delete_many({}).deleted_count
    print(f"\nWiped {wiped} compute_results cache entries")

    print("\nDone. Refresh the dashboards page and the two new tabs should appear.")


if __name__ == "__main__":
    if not (WORKTREE / ".env.instance").exists():
        print(
            f"[warn] no .env.instance at {WORKTREE!r}; falling back to defaults "
            f"(mongo:{MONGO_PORT}, minio:{MINIO_PORT})"
        )
    os.chdir(WORKTREE)
    main()
