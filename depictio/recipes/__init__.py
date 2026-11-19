"""Recipe loader and executor with 5 automatic validation checkpoints."""

from __future__ import annotations

import importlib.util
import inspect
import re
import weakref
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import polars as pl

from depictio.models.models.transforms import RecipeSource

if TYPE_CHECKING:  # pragma: no cover - import kept out of the runtime path
    from depictio.cli.cli.utils.data_root import DataRoot

# Recipes live in one of two homes:
#   1. Module-owned (preferred): co-located in the catalog module folder, referenced
#      as `<module>/{name}.py`  → depictio/catalog/{module}/{name}.py
#      A reshape that is intrinsic to a tool output belongs with that tool.
#   2. Pipeline-keyed (legacy): co-located with the project templates that use them,
#      referenced as `nf-core/{pipeline}/{name}.py`:
#        Shared:            projects/{pipeline}/recipes/{name}.py
#        Version override:  projects/{pipeline}/{version}/recipes/{name}.py
#      Kept for reshapes that are genuinely pipeline- (or pipeline-version-) specific.
PROJECTS_DIR = Path(__file__).parent.parent / "projects"
CATALOG_DIR = Path(__file__).parent.parent / "catalog"


class RecipeError(Exception):
    """Raised when a recipe fails validation."""


class RecipeSourceMissing(RecipeError):
    """A required input file of the recipe is not in the data root.

    Raised apart so a project with several runs can tell a run where that
    pipeline step did not run (skipped) from a recipe that is broken (fails).
    """


# Pre-#863 constant names. A recipe still using them fails loudly instead of
# half-working: the optional schema is read with a ``None`` default, so a module
# that only renamed the required schema would silently skip optional validation.
_RENAMED_CONSTANTS = {
    "EXPECTED_SCHEMA": "OUTPUT_SCHEMA",
    "OPTIONAL_SCHEMA": "OPTIONAL_OUTPUT_SCHEMA",
}


# ---------------------------------------------------------------------------
# Path resolution: versioned-then-shared fallback
# ---------------------------------------------------------------------------


def resolve_recipe_path(
    recipe_ref: str, pipeline_version: str | None = None, search_dir: Path | None = None
) -> Path:
    """Resolve the filesystem path for a recipe using versioned-then-shared fallback.

    Args:
        recipe_ref: Pipeline-qualified recipe name, e.g. 'nf-core/ampliseq/alpha_diversity.py'.
        pipeline_version: Optional pipeline version, e.g. '2.16.0'. When provided, a
            version-specific override is tried first before falling back to the shared recipe.

    Resolution order:
        1. PROJECTS_DIR/{pipeline}/{version}/recipes/{name}  — version override (if version given)
        2. CATALOG_DIR/{module}/{name}                       — module-owned recipe
        3. PROJECTS_DIR/{pipeline}/recipes/{name}            — pipeline-keyed shared fallback
    """
    *pipeline_parts, name = recipe_ref.split("/")
    pipeline = "/".join(pipeline_parts)

    # A tool folder validated outside the catalog (a contribution not yet in the
    # repo, `catalog validate --path <dir>`): its module-owned recipe sits next to
    # its YAML. Only when the ref's module is that folder, so it cannot shadow
    # another module's recipe.
    if search_dir is not None and pipeline == search_dir.name and (search_dir / name).exists():
        return search_dir / name

    if pipeline_version:
        versioned = PROJECTS_DIR / pipeline / pipeline_version / "recipes" / name
        if versioned.exists():
            return versioned

    # Module-owned recipe: `<module>/{name}.py` lives in the catalog module folder.
    # Pipeline-qualified refs (`nf-core/{pipeline}/{name}.py`) never collide here —
    # CATALOG_DIR/nf-core/{pipeline}/ does not exist.
    module_owned = CATALOG_DIR / pipeline / name
    if module_owned.exists():
        return module_owned

    shared = PROJECTS_DIR / pipeline / "recipes" / name
    if shared.exists():
        return shared

    if pipeline_version:
        raise RecipeError(
            f"Recipe not found: {recipe_ref} "
            f"(tried version '{pipeline_version}' override and shared)"
        )
    raise RecipeError(f"Recipe not found: {recipe_ref}")


# ---------------------------------------------------------------------------
# Checkpoint 1: Load recipe module
# ---------------------------------------------------------------------------


def load_recipe(
    recipe_name: str, pipeline_version: str | None = None, search_dir: Path | None = None
) -> ModuleType:
    """Load a recipe Python module by name.

    Args:
        recipe_name: Pipeline-qualified recipe name (e.g. 'nf-core/ampliseq/alpha_diversity.py').
        pipeline_version: Optional pipeline version for version-specific recipe lookup.

    Validates that the module has SOURCES, OUTPUT_SCHEMA, and a callable transform(),
    and rejects the pre-rename constant names (EXPECTED_SCHEMA, OPTIONAL_SCHEMA).
    """
    recipe_path = resolve_recipe_path(recipe_name, pipeline_version, search_dir)

    spec = importlib.util.spec_from_file_location(
        f"depictio.recipes.{recipe_name.replace('/', '.')}", recipe_path
    )
    if spec is None or spec.loader is None:
        raise RecipeError(f"Could not load recipe module: {recipe_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Reject the old constant names before the required-attribute checks, so a
    # half-renamed recipe gets the migration hint rather than a generic error.
    legacy = [old for old in _RENAMED_CONSTANTS if hasattr(module, old)]
    if legacy:
        renames = " and ".join(f"{old} to {_RENAMED_CONSTANTS[old]}" for old in legacy)
        raise RecipeError(f"Recipe {recipe_name}: rename {renames}")

    # Validate required attributes
    if not hasattr(module, "SOURCES"):
        raise RecipeError(f"Recipe {recipe_name} missing SOURCES")
    if not hasattr(module, "OUTPUT_SCHEMA"):
        raise RecipeError(f"Recipe {recipe_name} missing OUTPUT_SCHEMA")
    if not callable(getattr(module, "transform", None)):
        raise RecipeError(f"Recipe {recipe_name} missing callable transform()")

    sources = module.SOURCES
    if not isinstance(sources, list) or len(sources) == 0:
        raise RecipeError(f"Recipe {recipe_name} SOURCES must be a non-empty list")
    for s in sources:
        if not isinstance(s, RecipeSource):
            raise RecipeError(f"Recipe {recipe_name} SOURCES must contain RecipeSource instances")
        for col_name, dtype in (s.input_schema or {}).items():
            if not _is_polars_dtype(dtype):
                raise RecipeError(
                    f"Recipe {recipe_name}: source '{s.ref}' input_schema column "
                    f"'{col_name}' is not a polars dtype: {dtype!r}"
                )

    return module


# ---------------------------------------------------------------------------
# Checkpoint 2: Resolve sources (read files into DataFrames)
# ---------------------------------------------------------------------------


def _is_remote_location(location: str | Path) -> bool:
    """Whether ``location`` is a URL rather than a filesystem path.

    String handling on purpose: ``Path('s3://bucket/x.csv')`` collapses the
    double slash and has no usable ``suffix``, so anything that sniffs a remote
    location must never route it through ``pathlib``.
    """
    return "://" in str(location)


def _as_data_root(data_dir: str | Path | DataRoot) -> DataRoot:
    """The :class:`DataRoot` for whatever the caller passed.

    A ``str`` or ``Path`` is a directory on disk, so it is wrapped and every
    existing caller keeps working unchanged. A caller that already holds a root
    (the ingestion layer, which may have built an :class:`S3DataRoot` from one
    paginated listing) hands it straight through, so a recipe with a dozen
    sources costs no extra listings.

    Deliberately not ``data_root.as_data_root``: that one coerces a location a
    *user* supplied, so it absolutises a path and reads an ``s3://`` string as a
    prefix. A recipe's ``data_dir`` has always meant a directory on disk and
    keeps whatever spelling the caller used; a remote root reaches here as an
    already-built :class:`DataRoot`, never as a string.
    """
    if isinstance(data_dir, str | Path):
        # Imported lazily: ``depictio.recipes`` is pulled in by the API and the
        # catalog, neither of which should have to import the CLI package.
        from depictio.cli.cli.utils.data_root import LocalDataRoot

        return LocalDataRoot(str(data_dir))
    return data_dir


def _read_source_file(
    location: str | Path,
    source: RecipeSource,
    storage_options: dict | None = None,
    rel_path: str | None = None,
    root: DataRoot | None = None,
) -> pl.DataFrame:
    """Read a single source file into a DataFrame.

    ``location`` is whatever the data root calls the file: an absolute
    filesystem path, or an ``s3://`` URL.

    A remote location is read through polars' *lazy* readers and collected
    immediately. This is not an optimisation, it is the only thing that works:
    ``pl.read_csv`` routes an ``s3://`` path through fsspec/s3fs, which does not
    understand object_store options and dies on ``aws_skip_signature`` with
    ``AioSession.__init__() got an unexpected keyword argument``. The scanners
    use the native Rust object store, which does. ``deltatables``'
    ``_read_remote_file_lazy`` scans for the same reason. Every ``read_kwargs``
    the bundled recipes use (``separator``, ``skip_rows``,
    ``skip_rows_after_header``, ``infer_schema_length``) is accepted by
    ``scan_csv``; the eager-only ones are ``columns``, ``batch_size``,
    ``n_threads``, ``sample_size`` and ``use_pyarrow``.

    A local location keeps the eager path unchanged, and is never handed
    ``storage_options``.

    When the source declares ``source_path``, a column of that name is added
    holding ``rel_path``, the file's path relative to the data root (the full
    location when the caller has none, e.g. an absolute override outside the
    root), so the recipe can derive a key the content lacks.

    A source declared as a CSV/TSV file, repointed at a YAML or JSON
    samplesheet (``--var SAMPLESHEET_FILE=sheet.yaml``), is read as a list of
    records (``record_sheets``), through ``root`` when the file is under it.
    """
    if _repointed_at_record_sheet(source, rel_path or location):
        return _mark_record_sheet(
            _with_source_path(
                _read_record_source(location, source, root, rel_path), source, location, rel_path
            )
        )

    kwargs = dict(source.read_kwargs or {})
    remote = _is_remote_location(location)
    if remote and storage_options is not None:
        kwargs["storage_options"] = storage_options

    scan, read, format_kwargs = _format_readers(source)
    if remote:
        df = scan(location, **format_kwargs, **kwargs).collect()
    else:
        df = read(location, **format_kwargs, **kwargs)
    return _with_source_path(df, source, location, rel_path)


# Frames read from a YAML/JSON samplesheet, by id: such a sheet has keys, not
# columns, and ``validate_sources`` says so. Weak, so a frame's entry goes with it.
_RECORD_SHEET_FRAMES: weakref.WeakValueDictionary[int, pl.DataFrame] = weakref.WeakValueDictionary()


def _mark_record_sheet(df: pl.DataFrame) -> pl.DataFrame:
    _RECORD_SHEET_FRAMES[id(df)] = df
    return df


def _from_record_sheet(df: pl.DataFrame) -> bool:
    return _RECORD_SHEET_FRAMES.get(id(df)) is df


def _repointed_at_record_sheet(source: RecipeSource, location: str | Path) -> bool:
    """Whether ``location`` is a YAML/JSON samplesheet standing in for a CSV/TSV ``source``.

    Only a repointed ``path`` source qualifies. Recipes that read their own
    ``.json`` outputs as one text column (isoseq, crisprseq, pairgenomealign)
    declare that ``.json`` path or glob themselves, and keep that read.
    """
    # Lazily, for the same reason as in ``_as_data_root``.
    from depictio.cli.cli.utils.record_sheets import is_record_sheet

    return (
        source.format in ("csv", "tsv")
        and source.glob_pattern is None
        and source.path is not None
        and not is_record_sheet(source.path)
        and is_record_sheet(location)
    )


def _read_record_source(
    location: str | Path, source: RecipeSource, root: DataRoot | None, rel_path: str | None
) -> pl.DataFrame:
    """A YAML/JSON samplesheet ``source`` points at, read through ``root`` when under it."""
    from depictio.cli.cli.utils.record_sheets import RecordSheetError, read_record_sheet

    if root is not None and rel_path is not None:
        data = root.read_bytes(rel_path)
    else:
        data = Path(location).read_bytes()
    try:
        return read_record_sheet(data, str(location))
    except RecordSheetError as exc:
        raise RecipeError(f"Source '{source.ref}': {exc}") from exc


def _format_readers(source: RecipeSource) -> tuple[Any, Any, dict]:
    """``(lazy reader, eager reader, kwargs the format itself implies)`` for ``source``.

    Looked up per call rather than built once at import, so the readers stay
    the attributes of ``pl`` at the time of the read.
    """
    readers = {
        "csv": (pl.scan_csv, pl.read_csv, {}),
        "tsv": (pl.scan_csv, pl.read_csv, {"separator": "\t"}),
        "parquet": (pl.scan_parquet, pl.read_parquet, {}),
    }
    if source.format not in readers:
        raise RecipeError(f"Unsupported format: {source.format}")
    return readers[source.format]


def _with_source_path(
    df: pl.DataFrame, source: RecipeSource, location: str | Path, rel_path: str | None
) -> pl.DataFrame:
    """``df`` with the ``source_path`` column ``source`` declares, if it declares one."""
    if not source.source_path:
        return df
    if source.source_path in df.columns:
        raise RecipeError(
            f"Source '{source.ref}': source_path column '{source.source_path}' "
            f"already exists in {location}"
        )
    label = rel_path if rel_path is not None else str(location)
    return df.with_columns(pl.lit(label, dtype=pl.Utf8).alias(source.source_path))


def _read_source_outside_root(
    location: str, source: RecipeSource, root: DataRoot
) -> pl.DataFrame | None:
    """Read a source a template pointed outside the data root, as it is.

    ``location`` is an absolute path or a URL the root does not hold, such as
    a ``--var SAMPLESHEET_FILE=...`` override. A URL is read by the reader
    every ``url`` collection is read with (``deltatables._read_remote_file_lazy``):
    an ``s3://`` one through the read target resolved for that very URL, with
    the configuration the root was built with, an ``http(s)://`` one through
    the fetch gateway in server context. A local path follows the rule every
    location outside the root follows (``templates._local_fallback_allowed``):
    the CLI reads its own disk, a server only what its local-data policy
    allows, and refuses anything else before looking at its disk at all.

    Returns None for an optional local source that is absent.
    """
    if _is_remote_location(location):
        from depictio.cli.cli.utils.deltatables import _read_remote_file_lazy
        from depictio.cli.cli.utils.record_sheets import RecordSheetError

        _scan, _read, format_kwargs = _format_readers(source)
        kwargs = {**format_kwargs, **(source.read_kwargs or {})}
        if _repointed_at_record_sheet(source, location):
            # No CSV options, so the remote reader reads it as records.
            kwargs = {}
        elif source.format == "csv":
            # The format the recipe declared, as on every other read of it: the
            # remote reader would otherwise pick tabs for a ``.tsv`` name.
            kwargs.setdefault("separator", ",")
        try:
            frame = _read_remote_file_lazy(location, source.format, kwargs, root.CLI_config)
        except RecordSheetError as exc:
            raise RecipeError(f"Source '{source.ref}': {exc}") from exc
        df = _with_source_path(frame.collect(), source, location, None)
        return _mark_record_sheet(df) if _repointed_at_record_sheet(source, location) else df

    from depictio.cli.cli.utils.templates import _local_fallback_allowed

    if not _local_fallback_allowed(root, location):
        raise RecipeError(
            f"Source '{source.ref}': '{location}' is outside the data root "
            f"{root.location}, and not in a folder this server may read."
        )
    if not Path(location).is_file():
        if source.optional:
            return None
        raise RecipeSourceMissing(f"Source '{source.ref}': file not found: {location}")
    return _read_source_file(location, source)


def _resolve_glob_source(
    root: str | Path | DataRoot, source: RecipeSource, pattern_override: str | None = None
) -> pl.DataFrame | None:
    """Glob for multiple files and concatenate into a single DataFrame.

    ``pattern_override`` (from a DC's ``source_overrides``) repoints the source at a
    different glob — e.g. a route conditional pointing the lineage recipes at the
    nanopore ``artic_minion/`` layout instead of the illumina default.

    A glob that matches nothing is ``None`` for an ``optional`` source (as for an
    optional file) and an error otherwise.
    """
    pattern = pattern_override or source.glob_pattern
    if pattern is None:
        raise RecipeError(f"Source '{source.ref}' has no glob_pattern")

    root = _as_data_root(root)
    matched_files = root.glob(pattern)  # root-relative and already sorted
    if not matched_files:
        if source.optional:
            return None
        raise RecipeSourceMissing(
            f"Source '{source.ref}': no files matched glob '{pattern}' in {root.location}"
        )

    storage_options = root.storage_options()
    frames: list[pl.DataFrame] = []
    for rel_path in matched_files:
        # A zero-byte output has no header for polars to parse; it holds no rows.
        if root.size(rel_path) == 0:
            continue
        df = _read_source_file(
            root.url(rel_path), source, storage_options, rel_path=rel_path, root=root
        )
        if not df.is_empty():
            frames.append(df)

    if not frames:
        raise RecipeError(
            f"Source '{source.ref}': all {len(matched_files)} matched files were empty "
            f"in {root.location}"
        )

    return pl.concat(frames, how="diagonal_relaxed")


def resolve_sources(
    module: ModuleType,
    data_dir: str | Path | DataRoot,
    overrides: dict[str, str] | None = None,
) -> dict[str, pl.DataFrame]:
    """Resolve all recipe sources by reading files from data_dir.

    Args:
        module: Loaded recipe module.
        data_dir: Root holding the workflow output files. A directory path
            (``str`` or ``Path``) or a :class:`DataRoot`, which is how a recipe
            gets pointed at an ``s3://`` prefix instead of a local directory.
        overrides: Optional dict mapping source ref -> override path (file sources)
            or glob pattern (glob sources). A path is relative to the root, or
            an absolute path or URL: one under the root is read through it, one
            outside it as it is (see ``_read_source_outside_root``).

    Returns:
        Dict mapping source ref names to DataFrames.
    """
    # Lazily, for the same reason as in ``_as_data_root``.
    from depictio.cli.cli.utils.data_root import relative_to_root

    root = _as_data_root(data_dir)
    storage_options = root.storage_options()
    sources: dict[str, pl.DataFrame] = {}

    for source in module.SOURCES:
        if source.dc_ref is not None:
            # dc_ref sources are resolved externally (e.g. from another DC)
            # Skip here — caller must inject these
            continue

        # Glob-based source: match multiple files and concatenate. An override (if
        # present) repoints the glob pattern for this source.
        if source.glob_pattern is not None:
            pattern_override = overrides.get(source.ref) if overrides else None
            sources[source.ref] = _resolve_glob_source(root, source, pattern_override)  # type: ignore[assignment]
            continue

        # Determine file path (apply override if present)
        location = source.path
        if overrides and source.ref in overrides:
            location = overrides[source.ref]

        if location is None:
            raise RecipeError(f"Source '{source.ref}' has no path and no dc_ref")

        rel_path = relative_to_root(root, location)
        if rel_path is None:
            # An absolute path or a URL outside the root, which a template
            # variable can set (``{SAMPLESHEET_FILE}``): read as it is, never
            # re-rooted under the root.
            file_location = location
            df = _read_source_outside_root(location, source, root)
            if df is None:
                sources[source.ref] = None  # type: ignore[assignment]
                continue
        else:
            # The absolute location, so a failure names s3://bucket/prefix/file.csv
            # rather than the bare fragment the recipe declared.
            file_location = root.url(rel_path)
            if not root.exists(rel_path):
                # `optional` has always meant "pass None to transform() when this
                # source cannot be resolved"; until now only dc_ref sources honoured
                # it, so an optional *file* source still hard-failed the whole recipe.
                # A recipe that can read either of two pipeline outputs (they vary by
                # classifier / route) has no way to express that otherwise.
                if source.optional:
                    sources[source.ref] = None  # type: ignore[assignment]
                    continue
                raise RecipeSourceMissing(f"Source '{source.ref}': file not found: {file_location}")
            df = _read_source_file(
                file_location, source, storage_options, rel_path=rel_path, root=root
            )

        if df.is_empty():
            raise RecipeError(f"Source '{source.ref}' loaded 0 rows from {file_location}")

        sources[source.ref] = df

    return sources


# ---------------------------------------------------------------------------
# Checkpoints 3 to 5: check inputs, execute transform, validate output
# ---------------------------------------------------------------------------


def _is_polars_dtype(dtype: object) -> bool:
    return isinstance(dtype, pl.DataType) or (
        isinstance(dtype, type) and issubclass(dtype, pl.DataType)
    )


def _dtype_compatible(actual: pl.DataType, declared: pl.DataType) -> bool:
    """Whether a column read as ``actual`` can feed a recipe that expects ``declared``.

    Readers infer types from the data, so the check is deliberately loose: a text
    or all-null column may still hold what the recipe casts itself, and one numeric
    type stands for another (a count column of whole numbers reads as Int64 even
    where the recipe declares Float64). A structural mismatch, such as a list
    where a number is expected, still fails.
    """
    if actual == declared or actual in (pl.String, pl.Null):
        return True
    if actual.is_numeric() and declared.is_numeric():
        return True
    return declared == pl.String and not actual.is_nested()


def validate_sources(
    module: ModuleType, sources: dict[str, pl.DataFrame | None], recipe_name: str
) -> list[str]:
    """Check every resolved source against its ``input_schema``.

    Runs between resolving the sources and ``transform()``, so a pipeline output
    that lacks a column names the source and the column instead of failing inside
    the transform. Sources without an ``input_schema``, optional sources resolved
    to ``None`` and empty ``dc_ref`` frames (an upstream DC with no rows, which the
    recipe handles itself; empty files already fail while resolving) are skipped.

    Returns the refs of the sources that were checked.
    """
    checked: list[str] = []
    for source in module.SOURCES:
        df = sources.get(source.ref)
        if not source.input_schema or df is None or df.is_empty():
            continue
        # A YAML/JSON samplesheet names its fields keys, a table columns.
        field = "key" if _from_record_sheet(df) else "column"
        missing = [c for c in source.input_schema if c not in df.columns]
        if missing:
            raise RecipeError(
                f"Recipe {recipe_name}: source '{source.ref}' lacks input {field}(s) "
                f"{missing}. Got {field}s: {df.columns}"
            )
        for col_name, declared in source.input_schema.items():
            actual = df[col_name].dtype
            if not _dtype_compatible(actual, declared):
                raise RecipeError(
                    f"Recipe {recipe_name}: source '{source.ref}' input {field} "
                    f"'{col_name}' expected {declared}, got {actual}"
                )
        checked.append(source.ref)
    return checked


def validate_schema(
    result: pl.DataFrame,
    output_schema: dict,
    recipe_name: str,
    optional_output_schema: dict | None = None,
) -> None:
    """Validate that the result DataFrame matches the recipe's output schema.

    The schemas describe the stored table: a ``pl.Utf8`` column may be held as
    Categorical or Enum to save memory, it is written as String (#1418).

    Args:
        result: Output DataFrame from transform().
        output_schema: Dict of column_name → polars dtype. All must be present.
        recipe_name: Recipe name used in error messages.
        optional_output_schema: Dict of column_name → polars dtype. Validated only if present.
    """

    def stored(dtype: pl.DataType) -> pl.DataType:
        return pl.String() if isinstance(dtype, pl.Categorical | pl.Enum) else dtype

    for col_name, expected_type in output_schema.items():
        if col_name not in result.columns:
            raise RecipeError(
                f"Recipe {recipe_name}: missing output column '{col_name}'. "
                f"Got columns: {result.columns}"
            )
        actual_type = result[col_name].dtype
        if stored(actual_type) != expected_type:
            raise RecipeError(
                f"Recipe {recipe_name}: column '{col_name}' expected {expected_type}, "
                f"got {actual_type}"
            )
    if optional_output_schema:
        for col_name, expected_type in optional_output_schema.items():
            if col_name in result.columns:
                actual_type = result[col_name].dtype
                if stored(actual_type) != expected_type:
                    raise RecipeError(
                        f"Recipe {recipe_name}: optional column '{col_name}' expected "
                        f"{expected_type}, got {actual_type}"
                    )


_UNRESOLVED_PLACEHOLDER = re.compile(r"^\{[A-Z0-9_]+\}$")


@dataclass(frozen=True)
class RecipeContext:
    """What a two-argument ``transform(sources, context)`` receives.

    Recipes that describe files rather than read them (a genome-track manifest
    lists which track files the run published) ask the run folder what it holds
    through this, local or remote alike.
    """

    root: DataRoot
    # The collection's dc_specific_properties (e.g. a genomic_tracks manifest's
    # ``remote_base_uri``, set when the run is read in place).
    properties: dict = field(default_factory=dict)

    @classmethod
    def of(cls, data_dir: str | Path | DataRoot, properties: dict | None = None) -> RecipeContext:
        """The context for whatever data root the caller passed."""
        return cls(root=_as_data_root(data_dir), properties=dict(properties or {}))

    @property
    def reads_in_place(self) -> bool:
        """The run's files are read from a remote folder, not from ``root``."""
        return bool(self.properties.get("remote_base_uri"))

    def exists(self, rel_path: str) -> bool:
        """Whether the run folder holds ``rel_path``."""
        return self.root.exists(rel_path)

    def glob(self, pattern: str) -> list[str]:
        """Run-relative paths matching ``pattern`` (sorted)."""
        return self.root.glob(pattern)


def call_transform(
    module: Any,
    sources: dict,
    params: dict[str, str] | None = None,
    context: RecipeContext | None = None,
    entry: str = "transform",
) -> Any:
    """Call ``module.transform`` (or ``entry``), passing template ``params`` and the run context when it takes them.

    A recipe opts in to ``params`` by declaring a ``params`` keyword. Values that are
    still an unresolved ``{VAR}`` placeholder (the template variable was not set) are
    dropped, so the recipe sees the parameter as absent and uses its own fallback.
    A recipe opts in to the context with a second positional argument.
    """
    fn = getattr(module, entry)
    declared = inspect.signature(fn).parameters
    args: list[Any] = [sources]
    if context is not None and len([n for n in declared if n != "params"]) >= 2:
        args.append(context)
    if params is not None and "params" in declared:
        clean = {
            k: v
            for k, v in params.items()
            if v is not None and not _UNRESOLVED_PLACEHOLDER.match(str(v).strip())
        }
        return fn(*args, params=clean)
    return fn(*args)


def streams_batches(module: Any) -> bool:
    """Whether a recipe can hand its output over in batches (``transform_batches``).

    A recipe whose table is too large to hold next to its inputs (#1418) may
    define ``transform_batches(sources)``, a generator of frames that together
    make the table ``transform`` returns. Ingestion then writes each batch as
    it comes (``execute_recipe_batches``); every other caller (preview, an
    aggregate over runs, the tests) keeps calling ``transform``. A batch must
    not carry ``depictio_run_id``: ingestion tags the rows with their run.
    A batch keeps its row order in the table, the batches may land in any order
    (``delta_versioning._arrow_stream``): no batch may need another to be read.
    """
    return callable(getattr(module, "transform_batches", None))


def execute_recipe(
    recipe_name: str,
    data_dir: str | Path | DataRoot,
    overrides: dict[str, str] | None = None,
    extra_sources: dict[str, pl.DataFrame] | None = None,
    pipeline_version: str | None = None,
    params: dict[str, str] | None = None,
    properties: dict | None = None,
    sources: dict[str, pl.DataFrame] | None = None,
) -> pl.DataFrame:
    """Full pipeline: load → resolve → transform → validate.

    Args:
        recipe_name: Pipeline-qualified recipe name (e.g. 'nf-core/ampliseq/alpha_diversity.py').
        data_dir: Root holding the workflow output files: a directory path or a
            :class:`DataRoot` (which may be an ``s3://`` prefix).
        overrides: Optional source path overrides.
        extra_sources: Optional pre-loaded DataFrames for dc_ref sources.
        pipeline_version: Optional pipeline version for version-specific recipe lookup.
        params: Optional template parameters, passed to ``transform(sources, params=...)``
            when the recipe accepts them (see ``call_transform``).
        sources: The file sources, already read (from several run folders,
            put back together by the caller). ``data_dir`` is then only the
            context the transform receives.

    Returns:
        Validated output DataFrame.
    """
    module, sources = _prepared_sources(
        recipe_name, data_dir, overrides, extra_sources, pipeline_version, sources
    )

    # Checkpoint 4: transform. A recipe whose transform() takes a second
    # argument also receives the run folder, for recipes that describe files
    # rather than read them (a genome-track manifest lists which track files
    # the run published).
    result = call_transform(module, sources, params, RecipeContext.of(data_dir, properties))
    if not isinstance(result, pl.DataFrame):
        raise RecipeError(
            f"Recipe {recipe_name}: transform() must return pl.DataFrame, "
            f"got {type(result).__name__}"
        )
    if result.is_empty():
        raise RecipeError(f"Recipe {recipe_name}: transform() produced empty DataFrame")

    # Checkpoint 5: output schema (required + optional columns)
    validate_schema(
        result,
        module.OUTPUT_SCHEMA,
        recipe_name,
        getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None),
    )

    return result


def execute_recipe_batches(
    recipe_name: str,
    data_dir: str | Path | DataRoot,
    overrides: dict[str, str] | None = None,
    extra_sources: dict[str, pl.DataFrame] | None = None,
    pipeline_version: str | None = None,
    params: dict[str, str] | None = None,
    properties: dict | None = None,
    sources: dict[str, pl.DataFrame] | None = None,
) -> Iterator[pl.DataFrame]:
    """``execute_recipe`` for a recipe that ``streams_batches``: its table, a batch at a time.

    Loading, reading the sources and checking them happen at the call, so a
    missing input raises here (``RecipeSourceMissing``) as it does for
    ``execute_recipe``. Each batch is checked against the output schema as it
    comes; empty ones are dropped, and a recipe that yields no row at all
    raises once its batches are spent, as an empty table does.
    """
    module, sources = _prepared_sources(
        recipe_name, data_dir, overrides, extra_sources, pipeline_version, sources
    )
    if not streams_batches(module):
        raise RecipeError(f"Recipe {recipe_name} has no transform_batches()")
    batches = call_transform(
        module,
        sources,
        params,
        RecipeContext.of(data_dir, properties),
        entry="transform_batches",
    )
    optional = getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None)

    def checked() -> Iterator[pl.DataFrame]:
        produced = False
        for batch in batches:
            if not isinstance(batch, pl.DataFrame):
                raise RecipeError(
                    f"Recipe {recipe_name}: transform_batches() must yield pl.DataFrame, "
                    f"got {type(batch).__name__}"
                )
            if batch.is_empty():
                continue
            validate_schema(batch, module.OUTPUT_SCHEMA, recipe_name, optional)
            produced = True
            yield batch
        if not produced:
            raise RecipeError(f"Recipe {recipe_name}: transform_batches() produced no row")

    return checked()


def _prepared_sources(
    recipe_name: str,
    data_dir: str | Path | DataRoot,
    overrides: dict[str, str] | None,
    extra_sources: dict[str, pl.DataFrame] | None,
    pipeline_version: str | None,
    sources: dict[str, pl.DataFrame] | None,
) -> tuple[ModuleType, dict[str, pl.DataFrame]]:
    """Checkpoints 1 to 3 of ``execute_recipe``: the loaded recipe and its checked sources."""
    # Checkpoint 1: load
    module = load_recipe(recipe_name, pipeline_version)

    # Checkpoint 2: resolve
    sources = dict(sources) if sources is not None else resolve_sources(module, data_dir, overrides)

    # Inject dc_ref sources
    if extra_sources:
        sources.update(extra_sources)

    # Check all sources are resolved; optional missing dc_ref sources are injected as None
    for source in module.SOURCES:
        if source.ref not in sources:
            if source.dc_ref is not None and source.optional:
                sources[source.ref] = None  # type: ignore[assignment]
            else:
                raise RecipeError(
                    f"Source '{source.ref}' not resolved. "
                    f"If it uses dc_ref, provide it via extra_sources."
                )

    # Checkpoint 3: input schema
    validate_sources(module, sources, recipe_name)
    return module, sources


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def list_recipes() -> list[str]:
    """List all available shared recipe names.

    Returns pipeline-qualified names (e.g. 'nf-core/ampliseq/alpha_diversity.py').
    Version-specific overrides are not listed — they are applied automatically
    based on pipeline version context during execution.
    """
    recipes = []
    for py_file in PROJECTS_DIR.rglob("recipes/*.py"):
        if py_file.name == "__init__.py":
            continue
        # Version overrides live inside a directory that has a template.yaml.
        # Shared recipes live at the pipeline level (no template.yaml in parent).
        version_dir = py_file.parent.parent  # dir containing the "recipes/" folder
        if (version_dir / "template.yaml").exists():
            continue  # skip version-specific overrides
        pipeline_dir = version_dir
        recipe_ref = str(pipeline_dir.relative_to(PROJECTS_DIR) / py_file.name)
        recipes.append(recipe_ref)
    # Module-owned recipes co-located in catalog module folders (`<module>/{name}.py`).
    for py_file in CATALOG_DIR.glob("*/*.py"):
        if py_file.name == "__init__.py":
            continue
        recipes.append(f"{py_file.parent.name}/{py_file.name}")
    return sorted(recipes)
