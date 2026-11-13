"""Show the start of one file of a data root, without a server.

The decoding half of ``POST /projects/run_file_preview``, kept free of FastAPI
and Mongo so the Project Builder's standalone server (``depictio
project-builder``) previews files exactly as the run-folder dialog does.

Every read is bounded: the first :data:`MAX_HEAD_BYTES` of the file (a gzip
file decompressed up to :data:`MAX_GZ_BYTES`), or, for a parquet file of at
most :data:`MAX_PARQUET_BYTES`, its schema, its row count and its first rows,
which polars reads without the rest. Nothing is ever read whole.
"""

from __future__ import annotations

import codecs
import io
import zlib
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from depictio.cli.cli.utils.data_root import DataRoot
from depictio.models.logging import logger

# How much of a file is read, and how much a gzip one may decompress to.
MAX_HEAD_BYTES = 64 * 1024
MAX_GZ_BYTES = 256 * 1024
# A parquet file larger than this is not opened at all.
MAX_PARQUET_BYTES = 512 * 1024 * 1024
# What a preview shows at most: columns of a table, characters of a cell, and
# lines and characters of a text.
MAX_PREVIEW_COLUMNS = 30
MAX_CELL_CHARS = 200
MAX_TEXT_LINES = 200
MAX_TEXT_CHARS = 64 * 1024

# The separators a plain text file is tried with, in order, and on how many of
# its first lines (comment lines left out).
SNIFFED_SEPARATORS = ("\t", ",", ";", "|")
SNIFFED_LINES = 20
# Rows polars infers column types from when they are asked for.
INFER_SCHEMA_ROWS = 1000

TABLE_SEPARATORS = {".csv": ",", ".tsv": "\t", ".tab": "\t"}
SNIFFED_SUFFIXES = frozenset({".txt", ".mqc"})
TEXT_SUFFIXES = frozenset({".json", ".yml", ".yaml", ".nwk", ".newick", ".log", ".md"})

_HTML = "An HTML report, open it in a browser."
_IMAGE = "An image, open it in an image viewer."
_ALIGNMENT = "An alignment file in a binary format."
NOT_PREVIEWED = {
    ".html": _HTML,
    ".htm": _HTML,
    ".pdf": "A PDF document, open it in a PDF viewer.",
    ".png": _IMAGE,
    ".jpg": _IMAGE,
    ".jpeg": _IMAGE,
    ".svg": _IMAGE,
    ".zip": "A zip archive, its files are not previewed.",
    ".tar": "An archive, its files are not previewed.",
    ".qza": "A QIIME 2 artifact (a zip archive), open it with QIIME 2.",
    ".qzv": "A QIIME 2 visualization, open it with QIIME 2 View.",
    ".bam": _ALIGNMENT,
    ".cram": _ALIGNMENT,
    ".bai": "An alignment index in a binary format.",
}
BINARY = "A binary file, it is not previewed."


class RunFilePreview(BaseModel):
    """What one file of a run folder holds, as much of it as the preview shows.

    ``format`` is ``table`` (``columns`` and ``rows``, every cell as text),
    ``text`` (``text``, its first lines) or ``none`` (``reason`` says why, in
    plain words). ``columns_total`` counts every column; ``rows_total`` every
    row, known for a parquet file and for a table read whole, None otherwise.
    ``truncated``: rows, columns, cells or text were cut.
    """

    location: str
    name: str
    size: int | None = None
    format: Literal["table", "text", "none"]
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str | None]] = Field(default_factory=list)
    columns_total: int = 0
    rows_total: int | None = None
    text: str | None = None
    truncated: bool = False
    reason: str | None = None
    # Each column's polars dtype name, read with type inference; only when
    # asked for (``infer_types``) and only for a table.
    dtypes: dict[str, str] | None = None


# ── decoding ─────────────────────────────────────────────────────────────────


def _suffix(name: str) -> str:
    """The last suffix of ``name``, lowercased, ``""`` for none (a dot-name has none)."""
    stem, dot, suffix = name.rpartition(".")
    return f".{suffix.lower()}" if dot and stem else ""


def _gunzip(head: bytes) -> tuple[bytes, bool]:
    """Up to :data:`MAX_GZ_BYTES` of the gzip data ``head`` decompresses to, and
    whether that is all of it.

    Member after member, since a block-gzipped file (``bgzip``) is a series of
    them. A head cut mid-member yields what it holds. ``zlib.error`` when the
    head is not gzip at all; past the first member, unreadable bytes only end
    the output.
    """
    out = bytearray()
    data = head
    while data and len(out) < MAX_GZ_BYTES:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out += decompressor.decompress(data, MAX_GZ_BYTES - len(out))
        except zlib.error:
            if not out:
                raise
            return bytes(out), False
        if not decompressor.eof:
            return bytes(out), False
        data = decompressor.unused_data
    return bytes(out), not data


def _as_text(data: bytes, complete: bool) -> str | None:
    """``data`` as UTF-8 text, None when it is not text (a NUL byte, an invalid sequence).

    A head that stops short of the file may cut a character in two, which is
    left out rather than taken for binary.
    """
    if b"\x00" in data:
        return None
    try:
        return codecs.getincrementaldecoder("utf-8")().decode(data, final=complete)
    except UnicodeDecodeError:
        return None


def _whole_lines(text: str, complete: bool) -> str:
    """``text`` without the line a cut read left incomplete (all of it when complete,
    or when it holds a single line)."""
    if complete or "\n" not in text:
        return text
    return text[: text.rfind("\n") + 1]


def _cell(value: object) -> tuple[str | None, bool]:
    """One cell as text, cut at :data:`MAX_CELL_CHARS`, and whether it was cut."""
    if value is None:
        return None, False
    text = value if isinstance(value, str) else str(value)
    if len(text) <= MAX_CELL_CHARS:
        return text, False
    return f"{text[:MAX_CELL_CHARS]}...", True


# ── the formats ──────────────────────────────────────────────────────────────


def _sniffed_separator(text: str) -> str | None:
    """The separator of a plain text table, or None when it is not one.

    The first of :data:`SNIFFED_SEPARATORS` that splits each of the first
    :data:`SNIFFED_LINES` lines that are not comments (``#``) into the same
    number of fields, at least two.
    """
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    lines = lines[:SNIFFED_LINES]
    if not lines:
        return None
    for separator in SNIFFED_SEPARATORS:
        widths = {len(line.split(separator)) for line in lines}
        if len(widths) == 1 and widths.pop() >= 2:
            return separator
    return None


def _without_leading_comments(text: str, separator: str) -> str:
    """``text`` from its header on: the leading ``#`` lines narrower than its first
    data line are comments (a MultiQC custom-content header, a QIIME 2 feature
    table's ``# Constructed from biom file``), and a ``#`` line as wide is the
    header itself (``#OTU ID``, a VCF's ``#CHROM``)."""
    lines = text.splitlines(keepends=True)
    first = next((line for line in lines if line.strip() and not line.startswith("#")), "")
    width = max(len(first.split(separator)), 2)
    start = 0
    while (
        start < len(lines)
        and lines[start].startswith("#")
        and len(lines[start].split(separator)) < width
    ):
        start += 1
    return "".join(lines[start:])


def _inferred_dtypes(data: bytes, separator: str) -> dict[str, str] | None:
    """Each column's dtype as polars infers it from the head ``data``, or None.

    The preview itself reads every cell as text, so a cell polars cannot type
    never hides the table; this second, typed read only names the types.
    """
    try:
        frame = pl.read_csv(
            io.BytesIO(data),
            separator=separator,
            has_header=True,
            infer_schema_length=INFER_SCHEMA_ROWS,
            truncate_ragged_lines=True,
        )
    except (pl.exceptions.PolarsError, ValueError):
        return None
    return dtype_names(frame.schema)


def dtype_names(schema) -> dict[str, str]:
    """``{column: dtype name}``, the name without its parameters (``Datetime``, not
    ``Datetime(time_unit='us')``), as ``compose.column_types`` names them."""
    return {name: str(dtype).split("(", 1)[0] for name, dtype in schema.items()}


def _table(
    text: str,
    separator: str,
    *,
    complete: bool,
    max_rows: int,
    base: dict,
    infer_types: bool = False,
) -> RunFilePreview | None:
    """``text`` read as a table with a header, None when polars cannot parse it."""
    data = _without_leading_comments(text, separator).encode()
    try:
        frame = pl.read_csv(
            io.BytesIO(data),
            separator=separator,
            has_header=True,
            infer_schema_length=0,
            truncate_ragged_lines=True,
        )
    except (pl.exceptions.PolarsError, ValueError) as exc:
        logger.debug(f"run_file_preview: {base['location']} is not a table: {exc}")
        return None
    if infer_types:
        base = {**base, "dtypes": _inferred_dtypes(data, separator)}
    return _frame_preview(
        frame,
        columns_total=frame.width,
        rows_total=frame.height if complete else None,
        cut=not complete,
        max_rows=max_rows,
        base=base,
    )


def _frame_preview(
    frame: pl.DataFrame,
    *,
    columns_total: int,
    rows_total: int | None,
    cut: bool,
    max_rows: int,
    base: dict,
) -> RunFilePreview:
    """A table preview of the first ``max_rows`` rows and :data:`MAX_PREVIEW_COLUMNS`
    columns of ``frame``, every cell as text.

    ``columns_total`` and ``rows_total`` are those of the file, which ``frame``
    may hold only the start of; ``cut``: some of the file was left unread.
    """
    shown = frame.columns[:MAX_PREVIEW_COLUMNS]
    rows: list[list[str | None]] = []
    cells_cut = False
    for values in frame.select(shown).head(max_rows).rows():
        row: list[str | None] = []
        for value in values:
            text, was_cut = _cell(value)
            row.append(text)
            cells_cut = cells_cut or was_cut
        rows.append(row)
    return RunFilePreview(
        **base,
        format="table",
        columns=shown,
        rows=rows,
        columns_total=columns_total,
        rows_total=rows_total,
        truncated=(
            cut
            or cells_cut
            or columns_total > len(shown)
            or frame.height > max_rows
            or (rows_total is not None and rows_total > max_rows)
        ),
    )


def _text(text: str, *, complete: bool, base: dict) -> RunFilePreview:
    """The first :data:`MAX_TEXT_LINES` lines of ``text``, at most :data:`MAX_TEXT_CHARS`."""
    lines = text.splitlines(keepends=True)
    shown = "".join(lines[:MAX_TEXT_LINES])
    cut = not complete or len(lines) > MAX_TEXT_LINES or len(shown) > MAX_TEXT_CHARS
    return RunFilePreview(**base, format="text", text=shown[:MAX_TEXT_CHARS], truncated=cut)


def _not_shown(reason: str, *, base: dict) -> RunFilePreview:
    return RunFilePreview(**base, format="none", reason=reason)


def _parquet(root, *, max_rows: int, base: dict, infer_types: bool = False) -> RunFilePreview:
    """The schema, the row count and the first rows of a parquet file.

    Through polars, which reads the footer and the row groups the first rows
    are in, never the rest: from the path below a local root, or from the
    ``s3://`` URL with the root's own storage options, so it is read with the
    target the root was listed with. The file was opened through the root
    first, which checks it is there and readable and gives its size.
    """
    if base["size"] is not None and base["size"] > MAX_PARQUET_BYTES:
        return _not_shown(
            f"A parquet file of {base['size']:,} bytes, larger than the "
            f"{MAX_PARQUET_BYTES // (1024 * 1024)} MB this preview opens.",
            base=base,
        )
    try:
        scan = pl.scan_parquet(base["location"], storage_options=root.storage_options())
        schema = scan.collect_schema()
        names = schema.names()
        rows_total = int(scan.select(pl.len()).collect().item())
        frame = scan.select(names[:MAX_PREVIEW_COLUMNS]).head(max_rows).collect()
    except Exception as exc:  # noqa: BLE001 - a preview never fails on a file it cannot parse
        logger.info(f"run_file_preview: cannot read parquet {base['location']}: {exc}")
        return _not_shown("This parquet file could not be read.", base=base)
    if infer_types:
        base = {**base, "dtypes": dtype_names(schema)}
    return _frame_preview(
        frame,
        columns_total=len(names),
        rows_total=rows_total,
        cut=False,
        max_rows=max_rows,
        base=base,
    )


def _decoded_preview(
    data: bytes,
    suffix: str,
    *,
    complete: bool,
    max_rows: int,
    base: dict,
    infer_types: bool = False,
) -> RunFilePreview:
    """The preview of ``data``, the start of a file whose (inner) suffix is ``suffix``:
    a table when it is one, a text when it is text, nothing shown otherwise."""
    if suffix in TABLE_SEPARATORS or suffix in TEXT_SUFFIXES or suffix in SNIFFED_SUFFIXES:
        # Declared text: an invalid byte is replaced rather than refused.
        text = data.decode("utf-8", errors="replace")
    else:
        decoded = _as_text(data, complete)
        if decoded is None:
            return _not_shown(BINARY, base=base)
        text = decoded
    text = _whole_lines(text, complete)
    if suffix in TEXT_SUFFIXES:
        return _text(text, complete=complete, base=base)
    separator = TABLE_SEPARATORS.get(suffix) or _sniffed_separator(text)
    if separator is not None:
        table = _table(
            text,
            separator,
            complete=complete,
            max_rows=max_rows,
            base=base,
            infer_types=infer_types,
        )
        if table is not None:
            return table
    return _text(text, complete=complete, base=base)


# ── one file of a root ───────────────────────────────────────────────────────


def preview_root_file(
    root: DataRoot, relative: str, *, max_rows: int = 20, infer_types: bool = False
) -> RunFilePreview:
    """The preview of the file ``relative`` (root-relative) of ``root``.

    Read through the root alone, so its confinement applies:
    ``FileNotFoundError`` when it is not a file there, ``LocalPathRefused``
    when the server's policy does not let it be read, an S3 error as the root
    raises it. ``infer_types`` adds each column's dtype to a table preview.
    """
    name = relative.rsplit("/", 1)[-1]
    suffix = _suffix(name)
    inner = _suffix(name[: -len(suffix)]) if suffix == ".gz" else suffix
    # Nothing is read of a file that is not shown: the root checks it, and sizes it.
    wanted = 0 if inner in NOT_PREVIEWED or suffix == ".parquet" else MAX_HEAD_BYTES
    head, size = root.read_head(relative, wanted)

    base = {"location": root.url(relative), "name": name, "size": size}
    if suffix == ".parquet":
        return _parquet(root, max_rows=max_rows, base=base, infer_types=infer_types)
    if inner in NOT_PREVIEWED:
        return _not_shown(NOT_PREVIEWED[inner], base=base)

    complete = len(head) >= size if size is not None else len(head) < MAX_HEAD_BYTES
    data = head
    if suffix == ".gz":
        try:
            data, ended = _gunzip(head)
        except zlib.error:
            return _not_shown("This file could not be decompressed.", base=base)
        complete = complete and ended
    return _decoded_preview(
        data, inner, complete=complete, max_rows=max_rows, base=base, infer_types=infer_types
    )
