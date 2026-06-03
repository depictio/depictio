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

from depictio.models.components.types import (
    AdvancedVizKind,
    AggregationFunction,
    ChartType,
    ComponentType,
)

CATALOG_DIR = Path(__file__).resolve().parents[3] / "catalog"
# Module-keyed, catalog-local sample data (one file per output, named by id).
# Pipeline-agnostic and committed with the catalog → usable for both validation
# (Level-3 grounding) and `catalog preview`.
FIXTURES_DIR = CATALOG_DIR / "_fixtures"

# plotly-express kwargs whose VALUES are column names (grounded against data);
# other dict_kwargs (title, points, log_x…) are passed through untouched.
_FIGURE_COLUMN_KWARGS: frozenset[str] = frozenset(
    {"x", "y", "color", "facet_col", "facet_row", "size", "symbol", "names", "values", "hover_name"}
)

# Render targets = depictio's real component registry (`ComponentType`:
# advanced_viz, figure, table, card, text, jbrowse, image, map) plus the
# dash-module `multiqc` component. Validated against the actual components, so a
# catalog entry can only target a component that exists.
ComponentKind = ComponentType | Literal["multiqc"]

# How a multi-metric card renders its secondary strip (mirrors CardLiteComponent).
CardLayout = Literal["vertical", "compact", "box_plot", "top_n", "coverage", "concentration"]


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
    """One render target for an output: a dashboard component + its binding.

    - `advanced_viz` → `kind` + `roles` (role → column).
    - `figure` → either UI mode (`visu_type` + `dict_kwargs`, plotly-express) or
      code mode (`code`: an inline snippet that sets `fig`, depictio's
      figure `code_content`).
    - `card` → `column` + `aggregation` (a metric/KPI).
    - `multiqc`/`table`/… → no extra binding.
    """

    component: ComponentKind
    # advanced_viz
    kind: AdvancedVizKind | None = None
    roles: dict[str, str] = Field(default_factory=dict)  # viz role -> column
    # figure
    visu_type: ChartType | None = None  # UI mode: box/scatter/bar/histogram…
    dict_kwargs: dict[str, str] = Field(default_factory=dict)  # plotly-express kwargs
    code: str | None = None  # code mode: inline Python that sets `fig`
    # card (single- or multi-metric)
    column: str | None = None
    aggregation: AggregationFunction | None = None  # hero metric
    aggregations: list[AggregationFunction] = Field(
        default_factory=list
    )  # secondary (multi-metric)
    secondary_layout: CardLayout | None = None  # vertical/compact/box_plot(Tukey)/top_n/coverage/…
    breakdown_col: str | None = None  # group-by column for top_n / concentration
    top_n_count: int | None = Field(default=None, ge=1, le=5)
    coverage_max: float | None = None  # denominator for secondary_layout=coverage
    filter_expr: str | None = None  # optional polars pre-filter
    # multiqc
    section: str | None = None

    model_config = ConfigDict(extra="forbid")

    def bound_columns(self) -> set[str]:
        """Columns this render binds to (for grounding against the data shape)."""
        cols = set(self.roles.values())
        cols |= {v for k, v in self.dict_kwargs.items() if k in _FIGURE_COLUMN_KWARGS}
        if self.column:
            cols.add(self.column)
        if self.breakdown_col:
            cols.add(self.breakdown_col)
        return cols  # NB: `code`-mode figures are free-form → not grounded

    @model_validator(mode="after")
    def _check_component(self) -> Render:
        c = self.component
        # advanced_viz: kind + roles
        if c == "advanced_viz":
            if not self.kind:
                raise ValueError("renders_as advanced_viz requires a 'kind'")
            from depictio.models.components.advanced_viz.schemas import CANONICAL_SCHEMAS

            unknown = set(self.roles) - set(CANONICAL_SCHEMAS.get(self.kind, {}))
            if unknown:
                raise ValueError(
                    f"renders_as {self.kind}: unknown role(s) {sorted(unknown)}; "
                    f"valid roles: {sorted(CANONICAL_SCHEMAS.get(self.kind, {}))}"
                )
        else:
            if self.kind is not None:
                raise ValueError(f"'kind' is only valid for component=advanced_viz, not {c}")
            if self.roles:
                raise ValueError(f"'roles' is only valid for component=advanced_viz, not {c}")
        # figure: visu_type (UI) or code (code mode)
        if c == "figure":
            if not (self.visu_type or self.code):
                raise ValueError(
                    "renders_as figure requires 'visu_type' (UI) or 'code' (code mode)"
                )
        elif self.visu_type or self.dict_kwargs or self.code:
            raise ValueError(f"figure fields are only valid for component=figure, not {c}")
        # card: column + hero aggregation (+ optional secondary aggregations / filter)
        if c == "card":
            if not (self.column and self.aggregation):
                raise ValueError("renders_as card requires 'column' and 'aggregation'")
            if self.secondary_layout in ("top_n", "concentration") and not self.breakdown_col:
                raise ValueError(
                    f"secondary_layout={self.secondary_layout!r} requires 'breakdown_col'"
                )
            if self.secondary_layout == "coverage" and self.coverage_max is None:
                raise ValueError("secondary_layout='coverage' requires 'coverage_max'")
        elif any(
            (
                self.column,
                self.aggregation,
                self.aggregations,
                self.secondary_layout,
                self.breakdown_col,
                self.top_n_count,
                self.coverage_max,
                self.filter_expr,
            )
        ):
            raise ValueError(f"card fields are only valid for component=card, not {c}")
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

    # A bundled sample of this output's bindable shape (path under
    # depictio/projects/, e.g. nf-core/ampliseq/2.16.0/alpha_diversity_multi_canonical.tsv).
    # Used by `catalog validate` (ground renders against real columns) and, later,
    # by `catalog preview` (render the component on real data).
    fixture: str | None = None

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
            # Renders must bind to declared columns (unless a fixture grounds them).
            for r in self.renders_as:
                missing = r.bound_columns() - set(self.columns)
                if missing and not self.fixture:
                    raise ValueError(
                        f"output {self.id!r} render {r.kind or r.component}: "
                        f"binds unknown column(s) {sorted(missing)}; "
                        f"declared columns: {sorted(self.columns)}"
                    )
        elif not self.recipe and not self.fixture:
            # No columns, no recipe, no fixture: bindings can't be grounded.
            # Allowed only for non-tabular / binding-less renders (multiqc, figure code…).
            for r in self.renders_as:
                if r.bound_columns():
                    raise ValueError(
                        f"output {self.id!r} render {r.kind or r.component}: binds "
                        f"{sorted(r.bound_columns())} but has no 'columns', 'recipe' or "
                        f"'fixture' to ground them"
                    )
        # recipe/fixture grounding (against the recipe's real output or the
        # fixture's real columns) is done by `depictio catalog validate`.
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
        if path.name.startswith((".", "_")):
            continue  # skip non-tool dirs/files like _index/
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
# Existence checks against vendored indices (offline) — used by `validate`.
# nf-core modules + EDAM terms are validated for existence; bio.tools stays
# format-only (its registry is too large to vendor).
# ---------------------------------------------------------------------------

INDEX_DIR = CATALOG_DIR / "_index"


def load_index(name: str) -> set[str]:
    """Load a vendored index (`_index/<name>.txt`); `#`/blank lines ignored."""
    path = INDEX_DIR / f"{name}.txt"
    if not path.exists():
        return set()
    return {
        s for line in path.read_text().splitlines() if (s := line.strip()) and not s.startswith("#")
    }


def _nf_core_module(url: str | None) -> str | None:
    if url and "/modules/nf-core/" in url:
        return url.split("/modules/nf-core/", 1)[1].rstrip("/")
    return None


def check_existence(entries: tuple[CatalogEntry, ...] | list[CatalogEntry]) -> list[str]:
    """Check nf-core modules + EDAM terms exist in the vendored indices.

    Returns a list of problems (empty = all good). A missing/empty index is
    skipped (graceful), so seeding-then-refreshing stays non-breaking.
    """
    nf_index = load_index("nf_core_modules")
    edam_index = load_index("edam_terms")
    problems: list[str] = []

    def _check_nf(url: str | None, ctx: str) -> None:
        module = _nf_core_module(url)
        if module and nf_index and module not in nf_index:
            problems.append(f"{ctx}: nf-core module {module!r} not in vendored index")

    def _check_edam(urls: list[str], ctx: str) -> None:
        for url in urls:
            term = url.rstrip("/").rsplit("/", 1)[-1]
            if edam_index and term not in edam_index:
                problems.append(f"{ctx}: EDAM term {term!r} not in vendored index")

    for entry in entries:
        _check_nf(entry.nf_core_url, entry.id)
        _check_edam(entry.edam_topics, entry.id)
        for out in entry.outputs:
            _check_nf(out.nf_core_url, out.id)
            _check_edam(out.edam_operations + out.edam_formats, out.id)
    return problems


# ---------------------------------------------------------------------------
# Recipe output columns — used by `catalog validate` to ground recipe outputs.
# Imports a recipe module, so it lives here but is only called from the CLI/CI.
# ---------------------------------------------------------------------------


def fixture_path(fixture_ref: str) -> Path:
    """Resolve a module-keyed fixture name to its path under `_fixtures/`."""
    return FIXTURES_DIR / fixture_ref


def fixture_columns(fixture_ref: str) -> list[str]:
    """Read the column header of a module-keyed fixture (csv/tsv/parquet)."""
    import polars as pl

    path = fixture_path(fixture_ref)
    if path.suffix == ".parquet":
        return list(pl.read_parquet_schema(path).keys())
    sep = "\t" if path.suffix == ".tsv" else ","
    return pl.read_csv(path, separator=sep, n_rows=0).columns


def recipe_output_columns(recipe_ref: str) -> list[str]:
    """Return the output column names a recipe produces (its EXPECTED_SCHEMA)."""
    from depictio.recipes import load_recipe

    module = load_recipe(recipe_ref)
    return list(module.EXPECTED_SCHEMA.keys())


# ---------------------------------------------------------------------------
# Recognition: match a scanned run directory against the catalog
# ---------------------------------------------------------------------------


class CatalogMatch(BaseModel):
    """One recognised file: which tool/output it is, where, and what it renders.

    `renders` lists the dashboard components the matched output maps to, as
    `"component"` or `"component:kind"` strings — the building blocks a guided
    dashboard would assemble for this module.
    """

    tool_id: str
    output_id: str
    path: str
    mode: str | None = None
    renders: list[str] = Field(default_factory=list)


def read_software_versions(run_dir: str | Path) -> set[str]:
    """Collect the tool names from a run's nf-core ``software_versions.yml``.

    nf-core writes ``{PROCESS: {tool: version}}``; we return the set of tool
    names (lowercased) actually executed — the module-level provenance used to
    scope/confirm recognition. Empty set if no such file is found.
    """
    run_dir = Path(run_dir)
    tools: set[str] = set()
    for path in run_dir.rglob("software_versions.yml"):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except Exception:
            continue
        for versions in data.values():
            if isinstance(versions, dict):
                tools.update(str(tool).lower() for tool in versions)
    return tools


def match_run_dir(
    run_dir: str | Path,
    entries: tuple[CatalogEntry, ...] | None = None,
    confirm_with_versions: bool = False,
) -> list[CatalogMatch]:
    """Walk ``run_dir`` and return every module output the catalog recognises.

    The catalog analogue of MultiQC's file search, at **module granularity**
    (pipeline-agnostic). NOTE: exposed via `depictio catalog match`/`compose`
    and intended as the scan-time recogniser; not yet wired into live ingestion.

    With ``confirm_with_versions=True`` and a ``software_versions.yml`` present,
    matches are restricted to tools the run actually executed — a second signal
    on top of filename matching (no file present → no restriction, non-breaking).
    """
    run_dir = Path(run_dir)
    entries = entries if entries is not None else load_catalog_entries()
    executed = read_software_versions(run_dir) if confirm_with_versions else set()
    matches: list[CatalogMatch] = []
    for entry in entries:
        if executed and entry.id.lower() not in executed:
            continue  # tool not in the run's software_versions.yml
        for output in entry.outputs:
            f = output.find
            if f.path_glob:
                candidates = [p for p in run_dir.glob(f.path_glob) if p.is_file()]
            elif f.filename:
                candidates = [p for p in run_dir.rglob(f.filename) if p.is_file()]
            else:
                candidates = []
            renders: list[str] = [
                f"{r.component}:{r.kind}" if r.kind else str(r.component) for r in output.renders_as
            ]
            for path in candidates:
                if f.filename and not fnmatch(path.name, f.filename):
                    continue
                matches.append(
                    CatalogMatch(
                        tool_id=entry.id,
                        output_id=output.id,
                        path=path.relative_to(run_dir).as_posix(),
                        mode=output.mode,
                        renders=renders,
                    )
                )
    return matches


def compose_run_dir(
    run_dir: str | Path,
    entries: tuple[CatalogEntry, ...] | None = None,
    confirm_with_versions: bool = False,
) -> dict[str, list[CatalogMatch]]:
    """Group recognised module outputs by tool — a guided-dashboard *proposal*.

    This is the pipeline-agnostic composition step: scan a run (an nf-core
    pipeline OR a custom workflow reusing nf-core modules), recognise the module
    outputs present, and group them so a starter dashboard can be assembled from
    each module's `renders`. A preview only — it does not yet build a dashboard.
    """
    by_tool: dict[str, list[CatalogMatch]] = {}
    for match in match_run_dir(run_dir, entries, confirm_with_versions=confirm_with_versions):
        by_tool.setdefault(match.tool_id, []).append(match)
    return by_tool
