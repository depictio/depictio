"""Genome-browser tracks for the builder: their formats, a manifest made from
picked track files, and the checks a manifest gets before it is ingested.

A ``genomic_tracks`` collection reads a *manifest*: a table with one row per
track and the track's location in a ``uri`` column. Track files themselves are
never scanned. The builder can write that manifest from files the user ticks
(``manifest_for``), and ``check_manifest`` reads one back the way ingestion
will, so a missing file, an index left behind or a format nobody can infer
shows before the project exists rather than as an empty browser after.

Format and index inference are the genomic tracks model's own when this
Depictio has it; the copies below are what the builder uses until then, kept
to the same rules.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import PurePosixPath
from typing import Any

from depictio.cli.cli.utils.compose import slug
from depictio.cli.cli.utils.data_root import DataRoot
from depictio.cli.cli.utils.file_preview import preview_root_file
from depictio.models.local_access import LocalPathRefused
from depictio.project_builder.capabilities import genomic_tracks_model
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.roots import confine_rel

MANIFEST_COLUMNS = ("track_id", "sample", "format", "uri", "index_uri", "name")
MAX_MANIFEST_FILES = 2000
# Manifest rows read back for the checks; a manifest is one row per track.
MAX_CHECKED_ROWS = 5000
MAX_LISTED = 50

_EXTENSION_FORMATS: tuple[tuple[str, str], ...] = (
    (".narrowpeak.gz", "narrowpeak"),
    (".broadpeak.gz", "broadpeak"),
    (".bedgraph.gz", "bedgraph"),
    (".gff3.gz", "gff3"),
    (".gff.gz", "gff3"),
    (".gtf.gz", "gtf"),
    (".vcf.gz", "vcf"),
    (".bed.gz", "bed"),
    (".fasta.gz", "fasta"),
    (".fa.gz", "fasta"),
    (".fna.gz", "fasta"),
    (".narrowpeak", "narrowpeak"),
    (".broadpeak", "broadpeak"),
    (".bedgraph", "bedgraph"),
    (".bigwig", "bigwig"),
    (".bigbed", "bigbed"),
    (".fasta", "fasta"),
    (".gff3", "gff3"),
    (".cram", "cram"),
    (".gff", "gff3"),
    (".gtf", "gtf"),
    (".vcf", "vcf"),
    (".bam", "bam"),
    (".bed", "bed"),
    (".bw", "bigwig"),
    (".bb", "bigbed"),
    (".fna", "fasta"),
    (".fa", "fasta"),
)
_INDEX_SUFFIX = {"bam": ".bai", "cram": ".crai"}
_TABIX_FORMATS = frozenset({"bed", "bedgraph", "narrowpeak", "broadpeak", "vcf", "gff3", "gtf"})
# An index the browser cannot do without: range reads of BAM/CRAM and of
# bgzipped tabix files. A plain-text BED/VCF is read whole, and a FASTA is
# reference material, not a track.
_REQUIRED_INDEX = frozenset({"bam", "cram"})
_REMOTE = re.compile(r"^(s3|https?)://", re.IGNORECASE)


def infer_track_format(uri: str) -> str | None:
    """A track's format from its name; None when it has no known extension."""
    module = genomic_tracks_model()
    if module is not None and hasattr(module, "infer_track_format"):
        return module.infer_track_format(uri)
    path = uri.split("?", 1)[0].split("#", 1)[0].lower()
    for suffix, fmt in _EXTENSION_FORMATS:
        if path.endswith(suffix):
            return fmt
    return None


def infer_index_uri(uri: str, fmt: str) -> str | None:
    """Where a track's index conventionally sits, or None when it needs none."""
    module = genomic_tracks_model()
    if module is not None and hasattr(module, "infer_index_uri"):
        return module.infer_index_uri(uri, fmt)
    if fmt in _INDEX_SUFFIX:
        return uri + _INDEX_SUFFIX[fmt]
    if fmt in _TABIX_FORMATS and uri.lower().endswith(".gz"):
        return uri + ".tbi"
    if fmt == "fasta":
        return uri + ".fai"
    return None


def index_required(uri: str, fmt: str) -> bool:
    """Whether the browser can only read the track through its index."""
    return fmt in _REQUIRED_INDEX or (fmt in _TABIX_FORMATS and uri.lower().endswith(".gz"))


def _track_stem(name: str) -> str:
    lowered = name.lower()
    for suffix, _fmt in _EXTENSION_FORMATS:
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return PurePosixPath(name).stem


def _sample_of(rel: str, sample_regex: re.Pattern[str] | None) -> str:
    name = PurePosixPath(rel).name
    if sample_regex is not None:
        for candidate in (name, rel):
            found = sample_regex.search(candidate)
            if found and found.groupdict().get("sample"):
                return found.group("sample")
    return _track_stem(name)


def manifest_for(
    root: DataRoot, files: list[str], sample_regex: str | None = None
) -> dict[str, Any]:
    """A track manifest for ``files`` (root-relative), uris relative to the data root.

    One row per file of a known track format; index files the user ticked are
    taken as indexes, not tracks. ``sample_regex`` (a ``(?P<sample>…)`` group)
    names each track's sample, else the file name without its extension does.
    """
    if not files:
        raise BuilderRefused(422, "Pick at least one track file.", "tracks_none")
    if len(files) > MAX_MANIFEST_FILES:
        raise BuilderRefused(
            422, f"At most {MAX_MANIFEST_FILES} track files per manifest.", "tracks_too_many"
        )
    compiled = None
    if sample_regex:
        try:
            compiled = re.compile(sample_regex)
        except (re.error, OverflowError, RecursionError) as exc:
            raise BuilderRefused(
                422, f"Invalid sample regex: {exc}", "sample_regex_invalid"
            ) from exc
        if "sample" not in compiled.groupindex:
            raise BuilderRefused(
                422, "The sample regex needs a group named sample.", "sample_regex_invalid"
            )

    picked = list(dict.fromkeys(confine_rel(rel) for rel in files if rel))
    index_names = {
        rel
        for rel in picked
        if PurePosixPath(rel).suffix.lower() in (".bai", ".crai", ".tbi", ".csi", ".fai", ".gzi")
    }
    rows: list[dict[str, str]] = []
    warnings: list[str] = []
    used_ids: set[str] = set()
    skipped: list[str] = []
    missing_index: list[str] = []
    for rel in picked:
        if rel in index_names:
            continue
        fmt = infer_track_format(rel)
        if fmt is None:
            skipped.append(rel)
            continue
        if not root.exists(rel):
            raise BuilderRefused(404, f"'{rel}' is not a file of the data root.", "file_missing")
        index = infer_index_uri(rel, fmt)
        index_uri = index if index and (index in index_names or root.exists(index)) else ""
        if not index_uri and index_required(rel, fmt):
            missing_index.append(rel)
        base = slug(_track_stem(PurePosixPath(rel).name), 48) or "track"
        track_id, n = base, 2
        while track_id in used_ids:
            track_id, n = f"{base}_{n}", n + 1
        used_ids.add(track_id)
        rows.append(
            {
                "track_id": track_id,
                "sample": _sample_of(rel, compiled),
                "format": fmt,
                "uri": rel,
                "index_uri": index_uri,
                "name": _track_stem(PurePosixPath(rel).name),
            }
        )
    if skipped:
        warnings.append(
            f"{len(skipped)} file(s) of no known track format left out: "
            + ", ".join(skipped[:5])
            + ("…" if len(skipped) > 5 else "")
        )
    if missing_index:
        warnings.append(
            f"{len(missing_index)} track(s) need an index that is not next to them (.bai, "
            ".crai or .tbi): "
            + ", ".join(missing_index[:5])
            + ("…" if len(missing_index) > 5 else "")
        )
    if not rows:
        raise BuilderRefused(422, "None of the picked files is a track.", "tracks_none")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=MANIFEST_COLUMNS, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return {
        "columns": list(MANIFEST_COLUMNS),
        "rows": rows,
        "tsv": buffer.getvalue(),
        "warnings": warnings,
    }


def _resolve(base: str, uri: str) -> str | None:
    """A relative ``uri`` as a root-relative path under ``base``; None when it leaves the root."""
    parts: list[str] = []
    for part in f"{base}/{uri}".split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def check_manifest(
    root: DataRoot,
    manifest: str,
    *,
    uri_column: str = "uri",
    format_column: str | None = "format",
    index_column: str | None = "index_uri",
    default_format: str | None = None,
    tracks_base: str | None = None,
) -> dict[str, Any]:
    """What ingestion will make of the manifest ``manifest`` (root-relative).

    ``tracks_base``: the root-relative folder relative uris resolve against
    (default: the manifest's folder, as at ingestion). Files are looked for
    under a local root only; an ``s3://`` root's tracks are read in place.
    """
    try:
        preview = preview_root_file(root, manifest, max_rows=MAX_CHECKED_ROWS)
    except (FileNotFoundError, LocalPathRefused) as exc:
        raise BuilderRefused(
            404, f"Cannot read the manifest {manifest}: {exc}", "file_missing"
        ) from exc
    columns = list(preview.columns or [])
    result: dict[str, Any] = {
        "rows": preview.rows_total if preview.rows_total is not None else len(preview.rows or []),
        "columns": columns,
        # Only the head of a large manifest is read: the checks cover the rows shown.
        "truncated": preview.truncated,
        "missing_uri_column": uri_column not in columns,
        "unknown_format": [],
        "duplicate_uris": [],
        "missing_files": [],
        "missing_indexes": [],
        "absolute_uris": [],
    }
    if preview.format != "table" or result["missing_uri_column"]:
        return result
    base = tracks_base if tracks_base is not None else str(PurePosixPath(manifest).parent)
    base = "" if base == "." else base.strip("/")
    seen: set[str] = set()
    for row in [dict(zip(columns, values)) for values in preview.rows or []]:
        uri = str(row.get(uri_column) or "").strip()
        if not uri:
            continue
        if uri in seen and uri not in result["duplicate_uris"]:
            result["duplicate_uris"].append(uri)
        seen.add(uri)
        fmt = str(row.get(format_column) or "").strip().lower() if format_column else ""
        fmt = fmt or infer_track_format(uri) or (default_format or "")
        if not fmt:
            result["unknown_format"].append(uri)
            continue
        if uri.startswith("/") or uri.lower().startswith("file:"):
            result["absolute_uris"].append(uri)
            continue
        if _REMOTE.match(uri) or root.is_remote:
            continue
        rel = _resolve(base, uri)
        if rel is None or not root.exists(rel):
            result["missing_files"].append(uri)
            continue
        index = str(row.get(index_column) or "").strip() if index_column else ""
        index_rel = _resolve(base, index) if index else None
        if index_rel is None:
            inferred = infer_index_uri(rel, fmt)
            index_rel = inferred if inferred and index_required(rel, fmt) else None
            if index_rel is None:
                continue
        if not root.exists(index_rel):
            result["missing_indexes"].append(uri)
    for key in (
        "unknown_format",
        "duplicate_uris",
        "missing_files",
        "missing_indexes",
        "absolute_uris",
    ):
        result[key] = result[key][:MAX_LISTED]
    return result
