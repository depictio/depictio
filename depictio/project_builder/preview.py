"""Tabular preview + schema inference for a picked file (middle column).

Service-free: reads the local file with polars only. Mirrors the csv/tsv/parquet
sniffing in ``depictio.catalog.payload._load_fixture_df`` so the schema the
Project Builder shows matches what ``build_payload`` will bind against.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from depictio.project_builder.paths import rel_to_root, safe_resolve

_PREVIEW_ROWS = 50
_MAX_INFER_ROWS = 1000


def _separator(path: Path) -> str:
    return "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","


def _format(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".tsv": "tsv",
        ".txt": "tsv",
        ".csv": "csv",
        ".parquet": "parquet",
        ".feather": "feather",
    }.get(suffix, "csv")


def _read_df(path: Path):  # -> pl.DataFrame
    import polars as pl

    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix == ".feather":
        return pl.read_ipc(path)
    return pl.read_csv(path, separator=_separator(path), n_rows=_MAX_INFER_ROWS)


def schema_of(root: Path, rel: str) -> dict[str, str]:
    """Column→dtype map for a file (no preview rows).

    Used to compare schemas across the files a scan glob matches. Reads through
    the same ``_read_df`` sniffing as ``preview_file`` so the dtypes agree.
    """
    path = safe_resolve(root, rel)
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {rel!r}")
    df = _read_df(path)
    return {name: str(dtype) for name, dtype in df.schema.items()}


def preview_file(root: Path, rel: str) -> dict[str, Any]:
    """Return ``{schema, columns, rows, format, separator, n_rows_preview, truncated}``."""
    path = safe_resolve(root, rel)
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {rel!r}")

    df = _read_df(path)
    schema = {name: str(dtype) for name, dtype in df.schema.items()}
    head = df.head(_PREVIEW_ROWS)
    return {
        "path": rel_to_root(root, path),
        "format": _format(path),
        "separator": _separator(path),
        "columns": list(schema.keys()),
        "schema": schema,
        "rows": head.to_dicts(),
        "n_rows_preview": head.height,
        # We cap inference at _MAX_INFER_ROWS, so "truncated" is a lower bound.
        "truncated": df.height >= _MAX_INFER_ROWS,
    }
