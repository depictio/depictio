"""Declarative bio-catalog: the community-extensible tool→viz mapping layer.

Structured like MultiQC modules / nf-core modules:

    depictio/catalog/
      pangolin.yaml            # single-output tool  -> one file
      qiime2/                  # multi-output tool   -> a folder
        module.yaml            #   tool identity (links to nf-core + bio.tools)
        taxa_barplot.yaml      #   one output / running mode = one file
        ancombc.yaml
        ...

A **module** is a tool. An **output** is one of the tool's files (one running
mode). Each output declares, self-contained:

  - `find`   — how depictio-cli *recognises* the file on disk (filename glob /
               path glob / content match / required columns), exactly like
               MultiQC's search_patterns (`fn` / `contents`).
  - `file_schema` — the columns + dtypes the tool actually writes (the raw file
               as-emitted), so you can see what the file looks like.
  - `reshape`— how to turn that raw file into a viz-ready shape (melt / pivot /
               aggregate, or a `recipe` for arbitrary logic).
  - `feeds_viz` + `role_mapping` — which depictio visualisation(s) it maps to.

Identity is resolvable: `biotools_id` -> https://bio.tools/<id>,
`nf_core_module` -> the nf-core/modules tree, `edam_*` -> edamontology.org.

Catalog entries compile down to the `Producer` primitives the suggestion engine
already understands (see `entry_to_producers`), and merge via
`producers.all_producers()` (hand-curated wins on name collision).
"""

from __future__ import annotations

from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.models.components.types import AdvancedVizKind

if TYPE_CHECKING:
    from depictio.models.components.advanced_viz.producers import Producer

CATALOG_DIR = Path(__file__).resolve().parents[3] / "catalog"

ReshapeKind = Literal["identity", "melt", "pivot", "aggregate", "recipe"]


# ---------------------------------------------------------------------------
# Resolvable identity links
# ---------------------------------------------------------------------------


def biotools_url(biotools_id: str) -> str:
    return f"https://bio.tools/{biotools_id}"


def nf_core_module_url(module: str) -> str:
    return f"https://github.com/nf-core/modules/tree/master/modules/nf-core/{module}"


def edam_url(term: str) -> str:
    return f"http://edamontology.org/{term}"


# ---------------------------------------------------------------------------
# Recognition: how depictio-cli finds a file (MultiQC search_patterns analogue)
# ---------------------------------------------------------------------------


class CatalogFind(BaseModel):
    """How to recognise this tool output among the files in a run directory.

    Mirrors MultiQC's search_patterns: a filename glob (`fn`), a content match
    (`contents`), plus depictio extras (a path glob and a tabular column check).
    A file matches when *all* of the declared conditions hold.
    """

    filename: str | None = None  # glob on the basename, e.g. "*.pangolin.csv"
    path_glob: str | None = None  # glob on the path relative to the run root
    content_contains: str | None = None  # substring in the file head (text files)
    required_columns: list[str] = Field(default_factory=list)  # must all be present

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one_condition(self) -> CatalogFind:
        if not (self.filename or self.path_glob or self.content_contains or self.required_columns):
            raise ValueError(
                "find must declare at least one of: filename, path_glob, "
                "content_contains, required_columns"
            )
        return self


class CatalogReadOptions(BaseModel):
    """How to read the raw file into a DataFrame."""

    format: Literal["csv", "tsv", "parquet"] = "csv"
    separator: str | None = None
    comment_prefix: str | None = None
    skip_rows: int = 0
    has_header: bool = True

    model_config = ConfigDict(extra="forbid")


class CatalogReshape(BaseModel):
    """Declarative reshape from the raw file's shape to a viz-ready shape.

    `kind="recipe"` is the escape hatch for arbitrary logic and points at an
    existing `projects/<pipeline>/recipes/<name>.py` transform.
    """

    kind: ReshapeKind = "identity"

    # melt (wide -> long)
    id_vars: list[str] | None = None
    value_vars: list[str] | None = None
    variable_name: str | None = None
    value_name: str | None = None

    # pivot (long -> wide)
    index: list[str] | None = None
    on: str | None = None
    values: str | None = None

    # aggregate
    group_by: list[str] | None = None
    agg: Literal["sum", "mean", "median", "max", "min", "count"] | None = None

    # recipe escape hatch — pipeline-qualified recipe name
    recipe: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check_required_params(self) -> CatalogReshape:
        if self.kind == "recipe" and not self.recipe:
            raise ValueError("reshape.kind='recipe' requires a 'recipe' reference")
        if self.kind == "melt" and not self.id_vars:
            raise ValueError("reshape.kind='melt' requires 'id_vars'")
        if self.kind == "pivot" and not (self.on and self.values):
            raise ValueError("reshape.kind='pivot' requires 'on' and 'values'")
        if self.kind == "aggregate" and not (self.group_by and self.agg):
            raise ValueError("reshape.kind='aggregate' requires 'group_by' and 'agg'")
        return self


class CatalogOutput(BaseModel):
    """One file a tool emits, in one running mode → one visualisation mapping."""

    id: str
    description: str = ""
    mode: str | None = None  # running mode / subcommand (e.g. "taxa-barplot")

    # Per-output identity (overrides the module's, for multi-module tools like
    # QIIME 2 whose subcommands are separate nf-core modules).
    nf_core_module: str | None = None
    biotools_id: str | None = None
    edam_operations: list[str] = Field(default_factory=list)
    edam_formats: list[str] = Field(default_factory=list)

    # Which pipeline(s) emit this output (provenance), e.g. "nf-core/ampliseq".
    pipelines: list[str] = Field(default_factory=list)

    # Recognition + parsing.
    find: CatalogFind
    read_options: CatalogReadOptions = Field(default_factory=CatalogReadOptions)

    # The schema of the file AS EMITTED by the tool (column name -> polars dtype
    # string). Documents what the raw file looks like before any reshape.
    file_schema: dict[str, str] = Field(default_factory=dict)

    # Raw file -> viz-ready shape, and the viz it then maps to.
    reshape: CatalogReshape = Field(default_factory=CatalogReshape)
    feeds_viz: list[AdvancedVizKind] = Field(default_factory=list)
    role_mapping: dict[AdvancedVizKind, dict[str, str]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class CatalogModule(BaseModel):
    """A tool (module). Carries the resolvable bio.tools / nf-core / EDAM identity."""

    id: str
    name: str
    description: str = ""
    homepage: str | None = None
    nf_core_module: str | None = None  # default for outputs that don't override
    biotools_id: str | None = None
    edam_topics: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CatalogEntry(BaseModel):
    """One module + all of its outputs (assembled from a file or a folder)."""

    schema_version: int = 1
    module: CatalogModule
    outputs: list[CatalogOutput] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_output_ids(self) -> CatalogEntry:
        ids = [o.id for o in self.outputs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate output ids in module {self.module.id!r}: {sorted(dupes)}")
        return self


# ---------------------------------------------------------------------------
# Compilation: CatalogEntry -> Producer primitives
# ---------------------------------------------------------------------------


def entry_to_producers(entry: CatalogEntry) -> list[Producer]:
    """Compile an entry to `Producer` fingerprints for the suggestion engine.

    Only outputs whose `find.required_columns` is set become column-matchable
    producers; the rest are recognised by filename/path/content at ingest time.
    """
    from depictio.models.components.advanced_viz.producers import Producer

    producers: list[Producer] = []
    for o in entry.outputs:
        if not o.find.required_columns:
            continue
        biotools_id = o.biotools_id or entry.module.biotools_id
        nf_core = o.nf_core_module or entry.module.nf_core_module
        tool_label = f"{entry.module.name} ({o.mode})" if o.mode else entry.module.name
        note_bits: list[str] = []
        if o.reshape.kind != "identity":
            note_bits.append(f"reshape={o.reshape.kind}")
        if o.reshape.recipe:
            note_bits.append(f"recipe={o.reshape.recipe}")
        if nf_core:
            note_bits.append(f"nf-core:{nf_core}")
        if biotools_id:
            note_bits.append(f"biotools:{biotools_id}")
        producers.append(
            Producer(
                name=o.id,
                tool=tool_label,
                description=o.description,
                required_columns=frozenset(o.find.required_columns),
                feeds_viz=tuple(o.feeds_viz),
                role_mapping=o.role_mapping,
                notes="; ".join(note_bits),
            )
        )
    return producers


# ---------------------------------------------------------------------------
# Loading: a flat file is one module; a folder is one module split across files
# ---------------------------------------------------------------------------

_MODULE_FILE = "module.yaml"


def _load_module_dir(directory: Path) -> CatalogEntry:
    """Assemble a CatalogEntry from a `<tool>/` folder.

    `module.yaml` holds the module identity; every other `*.yaml` is one output.
    """
    module_path = directory / _MODULE_FILE
    if not module_path.exists():
        raise ValueError(f"module folder {directory} is missing {_MODULE_FILE}")
    module = CatalogModule.model_validate(yaml.safe_load(module_path.read_text()))
    outputs: list[CatalogOutput] = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name == _MODULE_FILE:
            continue
        outputs.append(CatalogOutput.model_validate(yaml.safe_load(path.read_text())))
    if not outputs:
        raise ValueError(f"module folder {directory} has no output files")
    return CatalogEntry(module=module, outputs=outputs)


def load_entries_from_dir(directory: Path) -> list[CatalogEntry]:
    """Load + validate every module under ``directory`` (flat files + folders)."""
    entries: list[CatalogEntry] = []
    if not directory.exists():
        return entries
    for path in sorted(directory.iterdir()):
        try:
            if path.is_dir():
                entries.append(_load_module_dir(path))
            elif path.suffix == ".yaml":
                raw = yaml.safe_load(path.read_text())
                if raw is not None:
                    entries.append(CatalogEntry.model_validate(raw))
        except Exception as exc:
            raise ValueError(f"invalid catalog entry {path}: {exc}") from exc
    return entries


@lru_cache(maxsize=1)
def load_catalog_entries() -> tuple[CatalogEntry, ...]:
    return tuple(load_entries_from_dir(CATALOG_DIR))


@lru_cache(maxsize=1)
def load_catalog_producers() -> tuple[Producer, ...]:
    producers: list[Producer] = []
    for entry in load_catalog_entries():
        producers.extend(entry_to_producers(entry))
    return tuple(producers)


# ---------------------------------------------------------------------------
# Recognition: match a run directory against the catalog (depictio-cli)
# ---------------------------------------------------------------------------


class CatalogMatch(BaseModel):
    """One recognised file: which module/output it is, and where."""

    module_id: str
    output_id: str
    path: str
    mode: str | None = None
    feeds_viz: list[AdvancedVizKind] = Field(default_factory=list)


def _read_columns(path: Path, read_options: CatalogReadOptions) -> list[str] | None:
    """Read just the header columns of a file (best-effort)."""
    try:
        import polars as pl

        if read_options.format == "parquet":
            return list(pl.read_parquet_schema(path).keys())
        sep = read_options.separator or ("\t" if read_options.format == "tsv" else ",")
        df = pl.read_csv(
            path,
            separator=sep,
            comment_prefix=read_options.comment_prefix,
            has_header=read_options.has_header,
            skip_rows=read_options.skip_rows,
            n_rows=1,
        )
        return df.columns
    except Exception:
        return None


def _output_matches(output: CatalogOutput, path: Path) -> bool:
    """Apply the secondary find conditions (content / columns) to a candidate.

    Filename/path location is done by `_candidate_paths` via pathlib glob (which
    handles ``**`` correctly); here we only verify the content-based conditions.
    """
    f = output.find
    if f.filename and not fnmatch(path.name, f.filename):
        return False
    if f.content_contains:
        try:
            head = path.read_bytes()[:8192].decode("utf-8", "ignore")
        except Exception:
            return False
        if f.content_contains not in head:
            return False
    if f.required_columns:
        cols = _read_columns(path, output.read_options)
        if cols is None or not set(f.required_columns).issubset(cols):
            return False
    return True


def _candidate_paths(output: CatalogOutput, run_dir: Path) -> list[Path]:
    """Locate candidate files for an output using pathlib glob (``**`` aware)."""
    f = output.find
    if f.path_glob:
        return [p for p in run_dir.glob(f.path_glob) if p.is_file()]
    if f.filename:
        return [p for p in run_dir.rglob(f.filename) if p.is_file()]
    # content/column-only find: every file is a candidate
    return [p for p in run_dir.rglob("*") if p.is_file()]


def match_run_dir(
    run_dir: str | Path, entries: tuple[CatalogEntry, ...] | None = None
) -> list[CatalogMatch]:
    """Walk ``run_dir`` and return every file the catalog recognises.

    This is depictio-cli's recognition step — the catalog analogue of MultiQC's
    `find_log_files(search_patterns)`.
    """
    run_dir = Path(run_dir)
    entries = entries if entries is not None else load_catalog_entries()
    matches: list[CatalogMatch] = []
    for entry in entries:
        for output in entry.outputs:
            for path in _candidate_paths(output, run_dir):
                if _output_matches(output, path):
                    matches.append(
                        CatalogMatch(
                            module_id=entry.module.id,
                            output_id=output.id,
                            path=path.relative_to(run_dir).as_posix(),
                            mode=output.mode,
                            feeds_viz=output.feeds_viz,
                        )
                    )
    return matches


# ---------------------------------------------------------------------------
# Offline nf-core meta.yml importer (scaffolding)
# ---------------------------------------------------------------------------

EDAM_FORMAT_READ: dict[str, str] = {
    "format_3752": "csv",
    "format_3475": "tsv",
    "format_3751": "tsv",
    "format_2330": "csv",
    "format_3464": "json",
    "format_3750": "yaml",
}


def _edam_id(term: str) -> str:
    return term.rstrip("/").rsplit("/", 1)[-1]


def _walk_file_outputs(node: object, found: list[dict]) -> None:
    """Recursively collect ``{type: file, pattern, ontologies}`` leaves."""
    if isinstance(node, list):
        for item in node:
            _walk_file_outputs(item, found)
    elif isinstance(node, dict):
        node_dict: dict = node
        for key, value in node_dict.items():
            if isinstance(value, dict):
                value_dict: dict = value
                if value_dict.get("type") == "file":
                    found.append({"name": key, **value_dict})
                    continue
            _walk_file_outputs(value, found)


def meta_yml_to_entry(meta: dict) -> CatalogEntry:
    """Scaffold a draft `CatalogEntry` from a parsed nf-core module ``meta.yml``.

    Infers module identity, bio.tools id, EDAM formats and a `find.path_glob`
    from each output channel's pattern. Leaves `file_schema`, `reshape` and
    `feeds_viz` for the contributor — those can't be derived from metadata.
    """
    tools_raw: object = meta.get("tools") or []
    biotools_id: str | None = None
    homepage: str | None = None
    tool_desc = ""
    if isinstance(tools_raw, list) and tools_raw and isinstance(tools_raw[0], dict):
        values = list(tools_raw[0].values())
        if values and isinstance(values[0], dict):
            first: dict = values[0]
            tool_desc = str(first.get("description") or "").strip()
            hp = first.get("homepage")
            homepage = str(hp) if hp else None
            ident = str(first.get("identifier") or "")
            if ident.startswith("biotools:"):
                biotools_id = ident.split(":", 1)[1]

    name = str(meta.get("name", "unknown"))
    module_id = name.split("_")[0]
    module = CatalogModule(
        id=module_id,
        name=name,
        description=tool_desc,
        homepage=homepage,
        nf_core_module=name.replace("_", "/"),
        biotools_id=biotools_id,
    )

    output_block = meta.get("output")
    outputs: list[CatalogOutput] = []
    for channel, body in (output_block if isinstance(output_block, dict) else {}).items():
        if channel == "versions":
            continue
        files: list[dict] = []
        _walk_file_outputs(body, files)
        if not files:
            continue
        patterns = [str(p) for f in files if (p := f.get("pattern") or f.get("name"))]
        edam_formats: list[str] = []
        read_fmt: Literal["csv", "tsv", "parquet"] = "csv"
        for f in files:
            ontologies = f.get("ontologies") or []
            for onto in ontologies if isinstance(ontologies, list) else []:
                if isinstance(onto, dict) and "edam" in onto:
                    fid = _edam_id(str(onto["edam"]))
                    edam_formats.append(fid)
                    mapped = EDAM_FORMAT_READ.get(fid)
                    if mapped == "tsv":
                        read_fmt = "tsv"
                    elif mapped == "csv":
                        read_fmt = "csv"
        outputs.append(
            CatalogOutput(
                id=f"{module_id}_{channel}",
                description=str(files[0].get("description") or "").strip(),
                mode=str(channel),
                edam_formats=edam_formats,
                find=CatalogFind(filename=patterns[0] if patterns else f"*_{channel}"),
                read_options=CatalogReadOptions(format=read_fmt),
            )
        )

    if not outputs:
        outputs.append(
            CatalogOutput(id=f"{module_id}_output", mode="output", find=CatalogFind(filename="*"))
        )

    return CatalogEntry(module=module, outputs=outputs)
