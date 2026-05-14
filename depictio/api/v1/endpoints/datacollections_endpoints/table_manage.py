"""Append / replace / clear handlers for Table data collections.

Direct delta-lake operations: the original source files are gone after the
DC is first created (the upload temp dir is wiped), so we can't re-run the
CLI scan+process pipeline. Instead we read the existing delta back into a
DataFrame, mix it with the new uploads, and overwrite the delta — bumping
the deltatables_collection aggregation version and dropping cached
DataFrames so subsequent renders see fresh data.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from typing import Any

import polars as pl
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import deltatables_collection, projects_collection, users_collection
from depictio.api.v1.endpoints.datacollections_endpoints.utils import _user_can_edit_project
from depictio.api.v1.s3 import polars_s3_config, s3_client
from depictio.models.models.base import PyObjectId
from depictio.models.models.deltatables import Aggregation, DeltaTableAggregated
from depictio.models.models.users import User

_MAX_PER_FILE_BYTES = 50 * 1024 * 1024
_MAX_TOTAL_BYTES = 500 * 1024 * 1024

# Columns the CLI aggregator adds — strip from existing-delta reads so they
# don't get duplicated when we re-aggregate and re-add them on write.
_CLI_AUGMENTED_COLUMNS = {"aggregation_time", "depictio_run_id"}


def _delta_location_for(dc_id: str) -> str:
    """The conventional S3 location for a Table DC's delta lake.

    Mirrors `client_aggregate_data` (cli/utils/deltatables.py): one delta per
    DC at ``s3://{bucket}/{dc_id}``.
    """
    return f"s3://{settings.minio.bucket}/{dc_id}"


def _load_table_dc(data_collection_id: str, current_user) -> tuple[dict, dict]:
    """Resolve (project_doc, dc_dict) for a Table DC, enforcing edit perms.

    404 (not 403) on permission failure to match the MultiQC convention.
    """
    try:
        dc_oid = ObjectId(data_collection_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid data collection id: {exc}")

    project_doc = projects_collection.find_one({"workflows.data_collections._id": dc_oid})
    if not project_doc:
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )
    if not _user_can_edit_project(
        project_doc, current_user.id, getattr(current_user, "is_admin", False)
    ):
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )

    dc_dict: dict | None = None
    for wf_dict in project_doc.get("workflows", []) or []:
        for d in wf_dict.get("data_collections", []) or []:
            if str(d.get("_id") or d.get("id")) == data_collection_id:
                dc_dict = d
                break
        if dc_dict:
            break
    if not dc_dict:
        raise HTTPException(
            status_code=404, detail=f"Data collection {data_collection_id} not found."
        )

    dc_type = ((dc_dict.get("config") or {}).get("type") or "").lower()
    if dc_type != "table":
        raise HTTPException(
            status_code=400,
            detail=f"Data collection {data_collection_id} is type {dc_type!r}, expected 'table'.",
        )
    return project_doc, dc_dict


def _read_uploaded_table(
    file_bytes: bytes,
    filename: str,
    file_format: str,
    polars_kwargs: dict,
) -> pl.DataFrame:
    """Parse one uploaded file into a polars DataFrame using the DC's format.

    Materialises through a temp file because polars scanners want a path —
    matches the file-format dispatch in cli/utils/deltatables.py:read_single_file_lazy.
    """
    if not file_bytes:
        raise HTTPException(status_code=400, detail=f"Empty upload: {filename}")
    if len(file_bytes) > _MAX_PER_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"{filename}: file too large "
                f"({len(file_bytes) / (1024 * 1024):.1f}MB > "
                f"{_MAX_PER_FILE_BYTES / (1024 * 1024):.0f}MB)."
            ),
        )

    suffix = f".{file_format}" if file_format else ".dat"
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(file_bytes)

        if file_format in ("csv", "tsv", "txt"):
            kwargs = dict(polars_kwargs)
            if file_format == "tsv" and "separator" not in kwargs:
                kwargs["separator"] = "\t"
            return pl.read_csv(temp_path, **kwargs)
        if file_format == "parquet":
            return pl.read_parquet(temp_path, **polars_kwargs)
        if file_format == "feather":
            return pl.read_ipc(temp_path, **polars_kwargs)
        if file_format in ("xls", "xlsx"):
            return pl.read_excel(temp_path, **polars_kwargs)
        raise HTTPException(status_code=400, detail=f"Unsupported table file format: {file_format}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse {filename} as {file_format}: {exc}",
        )
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _align_and_concat(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Schema-align (Utf8 on conflict, null-fill missing) and vertical-concat.

    Mirrors the behavior of cli/utils/deltatables.py:align_lazy_schemas so the
    resulting delta has the same shape it would if the CLI had reaggregated.
    """
    unified: dict[str, Any] = {}
    schemas: list[dict[str, Any]] = []
    for df in frames:
        schema = dict(df.schema)
        schemas.append(schema)
        for col, dtype in schema.items():
            if col not in unified:
                unified[col] = dtype
            elif unified[col] != dtype:
                unified[col] = pl.Utf8

    aligned: list[pl.DataFrame] = []
    for df, schema in zip(frames, schemas):
        exprs = []
        for col, dtype in unified.items():
            if col in schema:
                exprs.append(pl.col(col).cast(dtype).alias(col))
            else:
                exprs.append(pl.lit(None).cast(dtype).alias(col))
        aligned.append(df.select(exprs))

    combined = pl.concat(aligned)
    return combined.with_columns(
        pl.lit(datetime.now().strftime("%Y-%m-%d %H:%M:%S")).alias("aggregation_time")
    )


def _bump_table_dc_aggregation(
    data_collection_id: str,
    current_user,
    delta_location: str,
    combined_df: pl.DataFrame,
) -> int:
    """Append a new Aggregation row + return the new aggregation_version.

    Mirrors the upsert path in deltatables_endpoints/routes.py:upsert_deltatable
    so render_multiqc / render_table cache keys (which salt with the latest
    aggregation_version) bump correctly. We skip ``precompute_columns_specs``
    here — the CLI flow recomputes it on the next full process. For the
    realtime invalidation path it's enough to bump the version + replace the
    aggregation row.
    """
    dc_oid = ObjectId(data_collection_id)
    query_dt = deltatables_collection.find_one({"data_collection_id": dc_oid})
    if query_dt:
        deltatable = DeltaTableAggregated.from_mongo(query_dt)
        version = (
            1 if not deltatable.aggregation else deltatable.aggregation[-1].aggregation_version + 1
        )
    else:
        deltatable = DeltaTableAggregated(
            data_collection_id=PyObjectId(str(dc_oid)),
            delta_table_location=delta_location,
        )
        version = 1

    user_doc = users_collection.find_one({"_id": ObjectId(current_user.id)})
    if not user_doc:
        raise HTTPException(status_code=404, detail="Current user not found.")
    user = User.from_mongo(user_doc)
    userbase = user.turn_to_userbase()

    hash_series = combined_df.hash_rows(seed=0)
    hash_bytes = hash_series.to_numpy().tobytes()
    hash_df = hashlib.sha256(hash_bytes).hexdigest()
    final_hash = hashlib.sha256(
        f"{delta_location}{datetime.now().isoformat()}{hash_df}".encode()
    ).hexdigest()

    deltatable.aggregation.append(
        Aggregation(
            aggregation_time=datetime.now(),
            aggregation_by=userbase,
            aggregation_version=version,
            aggregation_hash=final_hash,
            aggregation_columns_specs=[],
        )
    )

    deltatables_collection.update_one(
        {"data_collection_id": dc_oid},
        {
            "$set": {
                "delta_table_location": delta_location,
                "aggregation": [a.mongo() for a in deltatable.aggregation],
            }
        },
        upsert=True,
    )
    return version


def _invalidate_table_caches_for_dc(dc_id: str) -> None:
    """Drop cached DataFrames + figure variants for a Table DC after mutation."""
    try:
        from depictio.api.v1.deltatables_utils import invalidate_data_collection_cache

        dropped_dfs = invalidate_data_collection_cache(dc_id)
        logger.info(f"Table DC invalidate dc={dc_id}: dropped {dropped_dfs} dataframe key(s)")
    except Exception as exc:
        logger.warning(f"Dataframe cache invalidation failed for dc={dc_id}: {exc}")

    # Belt-and-braces: tables don't currently use the multiqc figure cache,
    # but joined / derived components keyed by `dc=<id>` would benefit. The
    # delete_pattern is a substring match and a no-op when no keys exist.
    try:
        from depictio.api.cache import get_cache

        get_cache().delete_pattern(f"dc={dc_id}")
    except Exception as exc:
        logger.warning(f"Figure cache invalidation failed for dc={dc_id}: {exc}")


def _process_table_uploads(
    *,
    data_collection_id: str,
    decoded_files: list[tuple[bytes, str]],
    current_user,
    mode: str,
) -> dict:
    """Common path for append (mode='append') and replace (mode='replace').

    Append reads the existing delta first and concats with the uploads;
    replace skips the read and writes only the uploads. Both paths overwrite
    the delta and bump the aggregation version.
    """
    if mode not in ("append", "replace"):
        raise ValueError(f"Unsupported mode: {mode!r}")
    if not decoded_files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    total_bytes = sum(len(b) for b, _ in decoded_files)
    if total_bytes > _MAX_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Total upload size {total_bytes / (1024 * 1024):.1f}MB exceeds "
                f"{_MAX_TOTAL_BYTES / (1024 * 1024):.0f}MB limit."
            ),
        )

    _, dc_dict = _load_table_dc(data_collection_id, current_user)

    dc_props = (dc_dict.get("config") or {}).get("dc_specific_properties") or {}
    file_format = (dc_props.get("format") or "csv").lower()
    polars_kwargs = dict(dc_props.get("polars_kwargs") or {})

    new_dfs = [
        _read_uploaded_table(fb, fn or "upload.dat", file_format, polars_kwargs)
        for fb, fn in decoded_files
    ]

    delta_loc = _delta_location_for(data_collection_id)

    rows_before = 0
    frames: list[pl.DataFrame] = []
    if mode == "append":
        try:
            existing_df = pl.read_delta(delta_loc, storage_options=polars_s3_config)
            rows_before = existing_df.height
            cols_to_drop = [c for c in _CLI_AUGMENTED_COLUMNS if c in existing_df.columns]
            if cols_to_drop:
                existing_df = existing_df.drop(cols_to_drop)
            frames.append(existing_df)
        except Exception as exc:
            # No existing delta yet (first ingest never ran, or table was
            # cleared) — proceed as if replace.
            logger.info(
                f"Append: no readable existing delta at {delta_loc} "
                f"({type(exc).__name__}: {exc}); treating as initial write."
            )

    frames.extend(new_dfs)
    combined_df = _align_and_concat(frames)

    combined_df.write_delta(
        delta_loc,
        storage_options=polars_s3_config,
        delta_write_options={"schema_mode": "overwrite"},
        mode="overwrite",
    )

    new_version = _bump_table_dc_aggregation(
        data_collection_id, current_user, delta_loc, combined_df
    )
    _invalidate_table_caches_for_dc(data_collection_id)

    rows_added = combined_df.height - rows_before
    return {
        "success": True,
        "message": (
            f"Table DC {mode}d ({len(new_dfs)} file(s) ingested, "
            f"{rows_added} row(s) added, {combined_df.height} row(s) total). "
            f"aggregation_version={new_version}."
        ),
        "data_collection_id": data_collection_id,
        "rows_total": combined_df.height,
        "rows_added": rows_added,
        "aggregation_version": new_version,
    }


def append_table_uploads(
    *,
    data_collection_id: str,
    decoded_files: list[tuple[bytes, str]],
    current_user,
) -> dict:
    """Append uploads to an existing Table DC (preserves existing rows)."""
    return _process_table_uploads(
        data_collection_id=data_collection_id,
        decoded_files=decoded_files,
        current_user=current_user,
        mode="append",
    )


def replace_table_uploads(
    *,
    data_collection_id: str,
    decoded_files: list[tuple[bytes, str]],
    current_user,
) -> dict:
    """Replace all data in a Table DC with the new uploads."""
    return _process_table_uploads(
        data_collection_id=data_collection_id,
        decoded_files=decoded_files,
        current_user=current_user,
        mode="replace",
    )


def clear_table_data(*, data_collection_id: str, current_user) -> dict:
    """Wipe a Table DC's delta on S3 + Mongo aggregation, keeping the DC config.

    Mirrors the MultiQC clear semantics: the data collection definition stays
    so existing dashboard components keep their dc_id reference, but every
    row is gone until the next append/replace.
    """
    _load_table_dc(data_collection_id, current_user)

    delta_loc = _delta_location_for(data_collection_id)
    bucket = settings.minio.bucket
    s3_prefix = data_collection_id  # delta_loc is s3://{bucket}/{dc_id}/...
    deleted_s3_count = 0
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=s3_prefix + "/")
        objects_to_delete = [
            {"Key": obj["Key"]} for page in pages for obj in page.get("Contents", []) or []
        ]
        if objects_to_delete:
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i : i + 1000]
                s3_client.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            deleted_s3_count = len(objects_to_delete)
            logger.info(f"Cleared {deleted_s3_count} S3 object(s) under {delta_loc}")
        else:
            logger.info(f"Clear: no S3 objects found under {delta_loc}")
    except Exception as exc:
        logger.warning(f"Clear: S3 cleanup at {delta_loc} failed: {exc}")

    dc_oid = ObjectId(data_collection_id)
    delete_result = deltatables_collection.delete_many({"data_collection_id": dc_oid})
    deleted_mongo = int(getattr(delete_result, "deleted_count", 0) or 0)
    _invalidate_table_caches_for_dc(data_collection_id)

    return {
        "success": True,
        "message": (
            f"Table DC cleared ({deleted_s3_count} S3 object(s) removed, "
            f"{deleted_mongo} aggregation doc(s) cleared)."
        ),
        "data_collection_id": data_collection_id,
        "deleted_s3_count": deleted_s3_count,
        "deleted_mongo_count": deleted_mongo,
    }
