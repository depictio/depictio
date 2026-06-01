"""Declarative bio-catalog: the community-extensible tool→viz mapping layer.

This is the authoring/extension surface that sits *above* the hand-written
`producers.py` registry. Where `producers.py` is a curated Python tuple of
column-name fingerprints, the catalog is a directory of validated YAML
files — one per tool — that the community can extend with a PR that adds a
file (no Python required). Each catalog entry is validated against the
Pydantic models here, then *compiled down* to the same `Producer` primitives
the suggestion engine already understands (see `entry_to_producers`).

Three things the catalog captures that a bare `Producer` cannot:

1.  **Upstream identity.** Every tool carries the metadata nf-core and
    bio.tools already publish: an `nf_core_module`, a `biotools_id`, and
    EDAM ontology terms (topics / operations / formats). That lets a
    catalog entry be *scaffolded automatically* from an nf-core module's
    `meta.yml` (see `meta_yml_to_entry`) and gives the suggestion engine a
    semantic key beyond raw column names.

2.  **Many running modes per tool.** A heavyweight tool such as QIIME 2
    emits dozens of distinct artefacts depending on the subcommand
    (diversity, taxa-barplot, ancombc, …). The catalog models this the way
    nf-core models a module's many output channels: one `CatalogTool` owns
    many `CatalogOutput`s, each tagged with a `mode` and its own file
    pattern, fingerprint, reshape and viz affinity.

3.  **The reshape a raw file needs.** A tool's on-disk output rarely lands
    in the exact long/wide shape a viz wants — it must be melted, pivoted,
    or aggregated first. Each output declares that reshape declaratively
    (`CatalogReshape`) or defers to a full Python `recipe` for arbitrary
    logic. This makes the previously-implicit gap between "file on disk"
    and "DC a viz can bind to" explicit and validatable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.models.components.types import AdvancedVizKind

if TYPE_CHECKING:
    from depictio.models.components.advanced_viz.producers import Producer

# Catalog YAML files live at the package root, alongside (but distinct from)
# the per-pipeline `projects/.../recipes/`. Recipes are Python transforms
# scoped to one pipeline; the catalog is cross-pipeline tool metadata.
CATALOG_DIR = Path(__file__).resolve().parents[3] / "catalog"

ReshapeKind = Literal["identity", "melt", "pivot", "aggregate", "recipe"]


class CatalogReadOptions(BaseModel):
    """How to read a raw tool output file into a DataFrame.

    Captures the read-time quirks that today live as prose in
    `Producer.notes` (e.g. QIIME 2's biom TSV needs `comment_prefix='#'`,
    VCF needs `##` skipping). Polars-flavoured but tool-agnostic.
    """

    format: Literal["csv", "tsv", "parquet"] = "csv"
    separator: str | None = None
    comment_prefix: str | None = None
    skip_rows: int = 0
    has_header: bool = True

    model_config = ConfigDict(extra="forbid")


class CatalogReshape(BaseModel):
    """Declarative reshape from the raw file's shape to a bindable shape.

    Most real tool outputs are not in the long/wide form a viz wants. Rather
    than force a Python recipe for every tool, common reshapes are expressed
    declaratively so a catalog contributor never writes code for the easy
    cases. `kind="recipe"` is the escape hatch for arbitrary logic and points
    at an existing `projects/.../recipes/*.py` transform.
    """

    kind: ReshapeKind = "identity"

    # melt (wide -> long): unpivot value_vars, keeping id_vars
    id_vars: list[str] | None = None
    value_vars: list[str] | None = None
    variable_name: str | None = None
    value_name: str | None = None

    # pivot (long -> wide)
    index: list[str] | None = None
    on: str | None = None
    values: str | None = None

    # aggregate (group + reduce)
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


class CatalogFingerprint(BaseModel):
    """Column-name fingerprint that identifies this output on disk.

    Compiles directly to `Producer.required_columns`. Keep it minimal but
    discriminating (4-6 columns is usually enough). After the declared
    `reshape`, fingerprints describe the *post-reshape* column set the viz
    binds against.
    """

    required_columns: list[str] = Field(default_factory=list)
    optional_columns: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CatalogOutput(BaseModel):
    """One artefact a tool produces, in one running mode.

    The unit that answers "this file → these visualisations (after this
    reshape)". A tool with many modes owns many of these.
    """

    id: str
    description: str = ""
    # Subcommand / running mode that produced this artefact (e.g. QIIME 2
    # "diversity", "ancombc", "taxa barplot"). The key that lets one tool
    # fan out into many outputs without colliding.
    mode: str | None = None

    # Upstream provenance — links back to the nf-core module + EDAM terms
    # the meta.yml already declares for this output channel.
    nf_core_module: str | None = None
    edam_operations: list[str] = Field(default_factory=list)
    edam_formats: list[str] = Field(default_factory=list)

    # Where the file lands (glob, relative to the run root) + how to read it.
    file_patterns: list[str] = Field(default_factory=list)
    read_options: CatalogReadOptions = Field(default_factory=CatalogReadOptions)

    # How to get from the raw file to a bindable shape, and what that shape
    # looks like once reshaped.
    reshape: CatalogReshape = Field(default_factory=CatalogReshape)
    fingerprint: CatalogFingerprint | None = None

    # Viz affinity (post-reshape) + role→column pre-fill, mirroring Producer.
    feeds_viz: list[AdvancedVizKind] = Field(default_factory=list)
    role_mapping: dict[AdvancedVizKind, dict[str, str]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class CatalogTool(BaseModel):
    """A bioinformatics tool, with its bio.tools / EDAM / nf-core identity."""

    id: str
    name: str
    description: str = ""
    homepage: str | None = None
    biotools_id: str | None = None
    edam_topics: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CatalogEntry(BaseModel):
    """One catalog YAML file: a tool and all of its mapped outputs."""

    schema_version: int = 1
    tool: CatalogTool
    outputs: list[CatalogOutput] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_output_ids(self) -> CatalogEntry:
        ids = [o.id for o in self.outputs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate output ids in tool {self.tool.id!r}: {sorted(dupes)}")
        return self


# ---------------------------------------------------------------------------
# Compilation: CatalogEntry -> Producer primitives
# ---------------------------------------------------------------------------


def entry_to_producers(entry: CatalogEntry) -> list[Producer]:
    """Compile a catalog entry to the `Producer` fingerprints the engine uses.

    Outputs without a fingerprint (non-tabular artefacts, or scaffolds a
    contributor hasn't finished) are skipped — they carry provenance/docs
    value but can't drive the column-name suggestion path.
    """
    from depictio.models.components.advanced_viz.producers import Producer

    producers: list[Producer] = []
    for o in entry.outputs:
        if o.fingerprint is None or not o.fingerprint.required_columns:
            continue
        tool_label = f"{entry.tool.name} ({o.mode})" if o.mode else entry.tool.name
        note_bits: list[str] = []
        if o.reshape.kind != "identity":
            note_bits.append(f"reshape={o.reshape.kind}")
        if o.reshape.recipe:
            note_bits.append(f"recipe={o.reshape.recipe}")
        if o.nf_core_module:
            note_bits.append(f"nf-core:{o.nf_core_module}")
        if entry.tool.biotools_id:
            note_bits.append(f"biotools:{entry.tool.biotools_id}")
        producers.append(
            Producer(
                name=o.id,
                tool=tool_label,
                description=o.description,
                required_columns=frozenset(o.fingerprint.required_columns),
                feeds_viz=tuple(o.feeds_viz),
                role_mapping=o.role_mapping,
                notes="; ".join(note_bits),
            )
        )
    return producers


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_entries_from_dir(directory: Path) -> list[CatalogEntry]:
    """Load + validate every ``*.yaml`` catalog entry under ``directory``."""
    entries: list[CatalogEntry] = []
    if not directory.exists():
        return entries
    for path in sorted(directory.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        if raw is None:
            continue
        try:
            entries.append(CatalogEntry.model_validate(raw))
        except Exception as exc:  # surface the offending file, not a bare trace
            raise ValueError(f"invalid catalog entry {path}: {exc}") from exc
    return entries


@lru_cache(maxsize=1)
def load_catalog_entries() -> tuple[CatalogEntry, ...]:
    """All bundled catalog entries (cached)."""
    return tuple(load_entries_from_dir(CATALOG_DIR))


@lru_cache(maxsize=1)
def load_catalog_producers() -> tuple[Producer, ...]:
    """Compiled `Producer`s from every bundled catalog entry (cached)."""
    producers: list[Producer] = []
    for entry in load_catalog_entries():
        producers.extend(entry_to_producers(entry))
    return tuple(producers)


# ---------------------------------------------------------------------------
# Offline nf-core meta.yml importer (scaffolding)
# ---------------------------------------------------------------------------

# EDAM data-format term -> how depictio would read it. Only the table-ish
# formats matter for fingerprinting; everything else is recorded for docs.
EDAM_FORMAT_READ: dict[str, str] = {
    "format_3752": "csv",  # CSV
    "format_3475": "tsv",  # TSV
    "format_3751": "tsv",  # tab-separated values (generic)
    "format_2330": "csv",  # textual
    "format_3464": "json",  # JSON
    "format_3750": "yaml",  # YAML
}


def _edam_id(term: str) -> str:
    """Normalise an EDAM ontology URL/term to its bare id (``format_3752``)."""
    return term.rstrip("/").rsplit("/", 1)[-1]


def _walk_file_outputs(node: object, found: list[dict]) -> None:
    """Recursively collect ``{type: file, pattern, ontologies}`` leaves.

    nf-core ``meta.yml`` ``output:`` blocks nest channels as lists-of-lists
    interleaving a ``meta`` map with the actual file descriptors, so we walk
    the structure rather than assume a fixed depth.
    """
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
    """Scaffold a `CatalogEntry` from a parsed nf-core module ``meta.yml``.

    Produces a *draft* entry: tool identity + EDAM formats + file patterns are
    inferred, but `fingerprint` (column names) and `feeds_viz` are left for the
    contributor to complete — they can't be derived from the module metadata.
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
    tool_id = name.split("_")[0]
    tool = CatalogTool(
        id=tool_id,
        name=name,
        description=tool_desc,
        homepage=homepage,
        biotools_id=biotools_id,
    )

    output_block = meta.get("output")
    outputs: list[CatalogOutput] = []
    for channel, body in (output_block if isinstance(output_block, dict) else {}).items():
        if channel == "versions":
            continue  # versions.yml is housekeeping, never a viz source
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
                id=f"{tool_id}_{channel}",
                description=str(files[0].get("description") or "").strip(),
                mode=str(channel),
                nf_core_module=name,
                edam_formats=edam_formats,
                file_patterns=patterns,
                read_options=CatalogReadOptions(format=read_fmt),
            )
        )

    if not outputs:
        # Guarantee a non-empty draft so the scaffold validates and the
        # contributor sees where to fill in details.
        outputs.append(CatalogOutput(id=f"{tool_id}_output", mode="output"))

    return CatalogEntry(tool=tool, outputs=outputs)
