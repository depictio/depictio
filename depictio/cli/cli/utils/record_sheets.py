"""YAML and JSON samplesheets: a list of records with the columns of a CSV/TSV sheet.

Some labs keep their pipeline ``--input`` sheet as YAML or JSON instead of CSV::

    - sample: test
      fastq_1: reads_1.fq.gz
      strandedness: forward

One record is one row, one key one column. Wherever a CSV/TSV samplesheet is
read (a recipe source, a ``Table`` collection, the ``input/`` auto-detection,
``depictio manifest from-table``), a location with one of
``RECORD_SHEET_SUFFIXES`` is read with :func:`read_record_sheet` instead, so it
lands as the frame its CSV would. The extension decides, not the declared
format: a template declaring ``CSV`` keeps working when ``SAMPLESHEET_FILE``
points at a YAML sheet, and a ``.csv`` is never read as anything but CSV.

The CSV reader's options (``separator``, ``skip_rows``...) mean nothing to a
list of records and are ignored.
"""

from __future__ import annotations

import datetime
import json
from pathlib import PurePosixPath
from urllib.parse import urlparse

import polars as pl
import yaml

RECORD_SHEET_SUFFIXES = (".yaml", ".yml", ".json")

# What a CSV cell can hold. A nested list or mapping has no column to land in.
_SCALARS = (str, int, float, bool, datetime.date, datetime.datetime, type(None))


class RecordSheetError(ValueError):
    """A YAML/JSON sheet that is not a list of flat records."""


def _path_part(location: str) -> str:
    """The path of ``location``, without a URL's scheme, host or query."""
    return urlparse(location).path if "://" in location else location


def is_record_sheet(location: object) -> bool:
    """Whether ``location`` (a path, an ``s3://`` or ``http(s)://`` URL) is a YAML/JSON sheet."""
    return PurePosixPath(_path_part(str(location))).suffix.lower() in RECORD_SHEET_SUFFIXES


def parse_record_sheet(data: bytes | str, name: str) -> list[dict]:
    """The records of the YAML/JSON sheet ``data``; ``name`` is its location, for errors."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    if _path_part(name).lower().endswith(".json"):
        try:
            records = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RecordSheetError(f"{name} is not valid JSON: {exc}") from exc
    else:
        try:
            records = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RecordSheetError(f"{name} is not valid YAML: {exc}") from exc

    if not isinstance(records, list):
        raise RecordSheetError(
            f"{name} must be a list of records (one mapping per sample), "
            f"not a {type(records).__name__}"
        )
    for number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise RecordSheetError(f"In {name}, record {number} is not a mapping of column: value")
        for key, value in record.items():
            if not isinstance(value, _SCALARS):
                raise RecordSheetError(
                    f"In {name}, column '{key}' of record {number} holds a "
                    f"{type(value).__name__}; a samplesheet cell must be a single value"
                )
    return [{str(key): value for key, value in record.items()} for record in records]


def read_record_sheet(data: bytes | str, name: str) -> pl.DataFrame:
    """The YAML/JSON sheet ``data`` as a frame: one row per record, columns in first-seen order.

    A key a record leaves out is null in that row, as an empty CSV cell is.
    """
    records = parse_record_sheet(data, name)
    if not records:
        return pl.DataFrame()
    # Every record decides the schema, so a column first seen on the last
    # record still exists; a column whose records disagree on a type is
    # widened (to a string at worst) rather than refused.
    return pl.from_dicts(records, infer_schema_length=None, strict=False)
