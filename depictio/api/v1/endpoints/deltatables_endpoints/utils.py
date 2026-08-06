import collections
import functools
import os
from collections.abc import Callable

import polars as pl
from botocore.exceptions import ClientError
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.logging_init import logger
from depictio.api.v1.db import files_collection
from depictio.api.v1.s3 import s3_client
from depictio.api.v1.utils import numpy_to_python


def get_s3_folder_size(bucket_name, prefix):
    """
    Calculate the total size of all objects within a given S3 folder (prefix).

    Args:
        bucket_name: Name of the S3 bucket
        prefix: Prefix (path) of the folder in the bucket

    Returns:
        Total size of all objects in bytes

    Raises:
        HTTPException: If folder is empty, doesn't exist, or on error
    """
    total_size = 0
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        response_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

        objects_found = False
        for page in response_iterator:
            if "Contents" in page:
                objects_found = True
                for obj in page["Contents"]:
                    total_size += obj["Size"]

        if not objects_found:
            raise HTTPException(status_code=404, detail="Folder is empty or does not exist.")

        return total_size
    except ClientError as e:
        logger.error(f"Error listing objects in folder '{prefix}': {str(e)}")
        raise HTTPException(status_code=500, detail="Error listing folder contents.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error calculating folder size: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Unexpected error occurred while calculating folder size.",
        )


def read_table_for_DC_table(file_info, data_collection_config_raw, deltaTable):
    """
    Read a table file and return a Polars DataFrame.
    """

    file_path = file_info.file_location
    data_collection_config = data_collection_config_raw["dc_specific_properties"]

    if data_collection_config["format"].lower() in ["csv", "tsv", "txt"]:
        # Read the file using polars

        df = pl.read_csv(
            file_path,
            **dict(data_collection_config["polars_kwargs"]),
        )
    elif data_collection_config["format"].lower() in ["parquet"]:
        df = pl.read_parquet(file_path, **dict(data_collection_config["polars_kwargs"]))

    elif data_collection_config["format"].lower() in ["feather"]:
        df = pl.read_feather(file_path, **dict(data_collection_config["polars_kwargs"]))

    elif data_collection_config["format"].lower() in ["xls", "xlsx"]:
        df = pl.read_excel(file_path, **dict(data_collection_config["polars_kwargs"]))

    raw_cols = df.columns
    no_run_id = False

    if data_collection_config_raw.get("metatype"):
        if data_collection_config_raw["metatype"].lower() == "metadata":
            no_run_id = True

    if not no_run_id:
        df = df.with_columns(pl.lit(file_info.run_id).alias("depictio_run_id"))
        df = df.select(["depictio_run_id"] + raw_cols)

    # Update the file_info in MongoDB to mark it as processed
    files_collection.update_one(
        {"_id": ObjectId(file_info.id)},
        {
            "$set": {
                "aggregated": True,
                "data_collection.deltatable": deltaTable.mongo(),
            }
        },
    )
    return df


def upload_dir_to_s3(bucket_name, s3_folder, local_dir, s3_client):
    """Recursively upload a directory to S3 preserving the directory structure."""
    for root, dirs, files in os.walk(local_dir):
        for filename in files:
            local_path = os.path.join(root, filename)
            relative_path = os.path.relpath(local_path, local_dir)
            s3_path = os.path.join(s3_folder, relative_path).replace("\\", "/")
            s3_client.upload_file(local_path, bucket_name, s3_path)


# Per-column aggregations, expressed lazily so the frame is never materialised.
#
# Keyed by the ``pandas`` method name declared in ``agg_functions`` (or by the
# card-method name for the one entry whose ``pandas`` value is a callable —
# ``range``). Each entry maps a column expression to the polars expression that
# reproduces *exactly* what the pandas method used to return; the non-obvious
# arguments are all parity fixes, measured against pandas 2.2:
#
# - ``quantile``: polars defaults to ``nearest`` interpolation, pandas to ``linear``.
# - ``skew`` / ``kurt``: polars defaults to the biased estimator, pandas to the
#   bias-corrected one.
# - ``nunique`` / ``mode``: polars counts null as a distinct value, pandas drops it.
# - ``mode``: pandas ``.mode()`` returns the tied modes *sorted* and the caller
#   took the first one — i.e. the smallest. ``.min()`` over the modes is the
#   same value and stays a scalar, so every expression here reduces to one row.
#
# Each entry also declares what its memory scales with, which decides how the
# work is split into passes (see _aggregate). Measured on the benchmark 1 GB
# tier (14.1M rows, 12 columns) with the polars 1.42 streaming engine:
#
#   CHEAP        constant                  all 12 columns          → 0.37 GB
#   ORDER_STATS  the column                8 numeric columns       → 1.30 GB
#   CARDINALITY  the distinct values       1 near-unique string    → 2.20 GB
#
# Run together those buffers coexist and cost 5.4 GB; run as separate passes
# the cost is the maximum instead of the sum.
_CHEAP, _ORDER_STATS, _CARDINALITY = "cheap", "order_stats", "cardinality"

_POLARS_AGG_EXPRS: dict[str, tuple[str, Callable[[pl.Expr], pl.Expr]]] = {
    "count": (_CHEAP, lambda e: e.count()),
    "sum": (_CHEAP, lambda e: e.sum()),
    "mean": (_CHEAP, lambda e: e.mean()),
    "min": (_CHEAP, lambda e: e.min()),
    "max": (_CHEAP, lambda e: e.max()),
    "var": (_CHEAP, lambda e: e.var()),
    "std": (_CHEAP, lambda e: e.std()),
    # The bias-corrected estimators are undefined below 3 (skew) and 4
    # (kurtosis) observations — pandas returns NaN there, polars keeps
    # returning a number. Guard so tiny columns behave as they always did.
    "skew": (_CHEAP, lambda e: pl.when(e.count() >= 3).then(e.skew(bias=False))),
    "kurt": (_CHEAP, lambda e: pl.when(e.count() >= 4).then(e.kurtosis(bias=False))),
    # ``agg_functions["int64"]["card_methods"]["range"]["pandas"]`` is a lambda,
    # so it has no method name to key on — it is resolved by card-method name.
    "range": (_CHEAP, lambda e: e.max() - e.min()),
    # Order statistics need the whole column in memory.
    "median": (_ORDER_STATS, lambda e: e.median()),
    "quantile": (_ORDER_STATS, lambda e: e.quantile(0.5, interpolation="linear")),
    # These size with the column's cardinality, not with the row count.
    "nunique": (_CARDINALITY, lambda e: e.drop_nulls().n_unique()),
    "mode": (_CARDINALITY, lambda e: e.drop_nulls().mode().min()),
}

# Above this many distinct values, a column's cardinality aggregations get a
# pass to themselves instead of sharing one with the other columns. Three
# near-unique string columns computed together peaked at 6.7 GB; one pass each
# brought that to 3.2 GB for the same wall time.
_LARGE_CARDINALITY = 1_000_000

_NESTED_DTYPES = (pl.List, pl.Array, pl.Struct, pl.Binary, pl.Null, pl.Object)

_INTEGER_DTYPES = (
    pl.Int8,
    pl.Int16,
    pl.Int32,
    pl.Int64,
    pl.UInt8,
    pl.UInt16,
    pl.UInt32,
    pl.UInt64,
)


def _polars_type_name(dtype: pl.DataType) -> str:
    """Normalized type name for a polars dtype, ignoring nullability.

    The names are the ones the rest of the stack understands: the validator in
    ``models/models/deltatables.py``, the ``agg_functions`` lookup and the
    frontend type maps. They are *not* polars dtype names.
    """
    if dtype in _INTEGER_DTYPES:
        return "int64"
    if dtype in (pl.Float32, pl.Float64):
        return "float64"
    if dtype == pl.Boolean:
        return "bool"
    if dtype in (pl.Date, pl.Datetime):
        return "datetime"
    if dtype == pl.Duration:
        # Kept as "time" — that is what the pandas path emitted for
        # timedelta64 columns, and "timedelta" is not an accepted value of
        # DeltaTableColumn.validate_column_type.
        return "time"
    if dtype in (pl.Categorical, pl.Enum):
        return "category"
    # String, Time, Binary, Decimal, List, Struct, Null — everything the pandas
    # path used to surface as dtype "object".
    return "object"


def _legacy_type_name(dtype: pl.DataType, has_nulls: bool) -> str:
    """The name the previous ``to_pandas()`` implementation would have emitted.

    ``to_pandas()`` silently widened two cases (verified, not inferred):
    an integer column containing nulls came back as ``float64``, and a boolean
    column containing nulls came back as ``object``. Existing dashboards have
    those names recorded in their component metadata, so they must remain
    reachable — see ``precompute_columns_specs`` for when they are preferred.
    """
    if has_nulls and dtype in _INTEGER_DTYPES:
        return "float64"
    if has_nulls and dtype == pl.Boolean:
        return "object"
    return _polars_type_name(dtype)


def _column_expr(column: str, dtype: pl.DataType) -> pl.Expr:
    """Base expression for a column, adjusted so aggregations match pandas."""
    expr = pl.col(column)
    if dtype in (pl.Float32, pl.Float64):
        # pandas treats NaN as missing; polars treats it as a value. Without
        # this, count/nunique/mean/min/max all drift on any column holding NaN.
        expr = expr.fill_nan(None)
    elif dtype in (pl.Categorical, pl.Enum):
        # ``mode().min()`` on a categorical compares physical codes, not labels.
        expr = expr.cast(pl.Utf8)
    return expr


def _supports_approx_n_unique(dtype: pl.DataType) -> bool:
    """Whether HyperLogLog accepts this dtype (after ``_column_expr``'s casts).

    polars rejects it on temporal, decimal and nested dtypes; categoricals are
    fine because ``_column_expr`` casts them to Utf8.
    """
    return dtype in _INTEGER_DTYPES or dtype in (
        pl.Float32,
        pl.Float64,
        pl.Boolean,
        pl.String,
        pl.Categorical,
        pl.Enum,
    )


def _resolve_method_expr(
    method_name: str, method_info: dict
) -> tuple[str, Callable[[pl.Expr], pl.Expr]] | None:
    """Map one ``agg_functions`` card method to its cost class and expression."""
    pandas_method = method_info.get("pandas")
    if isinstance(pandas_method, str) and pandas_method in _POLARS_AGG_EXPRS:
        return _POLARS_AGG_EXPRS[pandas_method]
    if method_name in _POLARS_AGG_EXPRS:
        return _POLARS_AGG_EXPRS[method_name]
    return None


@functools.lru_cache(maxsize=1)
def _streaming_collect_kwargs() -> dict:
    """How to ask this polars for the streaming engine, or ``{}`` if it can't.

    The streaming engine is what keeps the scan from being materialised before
    the aggregations run. Its spelling changed across versions (the dev venv is
    on polars 1.19, the API container on 1.42), so it is probed once on a
    trivial plan rather than guessed from the version string.
    """
    probe = pl.LazyFrame({"x": [1]}).select(pl.col("x").sum())
    for kwargs in ({"engine": "streaming"}, {"streaming": True}):
        try:
            # Untyped on purpose: which spelling exists is a property of the
            # installed polars, not of the signature the type checker sees.
            _collect_with(probe, kwargs)
            return kwargs
        except Exception:  # noqa: S110 — unsupported spelling, try the next one
            continue
    logger.warning("polars streaming engine unavailable; column specs use the in-memory engine.")
    return {}


def _collect_with(lf: pl.LazyFrame, kwargs: dict) -> pl.DataFrame:
    """``lf.collect(**kwargs)`` with the version-dependent kwargs kept dynamic."""
    collect: Callable[..., pl.DataFrame] = lf.collect
    return collect(**kwargs)


def _collect(lf: pl.LazyFrame) -> pl.DataFrame:
    """Collect a pure-aggregation plan through the streaming engine when possible."""
    return _collect_with(lf, _streaming_collect_kwargs())


def precompute_columns_specs(
    aggregated_df: pl.DataFrame | pl.LazyFrame,
    agg_functions: dict,
    dc_data: dict,
    previous_types: dict[str, str] | None = None,
):
    """Return one spec dict per column: name, description, type and aggregations.

    Everything is computed as lazy polars aggregations — the frame is never
    materialised. This function runs on every Delta upsert, including data
    collections of tens of millions of rows, where the previous ``.to_pandas()``
    implementation allocated several gigabytes (every string cell became a
    Python ``str``) and got the API worker OOM-killed.

    ``previous_types`` maps column name to the type recorded by the previous
    aggregation. When a column is already known, its recorded name wins over the
    freshly derived one, so a re-ingest never silently changes the type a saved
    dashboard component was built against. Columns never seen before get the
    true polars type.
    """
    lf = aggregated_df.lazy()
    schema = lf.collect_schema()
    dc_config = dc_data["config"]
    columns_description = dc_config["dc_specific_properties"].get("columns_description") or {}

    # Build every aggregation up front, grouped by column and by cost class. The
    # final type depends on whether the column holds nulls, which is only known
    # after collecting — so all candidate types' methods are computed and the
    # ones that don't apply are dropped when the specs are assembled.
    plan: list[dict[str, list[pl.Expr]]] = []

    for idx, (column, dtype) in enumerate(schema.items()):
        base = _column_expr(column, dtype)
        column_exprs: dict[str, list[pl.Expr]] = {
            _CHEAP: [pl.col(column).null_count().alias(f"c{idx}__nulls")],
            _ORDER_STATS: [],
            _CARDINALITY: [],
        }
        seen: set[str] = set()

        # Only the types this dtype can actually take: a recorded type that
        # contradicts the dtype is discarded when the specs are assembled, so
        # there is nothing to compute for it.
        candidates = {
            _polars_type_name(dtype),
            _legacy_type_name(dtype, has_nulls=False),
            _legacy_type_name(dtype, has_nulls=True),
        }
        nested = isinstance(dtype, _NESTED_DTYPES)

        for type_name in sorted(candidates):
            for method_name, method_info in (
                agg_functions.get(type_name, {}).get("card_methods", {}).items()
            ):
                alias = f"c{idx}__{type_name}__{method_name}"
                if alias in seen:
                    continue
                if nested and method_name != "count":
                    # List/Struct/Binary/Null reject ordering and hashing; only
                    # counting them is meaningful. Skipping up front keeps
                    # _aggregate's retry path for genuine surprises.
                    continue
                resolved = _resolve_method_expr(method_name, method_info)
                if resolved is None:
                    logger.warning(
                        f"precompute_columns_specs: no polars equivalent for card method "
                        f"'{method_name}' of type '{type_name}' — skipping it."
                    )
                    continue
                cost, factory = resolved
                seen.add(alias)
                column_exprs[cost].append(factory(base).alias(alias))

        if column_exprs[_CARDINALITY] and _supports_approx_n_unique(dtype):
            # Planner signal only, never recorded: HyperLogLog is cheap and tells
            # us whether this column's exact cardinality aggregations deserve a
            # pass to themselves. Columns without it are treated as small — their
            # dtypes (temporal, decimal) hash to fixed-width keys, so a shared
            # pass stays affordable even at high cardinality.
            column_exprs[_CHEAP].append(base.approx_n_unique().alias(f"c{idx}__approx"))
        plan.append(column_exprs)

    aggregated = _aggregate(lf, plan)

    results = []
    for idx, (column, dtype) in enumerate(schema.items()):
        tmp_dict = collections.defaultdict(dict)
        tmp_dict["name"] = column
        tmp_dict["description"] = columns_description.get(column)

        null_count = aggregated.get(f"c{idx}__nulls")
        has_nulls = bool(null_count) if null_count is not None else False
        polars_name = _polars_type_name(dtype)
        legacy_name = _legacy_type_name(dtype, has_nulls)
        recorded = (previous_types or {}).get(column)
        if recorded in (legacy_name, polars_name):
            normalized_type = recorded
        else:
            normalized_type = polars_name
        tmp_dict["type"] = normalized_type

        for method_name in agg_functions.get(normalized_type, {}).get("card_methods", {}):
            value = aggregated.get(f"c{idx}__{normalized_type}__{method_name}")
            # None covers both "nothing to aggregate" (empty or all-null column,
            # where pandas returned an empty Series and the entry was skipped
            # too) and "aggregation dropped" (nested dtype, see _aggregate).
            if value is None:
                continue
            tmp_dict["specs"][str(method_name)] = numpy_to_python(value)

        results.append(tmp_dict)

    return results


def _run_pass(lf: pl.LazyFrame, exprs: list[pl.Expr]) -> dict:
    """Collect one batch of aggregations, degrading rather than aborting.

    Nested dtypes (List, Struct, Binary) accept some of the aggregations above
    and reject others. Rather than failing the whole upsert — which would leave
    every dashboard tile bound to that data collection on a 404 — a failing
    batch is retried expression by expression and only the offending ones are
    dropped.
    """
    if not exprs:
        return {}
    try:
        return _collect(lf.select(exprs)).to_dicts()[0]
    except Exception as e:
        logger.warning(
            f"precompute_columns_specs: aggregation batch failed ({e}); "
            "retrying its expressions individually."
        )

    out: dict = {}
    for expr in exprs:
        try:
            out.update(_collect(lf.select(expr)).to_dicts()[0])
        except Exception as e:
            logger.warning(f"precompute_columns_specs: dropping one aggregation — {e}")
    return out


def _aggregate(lf: pl.LazyFrame, plan: list[dict[str, list[pl.Expr]]]) -> dict:
    """Run the plan as one pass per cost class, keeping peak memory bounded.

    Every pass reads the table again, so this trades I/O for memory — on the
    benchmark 1 GB tier the extra passes cost under a second each, while running
    everything together costs 5.4 GB against 3.5 GB here. Cardinality
    aggregations on a column with more than ``_LARGE_CARDINALITY`` distinct
    values get a pass of their own: their hash tables are the one term that
    scales with the data, and several such columns sharing a pass add up (6.7 GB
    measured for three, against 3.2 GB one at a time).
    """
    out: dict = {}
    out.update(_run_pass(lf, [e for column in plan for e in column[_CHEAP]]))
    out.update(_run_pass(lf, [e for column in plan for e in column[_ORDER_STATS]]))

    small: list[pl.Expr] = []
    for idx, column in enumerate(plan):
        if not column[_CARDINALITY]:
            continue
        approx = out.get(f"c{idx}__approx") or 0
        if approx > _LARGE_CARDINALITY:
            out.update(_run_pass(lf, column[_CARDINALITY]))
        else:
            small += column[_CARDINALITY]
    out.update(_run_pass(lf, small))
    return out
