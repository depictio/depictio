#!/usr/bin/env python3
"""What a new nf-core release changes for a template, measured, not guessed.

Maintainer/CI tool (not part of the shipped CLI). ``nfcore_monitor.py report``
used to ask the release's megatest run one question per recipe source: is the
path still there? That misses most of what breaks a template between releases.
Take nf-core/ampliseq 2.18 → 3.1: the ASV table was renamed (its recipes fell
back on another table without a word), the top rank column became ``Domain``
(two recipes failed), new ``<rank>_confidence`` columns were summed as samples,
and the Phylum moved one taxonomic level up. A path check saw half of the first.

This module runs the template, exactly as ``depictio ingest`` resolves it, on
the run the template was built on and on the release's run, and compares the
two, layer by layer:

1. **Files** — every data collection and every recipe source: how many files it
   finds in each run. A source that found files and finds none is lost, optional
   or not, with the release's closest new file as the likely rename.
2. **Headers** — the first file of every source, in both runs: columns removed
   (an error when a recipe declares it needs them), added, and renamed in place
   (``Kingdom`` → ``Domain``: same position, one out and one in).
3. **Tables** — every collection is built, scans read and recipes run in
   dependency order (``dc_ref`` chains included), in both runs. A collection
   that built and now fails, or loses a column, is an error; its rows, nulls,
   categories and the sign of its numbers are compared and flagged when they
   move far (a fold change whose sign flips is a convention that changed).
4. **Parameters** — the two releases' ``nextflow_schema.json``: removed, added,
   renamed (same description or same default and a close name), default or
   type changed; and the two runs' own ``params.json`` values, nested ones
   included (a reference database's ``taxlevels``).
5. **Unclaimed outputs** — directories of the release's run that no collection
   reads and that the old run did not have: new outputs a person (or a model)
   decides about.

Every finding is deterministic: the same runs give the same report. What stays
a judgement is what to do with layer 5 and with a layer-3 shift.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

# Read the public megatest bucket anonymously, as a CLI user would. Set before
# depictio's settings are imported: they are read once.
os.environ.setdefault("DEPICTIO_CONTEXT", "cli")
os.environ.setdefault("DEPICTIO_REMOTE_PUBLIC_S3_BUCKETS", "nf-core-awsmegatests")

import polars as pl  # noqa: E402

# Recipe sources above this many bytes in total are not run (their DC, and the
# ones built on it, are reported as skipped): a megatest BAM-sized table would
# take the report hostage.
DEFAULT_MAX_BYTES = 200_000_000
HEADER_BYTES = 65_536
MAX_CATEGORIES = 50
_TEXT_SUFFIXES = (".tsv", ".csv", ".txt", ".tab", ".dpsi", ".tsv.gz", ".csv.gz", ".txt.gz")
_IGNORED_PARAM_VALUE = re.compile(r"^(s3|https?|gs|az)://|^/|\{|\bwork\b")


# ---------------------------------------------------------------------------
# Snapshots: what one run gives the template
# ---------------------------------------------------------------------------
@dataclass
class SourceSnapshot:
    ref: str
    kind: str  # "file" | "collection" | "url"
    pattern: str | None
    found: int | None
    files: list[str] = field(default_factory=list)  # root-relative
    header: list[str] | None = None
    required_columns: list[str] = field(default_factory=list)
    optional: bool = False
    # The reading recipe's source text: a column it names in quotes is one it
    # reads, declared in its input_schema or not.
    recipe_text: str = field(default="", repr=False)


@dataclass
class TableSnapshot:
    status: str  # "ok" | "fail" | "skipped"
    detail: str = ""
    rows: int = 0
    columns: dict[str, str] = field(default_factory=dict)
    null_frac: dict[str, float] = field(default_factory=dict)
    categories: dict[str, list[str]] = field(default_factory=dict)
    medians: dict[str, float] = field(default_factory=dict)
    scales: dict[str, float] = field(default_factory=dict)  # median |x|
    frame: pl.DataFrame | None = field(default=None, repr=False)


@dataclass
class DCSnapshot:
    tag: str
    kind: str  # "scan" | "recipe"
    status: str  # preview status: ok | empty | missing | pruned
    matched: int
    optional: bool = False
    files: list[str] = field(default_factory=list)
    header: list[str] | None = None
    sources: list[SourceSnapshot] = field(default_factory=list)
    table: TableSnapshot | None = None
    upstream: list[str] = field(default_factory=list)  # collections it reads (dc_ref)


@dataclass
class RunSnapshot:
    label: str
    location: str
    keys: list[str]
    variables: dict[str, str]
    dcs: dict[str, DCSnapshot]
    params: dict[str, Any]
    # Headers of files no collection reads, read on demand (rename candidates).
    extra_headers: dict[str, list[str]] = field(default_factory=dict)
    root: Any = field(default=None, repr=False)
    # The template.yaml and its dashboards, as text: what still names a column.
    template_text: str = field(default="", repr=False)

    def header_of(self, rel: str) -> list[str] | None:
        """The header of any file of the run, read once (a rename candidate)."""
        if rel not in self.extra_headers and self.root is not None:
            header = read_header(self.root, rel)
            if header is not None:
                self.extra_headers[rel] = header
        return self.extra_headers.get(rel)


# ---------------------------------------------------------------------------
# Building a snapshot
# ---------------------------------------------------------------------------
def _relative(root: Any, location: str) -> str:
    rel = root.relative_of(location)
    return rel if rel is not None else location


def _split_header(line: str, name: str) -> list[str]:
    sep = "\t" if "\t" in line or not name.endswith(".csv") else ","
    if sep == "," and "\t" in line:
        sep = "\t"
    return [cell.strip().strip('"') for cell in line.rstrip("\r\n").split(sep)]


def read_header(root: Any, rel: str) -> list[str] | None:
    """The column names of a delimited text file (first line), or a parquet's
    schema. None for anything else: a tree, a BAM, an HTML report."""
    name = rel.lower()
    try:
        if name.endswith(".parquet"):
            return list(pl.scan_parquet(root.url(rel), storage_options=root.storage_options())
                        .collect_schema().names())  # fmt: skip
        if not name.endswith(_TEXT_SUFFIXES):
            return None
        head, _ = root.read_head(rel, HEADER_BYTES)
        if name.endswith(".gz"):
            import zlib

            head = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(head)
        text = head.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("##")]
        return _split_header(lines[0], name.removesuffix(".gz")) if lines else None
    except Exception:  # noqa: BLE001 - a header we cannot read is no finding
        return None


def summarise(df: pl.DataFrame, location: str = "") -> TableSnapshot:
    """What a built table looks like, in the terms the comparison reads. Text
    naming the run's own location (a ``source_path``) is read relative to it:
    the two runs live at two locations by definition."""
    if location:
        prefix = location.rstrip("/") + "/"
        df = df.with_columns(
            pl.col(c).str.replace(prefix, "", literal=True)
            for c, t in df.schema.items()
            if t == pl.Utf8
        )
    snap = TableSnapshot(status="ok", rows=df.height)
    for name, dtype in df.schema.items():
        snap.columns[name] = str(dtype)
        if df.height:
            snap.null_frac[name] = df[name].null_count() / df.height
        if dtype == pl.Utf8 or dtype == pl.Categorical:
            values = df[name].drop_nulls().unique()
            if 0 < values.len() <= MAX_CATEGORIES:
                snap.categories[name] = sorted(str(v) for v in values.to_list())
        elif dtype.is_numeric() and dtype != pl.Boolean:
            series = df[name].cast(pl.Float64, strict=False).drop_nulls().drop_nans()
            if series.len():
                snap.medians[name] = float(series.median())  # type: ignore[arg-type]
                snap.scales[name] = float(series.abs().median())  # type: ignore[arg-type]
    snap.frame = df
    return snap


def _files_of(root: Any, pattern: str | None, path: bool) -> list[str]:
    if not pattern or "{" in pattern:
        return []
    rel = _relative(root, pattern)
    if path:
        return [rel] if root.exists(rel) else []
    return root.glob(rel)


def _read_scan(root: Any, dc_config: dict, files: list[str]) -> pl.DataFrame:
    """A scanned Table collection as ingestion reads it (format, polars kwargs,
    wildcard columns), from the files the scan matched."""
    from depictio.cli.cli.utils.deltatables import add_wildcard_columns, read_single_file_lazy

    props = dc_config.get("dc_specific_properties") or {}
    fmt = str(props.get("format") or PurePosixPath(files[0]).suffix.lstrip(".")).lower()
    kwargs = dict(props.get("polars_kwargs") or {})
    infos = [SimpleNamespace(file_location=root.url(rel)) for rel in files]
    frames = [read_single_file_lazy(info, fmt, kwargs) for info in infos]
    frames = add_wildcard_columns(frames, infos, dc_config.get("scan"))
    return pl.concat([f.collect() for f in frames], how="diagonal_relaxed")


def _overrides(dc_config: dict) -> dict[str, str]:
    raw = (dc_config.get("transform") or {}).get("source_overrides") or {}
    out = {}
    for ref, so in raw.items():
        if isinstance(so, dict):
            value = so.get("path") if so.get("path") is not None else so.get("glob_pattern")
        else:
            value = so
        if value:
            out[ref] = str(value)
    return out


def _build_tables(
    config: dict, root: Any, dcs: dict[str, DCSnapshot], max_bytes: int, size: Any = None
) -> None:
    """Build every collection that is a table, in dependency order, and record
    each one's :class:`TableSnapshot` on ``dcs``."""
    from depictio.recipes import execute_recipe, load_recipe

    frames: dict[str, pl.DataFrame] = {}
    pending: list[tuple[dict, str | None]] = []
    for workflow in config.get("workflows") or []:
        version = workflow.get("version") or None
        for dc in workflow.get("data_collections") or []:
            pending.append((dc, version))

    def size_of(files: Iterable[str]) -> int:
        return sum((size or root.size)(f) or 0 for f in files)

    progress = True
    while pending and progress:
        progress = False
        for item in list(pending):
            dc, version = item
            tag = dc.get("data_collection_tag") or ""
            snap = dcs.get(tag)
            dc_config = dc.get("config") or {}
            if snap is None:
                pending.remove(item)
                continue
            dc_type = str(dc_config.get("type") or "").lower()
            if dc_config.get("source") == "transformed" and not dc_config.get("scan"):
                recipe = (dc_config.get("transform") or {}).get("recipe")
                try:
                    module = load_recipe(recipe, version)
                except Exception as exc:  # noqa: BLE001
                    snap.table = TableSnapshot("fail", f"recipe import: {exc}")
                    pending.remove(item)
                    progress = True
                    continue
                refs = [s for s in module.SOURCES if s.dc_ref]
                waiting = [
                    s.dc_ref
                    for s in refs
                    if s.dc_ref not in frames and _still_pending(s.dc_ref, pending, dcs)
                ]
                if waiting:
                    continue
                pending.remove(item)
                progress = True
                missing = [s.dc_ref for s in refs if not s.optional and s.dc_ref not in frames]
                if missing:
                    snap.table = TableSnapshot(
                        "skipped", f"upstream not built: {', '.join(missing)}"
                    )
                    continue
                files = [f for s in snap.sources for f in s.files]
                if size_of(files) > max_bytes:
                    snap.table = TableSnapshot(
                        "skipped", f"sources over {max_bytes // 1_000_000} MB"
                    )
                    continue
                transform = dc_config.get("transform") or {}
                try:
                    df = execute_recipe(
                        recipe,
                        root,
                        overrides=_overrides(dc_config) or None,
                        extra_sources={s.ref: frames[s.dc_ref] for s in refs if s.dc_ref in frames},
                        pipeline_version=version,
                        params={k: str(v) for k, v in (transform.get("params") or {}).items()}
                        or None,
                        properties=dc_config.get("dc_specific_properties") or None,
                    )
                except Exception as exc:  # noqa: BLE001 - the failure is the finding
                    snap.table = TableSnapshot("fail", f"{type(exc).__name__}: {exc}"[:300])
                    continue
                frames[tag] = df
                snap.table = summarise(df, root.location)
            elif dc_type == "table":
                pending.remove(item)
                progress = True
                if snap.status != "ok" or not snap.files:
                    snap.table = TableSnapshot("skipped", f"no file ({snap.status})")
                    continue
                if size_of(snap.files) > max_bytes:
                    snap.table = TableSnapshot("skipped", f"files over {max_bytes // 1_000_000} MB")
                    continue
                try:
                    df = _read_scan(root, dc_config, snap.files)
                except Exception as exc:  # noqa: BLE001
                    snap.table = TableSnapshot("fail", f"{type(exc).__name__}: {exc}"[:300])
                    continue
                frames[tag] = df
                snap.table = summarise(df, root.location)
            else:
                pending.remove(item)
                progress = True


def _still_pending(tag: str, pending: list, dcs: dict[str, DCSnapshot]) -> bool:
    return tag in dcs and any((dc.get("data_collection_tag") == tag) for dc, _ in pending)


def snapshot_run(
    template_id: str,
    location: str,
    variables: dict[str, str] | None = None,
    *,
    label: str = "",
    build: bool = True,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> RunSnapshot:
    """Resolve ``template_id`` against ``location`` (a folder or ``s3://`` prefix)
    as ingestion would, and record what every collection and source finds."""
    from depictio.cli.cli.utils.data_root import as_data_root
    from depictio.cli.cli.utils.template_preview import preview_data_root
    from depictio.cli.cli.utils.templates import _read_run_params, resolve_template

    root = as_data_root(location)
    resolution = resolve_template(
        template_id=template_id, data_root=root, extra_vars=dict(variables or {})
    )
    config, _meta, _origin, _paths, resolved = resolution
    preview = preview_data_root(template_id, root, resolution=resolution)

    recipe_schemas = _recipe_input_columns(config)
    upstream = _upstream(config)
    dcs: dict[str, DCSnapshot] = {}
    scan_files = _scan_files(config, root)
    for row in preview.data_collections:
        snap = DCSnapshot(row.tag, row.kind, row.status, row.matched, row.optional)
        if row.kind == "scan":
            snap.files = scan_files.get(row.tag, [])
            if snap.files:
                snap.header = read_header(root, snap.files[0])
        for src in row.recipe.sources if row.recipe else []:
            files: list[str] = []
            if src.kind == "file":
                is_path = bool(src.pattern) and not any(ch in src.pattern for ch in "*?[")
                files = _files_of(root, src.pattern, is_path)
            source = SourceSnapshot(
                ref=src.ref,
                kind=src.kind,
                pattern=_relative(root, src.pattern) if src.pattern else None,
                found=len(files) if src.kind == "file" else int(bool(src.found)),
                files=files,
                required_columns=recipe_schemas.get((row.tag, src.ref), ([], ""))[0],
                optional=bool(src.optional),
                recipe_text=recipe_schemas.get((row.tag, src.ref), ([], ""))[1],
            )
            if files:
                source.header = read_header(root, files[0])
            snap.sources.append(source)
        snap.upstream = upstream.get(row.tag, [])
        dcs[row.tag] = snap
    if build:
        if getattr(root, "is_remote", False):
            # A remote run is mirrored once: recipes read the same files many
            # times over (sarek's VCFs feed a dozen collections).
            _build_on_mirror(template_id, root, variables, dcs, max_bytes)
        else:
            _build_tables(config, root, dcs, max_bytes)
    try:
        params = _read_run_params(root)
    except Exception:  # noqa: BLE001
        params = {}
    keys = [o.relative for o in getattr(root, "objects", [])] or root.glob("**/*")
    return RunSnapshot(
        label or location, root.location, keys, dict(resolved), dcs, params, root=root,
        template_text=_template_text(template_id),
    )  # fmt: skip


def _template_text(template_id: str) -> str:
    """``template.yaml`` and every dashboard YAML next to it, as one text: a
    column none of them names is one nothing in the template reads."""
    from depictio.cli.cli.utils import templates as templates_mod

    try:
        path = templates_mod.locate_template(template_id)
    except Exception:  # noqa: BLE001 - unknown: every lost column stays an error
        return ""
    files = [path, *sorted(path.parent.glob("dashboards/**/*.yaml"))]
    return "\n".join(f.read_text(errors="replace") for f in files if f.is_file())


def _names(text: str, col: str) -> bool:
    """Whether the YAML ``text`` names ``col`` as a whole scalar: a value
    (``column: sample``, ``- sample``, ``{column: "sample"}``) or a key
    (``"sample": "…"``). Prose does not count: a comment or a description
    that mentions an old column name reads nothing."""
    c = re.escape(col)
    value = rf"[:\-\[,{{]\s*([\"']?){c}\1\s*(?:$|[,}}\]#])"
    key = rf"^\s*(?:-\s+)?([\"']?){c}\2\s*:"
    return re.search(rf"{value}|{key}", text, re.MULTILINE) is not None


def _build_on_mirror(
    template_id: str, root: Any, variables: dict[str, str] | None, dcs: dict[str, DCSnapshot],
    max_bytes: int,
) -> None:  # fmt: skip
    """Download what the collections read (files over ``max_bytes`` left out,
    so the collections reading them are reported skipped), resolve the template
    again on that copy and build the tables there."""
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    from depictio.cli.cli.utils.data_root import as_data_root
    from depictio.cli.cli.utils.templates import resolve_template

    wanted = {f for dc in dcs.values() for f in dc.files}
    wanted |= {f for dc in dcs.values() for s in dc.sources for f in s.files}
    wanted |= {
        o.relative for o in root.objects if o.relative.startswith(("pipeline_info/", "input/"))
    }
    wanted = {f for f in wanted if (root.size(f) or 0) <= max_bytes}

    with tempfile.TemporaryDirectory(prefix="nfcore-drift-") as tmp:
        base = Path(tmp)

        def fetch(rel: str) -> None:
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(root.read_bytes(rel))

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(fetch, sorted(wanted)))
        mirror = as_data_root(str(base))
        config = resolve_template(
            template_id=template_id, data_root=mirror, extra_vars=dict(variables or {})
        )[0]
        # Sizes from the listing: a file left out of the mirror still counts.
        _build_tables(config, mirror, dcs, max_bytes, size=root.size)


def _recipe_input_columns(config: dict) -> dict[tuple[str, str], tuple[list[str], str]]:
    """``(dc_tag, source_ref) -> (declared columns, recipe source text)`` for every
    file source of every recipe."""
    import inspect

    from depictio.recipes import load_recipe

    out: dict[tuple[str, str], tuple[list[str], str]] = {}
    for workflow in config.get("workflows") or []:
        version = workflow.get("version") or None
        for dc in workflow.get("data_collections") or []:
            transform = (dc.get("config") or {}).get("transform") or {}
            if not transform.get("recipe"):
                continue
            try:
                module = load_recipe(transform["recipe"], version)
            except Exception:  # noqa: BLE001
                continue
            try:
                text = inspect.getsource(module)
            except (OSError, TypeError):
                text = ""
            for src in module.SOURCES:
                if src.dc_ref is None:
                    cols = [c for c in (src.input_schema or {}) if c != src.source_path]
                    out[(dc["data_collection_tag"], src.ref)] = (cols, text)
    return out


def _upstream(config: dict) -> dict[str, list[str]]:
    """``dc_tag -> collections its recipe reads`` (``dc_ref`` sources)."""
    from depictio.recipes import load_recipe

    out: dict[str, list[str]] = {}
    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            transform = (dc.get("config") or {}).get("transform") or {}
            if not transform.get("recipe"):
                continue
            try:
                module = load_recipe(transform["recipe"], workflow.get("version") or None)
            except Exception:  # noqa: BLE001
                continue
            out[dc["data_collection_tag"]] = [s.dc_ref for s in module.SOURCES if s.dc_ref]
    return out


def _scan_files(config: dict, root: Any) -> dict[str, list[str]]:
    from depictio.cli.cli.utils.template_preview import scan_dc_hits

    out: dict[str, list[str]] = {}
    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            dc_config = dc.get("config") or {}
            if dc_config.get("source") == "transformed" and not dc_config.get("scan"):
                continue
            scan = dc_config.get("scan") or {}
            mode = str(scan.get("mode") or "").lower()
            tag = dc.get("data_collection_tag") or ""
            if mode in ("single", "url"):
                params = scan.get("scan_parameters") or {}
                location = params.get("filename") or params.get("url") or ""
                rel = root.relative_of(location) if location else None
                out[tag] = [rel] if rel is not None and root.exists(rel) else []
            else:
                out[tag] = scan_dc_hits(dc_config, root, []) or []
    return out


# ---------------------------------------------------------------------------
# Comparing two snapshots
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    level: str  # "error" | "warn" | "info"
    layer: str  # files | headers | tables | params | outputs
    subject: str  # dc tag, dc.source, param name, directory
    message: str
    hint: str = ""

    @property
    def icon(self) -> str:
        return {"error": "❌", "warn": "⚠️", "info": "ℹ️"}[self.level]


def rename_candidates(
    lost: str, old_keys: set[str], new_keys: set[str], limit: int = 2
) -> list[str]:
    """Files only the new run has that most look like ``lost``: same folder
    first, then the closest name with the same extension."""
    lost_path = PurePosixPath(lost)
    suffix = "".join(lost_path.suffixes[-1:])
    fresh = [
        k for k in new_keys - old_keys
        if not k.endswith("/") and not _hidden(k) and "".join(PurePosixPath(k).suffixes[-1:]) == suffix
    ]  # fmt: skip

    def name_ratio(key: str) -> float:
        return difflib.SequenceMatcher(None, lost_path.name, PurePosixPath(key).name).ratio()

    def plausible(key: str) -> bool:
        # The same folder and extension (a file renamed in place, sample names
        # aside), or a close name elsewhere (a file moved).
        return str(PurePosixPath(key).parent) == str(lost_path.parent) or name_ratio(key) >= 0.75

    ranked = sorted(
        (k for k in fresh if plausible(k)),
        key=lambda k: (str(PurePosixPath(k).parent) == str(lost_path.parent), name_ratio(k)),
        reverse=True,
    )
    return ranked[:limit]


def _hidden(key: str) -> bool:
    return any(part.startswith(".") for part in key.split("/"))


def header_changes(
    old: list[str], new: list[str]
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Removed and added columns, and the ones renamed in place: a column gone
    whose position a new column now holds (``Kingdom`` → ``Domain``)."""
    removed = [c for c in old if c not in new]
    added = [c for c in new if c not in old]
    renamed: list[tuple[str, str]] = []
    for col in list(removed):
        i = old.index(col)
        if i < len(new) and new[i] in added:
            renamed.append((col, new[i]))
    for a, b in renamed:
        removed.remove(a)
        added.remove(b)
    return removed, added, renamed


def _added_pattern(added: list[str]) -> str:
    """``domain_confidence, phylum_confidence, ...`` -> ``*_confidence``."""
    if len(added) < 3:
        return ""
    suffix = os.path.commonprefix([c[::-1] for c in added])[::-1]
    prefix = os.path.commonprefix(added)
    if len(suffix) >= 3:
        return f"*{suffix}"
    if len(prefix) >= 3:
        return f"{prefix}*"
    return ""


def compare_runs(old: RunSnapshot, new: RunSnapshot) -> list[Finding]:
    """Every difference between what the template got from ``old`` and from ``new``."""
    findings: list[Finding] = []
    old_keys, new_keys = set(old.keys), set(new.keys)
    lost = {
        tag for tag, o in old.dcs.items()
        if o.status == "ok" and (tag not in new.dcs or new.dcs[tag].status != "ok")
    }  # fmt: skip
    followers: dict[str, list[str]] = {}
    for tag, o in old.dcs.items():
        n = new.dcs.get(tag)
        if n is None:
            findings.append(Finding(
                "warn", "files", tag,
                "collection dropped by the template's conditionals on the release's run",
                "a route variable (from params.json) changed: check the conditionals",
            ))  # fmt: skip
            continue
        if o.status == "ok" and n.status != "ok":
            # A collection built on one that lost its data follows from it:
            # reported once, under the cause, not as a cascade of its own.
            cause = next((u for u in o.upstream if u in lost), None)
            own_source_lost = any(
                (s.found or 0) > 0 and not (_source(n, s.ref).found or 0)
                for s in o.sources if s.kind == "file"
            )  # fmt: skip
            if cause is not None:
                followers.setdefault(_root_cause(cause, old.dcs, lost), []).append(tag)
            elif not own_source_lost:
                findings.append(Finding(
                    "error", "files", tag,
                    f"found its data in {old.label} ({o.matched} file(s)), {n.status} in {new.label}",
                    _hint_for_files(o.files, old_keys, new_keys),
                ))  # fmt: skip
        elif o.kind == "scan" and o.matched and n.matched == 0 and n.status == "ok":
            findings.append(Finding("error", "files", tag, f"{o.matched} file(s) → 0"))
        still_builds = bool(
            o.table and n.table and o.table.status == "ok" and n.table.status == "ok"
        )
        findings += _compare_sources(
            tag, o, n, old_keys, new_keys, old.label, new.label, new.header_of, still_builds
        )
        if o.header and n.header:
            findings += _compare_header(tag, o.header, n.header, [])
        lost_files = tag in lost or any(
            (s.found or 0) > 0 and not (_source(n, s.ref).found or 0)
            for s in o.sources if s.kind == "file"
        )  # fmt: skip
        findings += _compare_tables(
            tag, o.table, n.table, old.label, new.label, explained=lost_files,
            template_text=new.template_text,
        )  # fmt: skip
    for cause, tags in followers.items():
        findings.append(Finding(
            "info", "files", cause, f"{len(tags)} collection(s) built on it follow: {', '.join(tags)}",
        ))  # fmt: skip
    findings += _unclaimed_outputs(old, new)
    findings += compare_run_params(old.params, new.params)
    return findings


def _source(dc: DCSnapshot, ref: str) -> SourceSnapshot:
    return next((s for s in dc.sources if s.ref == ref), SourceSnapshot(ref, "file", None, 0))


def _root_cause(tag: str, dcs: dict[str, DCSnapshot], lost: set[str]) -> str:
    seen = set()
    while tag not in seen:
        seen.add(tag)
        upstream = next((u for u in dcs[tag].upstream if u in lost), None) if tag in dcs else None
        if upstream is None:
            return tag
        tag = upstream
    return tag


def _hint_for_files(files: list[str], old_keys: set[str], new_keys: set[str]) -> str:
    for f in files[:1]:
        candidates = rename_candidates(f, old_keys, new_keys)
        if candidates:
            return f"`{f}` → likely `{candidates[0]}`"
    return ""


def _compare_sources(
    tag: str, o: DCSnapshot, n: DCSnapshot, old_keys: set[str], new_keys: set[str],
    old_label: str, new_label: str, header_of: Any = None, still_builds: bool = False,
) -> list[Finding]:  # fmt: skip
    out: list[Finding] = []
    new_sources = {s.ref: s for s in n.sources}
    seen: set[str | None] = set()
    for so in o.sources:
        sn = new_sources.get(so.ref)
        if sn is None or so.kind != "file" or so.pattern in seen:
            continue
        seen.add(so.pattern)
        subject = f"{tag}.{so.ref}"
        if (so.found or 0) > 0 and not (sn.found or 0):
            what = "optional source" if so.optional else "source"
            out.append(Finding(
                "error", "files", subject,
                f"{what} `{so.pattern}` found {so.found} file(s) in {old_label}, none in {new_label}"
                + (" (the recipe silently uses its fallback)" if so.optional else ""),
                _hint_for_files(so.files, old_keys, new_keys),
            ))  # fmt: skip
            # What the renamed file holds is what the template will read once
            # repointed: compare its header now rather than one release later.
            candidate = (
                (rename_candidates(so.files[0], old_keys, new_keys) or [None])[0]
                if so.files
                else None
            )
            cand_header = header_of(candidate) if candidate and header_of else None
            if cand_header and so.header:
                out += _compare_header(f"{subject} (→ {PurePosixPath(candidate).name})",
                                       so.header, cand_header, so.required_columns, so.recipe_text)  # fmt: skip
        elif not (so.found or 0) and (sn.found or 0):
            out.append(
                Finding(
                    "info", "files", subject, f"source `{sn.pattern}` now finds {sn.found} file(s)"
                )
            )
        if so.header and sn.header:
            out += _compare_header(
                subject, so.header, sn.header, so.required_columns, so.recipe_text, still_builds
            )
    return out


# A header whose columns are data (one per sample, per taxon) changes with the
# data: past this share of changed columns it is summarised, not itemised.
DATA_HEADER_SHARE = 0.5
DATA_HEADER_MIN = 6


def _reads(text: str, col: str) -> bool:
    return bool(text) and (f'"{col}"' in text or f"'{col}'" in text)


def _compare_header(
    subject: str, old: list[str], new: list[str], required: list[str], text: str = "",
    still_builds: bool = False,
) -> list[Finding]:  # fmt: skip
    """``required`` columns are declared by the recipe; a column only quoted in
    its source is ``named``. A named column that left the header is an error
    unless the collection was built on both runs: then the build, which ran the
    recipe, says more than a string search of its source."""
    out: list[Finding] = []
    named = [c for c in old if c not in required and _reads(text, c)]
    if not still_builds:
        required, named = list(required) + named, []
    removed, added, renamed = header_changes(old, new)
    changed = len(set(old) ^ set(new))
    if len(old) >= DATA_HEADER_MIN and changed / max(len(old), len(new)) > DATA_HEADER_SHARE:
        lost = [c for c in required if c not in new]
        if lost:
            out.append(Finding("error", "headers", subject,
                               f"declared column(s) gone: {', '.join(f'`{c}`' for c in lost)}"))  # fmt: skip
        kept = [c for c in old if c in new]
        out.append(Finding(
            "info", "headers", subject,
            f"columns are data ({changed} of {len(set(old) | set(new))} differ; kept: "
            f"{', '.join(f'`{c}`' for c in kept[:5]) or 'none'})",
        ))  # fmt: skip
        return out

    def hint(col: str) -> str:
        if col in required:
            return "the recipe reads it"
        if col in named:
            return "the recipe names it, but the collection still builds"
        return ""

    for a, b in renamed:
        level = "error" if a in required else "warn"
        out.append(Finding(level, "headers", subject,
                           f"column `{a}` became `{b}` (same position)", hint(a)))  # fmt: skip
    for col in removed:
        level = "error" if col in required else "warn"
        out.append(Finding(level, "headers", subject, f"column `{col}` is gone", hint(col)))
    if added:
        pattern = _added_pattern(added)
        shown = ", ".join(f"`{c}`" for c in added[:8]) + (" …" if len(added) > 8 else "")
        out.append(Finding(
            "warn", "headers", subject,
            f"{len(added)} new column(s): {shown}",
            f"a family ({pattern}): a recipe that reads every other column as a sample counts them"
            if pattern else "",
        ))  # fmt: skip
    return out


def _compare_tables(
    tag: str, o: TableSnapshot | None, n: TableSnapshot | None, old_label: str, new_label: str,
    explained: bool = False, template_text: str = "",
) -> list[Finding]:  # fmt: skip
    """``template_text`` is the new template with its dashboards: an output
    column it no longer names was dropped or renamed on purpose (a warning);
    one it still names is read by a link or a figure that now finds nothing."""
    if o is None or n is None or o.status != "ok":
        return []
    if n.status != "ok" and explained:
        return []  # the lost files are the finding
    if n.status != "ok":
        return [
            Finding(
                "error",
                "tables",
                tag,
                f"built in {old_label}, {n.status} in {new_label}: {n.detail}",
            )
        ]
    out: list[Finding] = []
    for col in o.columns:
        if col not in n.columns:
            if template_text and not _names(template_text, col):
                out.append(Finding("warn", "tables", tag, f"output column `{col}` is gone",
                                   "the template no longer names it"))  # fmt: skip
            else:
                out.append(Finding("error", "tables", tag, f"output column `{col}` is gone",
                                   "the template still names it" if template_text else ""))  # fmt: skip
        elif o.columns[col] != n.columns[col]:
            out.append(
                Finding("warn", "tables", tag, f"`{col}`: {o.columns[col]} → {n.columns[col]}")
            )
    if o.rows and n.rows == 0:
        out.append(Finding("error", "tables", tag, f"{o.rows} rows → 0"))
    elif o.rows and (n.rows / o.rows < 0.2 or n.rows / o.rows > 5):
        out.append(Finding("warn", "tables", tag, f"{o.rows} rows → {n.rows}"))
    for col, frac in n.null_frac.items():
        before = o.null_frac.get(col)
        if before is not None and frac - before >= 0.5:
            out.append(Finding("warn", "tables", tag, f"`{col}`: {before:.0%} → {frac:.0%} null"))
    for col, values in o.categories.items():
        after = n.categories.get(col)
        if not after or not values:
            continue
        overlap = len(set(values) & set(after)) / len(set(values) | set(after))
        if overlap < 0.2:
            out.append(Finding(
                "warn", "tables", tag,
                f"`{col}` values changed: {', '.join(values[:4])} → {', '.join(after[:4])}",
            ))  # fmt: skip
    for col, before in o.medians.items():
        after = n.medians.get(col)
        sa, sb = o.scales.get(col) or 0.0, n.scales.get(col) or 0.0
        if after is None or not sa or not sb:
            continue
        # A median far from zero against the column's own scale that changes
        # sign: the whole distribution moved, not noise around zero.
        if (before > 0) != (after > 0) and abs(before) > 0.25 * sa and abs(after) > 0.25 * sb:
            out.append(Finding(
                "warn", "tables", tag, f"`{col}` median changed sign: {before:.3g} → {after:.3g}",
                "a convention may have flipped (treatment/control order, log ratio direction)",
            ))  # fmt: skip
        if max(sa, sb) / min(sa, sb) > 100:
            out.append(
                Finding(
                    "warn",
                    "tables",
                    tag,
                    f"`{col}` scale {sa:.3g} → {sb:.3g} (×100+): a unit changed?",
                )
            )
    out += _paired_values(tag, o.frame, n.frame)
    return out


MIN_PAIRED_ROWS = 30


def _key_columns(a: pl.DataFrame, b: pl.DataFrame) -> list[str] | None:
    """The fewest text columns (one or two) that identify a row in both tables
    and pair enough rows across them: what lets the two runs' values be
    compared row by row (a gene in a contrast, an event, a sample)."""
    text = [c for c, t in a.schema.items() if t == pl.Utf8 and b.schema.get(c) == pl.Utf8]
    text.sort(key=lambda c: -a[c].n_unique())
    candidates: list[list[str]] = [[c] for c in text[:6]]
    candidates += [[x, y] for i, x in enumerate(text[:5]) for y in text[i + 1 : 5]]
    for cols in candidates:
        if a.select(cols).is_duplicated().any() or b.select(cols).is_duplicated().any():
            continue
        shared = a.select(cols).join(b.select(cols), on=cols, how="inner").height
        if shared >= MIN_PAIRED_ROWS and shared >= 0.3 * min(a.height, b.height):
            return cols
    return None


def _paired_values(tag: str, a: pl.DataFrame | None, b: pl.DataFrame | None) -> list[Finding]:
    """Numbers of the same row in both runs: anti-correlated means the
    convention flipped (a log ratio, a delta PSI now oriented the other way)."""
    if a is None or b is None or not a.height or not b.height:
        return []
    keys = _key_columns(a, b)
    if keys is None:
        return []
    numeric = [
        c for c, t in a.schema.items()
        if c not in keys and t.is_numeric() and t != pl.Boolean and b.schema.get(c, pl.Null).is_numeric()
    ]  # fmt: skip
    if not numeric:
        return []
    joined = a.select(keys + numeric).join(
        b.select(keys + numeric), on=keys, how="inner", suffix="__new"
    )
    out = []
    for col in numeric:
        pair = (
            joined.select(
                pl.col(col).cast(pl.Float64, strict=False).alias("x"),
                pl.col(f"{col}__new").cast(pl.Float64, strict=False).alias("y"),
            )
            .drop_nulls()
            .drop_nans()
        )
        if pair.height < MIN_PAIRED_ROWS or pair["x"].std() == 0 or pair["y"].std() == 0:
            continue
        r = pair.select(pl.corr("x", "y")).item()
        if r is not None and r < -0.5:
            out.append(Finding(
                "warn", "tables", tag,
                f"`{col}` anti-correlated with the old run on {pair.height} rows paired by "
                f"{', '.join(keys)} (r = {r:.2f})",
                "the sign convention flipped (ordination axes flip freely: ignore those)",
            ))  # fmt: skip
    return out


STRUCTURE_DEPTH = 2


def _dirs(keys: Iterable[str], depth: int = STRUCTURE_DEPTH) -> set[str]:
    out = set()
    for key in keys:
        parts = key.split("/")[:-1]
        for level in range(1, min(len(parts), depth) + 1):
            out.add("/".join(parts[:level]) + "/")
    return out


# Folders of a run that are not pipeline outputs: the user's sheets a fetch or
# a CI run copies in, and the run's own bookkeeping.
_NOT_OUTPUTS = {"input", "pipeline_info"}


def _unclaimed_outputs(old: RunSnapshot, new: RunSnapshot) -> list[Finding]:
    """Folders of the release's run that the old run lacked and no collection reads."""
    read = {f for dc in new.dcs.values() for f in dc.files}
    read |= {f for dc in new.dcs.values() for s in dc.sources for f in s.files}
    read_dirs = _dirs(read, depth=10)
    fresh = sorted(
        d for d in _dirs(new.keys) - _dirs(old.keys)
        if not _hidden(d) and d.split("/")[0] not in _NOT_OUTPUTS
    )  # fmt: skip
    out = []
    for d in fresh:
        if d in read_dirs or any(d.startswith(p) for p in fresh if p != d and d.startswith(p)):
            continue
        n_files = sum(1 for k in new.keys if k.startswith(d) and not k.endswith("/"))
        if n_files:
            out.append(Finding(
                "info", "outputs", d, f"new in the release, read by no collection ({n_files} file(s))",
                "a new output: a collection to add, or nothing to do",
            ))  # fmt: skip
    return out


# ---------------------------------------------------------------------------
# Parameters: the two schemas and the two runs' values
# ---------------------------------------------------------------------------
def schema_params(schema: dict) -> dict[str, dict]:
    """Every parameter of an nf-core ``nextflow_schema.json``, by name."""
    out: dict[str, dict] = {}
    groups = list((schema.get("definitions") or schema.get("$defs") or {}).values())
    groups.append(schema)
    for group in groups:
        for name, spec in (group.get("properties") or {}).items():
            if isinstance(spec, dict) and "properties" not in spec:
                out[name] = spec
    return out


def compare_schemas(old: dict, new: dict, read_by_template: Iterable[str] = ()) -> list[Finding]:
    """Removed, added and renamed parameters; changed defaults and types."""
    a, b = schema_params(old), schema_params(new)
    read = set(read_by_template)
    gone = [p for p in a if p not in b]
    fresh = [p for p in b if p not in a]
    out: list[Finding] = []
    pairs: dict[str, str] = {}
    for p in gone:
        best, best_score = None, 0.0
        for q in fresh:
            if q in pairs.values():
                continue
            desc = difflib.SequenceMatcher(
                None, str(a[p].get("description", "")), str(b[q].get("description", ""))
            ).ratio()
            name = difflib.SequenceMatcher(None, p.lower(), q.lower()).ratio()
            same_default = "default" in a[p] and a[p].get("default") == b[q].get("default")
            score = max(desc, name) + (0.2 if same_default else 0)
            if score > best_score:
                best, best_score = q, score
        if best is not None and best_score >= 0.75:
            pairs[p] = best
    for p in gone:
        level = "error" if p in read else "warn"
        if p in pairs:
            out.append(Finding(level, "params", p, f"renamed `--{pairs[p]}`?"))
        else:
            out.append(Finding(level, "params", p, "removed"))
    for q in fresh:
        if q in pairs.values():
            continue
        level = "warn" if q.startswith(("skip_", "run_")) else "info"
        out.append(
            Finding(
                level,
                "params",
                q,
                f"new ({b[q].get('type', '?')}, default {b[q].get('default')!r})",
            )
        )
    for p in set(a) & set(b):
        da, db = a[p].get("default"), b[p].get("default")
        if da != db:
            level = (
                "error" if p in read else ("warn" if p.startswith(("skip_", "run_")) else "info")
            )
            out.append(Finding(level, "params", p, f"default {da!r} → {db!r}"))
        if a[p].get("type") != b[p].get("type"):
            out.append(
                Finding("warn", "params", p, f"type {a[p].get('type')} → {b[p].get('type')}")
            )
    return out


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    return {prefix: value}


def compare_run_params(old: dict, new: dict) -> list[Finding]:
    """Values the two runs' ``params.json`` disagree on, nested ones included:
    what the run actually used (a database's ``taxlevels``), not what the schema
    says. Paths, URLs and timestamps differ every run and are left out."""
    if not old or not new:
        return []
    a, b = _flatten(old), _flatten(new)
    changes: dict[tuple[str, str], list[str]] = {}
    for key in sorted(set(a) & set(b)):
        va, vb = a[key], b[key]
        if va == vb or any(_IGNORED_PARAM_VALUE.search(str(v)) for v in (va, vb) if v is not None):
            continue
        if key.split(".")[0] in _RUN_SPECIFIC_PARAMS or key.rsplit(".", 1)[-1] in _PROSE_FIELDS:
            continue
        sa, sb = json.dumps(va), json.dumps(vb)
        if max(len(sa), len(sb)) > 160:
            continue
        changes.setdefault((sa, sb), []).append(key)
    out = []
    for (sa, sb), keys in changes.items():
        subject = keys[0] if len(keys) == 1 else f"{keys[0]} (+{len(keys) - 1} like it)"
        out.append(Finding("info", "params", subject, f"run value {sa} → {sb}"))
    return out


# Values that differ every run, and descriptive fields of reference-database
# catalogues: never a change in what the pipeline computes.
_RUN_SPECIFIC_PARAMS = {
    "outdir", "input", "trace_report_suffix", "config_profile_name",
    "config_profile_description", "custom_config_version", "custom_config_base",
}  # fmt: skip
_PROSE_FIELDS = {"citation", "title", "dbversion", "fmtscript", "file", "doi", "url", "description"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
LAYER_TITLES = {
    "files": "Files the collections find",
    "headers": "Columns of the files read",
    "tables": "Collections built on both runs",
    "params": "Parameters",
    "outputs": "New outputs no collection reads",
}


def _merge(findings: list[Finding]) -> list[Finding]:
    """One line for one change seen by several collections (a file four recipes read)."""
    merged: dict[tuple[str, str, str, str], Finding] = {}
    for f in findings:
        key = (f.level, f.layer, f.message, f.hint)
        if key in merged:
            merged[key].subject += f"`, `{f.subject}"
        else:
            merged[key] = Finding(f.level, f.layer, f.subject, f.message, f.hint)
    return list(merged.values())


def render(findings: list[Finding], old_label: str, new_label: str, limit: int = 40) -> list[str]:
    errors = sum(f.level == "error" for f in findings)
    warns = sum(f.level == "warn" for f in findings)
    lines = [
        f"## Differential ingestion — {old_label} → {new_label}: "
        f"{errors} error(s), {warns} warning(s)"
    ]
    if not findings:
        lines += ["- the template finds, reads and builds the same on both runs", ""]
        return lines
    findings = _merge(findings)
    for layer, title in LAYER_TITLES.items():
        group = [f for f in findings if f.layer == layer]
        if not group:
            continue
        group.sort(key=lambda f: ("error", "warn", "info").index(f.level))
        lines.append(f"### {title}")
        for f in group[:limit]:
            line = f"- {f.icon} `{f.subject}` — {f.message}"
            if f.hint:
                line += f" · _{f.hint}_"
            lines.append(line)
        if len(group) > limit:
            lines.append(f"- … and {len(group) - limit} more")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def diff_runs(
    template_id: str,
    old_location: str,
    new_location: str,
    variables: dict[str, str] | None = None,
    *,
    old_label: str = "old run",
    new_label: str = "new run",
    old_schema: dict | None = None,
    new_schema: dict | None = None,
    params_read: Iterable[str] = (),
    build: bool = True,
    max_bytes: int = DEFAULT_MAX_BYTES,
    new_template_id: str | None = None,
) -> tuple[list[Finding], list[str]]:
    """The findings and the rendered ``## Differential ingestion`` section.

    ``new_template_id`` runs another template on the new run: a version bump's
    copy, as edited for the release, against the template it was copied from on
    its own run. A path the copy already fixed is then no finding."""
    old = snapshot_run(
        template_id, old_location, variables, label=old_label, build=build, max_bytes=max_bytes
    )
    new = snapshot_run(
        new_template_id or template_id, new_location, variables,
        label=new_label, build=build, max_bytes=max_bytes,
    )  # fmt: skip
    findings = compare_runs(old, new)
    if old_schema and new_schema:
        findings += compare_schemas(old_schema, new_schema, params_read)
    return findings, render(findings, old_label, new_label)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--template", required=True, help="template id, e.g. nf-core/ampliseq/2.18.0"
    )
    parser.add_argument(
        "--old", required=True, help="run the template was built on (folder or s3://)"
    )
    parser.add_argument("--new", required=True, help="the new release's run (folder or s3://)")
    parser.add_argument(
        "--new-template", help="template run on --new (default: --template), e.g. a bump's copy"
    )
    parser.add_argument(
        "--var", action="append", default=[], help="KEY=VALUE, as for depictio ingest"
    )
    parser.add_argument("--no-build", action="store_true", help="files and headers only")
    parser.add_argument("--max-mb", type=float, default=DEFAULT_MAX_BYTES / 1e6)
    args = parser.parse_args(argv)
    variables = dict(v.split("=", 1) for v in args.var)
    findings, lines = diff_runs(
        args.template, args.old, args.new, variables,
        build=not args.no_build, max_bytes=int(args.max_mb * 1e6),
        new_template_id=args.new_template,
    )  # fmt: skip
    print("\n".join(lines))
    return 1 if any(f.level == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
