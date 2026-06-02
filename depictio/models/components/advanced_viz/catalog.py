"""Declarative bio-catalog: the tool→viz **linking table**.

For each tool output, one catalog entry links:

  - `find`        — how to recognise the raw nf-core file (used at scan time).
  - `recipe`      — optional `.py` that reshapes it. **The recipe owns the
                    output columns** (its `EXPECTED_SCHEMA`); the catalog does
                    not repeat them.
  - `columns`     — the bindable columns, declared **only when there is no
                    recipe** (raw == bindable). Omitted when a recipe is present.
  - `renders_as`  — which dashboard component(s) render it (advanced viz,
                    MultiQC plot, table…) + the role→column binding.
  - identity      — bio.tools / nf-core / EDAM URLs (robust anchors).

Anchored on bio.tools & nf-core for robustness, and consumed at **scan time**
to build or assist dashboards. This catalog is *not* a second column→viz
suggestion engine (`producers.py` already does that on canonical shapes); it is
the file → recipe → component map.

The model layer stays offline + import-cheap: it never imports recipe `.py`
files. Cross-checking `renders_as` roles against a recipe's real output columns
is done by `depictio catalog validate` (a trusted CLI/CI context), not here.
"""

from __future__ import annotations

from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.models.components.types import AdvancedVizKind, ComponentType

CATALOG_DIR = Path(__file__).resolve().parents[3] / "catalog"

# Render targets = depictio's real component registry (`ComponentType`:
# advanced_viz, figure, table, card, text, jbrowse, image, map) plus the
# dash-module `multiqc` component. Validated against the actual components, so a
# catalog entry can only target a component that exists.
ComponentKind = ComponentType | Literal["multiqc"]


def _check_identity_urls(
    nf_core_url: str | None,
    biotools_url: str | None,
    edam: dict[str, list[str]],
) -> None:
    """Validate identity references point at the right authority (offline check).

    Format-level only: guarantees well-formed bio.tools / nf-core / EDAM refs.
    Existence (the term/module is real) is a CI step against a vendored index.
    """
    if biotools_url and not biotools_url.startswith("https://bio.tools/"):
        raise ValueError(f"biotools_url must be a https://bio.tools/ URL, got {biotools_url!r}")
    if nf_core_url and "github.com/nf-core/modules" not in nf_core_url:
        raise ValueError(
            f"nf_core_url must point at github.com/nf-core/modules/..., got {nf_core_url!r}"
        )
    for category, urls in edam.items():  # category -> expected EDAM prefix
        for url in urls:
            if not url.startswith(f"http://edamontology.org/{category}_"):
                raise ValueError(
                    f"edam_{category} entries must be http://edamontology.org/{category}_NNNN URLs, "
                    f"got {url!r}"
                )


# Accepted polars dtype names for `columns` (string form, as polars prints them).
ALLOWED_DTYPES: frozenset[str] = frozenset(
    {
        "String",
        "Int64",
        "Int32",
        "UInt32",
        "UInt64",
        "Float64",
        "Float32",
        "Boolean",
        "Date",
        "Datetime",
        "Time",
        "Categorical",
        "List",
    }
)


# ---------------------------------------------------------------------------
# Recognition: how to find the raw file in a scanned run (MultiQC-style)
# ---------------------------------------------------------------------------


class CatalogFind(BaseModel):
    """How to recognise the raw output file among a scanned run's files."""

    filename: str | None = None  # glob on the basename, e.g. "*.pangolin.csv"
    path_glob: str | None = None  # glob on the path under the run root (** aware)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one(self) -> CatalogFind:
        if not (self.filename or self.path_glob):
            raise ValueError("find must declare at least one of: filename, path_glob")
        return self


class Render(BaseModel):
    """One render target for an output: a component + its role→column binding."""

    component: ComponentKind
    kind: AdvancedVizKind | None = None  # required iff component == advanced_viz
    roles: dict[str, str] = Field(default_factory=dict)  # viz role -> column name
    section: str | None = None  # e.g. the MultiQC module/section name

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check_component(self) -> Render:
        if self.component == "advanced_viz":
            if not self.kind:
                raise ValueError("renders_as advanced_viz requires a 'kind'")
            from depictio.models.components.advanced_viz.schemas import CANONICAL_SCHEMAS

            valid_roles = set(CANONICAL_SCHEMAS.get(self.kind, {}))
            unknown = set(self.roles) - valid_roles
            if unknown:
                raise ValueError(
                    f"renders_as {self.kind}: unknown role(s) {sorted(unknown)}; "
                    f"valid roles: {sorted(valid_roles)}"
                )
        elif self.kind is not None:
            raise ValueError(
                f"'kind' is only valid for component=advanced_viz, not {self.component}"
            )
        return self


class CatalogOutput(BaseModel):
    """One file a tool emits → one or more dashboard renders."""

    id: str
    mode: str | None = None
    description: str = ""

    find: CatalogFind
    recipe: str | None = None  # pipeline-qualified, e.g. nf-core/ampliseq/ancombc.py

    # Bindable columns. REQUIRED when there is no recipe (raw == bindable);
    # FORBIDDEN when a recipe is present (the recipe owns the output columns).
    columns: dict[str, str] = Field(default_factory=dict)

    renders_as: list[Render] = Field(default_factory=list)

    # Per-output identity overrides (e.g. QIIME 2 subcommands = distinct modules).
    nf_core_url: str | None = None
    biotools_url: str | None = None
    edam_operations: list[str] = Field(default_factory=list)
    edam_formats: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _columns_ownership(self) -> CatalogOutput:
        # No duplication: a recipe owns the output columns.
        if self.recipe and self.columns:
            raise ValueError(
                f"output {self.id!r}: a recipe is set, so the recipe owns the output "
                f"columns — remove 'columns' (it must not be duplicated in the YAML)"
            )
        bad = {c: t for c, t in self.columns.items() if t not in ALLOWED_DTYPES}
        if bad:
            raise ValueError(
                f"output {self.id!r}: unknown dtype(s) {bad}; allowed: {sorted(ALLOWED_DTYPES)}"
            )
        if self.columns:
            # Roles must bind to declared columns.
            for r in self.renders_as:
                missing = set(r.roles.values()) - set(self.columns)
                if missing:
                    raise ValueError(
                        f"output {self.id!r} render {r.kind or r.component}: "
                        f"role(s) bind to unknown column(s) {sorted(missing)}; "
                        f"declared columns: {sorted(self.columns)}"
                    )
        elif not self.recipe:
            # No columns and no recipe: roles can't be grounded. Allowed only
            # for non-tabular / role-less renders (multiqc_plot, figure, …).
            for r in self.renders_as:
                if r.roles:
                    raise ValueError(
                        f"output {self.id!r} render {r.kind or r.component}: has roles "
                        f"but no recipe and no 'columns' to bind them — declare 'columns' "
                        f"or add a 'recipe'"
                    )
        # recipe + no columns: roles are checked against the recipe's output by
        # `depictio catalog validate`.
        return self

    @model_validator(mode="after")
    def _identity_urls(self) -> CatalogOutput:
        _check_identity_urls(
            self.nf_core_url,
            self.biotools_url,
            {"operation": self.edam_operations, "format": self.edam_formats},
        )
        return self


class CatalogTool(BaseModel):
    """A tool. Identity is stored as directly-clickable URLs."""

    id: str
    name: str
    description: str = ""
    homepage: str | None = None
    nf_core_url: str | None = None
    biotools_url: str | None = None
    edam_topics: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _identity_urls(self) -> CatalogTool:
        _check_identity_urls(self.nf_core_url, self.biotools_url, {"topic": self.edam_topics})
        return self


class CatalogEntry(CatalogTool):
    """A tool + all its outputs (one flat file, or a folder of files)."""

    schema_version: int = 1
    outputs: list[CatalogOutput] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_output_ids(self) -> CatalogEntry:
        ids = [o.id for o in self.outputs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate output ids in tool {self.id!r}: {sorted(dupes)}")
        return self


# ---------------------------------------------------------------------------
# Loading: a flat file is one tool; a folder is one tool split across files
# ---------------------------------------------------------------------------

_MODULE_FILE = "module.yaml"


def _load_tool_dir(directory: Path) -> CatalogEntry:
    """Assemble an entry from a `<tool>/` folder: module.yaml + one file/output."""
    module_path = directory / _MODULE_FILE
    if not module_path.exists():
        raise ValueError(f"tool folder {directory} is missing {_MODULE_FILE}")
    tool = CatalogTool.model_validate(yaml.safe_load(module_path.read_text()))
    outputs: list[CatalogOutput] = []
    for path in sorted(directory.glob("*.yaml")):
        if path.name == _MODULE_FILE:
            continue
        outputs.append(CatalogOutput.model_validate(yaml.safe_load(path.read_text())))
    if not outputs:
        raise ValueError(f"tool folder {directory} has no output files")
    return CatalogEntry(**tool.model_dump(), outputs=outputs)


def load_entries_from_dir(directory: Path) -> list[CatalogEntry]:
    """Load + validate every tool under ``directory`` (flat files + folders)."""
    entries: list[CatalogEntry] = []
    if not directory.exists():
        return entries
    for path in sorted(directory.iterdir()):
        try:
            if path.is_dir():
                entries.append(_load_tool_dir(path))
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


# ---------------------------------------------------------------------------
# Recipe output columns — used by `catalog validate` to ground recipe outputs.
# Imports a recipe module, so it lives here but is only called from the CLI/CI.
# ---------------------------------------------------------------------------


def recipe_output_columns(recipe_ref: str) -> list[str]:
    """Return the output column names a recipe produces (its EXPECTED_SCHEMA)."""
    from depictio.recipes import load_recipe

    module = load_recipe(recipe_ref)
    return list(module.EXPECTED_SCHEMA.keys())


# ---------------------------------------------------------------------------
# Recognition: match a scanned run directory against the catalog
# ---------------------------------------------------------------------------


class CatalogMatch(BaseModel):
    """One recognised file: which tool/output it is, and where."""

    tool_id: str
    output_id: str
    path: str
    mode: str | None = None


def match_run_dir(
    run_dir: str | Path, entries: tuple[CatalogEntry, ...] | None = None
) -> list[CatalogMatch]:
    """Walk ``run_dir`` and return every file the catalog recognises.

    The catalog analogue of MultiQC's file search. NOTE: exposed via `depictio
    catalog match` and intended as the scan-time recogniser; it is not yet wired
    into the live ingestion path.
    """
    run_dir = Path(run_dir)
    entries = entries if entries is not None else load_catalog_entries()
    matches: list[CatalogMatch] = []
    for entry in entries:
        for output in entry.outputs:
            f = output.find
            if f.path_glob:
                candidates = [p for p in run_dir.glob(f.path_glob) if p.is_file()]
            elif f.filename:
                candidates = [p for p in run_dir.rglob(f.filename) if p.is_file()]
            else:
                candidates = []
            for path in candidates:
                if f.filename and not fnmatch(path.name, f.filename):
                    continue
                matches.append(
                    CatalogMatch(
                        tool_id=entry.id,
                        output_id=output.id,
                        path=path.relative_to(run_dir).as_posix(),
                        mode=output.mode,
                    )
                )
    return matches
