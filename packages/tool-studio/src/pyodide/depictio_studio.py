"""Tool Studio's entry points inside Pyodide (src/pyodide/engine.ts).

Runs next to the depictio modules the engine ships (depictio.recipes verbatim,
recipes.lib verbatim, RecipeSource extracted from the real transforms.py), and
does what ``catalog validate`` and ``execute_recipe`` do, with the server's own
functions wherever they do not need a data root on disk:

* ``polars_schema`` is ``read_fixture_schema`` (advanced_viz/catalog.py) on a
  text fixture: ``pl.read_csv`` with the separator the suffix implies and
  ``infer_schema_length=10_000``, dtype names without their parameters.
* ``run_recipe`` writes the recipe where ``resolve_recipe_path`` looks for a
  module-owned recipe and calls the real ``load_recipe`` (checkpoint 1), reads
  each source with the real ``_read_source_file`` (format, read_kwargs,
  source_path), then ``validate_sources``, ``call_transform`` and
  ``validate_schema`` (checkpoints 3 to 5). Only the binding of sources to
  files is Studio's own: the user hands files, not a run folder.

Every entry point takes and returns JSON strings, so the JS side never holds a
PyProxy.
"""

from __future__ import annotations

import ast
import contextlib
import fnmatch
import io
import json
import shutil
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import polars as pl

sys.dont_write_bytecode = True  # a rewritten recipe must never run a stale .pyc

ROOT = Path(__file__).parent
RUN_DIR = Path("/tmp/depictio_studio_run")
RECIPE_REF = "studio/recipe.py"
MAX_ROWS = 2000


def _dtype_name(dtype: object) -> str:
    """``_dtype_name`` of advanced_viz/catalog.py: the base name, no parameters."""
    return str(dtype).split("(", 1)[0]


# --- catalog validate's fixture schema ------------------------------------------


def polars_schema(file_name: str, text: str) -> str:
    sep = "\t" if PurePosixPath(file_name).suffix == ".tsv" else ","
    schema = pl.read_csv(
        io.BytesIO(text.encode("utf-8")), separator=sep, infer_schema_length=10_000
    ).schema
    return json.dumps([[name, _dtype_name(dtype)] for name, dtype in schema.items()])


# --- which packages a recipe needs ----------------------------------------------


def _module_file(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def _imports(tree: ast.AST, walk_all: bool) -> set[str]:
    nodes = ast.walk(tree) if walk_all else getattr(tree, "body", [])
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            # ``from depictio.recipes.lib import mosdepth`` imports a submodule.
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def imports_needed(code: str) -> str:
    """Top-level third-party packages the recipe reaches, through the shipped
    depictio modules too (their module-level imports only: a lazy import inside
    a helper the recipe never calls should not cost a download)."""
    try:
        pending = list(_imports(ast.parse(code), walk_all=True))
    except SyntaxError:
        pending = []
    pending.append("depictio.recipes")  # what run_recipe itself imports
    seen: set[str] = set()
    third_party: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        top = name.split(".")[0]
        if top == "depictio":
            path = _module_file(name)
            if path is not None:
                pending.extend(_imports(ast.parse(path.read_text()), walk_all=False))
        elif top not in sys.stdlib_module_names and top != "__future__":
            third_party.add(top)
    return json.dumps(sorted(third_party))


# --- running a recipe -----------------------------------------------------------


@dataclass
class _File:
    ref: str | None
    rel: str  # the path a ``source_path`` column records
    path: Path  # where it sits in the Pyodide FS


class _StudioRoot:
    """The ``DataRoot`` slice ``RecipeContext`` exposes, over the files handed in."""

    def __init__(self, files: list[_File]):
        self.location = str(RUN_DIR)
        self._rels = sorted(f.rel for f in files)

    def exists(self, rel_path: str) -> bool:
        return rel_path in self._rels

    def glob(self, pattern: str) -> list[str]:
        return [r for r in self._rels if fnmatch.fnmatch(r, pattern)]


def _write_files(raw: list[dict[str, Any]]) -> list[_File]:
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    files = []
    for i, item in enumerate(raw):
        name = str(item["fileName"])
        path = RUN_DIR / str(i) / (PurePosixPath(name).name or f"file{i}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(item.get("text", "")))
        rel = str(item.get("sourcePath") or name)
        files.append(_File(ref=item.get("ref") or None, rel=rel, path=path))
    return files


def _matches(source: Any, rel: str) -> bool:
    pattern = source.glob_pattern or source.path
    if not pattern:
        return False
    if fnmatch.fnmatch(rel, pattern):
        return True
    return fnmatch.fnmatch(PurePosixPath(rel).name, PurePosixPath(pattern).name)


def _bind(module: Any, files: list[_File], recipes: Any) -> dict[str, list[_File]]:
    """Which files feed which source: the refs the caller set; else one source and
    one file bind; else each file goes to the one source whose path or glob it
    matches."""
    refs = [s.ref for s in module.SOURCES]
    bound: dict[str, list[_File]] = {r: [] for r in refs}
    if any(f.ref for f in files):
        for f in files:
            if f.ref is None:
                continue
            if f.ref not in bound:
                raise recipes.RecipeError(
                    f"File '{f.rel}' is bound to source '{f.ref}', which the recipe does not "
                    f"declare (SOURCES: {refs})"
                )
            bound[f.ref].append(f)
        return bound
    if len(refs) == 1 and (len(files) == 1 or module.SOURCES[0].glob_pattern):
        bound[refs[0]] = list(files)
        return bound
    for f in files:
        hits = [s.ref for s in module.SOURCES if _matches(s, f.rel)]
        if len(hits) == 1:
            bound[hits[0]].append(f)
    return bound


def _guess_format(f: _File) -> str:
    suffix = PurePosixPath(f.rel).suffix.lower()
    if suffix in (".tsv", ".tab"):
        return "tsv"
    if suffix == ".csv":
        return "csv"
    with f.path.open() as fh:
        header = fh.readline()
    return "tsv" if "\t" in header and "," not in header else "csv"


def _as_read(source: Any, f: _File) -> Any:
    """A ``dc_ref`` source is read by its upstream collection's YAML in depictio,
    so its ``format`` default says nothing about the file: unless the recipe set
    one, the file's own extension (or header) decides."""
    if source.dc_ref is None or "format" in source.model_fields_set:
        return source
    return source.model_copy(update={"format": _guess_format(f)})


def _read(source: Any, files: list[_File], recipes: Any) -> pl.DataFrame | None:
    """One source, the way ``resolve_sources`` reads it: a glob source (or several
    files) concatenated diagonally, skipping empty files; a file source read
    whole and refused when empty. A ``dc_ref`` source stands for an upstream
    collection, whose file the user handed in."""
    if not files:
        if source.optional:
            return None
        raise recipes.RecipeSourceMissing(
            f"Source '{source.ref}': no file was given for it"
            + (f" (path {source.path!r})" if source.path else "")
            + (f" (glob {source.glob_pattern!r})" if source.glob_pattern else "")
            + (f" (dc_ref {source.dc_ref!r})" if source.dc_ref else "")
        )
    if source.glob_pattern is not None or len(files) > 1:
        frames = []
        for f in files:
            if f.path.stat().st_size == 0:
                continue
            df = recipes._read_source_file(str(f.path), _as_read(source, f), rel_path=f.rel)
            if not df.is_empty():
                frames.append(df)
        if not frames:
            raise recipes.RecipeError(
                f"Source '{source.ref}': all {len(files)} matched files were empty"
            )
        return pl.concat(frames, how="diagonal_relaxed")
    f = files[0]
    df = recipes._read_source_file(str(f.path), _as_read(source, f), rel_path=f.rel)
    if df.is_empty() and source.dc_ref is None:
        raise recipes.RecipeError(f"Source '{source.ref}' loaded 0 rows from {f.rel}")
    return df


def _tsv(df: pl.DataFrame) -> str:
    nested = [n for n, d in df.schema.items() if d.is_nested() or d == pl.Object]
    if nested:
        df = df.with_columns(
            pl.col(n).map_elements(
                lambda v: json.dumps(v.to_list() if hasattr(v, "to_list") else v, default=str),
                return_dtype=pl.String,
            )
            for n in nested
        )
    return df.head(MAX_ROWS).write_csv(separator="\t")


def _execute(code: str, raw: list[dict[str, Any]], state: dict[str, Any]) -> pl.DataFrame:
    import depictio.recipes as recipes

    recipe_path = Path(recipes.CATALOG_DIR) / RECIPE_REF
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text(code)

    # Checkpoint 1: the real loader (SOURCES / OUTPUT_SCHEMA / transform checks).
    module = recipes.load_recipe(RECIPE_REF)
    state["module"] = module

    # Checkpoint 2: read the handed-in files as resolve_sources reads a run folder.
    files = _write_files(raw)
    bound = _bind(module, files, recipes)
    sources: dict[str, pl.DataFrame | None] = {}
    for source in module.SOURCES:
        sources[source.ref] = _read(source, bound.get(source.ref, []), recipes)

    # Checkpoints 3 to 5, as execute_recipe runs them.
    recipes.validate_sources(module, sources, RECIPE_REF)
    context = recipes.RecipeContext(root=_StudioRoot(files), properties={})  # type: ignore[arg-type]
    result = recipes.call_transform(module, sources, None, context)
    if not isinstance(result, pl.DataFrame):
        raise recipes.RecipeError(
            f"Recipe {RECIPE_REF}: transform() must return pl.DataFrame, "
            f"got {type(result).__name__}"
        )
    if result.is_empty():
        raise recipes.RecipeError(f"Recipe {RECIPE_REF}: transform() produced empty DataFrame")
    recipes.validate_schema(
        result, module.OUTPUT_SCHEMA, RECIPE_REF, getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None)
    )
    return result


def _traceback_tail(limit: int = 30) -> str:
    lines = traceback.format_exc().rstrip().splitlines()
    return "\n".join(lines[-limit:])


def run_recipe(code: str, raw_json: str) -> str:
    raw = json.loads(raw_json)
    out = io.StringIO()
    state: dict[str, Any] = {}
    payload: dict[str, Any] = {
        "ok": False,
        "columns": [],
        "tsv": "",
        "rowCount": 0,
        "outputSchema": None,
        "stdout": "",
    }
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            result = _execute(code, raw, state)
        payload.update(
            ok=True,
            columns=[{"name": n, "dtype": _dtype_name(d)} for n, d in result.schema.items()],
            tsv=_tsv(result),
            rowCount=result.height,
        )
    except BaseException:  # noqa: BLE001 - a recipe's SystemExit is a failure too
        payload["error"] = _traceback_tail()
    module = state.get("module")
    schema = getattr(module, "OUTPUT_SCHEMA", None) if module is not None else None
    if isinstance(schema, dict):
        payload["outputSchema"] = {str(k): _dtype_name(v) for k, v in schema.items()}
    payload["stdout"] = out.getvalue()
    return json.dumps(payload)
