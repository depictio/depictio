"""Compose a Depictio template from a results directory, the way MultiQC builds its report.

When no bundled template fits a run, ``depictio run --data-root`` (and
``depictio template compose``) asks the catalog which files it recognises and
writes an ordinary template for them: a ``template.yaml`` (one workflow, one
data collection per recognised output) and ``dashboards/composed.yaml`` (an
Overview tab, one tab per pipeline stage present, a MultiQC tab). Everything
downstream is the template path every bundled pipeline already takes:
``resolve_template``, ingestion, dashboard import.

What the composer decides, deterministically:

- **Files.** One walk of the directory; each catalog ``find`` is matched against
  it. Every ``multiqc.parquet`` becomes a MultiQC collection whatever its
  folder, and its plots are read off the report itself.
- **Collections.** A raw output is scanned as is. A recipe output becomes a
  transformed collection whose sources are pointed at the files actually there
  (``source_overrides``), and whose ``dc_ref`` dependencies are tagged the way
  the recipe expects. Every composed collection is ``optional``: one that fails
  to ingest is skipped, and the import drops its tiles, instead of the run
  failing.
- **Tiles.** Each output's ``renders_as`` entries, checked against the columns
  the collection will have. Headline cards also go to the Overview, beside the
  MultiQC General Statistics and a per-sample table joined across tools.
- **Order.** Tabs follow the catalog's ``stage`` vocabulary; sections follow
  tools; the layout is ``compose_layout``.
- **The rest.** Tabular files no output recognises are reported with a
  proposal, and only added (to an "Other data" tab) when asked for.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from depictio.cli.cli.utils.compose_layout import layout_dashboard
from depictio.cli.cli.utils.multiqc_parquet import (
    MultiQCPlot,
    parquet_has_general_stats,
    parquet_plots,
)
from depictio.cli.cli_logging import logger
from depictio.models.components.advanced_viz.catalog import (
    STAGE_LABELS,
    STAGE_ORDER,
    CatalogEntry,
    CatalogMatch,
    CatalogOutput,
    Render,
    load_catalog_entries,
)

DASHBOARD_FILE = "dashboards/composed.yaml"
GENERAL_STATS_FILE = "general_stats.tsv"
MULTIQC_REPORT = "multiqc.parquet"
# Above this many files, a collection scans a glob regex instead of listing them.
MAX_LISTED_FILES = 20
MAX_UNRECOGNISED = 50
SAMPLE_COLUMNS = ("sample", "sample_id", "sampleid", "sample_name", "samplename", "id")
MAX_FILTER_VALUES = 50

TABULAR = {
    ".csv": ("csv", ","),
    ".tsv": ("tsv", "\t"),
    ".tab": ("tsv", "\t"),
    ".txt": ("tsv", "\t"),
    ".parquet": ("parquet", None),
}
STAGE_STYLE: dict[str, tuple[str, str]] = {
    "qc": ("mdi:check-decagram", "teal"),
    "alignment": ("mdi:dna", "blue"),
    "quantification": ("mdi:chart-bar", "cyan"),
    "peaks": ("mdi:chart-bell-curve", "grape"),
    "variants": ("mdi:dna", "red"),
    "fusions": ("mdi:set-merge", "pink"),
    "taxonomy": ("mdi:bacteria-outline", "green"),
    "annotation": ("mdi:file-document-outline", "violet"),
    "immune": ("mdi:account-group-outline", "indigo"),
    "differential": ("mdi:scale-balance", "orange"),
    "benchmarking": ("mdi:shield-check-outline", "yellow"),
    "other": ("mdi:folder-outline", "gray"),
}
# Directories never walked: hidden ones, and Nextflow's scratch area.
_SKIPPED_TOP_DIRS = {"work"}
# Where tabular files are bookkeeping, not results.
_NOT_RESULTS = {"pipeline_info"}


# ---------------------------------------------------------------------------
# Walking and matching
# ---------------------------------------------------------------------------


def walk(data_root: Path) -> list[str]:
    """Every file under ``data_root`` as a sorted POSIX path relative to it."""
    found: list[str] = []
    root = data_root.resolve()
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        parts = rel.parts
        if any(p.startswith(".") for p in parts) or (parts and parts[0] in _SKIPPED_TOP_DIRS):
            continue
        if path.is_file():
            found.append(rel.as_posix())
    return sorted(found)


def _segment_regex(segment: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(segment):
        ch = segment[i]
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        elif ch == "[" and "]" in segment[i + 2 :]:
            end = segment.index("]", i + 2)
            body = segment[i + 1 : end]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = end
        else:
            out.append(re.escape(ch))
        i += 1
    return "".join(out)


def glob_regex(pattern: str) -> str:
    """A regex matching relative POSIX paths the way ``Path.glob(pattern)`` does."""
    parts = [p for p in pattern.split("/") if p]
    out: list[str] = []
    for i, part in enumerate(parts):
        if part == "**":
            out.append("(?:[^/]+/)*")
        else:
            out.append(_segment_regex(part) + ("/" if i < len(parts) - 1 else ""))
    return "^" + "".join(out) + "$"


def filename_regex(pattern: str) -> str:
    """A regex matching relative paths whose basename matches ``pattern`` (``rglob``)."""
    return "^(?:.*/)?" + _segment_regex(pattern) + "$"


def include_regex(pattern: str) -> str:
    """A regex for an ``--include`` glob, read the way a person means it.

    A pattern with no ``/`` matches a file name at any depth (``'*.tsv'``), and a
    trailing ``**`` takes every file below (``'amp/**'``); otherwise it is
    ``Path.glob``'s pattern, relative to the results directory.
    """
    if "/" not in pattern:
        return filename_regex(pattern)
    if pattern.rstrip("/").endswith("**"):
        return glob_regex(pattern.rstrip("/") + "/*")
    return glob_regex(pattern)


def find_regexes(output: CatalogOutput) -> list[str]:
    find = output.find
    if find.path_glob:
        return [glob_regex(g) for g in find.path_globs()]
    if find.filename:
        return [filename_regex(find.filename)]
    return []


def match_files(
    files: Sequence[str], entries: Iterable[CatalogEntry] | None = None
) -> list[CatalogMatch]:
    """``match_run_dir`` over an already-walked file list: one walk, not one per output."""
    matches: list[CatalogMatch] = []
    for entry in entries if entries is not None else load_catalog_entries():
        for output in entry.outputs:
            regexes = [re.compile(r) for r in find_regexes(output)]
            renders = [
                f"{r.component}:{r.kind}" if r.kind else str(r.component) for r in output.renders_as
            ]
            for path in files:
                if any(r.match(path) for r in regexes):
                    matches.append(
                        CatalogMatch(
                            tool_id=entry.id,
                            output_id=output.id,
                            path=path,
                            mode=output.mode,
                            renders=renders,
                        )
                    )
    return matches


# ---------------------------------------------------------------------------
# Reading tables
# ---------------------------------------------------------------------------


def _dtype_name(dtype: Any) -> str:
    return str(dtype).split("(", 1)[0]


def table_format(path: str) -> tuple[str, str | None] | None:
    return TABULAR.get(PurePosixPath(path).suffix.lower())


def read_sample(path: Path, rows: int = 1000, has_header: bool = True):  # -> pl.DataFrame | None
    """The first ``rows`` rows of a tabular file, or None when it cannot be read as one."""
    import polars as pl

    fmt = table_format(path.name)
    if fmt is None:
        return None
    try:
        if fmt[0] == "parquet":
            return pl.read_parquet(path, n_rows=rows)
        frame = pl.read_csv(
            path,
            separator=fmt[1] or ",",
            n_rows=rows,
            infer_schema_length=rows,
            truncate_ragged_lines=True,
            has_header=has_header,
        )
    except Exception as exc:
        logger.debug(f"Could not read {path} as a table: {exc}")
        return None
    # A `.txt` that is not tab-separated reads as one wide column: not a table.
    return frame if frame.width >= 2 else None


def column_types(frame) -> dict[str, str]:
    return {name: _dtype_name(dtype) for name, dtype in frame.schema.items()}


_COLUMN_TYPE = {
    "String": "object",
    "Utf8": "object",
    "Categorical": "category",
    "Enum": "category",
    "Boolean": "bool",
    "Date": "datetime",
    "Datetime": "datetime",
    "Duration": "timedelta",
}


def column_type(dtype: str | None) -> str | None:
    """A polars dtype name as a component's ``column_type``; None when it has no equivalent."""
    if not dtype:
        return None
    if dtype.startswith(("Int", "UInt")):
        return "int64"
    if dtype.startswith("Float") or dtype.startswith("Decimal"):
        return "float64"
    return _COLUMN_TYPE.get(dtype)


def _sample_column(columns: Iterable[str]) -> str | None:
    lowered = {c.lower(): c for c in columns}
    return next((lowered[name] for name in SAMPLE_COLUMNS if name in lowered), None)


def slug(text: str, length: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:length] or "x"


def pretty(column: str) -> str:
    words = column.replace("_", " ").replace(".", " ").split()
    text = " ".join(words)
    return text[:1].upper() + text[1:] if text else column


_AGG_TITLE = {
    "average": "Mean {}",
    "median": "Median {}",
    "sum": "Total {}",
    "min": "Min {}",
    "max": "Max {}",
    "count": "{} count",
    "nunique": "Distinct {}",
    "range": "{} range",
}


def card_title(column: str, aggregation: str) -> str:
    label = pretty(column)
    template = _AGG_TITLE.get(aggregation, "{} (" + aggregation + ")")
    title = template.format(label if template.startswith("{}") else label.lower())
    return title[:1].upper() + title[1:]


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@dataclass
class Collection:
    """One data collection of the composed template and what it can show."""

    tag: str
    kind: str  # multiqc | raw | recipe | provider | unknown | general_stats
    config: dict[str, Any]
    description: str
    stage: str = "other"
    tool: CatalogEntry | None = None
    outputs: list[CatalogOutput] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)
    aliases: set[str] = field(default_factory=set)
    needs: list[str] = field(default_factory=list)
    renamed: bool = False
    plots: list[MultiQCPlot] = field(default_factory=list)
    general_stats: bool = False
    recipe: str | None = None
    overrides: dict[str, dict[str, str]] = field(default_factory=dict)

    def to_template(self) -> dict[str, Any]:
        return {
            "data_collection_tag": self.tag,
            "description": self.description,
            "optional": True,
            "config": self.config,
        }


def _scan(files: Sequence[str]) -> dict[str, Any]:
    """Scan exactly these files: a single scan for one, an anchored regex for several."""
    if len(files) == 1:
        return {"mode": "single", "scan_parameters": {"filename": "{DATA_ROOT}/" + files[0]}}
    if len(files) <= MAX_LISTED_FILES:
        pattern = "^(?:" + "|".join(re.escape(f) for f in files) + ")$"
    else:
        pattern = _common_glob_regex(files)
    return {"mode": "recursive", "scan_parameters": {"regex_config": {"pattern": pattern}}}


def _common_glob_regex(files: Sequence[str]) -> str:
    """A regex for many files: their common directory and suffix, anything in between."""
    parents = {str(PurePosixPath(f).parent) for f in files}
    suffix = PurePosixPath(files[0]).suffix
    if len(parents) == 1:
        parent = next(iter(parents))
        prefix = "" if parent == "." else re.escape(parent) + "/"
        return "^" + prefix + "[^/]+" + re.escape(suffix) + "$"
    return "^(?:.*/)?[^/]+" + re.escape(suffix) + "$"


def _table_config(files: Sequence[str]) -> dict[str, Any]:
    fmt, separator = table_format(files[0]) or ("tsv", "\t")
    properties: dict[str, Any] = {"format": fmt}
    if separator:
        properties["polars_kwargs"] = {"separator": separator}
    config: dict[str, Any] = {
        "type": "Table",
        "scan": _scan(files),
        "dc_specific_properties": properties,
    }
    if len(files) > 1:
        config["metatype"] = "Aggregate"
    return config


def _output_label(output: CatalogOutput) -> str:
    return output.name or pretty(output.id)


@dataclass
class Skipped:
    what: str
    why: str


@dataclass
class Composition:
    """What the composer recognised and decided, before anything is written."""

    data_root: Path
    files: list[str]
    collections: list[Collection]
    skipped: list[Skipped]
    unrecognised: list[dict[str, Any]]  # UnrecognisedFile dumps + private keys
    unrecognised_total: int

    @property
    def recognised(self) -> list[Collection]:
        return [c for c in self.collections if c.kind in ("raw", "recipe", "multiqc")]


def _multiqc_collections(files: Sequence[str], data_root: Path) -> list[Collection]:
    reports = [f for f in files if PurePosixPath(f).name == MULTIQC_REPORT]
    collections: list[Collection] = []
    for i, report in enumerate(reports):
        path = data_root / report
        plots = parquet_plots(path)
        general = parquet_has_general_stats(path)
        if not plots and not general:
            continue
        tag = "multiqc_data" if not collections else f"multiqc_data_{i + 1}"
        collections.append(
            Collection(
                tag=tag,
                kind="multiqc",
                description=f"MultiQC report ({report})",
                config={
                    "type": "MultiQC",
                    "scan": {
                        "mode": "recursive",
                        "scan_parameters": {
                            "regex_config": {"pattern": "^" + re.escape(report) + "$"}
                        },
                    },
                    "dc_specific_properties": {},
                },
                stage="qc",
                files=[report],
                plots=plots,
                general_stats=general,
            )
        )
    return collections


def _raw_collection(
    entry: CatalogEntry, output: CatalogOutput, files: list[str], data_root: Path
) -> Collection | Skipped:
    if table_format(files[0]) is None:
        return Skipped(output.id, f"{files[0]}: not a format the scan reads (csv, tsv, parquet)")
    frame = read_sample(data_root / files[0], rows=200)
    if frame is None:
        return Skipped(output.id, f"{files[0]} could not be read as a table")
    return Collection(
        tag=output.id,
        kind="raw",
        description=f"{_output_label(output)} ({entry.name}), recognised by the catalog",
        config=_table_config(files),
        stage=entry.stage_of(output),
        tool=entry,
        outputs=[output],
        files=files,
        columns=column_types(frame),
        aliases={output.id, output.id.removeprefix(f"{entry.id}_")},
    )


def _find_patterns(output: CatalogOutput) -> list[str]:
    if output.find.path_glob:
        return output.find.path_globs()
    if output.find.filename:
        return ["**/" + output.find.filename]
    return []


def _resolve_recipe_sources(
    recipe: str,
    outputs: list[CatalogOutput],
    matched: list[str],
    file_set: set[str],
) -> tuple[dict[str, dict[str, str]], set[str], list[str]]:
    """Point a recipe's sources at the files present.

    Returns ``(source_overrides, files_read, required_dc_refs)``; raises
    ``ValueError`` naming the source that cannot be satisfied. A source whose
    default path or glob is there needs nothing. Otherwise the matched file says
    where the tool's outputs live: its path minus a source's default path is a
    prefix every sibling path source is re-rooted under, and a glob source falls
    back to the catalog's own ``find`` pattern.
    """
    from depictio.recipes import load_recipe

    module = load_recipe(recipe)
    sources = list(module.SOURCES)
    overrides: dict[str, dict[str, str]] = {}
    used: set[str] = set()

    for source in sources:
        if not source.glob_pattern:
            continue
        regex = re.compile(glob_regex(source.glob_pattern))
        hits = [f for f in sorted(file_set) if regex.match(f)]
        if hits:
            used.update(hits)
            continue
        for pattern in (p for o in outputs for p in _find_patterns(o)):
            alt = re.compile(glob_regex(pattern))
            hits = [f for f in sorted(file_set) if alt.match(f)]
            if hits:
                overrides[source.ref] = {"glob_pattern": pattern}
                used.update(hits)
                break
        else:
            if not source.optional:
                raise ValueError(f"no file for its '{source.ref}' source ({source.glob_pattern})")

    path_sources = [s for s in sources if s.path]
    required = [s for s in path_sources if not s.optional]
    if all(s.path in file_set for s in required):
        used.update(s.path for s in path_sources if s.path in file_set)
    else:
        resolved: dict[str, str] | None = None
        for found in matched:
            for source in path_sources:
                assert source.path is not None
                if found == source.path or found.endswith("/" + source.path):
                    prefix = found[: len(found) - len(source.path)]
                    candidate = {s.ref: prefix + str(s.path) for s in path_sources}
                    if all(candidate[s.ref] in file_set for s in required):
                        resolved = candidate
                        break
            if resolved:
                break
        if resolved is None and len(required) == 1:
            only = required[0]
            name = PurePosixPath(str(only.path)).name
            same = [f for f in matched if PurePosixPath(f).name == name]
            if same:
                resolved = {only.ref: same[0]}
        if resolved is None:
            missing = next(s for s in required if s.path not in file_set)
            raise ValueError(f"its '{missing.ref}' file ({missing.path}) is not in this directory")
        for source in path_sources:
            target = resolved.get(source.ref)
            if target and target in file_set:
                if target != source.path:
                    overrides[source.ref] = {"path": target}
                used.add(target)
            elif source.path in file_set:
                used.add(str(source.path))

    needs = [s.dc_ref for s in sources if s.dc_ref and not s.optional]
    return overrides, used, needs


def _recipe_columns(recipe: str) -> dict[str, str]:
    from depictio.recipes import load_recipe

    module = load_recipe(recipe)
    columns = {name: _dtype_name(dtype) for name, dtype in module.OUTPUT_SCHEMA.items()}
    for name, dtype in (getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None) or {}).items():
        columns.setdefault(name, _dtype_name(dtype))
    return columns


def _recipe_collection(
    recipe: str,
    members: list[tuple[CatalogEntry, CatalogOutput, list[str]]],
    file_set: set[str],
) -> tuple[Collection | Skipped, set[str]]:
    entry, first, _ = members[0]
    outputs = [o for _, o, _ in members]
    matched = sorted({f for _, _, files in members for f in files})
    try:
        overrides, used, needs = _resolve_recipe_sources(recipe, outputs, matched, file_set)
        columns = _recipe_columns(recipe)
    except Exception as exc:
        return Skipped(first.id, f"recipe {recipe}: {exc}"), set()
    transform: dict[str, Any] = {"recipe": recipe}
    if overrides:
        transform["source_overrides"] = overrides
    aliases = {Path(recipe).stem}
    for e, o, _ in members:
        aliases |= {o.id, o.id.removeprefix(f"{e.id}_")}
    collection = Collection(
        tag=first.id,
        kind="recipe",
        description=", ".join(_output_label(o) for o in outputs) + f" ({entry.name}, {recipe})",
        config={
            "type": "Table",
            "source": "transformed",
            "transform": transform,
            "dc_specific_properties": {"format": "tsv"},
        },
        stage=entry.stage_of(first),
        tool=entry,
        outputs=outputs,
        files=matched,
        columns=columns,
        aliases=aliases,
        needs=needs,
        recipe=recipe,
        overrides=overrides,
    )
    return collection, used


def _resolve_dependencies(
    collections: list[Collection], skipped: list[Skipped]
) -> list[Collection]:
    """Tag each recipe's required ``dc_ref`` provider as it expects, then order providers first.

    A provider is another composed collection known under that name (its recipe
    stem or output id); failing that, the recipe's own matched files scanned as
    is (the ``<output>_raw`` pattern). A recipe whose dependency cannot be met is
    dropped, and so is anything that depended on it.
    """
    pool = list(collections)
    changed = True
    while changed:
        changed = False
        for collection in list(pool):
            for ref in collection.needs:
                provider = next((c for c in pool if c is not collection and c.tag == ref), None)
                if provider is None:
                    provider = next(
                        (
                            c
                            for c in pool
                            if c is not collection and ref in c.aliases and not c.renamed
                        ),
                        None,
                    )
                    if provider is not None:
                        provider.tag = ref
                        provider.renamed = True
                if provider is None and collection.files and table_format(collection.files[0]):
                    if collection.tag == ref:
                        # The recipe reads a collection named like its own output
                        # (mosdepth's): the raw scan takes the name, the recipe moves.
                        collection.tag = f"{ref}_view"
                    provider = Collection(
                        tag=ref,
                        kind="provider",
                        description=f"Raw input of {collection.tag}",
                        config=_table_config(collection.files),
                        stage=collection.stage,
                        tool=collection.tool,
                        files=collection.files,
                        aliases={ref},
                        renamed=True,
                    )
                    pool.append(provider)
                    changed = True
                if provider is None:
                    pool.remove(collection)
                    skipped.append(
                        Skipped(collection.tag, f"needs the '{ref}' collection, not found")
                    )
                    changed = True
                    break
            if changed:
                break

    ordered: list[Collection] = []
    remaining = list(pool)
    while remaining:
        ready = [c for c in remaining if all(any(o.tag == ref for o in ordered) for ref in c.needs)]
        if not ready:  # a cycle: keep declaration order rather than loop forever
            ready = remaining[:1]
        for c in ready:
            ordered.append(c)
            remaining.remove(c)
    return ordered


def _unique_tags(collections: list[Collection]) -> None:
    seen: set[str] = set()
    for collection in collections:
        tag, n = collection.tag, 2
        while tag in seen:
            tag, n = f"{collection.tag}_{n}", n + 1
        collection.tag = tag
        seen.add(tag)


def _is_results_file(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return not any(p in _NOT_RESULTS for p in parts)


def compose_run(
    data_root: str | Path,
    include_unknown: bool = False,
    include: Sequence[str] = (),
    entries: Sequence[CatalogEntry] | None = None,
) -> Composition:
    """Decide the composed project for ``data_root`` (nothing is written)."""
    root = Path(data_root).resolve()
    files = walk(root)
    file_set = set(files)
    entries = list(entries if entries is not None else load_catalog_entries())
    skipped: list[Skipped] = []

    collections = _multiqc_collections(files, root)
    used: set[str] = {f for c in collections for f in c.files}
    # Everything next to a MultiQC report is the report's own data dump.
    report_dirs = {str(PurePosixPath(f).parent) for f in used}

    by_output: dict[tuple[str, str], list[str]] = {}
    for match in match_files(files, entries):
        by_output.setdefault((match.tool_id, match.output_id), []).append(match.path)

    recipes: dict[str, list[tuple[CatalogEntry, CatalogOutput, list[str]]]] = {}
    for entry in entries:
        for output in entry.outputs:
            matched = by_output.get((entry.id, output.id))
            if not matched:
                continue
            if output.recipe:
                recipes.setdefault(output.recipe, []).append((entry, output, matched))
                continue
            if all(PurePosixPath(f).name == MULTIQC_REPORT for f in matched):
                continue  # a MultiQC section: read off the report above
            built = _raw_collection(entry, output, sorted(matched), root)
            if isinstance(built, Skipped):
                skipped.append(built)
                continue
            collections.append(built)
            used.update(built.files)

    for recipe, members in sorted(recipes.items()):
        built, read = _recipe_collection(recipe, members, file_set)
        if isinstance(built, Skipped):
            skipped.append(built)
            continue
        collections.append(built)
        used.update(read)
        used.update(built.files)

    collections = _resolve_dependencies(collections, skipped)
    _unique_tags(collections)

    candidates = [
        f
        for f in files
        if f not in used
        and table_format(f) is not None
        and _is_results_file(f)
        and str(PurePosixPath(f).parent) not in report_dirs
    ]
    include_regexes = [re.compile(include_regex(g)) for g in include]
    shapes = {
        path: shape
        for path in candidates[:MAX_SCANNED]
        if (shape := file_shape(root, path)) is not None
    }
    unrecognised: list[dict[str, Any]] = []
    for group in group_files(shapes, files):
        # The listing is capped; a file asked for by name is not.
        named = any(r.match(f) for f in group.files for r in include_regexes)
        if len(unrecognised) >= MAX_UNRECOGNISED and not named:
            if not include_regexes:
                break
            continue
        proposal = propose_group(root, group)
        if proposal is None:
            continue
        wanted = include_unknown or named
        proposal["_include"] = wanted
        unrecognised.append(proposal)
        if wanted:
            collections.append(_unknown_collection(proposal))
    _unique_tags(collections)
    return Composition(
        data_root=root,
        files=files,
        collections=collections,
        skipped=skipped,
        unrecognised=unrecognised,
        unrecognised_total=len(candidates),
    )


# ---------------------------------------------------------------------------
# Unrecognised files
# ---------------------------------------------------------------------------


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def distinct_labels(paths: Sequence[str]) -> list[str]:
    """The part of each path that tells it apart from the others.

    ``test_aws/multiqc/multiqc_data/multiqc.parquet`` and
    ``test_full_aws/multiqc/multiqc_data/multiqc.parquet`` give ``test_aws`` and
    ``test_full_aws``: the directories every path shares, at the start or the
    end, are dropped. A path left with nothing keeps its parent directory.
    """
    parts = [PurePosixPath(p).parts for p in paths]
    if len(parts) < 2:
        return [str(PurePosixPath(p).parent) for p in paths]
    shortest = min(len(p) for p in parts)
    head = 0
    while head < shortest and len({p[head] for p in parts}) == 1:
        head += 1
    tail = 0
    while tail < shortest - head and len({p[len(p) - 1 - tail] for p in parts}) == 1:
        tail += 1
    labels = []
    for path, p in zip(paths, parts):
        middle = p[head : len(p) - tail]
        labels.append("/".join(middle) if middle else str(PurePosixPath(path).parent))
    return labels


def looks_headerless(columns: Sequence[str]) -> bool:
    """Whether a table's "header" is really its first data row.

    Kraken-style reports and per-read outputs have no header row: read with one,
    their column names are numbers (``100.00``, ``438151``) or duplicates that
    polars renames ``<name>_duplicated_<n>``.
    """
    suspicious = [c for c in columns if _is_number(c) or "_duplicated_" in c]
    return len(suspicious) * 2 >= len(columns)


def _is_identifier(column: str) -> bool:
    """`taxonomy_id`, `taxID`, `gene_id`: numeric labels, not quantities to average."""
    return bool(re.search(r"(?:^|[_\-\s.])id$", column, re.IGNORECASE)) or bool(
        re.search(r"[a-z]I[dD]$", column)
    )


# Files of one shape, one per sample, are one collection with the sample read
# off their paths. Nothing here knows a tool: only where paths differ, what the
# files share, and their columns.

_SEPARATORS = "._-"
MAX_SCANNED = 2000
MAX_WILDCARD_VALUES = 500
MAX_GROUP_READ = 20


@dataclass
class FileGroup:
    """Unrecognised files of one shape: a single file, or one file per sample.

    ``pattern`` is the scan regex, ``{wildcard}`` standing where the paths
    differ; ``values`` is what stands there for each file.
    """

    files: list[str]
    wildcard: str | None = None
    pattern: str | None = None
    values: list[str] = field(default_factory=list)
    glob: str = ""
    label: str = ""

    @property
    def wildcard_regex(self) -> str:
        if len(self.values) > MAX_WILDCARD_VALUES:
            return "[^/]+?"
        return "|".join(re.escape(v) for v in sorted(set(self.values), key=len, reverse=True))


def _common_suffix(texts: Sequence[str]) -> str:
    """The longest end every text shares, started at a separator.

    ``s10.tsv`` and ``s20.tsv`` share ``.tsv``, not ``0.tsv``: a shared end
    that starts mid-word belongs to what differs.
    """
    suffix = texts[0]
    for text in texts[1:]:
        n = 0
        while n < min(len(suffix), len(text)) and suffix[-1 - n] == text[-1 - n]:
            n += 1
        suffix = suffix[len(suffix) - n :] if n else ""
    i = 0
    while i < len(suffix) and suffix[i] not in _SEPARATORS:
        i += 1
    return suffix[i:]


def _common_prefix(texts: Sequence[str]) -> str:
    """The longest start every text shares, ended at a separator (``MOCK_`` of ``MOCK_001``)."""
    prefix = texts[0]
    for text in texts[1:]:
        n = 0
        while n < min(len(prefix), len(text)) and prefix[n] == text[n]:
            n += 1
        prefix = prefix[:n]
    end = max((prefix.rfind(c) for c in _SEPARATORS), default=-1)
    return prefix[: end + 1]


def _as_group(paths: Sequence[str], wildcard: str) -> FileGroup | None:
    """``paths`` as one group, when one value per file is all that tells them apart.

    The value may appear in several places of a path (``ERZ01/ERZ01.txt``),
    each followed by an end the files share; anything else differing between
    them (two values, an empty one, two files with the same one) is not a group.
    """
    split = [PurePosixPath(p).parts for p in paths]
    varying = [i for i in range(len(split[0])) if len({parts[i] for parts in split}) > 1]
    if not varying:
        return None
    ends = {i: _common_suffix([parts[i] for parts in split]) for i in varying}
    values: list[str] = []
    for parts in split:
        cores = {parts[i][: len(parts[i]) - len(ends[i])] for i in varying}
        if len(cores) != 1:
            return None
        value = cores.pop()
        if not value or "/" in value:
            return None
        values.append(value)
    if len(set(values)) != len(values):
        return None
    start = _common_prefix(values)
    pattern, glob = [], []
    for i, segment in enumerate(split[0]):
        if i in ends:
            pattern.append(f"{{{wildcard}}}" + re.escape(ends[i]))
            glob.append(start + "*" + ends[i])
        else:
            pattern.append(re.escape(segment))
            glob.append(segment)
    return FileGroup(
        files=list(paths),
        wildcard=wildcard,
        pattern="^" + "/".join(pattern) + "$",
        values=values,
        glob="/".join(glob),
    )


def _pattern_regex(group: FileGroup) -> re.Pattern[str]:
    """The group's pattern as a regex: one value, the same wherever it appears."""
    placeholder = f"{{{group.wildcard}}}"
    regex = (group.pattern or "").replace(placeholder, "(?P<v>[^/]+?)", 1)
    return re.compile(regex.replace(placeholder, "(?P=v)"))


def _split_bucket(members: list[str], wildcard: str) -> list[FileGroup]:
    """Files of one shape, split into groups by the patterns that cover most of them.

    Candidate patterns come from pairs of files: each file with the next one,
    and with the first file of the next directory. The pattern covering the
    most files is taken first; on a tie, the one whose value appears in more
    places (``{sample}/{sample}.txt`` over ``ERZ01/{sample}.txt``).
    """
    ordered = sorted(members)
    parents = [str(PurePosixPath(p).parent) for p in ordered]
    next_dir = [len(ordered)] * len(ordered)
    for i in range(len(ordered) - 2, -1, -1):
        next_dir[i] = i + 1 if parents[i + 1] != parents[i] else next_dir[i + 1]
    candidates: dict[str, FileGroup] = {}
    for i, path in enumerate(ordered):
        for j in {i + 1, next_dir[i]}:
            if j < len(ordered):
                pair = _as_group([path, ordered[j]], wildcard)
                if pair and pair.pattern:
                    candidates.setdefault(pair.pattern, pair)
    regexes = {pattern: _pattern_regex(pair) for pattern, pair in candidates.items()}
    remaining = list(ordered)
    groups: list[FileGroup] = []
    while candidates and len(remaining) > 1:
        best: tuple[tuple[int, int], str, list[str]] | None = None
        for pattern in candidates:
            covered = [p for p in remaining if regexes[pattern].match(p)]
            key = (len(covered), pattern.count("{"))
            if len(covered) > 1 and (best is None or key > best[0]):
                best = (key, pattern, covered)
        if best is None:
            break
        _, pattern, covered = best
        del candidates[pattern]
        group = _as_group(covered, wildcard)
        if group is None:
            continue
        groups.append(group)
        taken = set(covered)
        remaining = [p for p in remaining if p not in taken]
    return groups + [FileGroup(files=[p], glob=p) for p in remaining]


def _contexts(value: str, path: str) -> set[str]:
    """The path segments ``value`` stands in, as whole words, each with it blanked out."""
    found = set()
    for segment in PurePosixPath(path).parts:
        for match in re.finditer(re.escape(value), segment):
            before = segment[match.start() - 1] if match.start() else ""
            after = segment[match.end()] if match.end() < len(segment) else ""
            if (not before or before in _SEPARATORS) and (not after or after in _SEPARATORS):
                found.add(segment[: match.start()] + "{}" + segment[match.end() :])
    return found


def _names_samples(group: FileGroup, all_files: Sequence[str]) -> bool:
    """Whether what tells the group's files apart is a sample.

    A sample's name turns up elsewhere in the run under another kind of name
    (``ERZ01.txt`` here, ``ERZ01.normalized.tsv`` there); variants of one
    output (``salmon.merged.gene_counts.tsv``, ``…gene_tpm.tsv``) only ever
    appear as themselves. Most of the values must turn up so.
    """
    own = set(group.files)
    checked = group.values[:20]
    found = 0
    for value in checked:
        mine = set().union(*(_contexts(value, p) for p in group.files))
        if any(
            _contexts(value, path) - mine for path in all_files if path not in own and value in path
        ):
            found += 1
    return found * 2 > len(checked)


def _name_wildcard(group: FileGroup, columns: Sequence[str], all_files: Sequence[str]) -> None:
    """``sample`` when the paths name samples the rows do not, else ``file``."""
    if not group.wildcard or not group.pattern:
        return
    samples = not _sample_column(columns) and _names_samples(group, all_files)
    name = "sample" if samples else "file"
    group.pattern = group.pattern.replace(f"{{{group.wildcard}}}", f"{{{name}}}")
    group.wildcard = name


def group_files(
    shapes: dict[str, tuple[Any, ...]], all_files: Sequence[str] = ()
) -> list[FileGroup]:
    """Unrecognised tabular files, grouped by shape.

    ``shapes`` maps each path to what its contents look like (its columns).
    Files of the same depth, extension and columns are one group when a single
    value tells them apart (``{sample}/{sample}.txt``); failing that, they are
    split by the patterns that cover most of them, and a file no pattern
    covers stands alone.
    """
    buckets: dict[tuple[Any, ...], list[str]] = {}
    for path, shape in shapes.items():
        posix = PurePosixPath(path)
        buckets.setdefault((len(posix.parts), posix.suffix.lower(), shape), []).append(path)
    groups: list[FileGroup] = []
    for (_, _, shape), members in buckets.items():
        members = sorted(members)
        columns = shape[1] if shape and shape[0] == "named" else ()
        whole = _as_group(members, "value") if len(members) > 1 else None
        found = [whole] if whole else []
        if not whole and len(members) > 1:
            found = _split_bucket(members, "value")
        elif not whole:
            found = [FileGroup(files=members, glob=members[0])]
        for group in found:
            _name_wildcard(group, columns, all_files or list(shapes))
        groups.extend(found)
    groups.sort(key=lambda g: g.files[0])
    _label_groups(groups)
    return groups


def _group_label(group: FileGroup) -> str:
    """A short name: the file's name, or for a group its directory and kind.

    ``arg/abricate/*/*.txt`` is ``abricate``; ``bracken-db/*.bracken.tsv`` is
    ``bracken-db · bracken``: the last literal directory, then the last word of
    the name the files share, before its extension.
    """
    if len(group.files) == 1:
        return PurePosixPath(group.files[0]).name
    parts = PurePosixPath(group.glob).parts
    directories = [p for p in parts[:-1] if "*" not in p]
    directory = directories[-1] if directories else ""
    name = parts[-1]
    if "*" in name:
        tokens = [t.strip(_SEPARATORS) for t in name.split("*")[-1].split(".")[:-1]]
        kind = next((t for t in reversed(tokens) if t), "")
    else:
        kind = PurePosixPath(name).stem
    words = [directory] if directory else []
    if kind and kind != directory:
        words.append(kind)
    return " · ".join(words) or "files"


def _label_groups(groups: list[FileGroup]) -> None:
    for group in groups:
        group.label = _group_label(group)
    by_label: dict[str, list[FileGroup]] = {}
    for group in groups:
        by_label.setdefault(group.label, []).append(group)
    for same in by_label.values():
        if len(same) < 2:
            continue
        for group, where in zip(same, distinct_labels([g.glob for g in same])):
            group.label = f"{group.label} ({where})"


def file_shape(data_root: Path, path: str) -> tuple[Any, ...] | None:
    """What a file's contents look like, to group it: its columns, or how many."""
    head = read_sample(data_root / path, rows=20)
    if head is None:
        return None
    if looks_headerless(head.columns):
        return ("headerless", head.width)
    return ("named", tuple(head.columns))


def propose_unrecognised(data_root: Path, path: str) -> dict[str, Any] | None:
    """What a single tabular file nothing recognised could show."""
    return propose_group(
        data_root, FileGroup(files=[path], glob=path, label=PurePosixPath(path).name)
    )


def _read_group(data_root: Path, group: FileGroup, has_header: bool):  # -> pl.DataFrame | None
    """A sample of the group's rows, each file's wildcard value in its own column."""
    import polars as pl

    files = group.files[:MAX_GROUP_READ]
    rows = max(50, 1000 // len(files))
    frames = []
    for path, value in zip(files, group.values or [None] * len(files)):
        frame = read_sample(data_root / path, rows=rows, has_header=has_header)
        if frame is None:
            continue
        if group.wildcard and value is not None and group.wildcard not in frame.columns:
            frame = frame.with_columns(pl.lit(value).alias(group.wildcard))
        frames.append(frame)
    if not frames:
        return None
    return pl.concat(frames, how="diagonal_relaxed") if len(frames) > 1 else frames[0]


def propose_group(data_root: Path, group: FileGroup) -> dict[str, Any] | None:
    """What a file, or a group of files of one shape, could show: a deterministic first guess.

    A sample column (the group's wildcard, else by name), up to four numeric
    columns as cards, up to three low-cardinality text columns as filters, one
    figure (a scatter of the first two numeric columns, else a box of the first
    numeric by the first category) and the table itself.
    """
    first = read_sample(data_root / group.files[0], rows=20)
    if first is None:
        return None
    headerless = looks_headerless(first.columns)
    frame = _read_group(data_root, group, has_header=not headerless)
    if frame is None:
        return None
    path = group.files[0]
    fmt = (table_format(path) or ("tsv", None))[0]
    types = column_types(frame)
    if group.wildcard and group.wildcard in types:
        sample = group.wildcard
    else:
        sample = None if headerless else _sample_column(types)
    numeric = [
        c
        for c, t in types.items()
        if column_type(t) in ("int64", "float64")
        and c != sample
        and not _is_identifier(c)
        and frame[c].n_unique() > 1
    ][:4]
    categorical = [
        c
        for c, t in types.items()
        if column_type(t) in ("object", "category") and 1 < frame[c].n_unique() <= MAX_FILTER_VALUES
    ]
    if sample and sample in categorical:
        categorical.remove(sample)
        categorical.insert(0, sample)
    categorical = categorical[:3]
    # Colour and group by a real category, not by the sample (one colour per row).
    groups = [c for c in categorical if c != sample] or categorical
    figure: dict[str, Any] | None = None
    if len(numeric) >= 2:
        kwargs = {"x": numeric[0], "y": numeric[1]}
        if groups:
            kwargs["color"] = groups[0]
        figure = {"visu_type": "scatter", "dict_kwargs": kwargs}
    elif numeric and groups:
        figure = {"visu_type": "box", "dict_kwargs": {"x": groups[0], "y": numeric[0]}}
    proposal = []
    if len(group.files) > 1:
        proposal.append(f"{len(group.files)} files, one per {group.wildcard}")
    if headerless:
        proposal.append("no header row: columns numbered")
    proposal += [f"card: mean of {c}" for c in numeric]
    proposal += [f"filter: {c}" for c in categorical]
    if figure:
        kw = figure["dict_kwargs"]
        proposal.append(f"figure: {figure['visu_type']} of {kw['y']} against {kw['x']}")
    proposal.append("table")
    return {
        "path": group.glob if len(group.files) > 1 else path,
        "title": group.label,
        "n_files": len(group.files),
        "format": fmt,
        "n_columns": len(types),
        "columns": list(types)[:30],
        "sample_column": sample,
        "proposal": proposal,
        "_group": group,
        "_types": types,
        "_headerless": headerless,
        "_numeric": numeric,
        "_categorical": categorical,
        "_figure": figure,
    }


def _unknown_collection(proposal: dict[str, Any]) -> Collection:
    group: FileGroup = proposal["_group"]
    config = _table_config(group.files)
    if group.wildcard and group.pattern:
        config["scan"] = {
            "mode": "recursive",
            "scan_parameters": {
                "regex_config": {
                    "pattern": group.pattern,
                    "wildcards": [{"name": group.wildcard, "wildcard_regex": group.wildcard_regex}],
                }
            },
        }
    # Read as the proposal read it: ragged lines cut to the header's width, and
    # a first line of data kept as data.
    properties = config["dc_specific_properties"]
    if properties.get("format") != "parquet":
        kwargs = {**properties.get("polars_kwargs", {}), "truncate_ragged_lines": True}
        if proposal.get("_headerless"):
            kwargs["has_header"] = False
        properties["polars_kwargs"] = kwargs
    what = proposal["path"] if len(group.files) == 1 else f"{group.glob} ({len(group.files)} files)"
    tag = (
        PurePosixPath(group.files[0]).with_suffix("").as_posix()
        if len(group.files) == 1
        else group.label
    )
    return Collection(
        tag=slug(tag),
        kind="unknown",
        description=f"{what}, not recognised by the catalog, included on request",
        config=config,
        files=list(group.files),
        columns=proposal["_types"],
    )


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------


def _lite_models() -> dict[str, Any]:
    from depictio.models.components.advanced_viz.component import AdvancedVizLiteComponent
    from depictio.models.components.lite import (
        CardLiteComponent,
        FigureLiteComponent,
        InteractiveLiteComponent,
        MultiQCLiteComponent,
        TableLiteComponent,
        TextLiteComponent,
    )

    return {
        "card": CardLiteComponent,
        "figure": FigureLiteComponent,
        "interactive": InteractiveLiteComponent,
        "table": TableLiteComponent,
        "text": TextLiteComponent,
        "multiqc": MultiQCLiteComponent,
        "advanced_viz": AdvancedVizLiteComponent,
    }


_CARD_FIELDS = (
    "aggregations",
    "secondary_layout",
    "breakdown_col",
    "top_n_count",
    "coverage_max",
    "threshold_value",
    "threshold_direction",
    "threshold_warn",
    "attrition_cols",
    "trend_col",
    "filter_expr",
)
_TABLE_FIELDS = (
    "columns",
    "page_size",
    "sortable",
    "filterable",
    "row_selection_enabled",
    "row_selection_column",
)


@dataclass
class Tile:
    component: dict[str, Any]
    headline: bool = False
    output_label: str = ""


class _Tagger:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def __call__(self, base: str) -> str:
        tag, n = slug(base, 60).replace("_", "-"), 2
        root = tag
        while tag in self.seen:
            tag, n = f"{root}-{n}", n + 1
        self.seen.add(tag)
        return tag


def _component(tagger: _Tagger, base: str, ctype: str, **fields: Any) -> dict[str, Any]:
    tag = tagger(base)
    return {
        "component_type": ctype,
        "tag": tag,
        # Deterministic, short and dash-free: the importer keeps it as is.
        "index": hashlib.sha1(tag.encode()).hexdigest()[:16],
        **fields,
    }


def _render_tile(
    render: Render,
    output: CatalogOutput,
    entry: CatalogEntry,
    collection: Collection,
    workflow: str,
    tagger: _Tagger,
) -> dict[str, Any] | str:
    """One catalog render as a component dict, or the reason it was left out."""
    from depictio.catalog.payload import advanced_viz_persist_config
    from depictio.models.components.advanced_viz.catalog import role_config_key

    missing = render.bound_columns() - set(collection.columns)
    if collection.columns and missing:
        return f"binds {sorted(missing)}, which {collection.tag} does not have"
    base = {
        "workflow_tag": workflow,
        "data_collection_tag": collection.tag,
        "section": entry.name,
    }
    stem = f"{collection.tag}-{render.component}"
    kind = render.component
    if kind == "card":
        assert render.column and render.aggregation
        fields: dict[str, Any] = {
            "title": card_title(render.column, render.aggregation),
            "column_name": render.column,
            "aggregation": render.aggregation,
        }
        ctype = column_type(collection.columns.get(render.column))
        if ctype:
            fields["column_type"] = ctype
        for name in _CARD_FIELDS:
            value = getattr(render, name)
            if value not in (None, [], ""):
                fields[name] = value
        return _component(tagger, stem, "card", **base, **fields)
    if kind == "figure":
        fields = {"title": _output_label(output)}
        if render.code:
            fields |= {"mode": "code", "code_content": render.code}
        else:
            fields |= {"visu_type": render.visu_type, "dict_kwargs": dict(render.dict_kwargs)}
        return _component(tagger, stem, "figure", **base, **fields)
    if kind == "interactive":
        assert render.column_name and render.interactive_type
        fields = {
            "title": pretty(render.column_name),
            "interactive_component_type": render.interactive_type,
            "column_name": render.column_name,
        }
        ctype = column_type(collection.columns.get(render.column_name))
        if ctype in ("bool", "timedelta"):
            return f"filter on {render.column_name}: no control fits a {ctype} column"
        if ctype:
            fields["column_type"] = ctype
        return _component(tagger, stem, "interactive", **base, **fields)
    if kind == "table":
        fields = {"title": _output_label(output)}
        for name in _TABLE_FIELDS:
            value = getattr(render, name)
            if value not in (None, [], ""):
                fields[name] = value
        return _component(tagger, stem, "table", **base, **fields)
    if kind == "advanced_viz":
        assert render.kind
        config = advanced_viz_persist_config(output, render) or {
            role_config_key(render.kind, role): col for role, col in render.roles.items()
        }
        config = {**config, "viz_kind": render.kind}
        fields = {
            "title": f"{_output_label(output)}: {render.kind.replace('_', ' ')}",
            "viz_kind": render.kind,
            "config": config,
        }
        if render.id:
            fields["use"] = f"{entry.id}/{render.id}"
        return _component(tagger, stem, "advanced_viz", **base, **fields)
    return f"{kind} tiles are not composed"


def _ordered_renders(output: CatalogOutput) -> list[Render]:
    indexed = list(enumerate(output.renders_as))
    indexed.sort(key=lambda ir: (ir[1].priority is None, ir[1].priority or 0, ir[0]))
    return [r for _, r in indexed]


def _validate(component: dict[str, Any], models: dict[str, Any]) -> str | None:
    model = models.get(component["component_type"])
    if model is None:
        return f"unknown component type {component['component_type']}"
    try:
        model.model_validate(component)
    except Exception as exc:
        return str(exc).splitlines()[0][:200]
    return None


def _collection_tiles(
    collection: Collection,
    workflow: str,
    tagger: _Tagger,
    models: dict[str, Any],
    skipped: list[Skipped],
) -> list[Tile]:
    tiles: list[Tile] = []
    assert collection.tool is not None
    for output in collection.outputs:
        for render in _ordered_renders(output):
            built = _render_tile(render, output, collection.tool, collection, workflow, tagger)
            if isinstance(built, str):
                skipped.append(Skipped(f"{output.id} {render.component}", built))
                continue
            problem = _validate(built, models)
            if problem:
                skipped.append(Skipped(f"{output.id} {render.component}", problem))
                continue
            tiles.append(Tile(built, bool(render.headline), _output_label(output)))
    return tiles


def _unknown_tiles(
    collection: Collection,
    proposal: dict[str, Any],
    workflow: str,
    tagger: _Tagger,
    models: dict[str, Any],
    skipped: list[Skipped],
) -> list[dict[str, Any]]:
    section = proposal["title"]
    base = {
        "workflow_tag": workflow,
        "data_collection_tag": collection.tag,
        "section": section,
    }
    types = proposal["_types"]
    built: list[dict[str, Any]] = []
    for column in proposal["_numeric"]:
        built.append(
            _component(
                tagger,
                f"{collection.tag}-card",
                "card",
                **base,
                title=card_title(column, "average"),
                column_name=column,
                aggregation="average",
                column_type=column_type(types[column]),
                secondary_layout="histogram",
            )
        )
    for column in proposal["_categorical"]:
        built.append(
            _component(
                tagger,
                f"{collection.tag}-filter",
                "interactive",
                **base,
                title=pretty(column),
                interactive_component_type="MultiSelect",
                column_name=column,
                column_type=column_type(types[column]),
            )
        )
    if proposal["_figure"]:
        built.append(
            _component(
                tagger,
                f"{collection.tag}-figure",
                "figure",
                **base,
                title=section,
                **proposal["_figure"],
            )
        )
    built.append(
        _component(
            tagger,
            f"{collection.tag}-table",
            "table",
            **base,
            title=section,
        )
    )
    kept: list[dict[str, Any]] = []
    for component in built:
        problem = _validate(component, models)
        if problem:
            skipped.append(Skipped(f"{proposal['path']} {component['component_type']}", problem))
        else:
            kept.append(component)
    return kept


# ---------------------------------------------------------------------------
# General statistics across tools
# ---------------------------------------------------------------------------

_POLARS_AGG = {
    "average": "mean",
    "median": "median",
    "sum": "sum",
    "min": "min",
    "max": "max",
    "nunique": "n_unique",
    "count": "len",
}


def _collection_frame(collection: Collection, data_root: Path):  # -> pl.DataFrame | None
    import polars as pl

    try:
        if collection.kind == "recipe" and collection.recipe:
            if collection.needs:
                return None  # its inputs are other collections, only joined at ingestion
            from depictio.recipes import execute_recipe

            overrides = {
                ref: o.get("path") or o.get("glob_pattern") or ""
                for ref, o in collection.overrides.items()
            }
            return execute_recipe(collection.recipe, data_root, overrides=overrides or None)
        frames = [read_sample(data_root / f, rows=1_000_000) for f in collection.files[:200]]
        frames = [f for f in frames if f is not None]
        return pl.concat(frames, how="diagonal_relaxed") if frames else None
    except Exception as exc:
        logger.info(f"General statistics: skipped {collection.tag} ({exc})")
        return None


def general_statistics(
    collections: Sequence[Collection], tiles: dict[str, list[Tile]], data_root: Path
):  # -> pl.DataFrame | None
    """One row per sample, one column per headline card, joined across tools.

    MultiQC's General Statistics for the outputs the catalog knows: each
    collection with headline cards and a sample column is aggregated per sample
    the way each card aggregates the whole table, sample names are normalised
    (`strip_stage_suffixes`), and the per-tool tables are joined on them.
    """
    import polars as pl

    from depictio.recipes.lib.sample_ids import strip_stage_suffixes

    joined = None
    for collection in collections:
        cards = [
            t.component
            for t in tiles.get(collection.tag, [])
            if t.headline
            and t.component["component_type"] == "card"
            and t.component["aggregation"] in _POLARS_AGG
        ]
        if not cards or collection.tool is None:
            continue
        sample = _sample_column(collection.columns)
        if sample is None:
            continue
        frame = _collection_frame(collection, data_root)
        if frame is None or sample not in frame.columns:
            continue
        exprs = []
        for card in cards:
            column, agg = card["column_name"], card["aggregation"]
            if column not in frame.columns or column == sample:
                continue
            expr = pl.len() if agg == "count" else getattr(pl.col(column), _POLARS_AGG[agg])()
            exprs.append(expr.alias(f"{collection.tool.name}: {card['title']}"))
        if not exprs:
            continue
        per_sample = (
            frame.with_columns(
                pl.col(sample)
                .cast(pl.String)
                .map_elements(strip_stage_suffixes, return_dtype=pl.String)
                .alias("sample")
            )
            .group_by("sample")
            .agg(exprs)
        )
        joined = (
            per_sample
            if joined is None
            else joined.join(per_sample, on="sample", how="full", coalesce=True)
        )
    if joined is None or joined.height == 0:
        return None
    return joined.sort("sample")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _where(proposal: dict[str, Any]) -> str:
    """Where an included collection's rows come from, for its section header."""
    n = proposal.get("n_files", 1)
    return proposal["path"] if n == 1 else f"{proposal['path']}: {n} files"


def _section(name: str, stage: str, **extra: Any) -> dict[str, Any]:
    icon, color = STAGE_STYLE.get(stage, STAGE_STYLE["other"])
    return {"name": name, "icon": icon, "color": color, **extra}


def _stage_rank(stage: str) -> int:
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER)


def _multiqc_tab(
    collection: Collection, workflow: str, tagger: _Tagger, models: dict[str, Any], title: str
) -> dict[str, Any] | None:
    from depictio.catalog.payload import multiqc_module

    multiqc = next((e for e in load_catalog_entries() if e.id == "multiqc"), None)
    section_stage: dict[str, str] = {}
    if multiqc is not None:
        for output in multiqc.outputs:
            for render in output.renders_as:
                if render.component == "multiqc" and render.section:
                    section_stage[render.section] = multiqc.stage_of(output)
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for plot in collection.plots:
        stage = section_stage.get(multiqc_module(plot.module), "qc")
        label = STAGE_LABELS.get(stage, "Other results")
        component = _component(
            tagger,
            f"mqc-{plot.module}",
            "multiqc",
            workflow_tag=workflow,
            data_collection_tag=collection.tag,
            section=label,
            title=f"{plot.module_name}: {plot.plot}",
            selected_module=plot.module,
            selected_plot=plot.plot,
        )
        if _validate(component, models) is None:
            by_stage.setdefault(stage, []).append(component)
    if not by_stage:
        return None
    stages = sorted(by_stage, key=_stage_rank)
    return {
        "title": title,
        "subtitle": f"Every plot of the MultiQC report ({collection.files[0]})",
        "tab_icon": "/assets/images/logos/multiqc_icon_color.svg",
        "tab_icon_color": "orange",
        "grid_sections": [_section(STAGE_LABELS.get(s, s), s) for s in stages],
        "components": [c for s in stages for c in by_stage[s]],
    }


def _sample_filter(collections: Sequence[Collection], workflow: str, tagger: _Tagger, section: str):
    """A MultiSelect on the first collection with a text sample column, if any."""
    for collection in collections:
        sample = _sample_column(collection.columns)
        if sample and column_type(collection.columns[sample]) in ("object", "category"):
            return _component(
                tagger,
                f"{collection.tag}-sample-filter",
                "interactive",
                workflow_tag=workflow,
                data_collection_tag=collection.tag,
                section=section,
                title="Sample",
                interactive_component_type="MultiSelect",
                column_name=sample,
                column_type=column_type(collection.columns[sample]),
            )
    return None


@dataclass
class ComposedTemplate:
    """A composed template written to disk, and what went into it."""

    template_dir: Path
    project_name: str
    composition: Composition
    tabs: list[str]
    headline: list[str]
    general_stats: bool


def write_template(
    composition: Composition,
    out_dir: str | Path,
    project_name: str | None = None,
    pipeline_name: str | None = None,
    pipeline_version: str | None = None,
    engine: str | None = None,
) -> ComposedTemplate:
    """Write ``template.yaml`` and ``dashboards/composed.yaml`` for a composition."""
    from depictio.models.models.templates import UnrecognisedFile

    out = Path(out_dir).resolve()
    (out / "dashboards").mkdir(parents=True, exist_ok=True)
    root = composition.data_root
    workflow = slug(pipeline_name.rsplit("/", 1)[-1]) if pipeline_name else "results"
    # No "/" in a project name: the API looks projects up by name in the URL path.
    name = project_name or (f"{root.name} ({root.parent.name})" if root.parent.name else root.name)
    models = _lite_models()
    tagger = _Tagger()
    skipped = composition.skipped

    collections = list(composition.collections)
    tiles: dict[str, list[Tile]] = {}
    for collection in collections:
        if collection.kind in ("raw", "recipe"):
            tiles[collection.tag] = _collection_tiles(collection, workflow, tagger, models, skipped)

    # General statistics across tools, written next to the template.
    stats = general_statistics(collections, tiles, root)
    general_path = out / GENERAL_STATS_FILE
    general_path.unlink(missing_ok=True)
    stats_collection: Collection | None = None
    if stats is not None:
        stats.write_csv(general_path, separator="\t")
        stats_collection = Collection(
            tag="general_stats",
            kind="general_stats",
            description="One row per sample: the headline metrics of every recognised tool",
            config={
                "type": "Table",
                "scan": {"mode": "single", "scan_parameters": {"filename": str(general_path)}},
                "dc_specific_properties": {"format": "tsv", "polars_kwargs": {"separator": "\t"}},
            },
            stage="qc",
            columns={k: _dtype_name(v) for k, v in stats.schema.items()},
        )
        collections.append(stats_collection)
        _unique_tags(collections)

    multiqc = [c for c in collections if c.kind == "multiqc"]
    family_filter = None
    overview_components: list[dict[str, Any]] = []
    overview_filters: list[dict[str, Any]] = []
    if multiqc:
        # Bound to the MultiQC report's own sample list, so it exists on every run
        # and its persistent section counts as every tab's filter.
        family_filter = _component(
            tagger,
            "overview-sample-filter",
            "interactive",
            workflow_tag=workflow,
            data_collection_tag=multiqc[0].tag,
            section="Samples",
            title="Sample",
            interactive_component_type="MultiSelect",
            column_name="sample",
            column_type="object",
        )
        overview_filters.append(family_filter)

    # Stage tabs.
    by_stage: dict[str, list[Collection]] = {}
    for collection in collections:
        if collection.kind in ("raw", "recipe") and tiles.get(collection.tag):
            by_stage.setdefault(collection.stage, []).append(collection)
    tabs: list[dict[str, Any]] = []
    headline: list[tuple[int, Tile]] = []

    for stage in sorted(by_stage, key=_stage_rank):
        members = by_stage[stage]
        components: list[dict[str, Any]] = []
        sections: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        filters: list[dict[str, Any]] = []
        filter_section = f"{STAGE_LABELS[stage]} filters"
        tools: list[str] = []
        described: dict[str, list[str]] = {}
        for collection in members:
            assert collection.tool is not None
            if collection.tool.name not in tools:
                tools.append(collection.tool.name)
            described.setdefault(collection.tool.name, []).extend(
                _output_label(o) for o in collection.outputs
            )
            for tile in tiles[collection.tag]:
                component = tile.component
                if component["component_type"] == "table":
                    component["section"] = "Tables"
                    tables.append(component)
                elif component["component_type"] == "interactive":
                    component["section"] = filter_section
                    filters.append(component)
                else:
                    components.append(component)
                if tile.headline:
                    headline.append((_stage_rank(stage), tile))
        if not filters and family_filter is None:
            sample_filter = _sample_filter(members, workflow, tagger, filter_section)
            if sample_filter and _validate(sample_filter, models) is None:
                filters.append(sample_filter)
        # A section per tool that has something to show besides its tables.
        shown = {c["section"] for c in components}
        sections = [
            _section(tool, stage, description=", ".join(dict.fromkeys(described[tool])))
            for tool in tools
            if tool in shown
        ]
        if tables:
            # Folded away under the charts; open when the tables are all there is.
            sections.append(
                _section("Tables", "other", collapsed=bool(components), icon="mdi:table")
            )
        tab: dict[str, Any] = {
            "title": STAGE_LABELS[stage],
            "subtitle": ", ".join(tools),
            "tab_icon": STAGE_STYLE[stage][0],
            "tab_icon_color": STAGE_STYLE[stage][1],
            "grid_sections": sections,
            "components": components + tables + filters,
        }
        if filters:
            tab["filter_sections"] = [_section(filter_section, stage, icon="mdi:filter-variant")]
        tabs.append(tab)

    labels = distinct_labels([c.files[0] for c in multiqc])
    for collection, label in zip(multiqc, labels):
        title = "MultiQC" if len(multiqc) == 1 else f"MultiQC ({label})"
        tab = _multiqc_tab(collection, workflow, tagger, models, title)
        if tab:
            tabs.append(tab)

    # Other data, on request only.
    included = [p for p in composition.unrecognised if p.get("_include")]
    if included:
        unknown_by_path = {c.files[0]: c for c in collections if c.kind == "unknown"}
        components = []
        for proposal in included:
            collection = unknown_by_path.get(proposal["_group"].files[0])
            if collection is not None:
                components += _unknown_tiles(
                    collection, proposal, workflow, tagger, models, skipped
                )
        if components:
            sections = [
                _section(p["title"], "other", description=_where(p))
                for p in included
                if p["_group"].files[0] in unknown_by_path
            ]
            tab = {
                "title": "Other data",
                "subtitle": "Files the catalog does not recognise, included on request",
                "tab_icon": "mdi:folder-outline",
                "tab_icon_color": "gray",
                "grid_sections": sections,
                "components": components,
            }
            # One filter section per collection, named like its grid section: a
            # filter narrows its own collection only, so "sample" in two of them is
            # two controls, and the section says which data each one filters.
            filter_names = list(
                dict.fromkeys(
                    c["section"] for c in components if c["component_type"] == "interactive"
                )
            )
            if filter_names:
                where = {p["title"]: _where(p) for p in included}
                tab["filter_sections"] = [
                    _section(
                        name,
                        "other",
                        icon="mdi:filter-variant",
                        collapsed=len(filter_names) > 1,
                        description=where.get(name),
                    )
                    for name in filter_names
                ]
            tabs.append(tab)

    # Overview.
    headline.sort(key=lambda rt: rt[0])
    key_metrics: list[dict[str, Any]] = []
    for _, tile in headline[:8]:
        copy = dict(tile.component)
        tag = tagger(f"overview-{copy['tag']}")
        title = copy["title"]
        copy |= {
            "tag": tag,
            "index": hashlib.sha1(tag.encode()).hexdigest()[:16],
            "section": "Key metrics",
            # Out of its tool's tab, a card says which output it reads.
            "title": f"{tile.output_label}: {title[:1].lower()}{title[1:]}",
        }
        key_metrics.append(copy)
    general: list[dict[str, Any]] = []
    for collection in multiqc:
        if collection.general_stats:
            general.append(
                _component(
                    tagger,
                    "overview-multiqc-general-stats",
                    "multiqc",
                    workflow_tag=workflow,
                    data_collection_tag=collection.tag,
                    section="General statistics",
                    title="MultiQC general statistics",
                    selected_module="general_stats",
                    selected_plot="general_stats",
                )
            )
    if stats_collection is not None:
        general.append(
            _component(
                tagger,
                "overview-general-stats-table",
                "table",
                workflow_tag=workflow,
                data_collection_tag=stats_collection.tag,
                section="General statistics",
                title="Headline metrics per sample, across tools",
                columns=list(stats_collection.columns),
            )
        )
    general = [c for c in general if _validate(c, models) is None]

    recognised_tools = sorted(
        {c.tool.name for c in collections if c.tool is not None and c.kind in ("raw", "recipe")}
    )
    intro = _intro(composition, recognised_tools, [t["title"] for t in tabs], bool(multiqc))
    overview_components.append(
        _component(
            tagger,
            "overview-intro",
            "text",
            section="About this run",
            title="What Depictio found in this directory",
            order=3,
            body=intro,
        )
    )
    overview_components += key_metrics + general + overview_filters
    grid_sections = [{"name": "About this run", "icon": "mdi:information-outline", "color": "blue"}]
    if key_metrics:
        grid_sections.append({"name": "Key metrics", "icon": "mdi:counter", "color": "blue"})
    if general:
        grid_sections.append({"name": "General statistics", "icon": "mdi:table", "color": "gray"})
    main: dict[str, Any] = {
        "title": name,
        "subtitle": f"Composed from {root}",
        "project_tag": name,
        "main_tab_name": "Overview",
        "tab_icon": "mdi:view-dashboard-outline",
        "tab_icon_color": "blue",
        "grid_sections": grid_sections,
        "components": overview_components,
    }
    if overview_filters:
        main["filter_sections"] = [
            {
                "name": "Samples",
                "icon": "mdi:filter-variant",
                "color": "teal",
                "description": "Applies to every tab",
                "persistent": True,
                "pin": "top",
            }
        ]

    for document in (main, *tabs):
        layout_dashboard(document)
    _check_dashboard(main, tabs)

    dashboard = {"main_dashboard": main, "tabs": tabs}
    (out / DASHBOARD_FILE).write_text(_dump(dashboard))

    unrecognised = [
        UnrecognisedFile.model_validate({k: v for k, v in p.items() if not k.startswith("_")})
        for p in composition.unrecognised
        if not p.get("_include")
    ]
    template = {
        "template": {
            "template_id": f"composed/{slug(root.name)}",
            "description": f"Composed by depictio from the catalog for {root}",
            "version": "1",
            "variables": [
                {"name": "DATA_ROOT", "description": "The results directory", "required": True}
            ],
            "dashboards": [DASHBOARD_FILE],
            "unrecognised_files": [u.model_dump() for u in unrecognised],
        },
        "name": name,
        "project_type": "advanced",
        "workflows": [
            {
                "name": workflow,
                **({"version": pipeline_version} if pipeline_version else {}),
                "engine": {"name": engine or "unknown"},
                "data_location": {"structure": "flat", "locations": ["{DATA_ROOT}"]},
                "data_collections": [c.to_template() for c in collections],
            }
        ],
    }
    (out / "template.yaml").write_text(
        "# Composed by `depictio template compose` from the catalog: edit freely, then\n"
        f"#   depictio run --template {out} --data-root {root}\n" + _dump(template)
    )
    return ComposedTemplate(
        template_dir=out,
        project_name=name,
        composition=composition,
        tabs=["Overview", *[t["title"] for t in tabs]],
        headline=[c["title"] for c in key_metrics],
        general_stats=stats_collection is not None,
    )


def _intro(composition: Composition, tools: list[str], tabs: list[str], multiqc: bool) -> str:
    lines = []
    if tools:
        noun = "tool" if len(tools) == 1 else "tools"
        lines.append(f"Recognised outputs of **{len(tools)} {noun}**: {', '.join(tools)}.")
    if multiqc:
        lines.append("A **MultiQC** report, every plot of which is in the MultiQC tab.")
    if tabs:
        lines.append("Tabs follow the pipeline: " + ", ".join(f"**{t}**" for t in tabs) + ".")
    left = [p for p in composition.unrecognised if not p.get("_include")]
    if composition.unrecognised_total:
        lines.append(
            f"{len(left)} other tabular file{'s' if len(left) != 1 else ''} not recognised by the "
            "catalog: the project page lists them, with what each could show "
            "(`--include-unknown` adds them)."
            if left
            else "Every other tabular file is in the **Other data** tab."
        )
    return "\n".join(lines) or "Nothing the catalog recognises."


def _check_dashboard(main: dict[str, Any], tabs: list[dict[str, Any]]) -> None:
    """Validate what the importer will: each document, and every section a tile names."""
    from depictio.models.models.dashboards import DashboardDataLite

    for document in (main, *tabs):
        DashboardDataLite.model_validate(document)
        declared = {s["name"] for s in document.get("grid_sections", [])} | {
            s["name"] for s in document.get("filter_sections", [])
        }
        for component in document["components"]:
            if component.get("section") not in declared:
                raise ValueError(
                    f"{document['title']}: tile {component['tag']} names an undeclared "
                    f"section {component.get('section')!r}"
                )


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # an Overview copy shares its tile's lists
        return True


def _str_representer(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_representer)


def _dump(data: Any) -> str:
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def default_compose_dir(data_root: str | Path) -> Path:
    """Where `depictio run` keeps the template it composes for ``data_root``."""
    import os

    root = Path(data_root).resolve()
    home = Path(os.environ.get("DEPICTIO_COMPOSE_HOME", "~/.depictio/composed")).expanduser()
    digest = hashlib.sha1(str(root).encode()).hexdigest()[:12]
    return home / f"{slug(root.name, 32)}-{digest}"


def compose_template(
    data_root: str | Path,
    out_dir: str | Path | None = None,
    include_unknown: bool = False,
    include: Sequence[str] = (),
    project_name: str | None = None,
    pipeline_name: str | None = None,
    pipeline_version: str | None = None,
    engine: str | None = None,
) -> ComposedTemplate | Composition:
    """Compose and write a template for ``data_root``.

    Returns the written template, or the bare composition when nothing in the
    directory was recognised (nothing is written then).
    """
    composition = compose_run(data_root, include_unknown=include_unknown, include=include)
    if not composition.recognised and not any(c.kind == "unknown" for c in composition.collections):
        return composition
    return write_template(
        composition,
        out_dir or default_compose_dir(data_root),
        project_name=project_name,
        pipeline_name=pipeline_name,
        pipeline_version=pipeline_version,
        engine=engine,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_report(result: ComposedTemplate | Composition, verbose: bool = False) -> None:
    """What was recognised, what was left out and why, what else is there."""
    from rich.table import Table

    from depictio.cli.cli.utils.rich_utils import console

    composition = result.composition if isinstance(result, ComposedTemplate) else result
    table = Table(title="Recognised", show_lines=False)
    table.add_column("Collection")
    table.add_column("Tool")
    table.add_column("Stage")
    table.add_column("Files")
    for c in composition.collections:
        if c.kind == "general_stats":
            continue
        tool = c.tool.name if c.tool else ("MultiQC" if c.kind == "multiqc" else "-")
        files = c.files[0] + (f" (+{len(c.files) - 1})" if len(c.files) > 1 else "")
        table.add_row(c.tag, tool, STAGE_LABELS.get(c.stage, c.stage), files)
    console.print(table)
    if isinstance(result, ComposedTemplate):
        console.print(f"Tabs: {', '.join(result.tabs)}", highlight=False)
        if result.headline:
            console.print(f"Key metrics: {', '.join(result.headline)}", highlight=False)
        if result.general_stats:
            console.print("General statistics: joined across tools per sample", highlight=False)
    if composition.skipped:
        shown = composition.skipped if verbose else composition.skipped[:15]
        console.print(f"Left out ({len(composition.skipped)}):", highlight=False)
        for s in shown:
            console.print(f"  - {s.what}: {s.why}", highlight=False, soft_wrap=True)
        if len(shown) < len(composition.skipped):
            console.print("  … (--verbose lists them all)", highlight=False)
    left = [p for p in composition.unrecognised if not p.get("_include")]
    if left:
        console.print(
            f"Not recognised ({composition.unrecognised_total} tabular file(s); "
            "--include-unknown or --include '<glob>' adds them):",
            highlight=False,
        )
        for p in left[: (len(left) if verbose else 10)]:
            console.print(
                f"  - {p['path']}: {', '.join(p['proposal'])}", highlight=False, soft_wrap=True
            )
        if not verbose and len(left) > 10:
            console.print("  …", highlight=False)
