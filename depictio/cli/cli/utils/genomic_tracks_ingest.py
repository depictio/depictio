"""Upload the local files of a ``genomic_tracks`` data collection to S3.

The manifest itself is ingested like any table (it becomes the DC's Delta
table); this module handles the files its rows point at. A relative track
location is resolved on disk against ``tracks_base_path`` (else the manifest's
own directory) and uploaded, with its index, to the DC's S3 folder under the
same relative path — which is exactly where the API's track proxy looks for it
(``remote_read.resolve_location``). ``s3://`` and ``https://`` locations are
read in place by the API and left alone.

A cheap chromosome-naming check samples the first lines of local text tracks,
so a manifest mixing ``chr1`` and ``1`` is flagged at ingestion rather than
showing up as an empty track in the browser. It only ever warns.
"""

from __future__ import annotations

import gzip
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from depictio.cli.cli.utils import deltatables
from depictio.cli.cli.utils.rich_utils import rich_print_checked_statement
from depictio.cli.cli_logging import logger
from depictio.models.models.cli import CLIConfig
from depictio.models.models.data_collections_types.genomic_tracks import (
    TABIX_FORMATS,
    CustomAssembly,
    DCGenomicTracksConfig,
    genomic_tracks_s3_prefix,
    infer_index_uri,
    infer_track_format,
    is_bgzipped,
)

# Formats whose track cannot be read without its index.
_INDEX_REQUIRED = frozenset({"bam", "cram"})
# Tab-separated text formats whose first column is the sequence name.
_TEXT_FORMATS = TABIX_FORMATS
_CHROM_SAMPLE_LINES = 200
_MAX_HTTPS_PROBES = 10
_UPLOAD_WORKERS = 8


@dataclass(frozen=True)
class TrackUpload:
    """One local file to upload: where it is, where it goes, whether it must exist."""

    local: Path
    key: str
    required: bool
    label: str


class TrackPathError(ValueError):
    """A manifest location that cannot be mapped under the DC's S3 folder."""


def _is_remote(uri: str) -> bool:
    return "://" in uri


def bucket_relative(path: str) -> str:
    """Normalise a relative location the way the API proxy does (no ``..``)."""
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise TrackPathError(
                f"'{path}' escapes its folder; set tracks_base_path so track paths stay below it"
            )
        parts.append(part)
    if not parts:
        raise TrackPathError("empty track path")
    return "/".join(parts)


def _split_s3(folder: str) -> tuple[str, str]:
    bucket, _, prefix = folder[len("s3://") :].partition("/")
    prefix = prefix.strip("/")
    return bucket, f"{prefix}/" if prefix else ""


def _cell(row: dict[str, Any], column: str | None) -> str | None:
    if not column:
        return None
    value = row.get(column)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _base_dir(props: DCGenomicTracksConfig, manifest_dir: Path) -> Path:
    if not props.tracks_base_path:
        return manifest_dir
    base = Path(props.tracks_base_path).expanduser()
    return base if base.is_absolute() else manifest_dir / base


def _props_of(data_collection) -> DCGenomicTracksConfig:
    props = data_collection.config.dc_specific_properties
    if isinstance(props, DCGenomicTracksConfig):
        return props
    if hasattr(props, "model_dump"):
        props = props.model_dump()
    return DCGenomicTracksConfig.model_validate(props or {})


# --------------------------------------------------------------------------
# Planning: manifest rows → uploads
# --------------------------------------------------------------------------


@dataclass
class UploadPlan:
    uploads: dict[str, TrackUpload] = field(default_factory=dict)
    remote_s3: int = 0
    # relative rows read in place under ``remote_base_uri`` (nothing to upload)
    in_place: int = 0
    https_uris: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # local text tracks to sample for the chromosome-naming check
    text_tracks: list[Path] = field(default_factory=list)

    def add(self, location: str, base_dir: Path, prefix: str, required: bool, label: str) -> None:
        try:
            key = prefix + bucket_relative(location)
        except TrackPathError as exc:
            self.errors.append(f"{label}: {exc}")
            return
        existing = self.uploads.get(key)
        if existing is None or (required and not existing.required):
            self.uploads[key] = TrackUpload(base_dir / location, key, required, label)


def plan_track_uploads(
    rows: list[dict[str, Any]],
    props: DCGenomicTracksConfig,
    base_dir: Path,
    prefix: str,
    plan: UploadPlan,
) -> None:
    """Add the uploads the manifest ``rows`` (read from one file) need to ``plan``."""
    for row in rows:
        uri = _cell(row, props.uri_column)
        if not uri:
            continue
        fmt = (_cell(row, props.format_column) or "").lower() or infer_track_format(uri)
        fmt = fmt or props.default_format
        if _is_remote(uri):
            if uri.lower().startswith("https://"):
                plan.https_uris.append(uri)
            else:
                plan.remote_s3 += 1
            continue
        if props.remote_base_uri:
            plan.in_place += 1
            continue

        plan.add(uri, base_dir, prefix, True, uri)
        if not fmt:
            logger.warning(f"genomic_tracks: no format for '{uri}' (set a format column)")
            continue
        if fmt in _TEXT_FORMATS:
            plan.text_tracks.append(base_dir / uri)

        explicit_index = _cell(row, props.index_column)
        if explicit_index:
            if not _is_remote(explicit_index):
                plan.add(explicit_index, base_dir, prefix, True, f"index of {uri}")
            continue
        inferred = infer_index_uri(uri, fmt)
        if inferred:
            required = fmt in _INDEX_REQUIRED or (fmt in TABIX_FORMATS and is_bgzipped(uri))
            plan.add(inferred, base_dir, prefix, required, f"index of {uri}")
        if fmt == "fasta" and is_bgzipped(uri):
            plan.add(f"{uri}.gzi", base_dir, prefix, False, f"gzi of {uri}")


def plan_assembly_uploads(
    assembly: CustomAssembly, base_dir: Path, prefix: str, plan: UploadPlan
) -> None:
    """Add the local files of a custom assembly (same defaults as the API proxy)."""
    fasta = assembly.fasta_uri
    files: list[tuple[str | None, str]] = [
        (fasta, "assembly FASTA"),
        (assembly.fai_uri or (f"{fasta}.fai" if fasta else None), "assembly .fai"),
        (
            assembly.gzi_uri or (f"{fasta}.gzi" if fasta and is_bgzipped(fasta) else None),
            "assembly .gzi",
        ),
        (assembly.twobit_uri, "assembly .2bit"),
        (assembly.chrom_sizes_uri, "assembly chrom.sizes"),
        (assembly.refname_aliases_uri, "assembly refName aliases"),
    ]
    for location, label in files:
        if location and not _is_remote(location):
            plan.add(location, base_dir, prefix, True, label)


# --------------------------------------------------------------------------
# Chromosome naming check (warnings only)
# --------------------------------------------------------------------------


def sample_sequence_names(path: Path, max_lines: int = _CHROM_SAMPLE_LINES) -> set[str]:
    """First-column names of the first ``max_lines`` data lines of a text track."""
    names: set[str] = set()
    opener = gzip.open if is_bgzipped(str(path)) else open
    try:
        with opener(path, "rt", errors="replace") as handle:  # type: ignore[operator]
            seen = 0
            for line in handle:
                if not line.strip() or line.startswith(("#", "track", "browser")):
                    continue
                names.add(line.split("\t", 1)[0].strip())
                seen += 1
                if seen >= max_lines:
                    break
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        logger.debug(f"genomic_tracks: could not sample {path}: {exc}")
    return names


def _reference_names(path: Path) -> set[str]:
    """Sequence names of a local .fai / chrom.sizes file (first column)."""
    try:
        with open(path) as handle:
            return {line.split("\t", 1)[0].strip() for line in handle if line.strip()}
    except OSError:
        return set()


def check_sequence_names(
    text_tracks: list[Path], assembly: str | CustomAssembly, reference: Path | None
) -> list[str]:
    """Warnings about sequence names that are unlikely to match the assembly."""
    warnings: list[str] = []
    known = _reference_names(reference) if reference is not None else set()
    has_aliases = isinstance(assembly, CustomAssembly) and bool(assembly.refname_aliases_uri)
    for path in dict.fromkeys(text_tracks):
        if not path.is_file():
            continue
        names = sample_sequence_names(path)
        if not names:
            continue
        prefixed = sorted(n for n in names if n.lower().startswith("chr"))
        bare = sorted(n for n in names if not n.lower().startswith("chr"))
        if prefixed and bare:
            warnings.append(
                f"{path.name} mixes 'chr'-prefixed ({prefixed[0]}) and bare ({bare[0]}) "
                "sequence names"
            )
        if known and not has_aliases:
            unknown = sorted(names - known)
            if unknown:
                warnings.append(
                    f"{path.name}: {len(unknown)} sequence name(s) not in the assembly "
                    f"(e.g. {', '.join(unknown[:3])}); add refname_aliases_uri to map them"
                )
    return warnings


def _local_reference(assembly: str | CustomAssembly, base_dir: Path) -> Path | None:
    if not isinstance(assembly, CustomAssembly):
        return None
    if assembly.fasta_uri:
        fai = assembly.fai_uri or f"{assembly.fasta_uri}.fai"
        candidate = None if _is_remote(fai) else base_dir / fai
    elif assembly.chrom_sizes_uri and not _is_remote(assembly.chrom_sizes_uri):
        candidate = base_dir / assembly.chrom_sizes_uri
    else:
        candidate = None
    return candidate if candidate is not None and candidate.is_file() else None


# --------------------------------------------------------------------------
# Remote probes and uploads
# --------------------------------------------------------------------------


def probe_https(uris: list[str], timeout: float = 5.0) -> list[str]:
    """HEAD a few remote tracks; return warnings (never fails the ingest)."""
    import httpx

    warnings: list[str] = []
    for uri in list(dict.fromkeys(uris))[:_MAX_HTTPS_PROBES]:
        try:
            resp = httpx.head(uri, timeout=timeout, follow_redirects=False)
        except Exception as exc:  # noqa: BLE001 - network errors of any kind
            warnings.append(f"{uri}: unreachable ({exc.__class__.__name__})")
            continue
        if 300 <= resp.status_code < 400:
            warnings.append(f"{uri}: redirects ({resp.status_code}); the proxy does not follow")
        elif resp.status_code >= 400:
            warnings.append(f"{uri}: answered {resp.status_code}")
    return warnings


def _list_existing_keys(s3_client, bucket: str, prefix: str) -> set[str]:
    from depictio.cli.cli.commands.images import _list_existing_keys as list_keys

    return list_keys(s3_client, bucket, prefix)


def manifests_from_frame(
    df: pl.DataFrame, data_dir: str | Path, run_dirs: list[str] | None = None
) -> list[tuple[list[dict[str, Any]], Path]]:
    """Group a recipe-built manifest by the directory its relative URIs resolve against.

    Single-run recipes resolve against ``data_dir``. Multi-run recipes tag rows
    with ``depictio_run_id`` (the run directory's name); those rows resolve
    against their own run directory.
    """
    base = Path(data_dir).expanduser().resolve()
    by_name = {Path(d).name: Path(d).expanduser().resolve() for d in run_dirs or []}
    if len(by_name) < 2 or "depictio_run_id" not in df.columns:
        return [(df.to_dicts(), base)]
    groups: dict[Path, list[dict[str, Any]]] = {}
    for row in df.to_dicts():
        run_dir = by_name.get(str(row.get("depictio_run_id")), base)
        groups.setdefault(run_dir, []).append(row)
    return [(rows, run_dir) for run_dir, rows in groups.items()]


def _read_manifests(
    files: list, props: DCGenomicTracksConfig
) -> list[tuple[list[dict[str, Any]], Path]]:
    manifests: list[tuple[list[dict[str, Any]], Path]] = []
    for file_info in files:
        df = deltatables.read_single_file_lazy(
            file_info, props.format, dict(props.polars_kwargs)
        ).collect()
        if props.uri_column not in df.columns:
            raise ValueError(
                f"Track manifest {file_info.file_location} has no '{props.uri_column}' "
                "column (uri_column)"
            )
        manifest_dir = Path(file_info.file_location).expanduser().resolve().parent
        manifests.append((df.to_dicts(), manifest_dir))
    return manifests


def upload_genomic_track_files(
    data_collection,
    CLI_config: CLIConfig,
    overwrite: bool = False,
    files: list | None = None,
    manifests: list[tuple[list[dict[str, Any]], Path]] | None = None,
    missing_ok: bool = False,
) -> dict[str, Any]:
    """Upload the local track, index and custom-assembly files of a tracks DC.

    Args:
        data_collection: The ``genomic_tracks`` DataCollection.
        CLI_config: CLI configuration (S3 credentials and bucket).
        overwrite: Re-upload files whose key already exists.
        files: The DC's registered manifest files, when the caller has them.
        manifests: Manifest rows with the directory they resolve against, in
            place of ``files`` (a recipe-built manifest has no file).
        missing_ok: Warn about missing local files instead of failing (recipe
            manifests list what a pipeline *may* have produced).

    Returns:
        Result dict with ``result`` ("success"/"error"), ``message`` and counts.
    """
    dc_id = str(data_collection.id)
    props = _props_of(data_collection)
    default_folder = f"s3://{CLI_config.s3_storage.bucket}/{genomic_tracks_s3_prefix(dc_id)}"
    base_folder = props.s3_base_folder or default_folder
    bucket, prefix = _split_s3(base_folder)
    # The API only serves a custom folder of Depictio's bucket inside the DC's own.
    if (
        not props.remote_base_uri
        and bucket == CLI_config.s3_storage.bucket
        and not base_folder.startswith(default_folder)
    ):
        return {
            "result": "error",
            "message": f"s3_base_folder in Depictio's bucket must be inside {default_folder}",
        }

    if manifests is None:
        if files is None:
            try:
                files = deltatables.fetch_file_data(dc_id, CLI_config)
            except Exception as e:
                return {"result": "error", "message": f"No manifest found for tracks DC: {e}"}
        if not files:
            return {"result": "error", "message": "No manifest found for tracks DC"}
        try:
            manifests = _read_manifests(files, props)
        except Exception as e:
            return {"result": "error", "message": f"Could not read track manifest: {e}"}
    if not manifests:
        return {"result": "error", "message": "No manifest rows for tracks DC"}

    plan = UploadPlan()
    for rows, manifest_dir in manifests:
        if rows and props.uri_column not in rows[0]:
            return {
                "result": "error",
                "message": f"Track manifest has no '{props.uri_column}' column (uri_column)",
            }
        plan_track_uploads(rows, props, _base_dir(props, manifest_dir), prefix, plan)
    first_base = _base_dir(props, manifests[0][1])
    if isinstance(props.assembly, CustomAssembly) and not props.remote_base_uri:
        plan_assembly_uploads(props.assembly, first_base, prefix, plan)

    if plan.in_place:
        rich_print_checked_statement(
            f"{plan.in_place} track(s) read in place under {props.remote_base_uri}", "info"
        )

    missing_required = [u for u in plan.uploads.values() if u.required and not u.local.is_file()]
    missing_optional = [
        u for u in plan.uploads.values() if not u.required and not u.local.is_file()
    ]
    problems = list(plan.errors) + [f"{u.label}: {u.local}" for u in missing_required]
    if problems:
        message = "Genomic tracks: missing or unusable local file(s):\n  " + "\n  ".join(problems)
        if any(u.label.startswith("index of") for u in missing_required):
            message += (
                "\n  (BAM/CRAM and bgzipped BED/VCF/GFF need an index: samtools index, "
                "tabix -p <format>; or set the index column)"
            )
        if not missing_ok:
            rich_print_checked_statement(message, "error")
            return {"result": "error", "message": message}
        rich_print_checked_statement(message, "warning")
    for u in missing_optional:
        logger.warning(f"genomic_tracks: optional {u.label} not found ({u.local}), skipped")

    for warning in check_sequence_names(
        plan.text_tracks, props.assembly, _local_reference(props.assembly, first_base)
    ):
        rich_print_checked_statement(f"Genomic tracks: {warning}", "warning")

    remote = plan.remote_s3 + len(plan.https_uris)
    if remote:
        rich_print_checked_statement(f"{remote} remote track(s), read in place", "info")
    for warning in probe_https(plan.https_uris):
        rich_print_checked_statement(f"Genomic tracks: {warning}", "warning")

    uploads = [u for u in plan.uploads.values() if u.local.is_file()]
    counts = {"uploaded": 0, "skipped": 0, "error": 0}
    if uploads:
        s3_client = deltatables._s3_client(CLI_config)
        existing = set() if overwrite else _list_existing_keys(s3_client, bucket, prefix)

        def _upload_one(item: TrackUpload) -> str:
            if item.key in existing:
                return "skipped"
            try:
                s3_client.upload_file(str(item.local), bucket, item.key)
            except Exception as e:  # noqa: BLE001 - boto raises many types
                logger.error(f"Failed to upload {item.local} to s3://{bucket}/{item.key}: {e}")
                return "error"
            return "uploaded"

        # boto3 low-level clients are thread-safe, so one client is shared.
        with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as executor:
            futures = [executor.submit(_upload_one, u) for u in uploads]
            for future in as_completed(futures):
                counts[future.result()] += 1

    if counts["error"]:
        return {
            "result": "error",
            "message": f"Failed to upload {counts['error']} track file(s) to s3://{bucket}/{prefix}",
            **counts,
        }
    if uploads:
        rich_print_checked_statement(
            f"Track files: {counts['uploaded']} uploaded, {counts['skipped']} already present "
            f"(s3://{bucket}/{prefix})",
            "success",
        )
    return {
        "result": "success",
        "message": f"Track files available under {props.remote_base_uri or base_folder}",
        "remote": remote,
        "in_place": plan.in_place,
        "missing": len(problems),
        **counts,
    }
