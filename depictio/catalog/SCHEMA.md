# Catalog schema reference

Machine-readable contract: **`catalog.schema.json`** (regenerate with
`depictio catalog schema -o depictio/catalog/catalog.schema.json`). The
`# yaml-language-server: $schema=` header gives editors live validation +
autocomplete. This page is the human companion.

Legend: **MUST** = required · **CAN** = optional (default shown). Unknown keys
are rejected (`extra="forbid"`).

---

## Layout: one folder per module (fixtures co-located)

Each tool is a folder: `module.yaml` (tool fields) + one YAML per output + each
output's fixture next to it (`<output>.tsv`). A single flat file (tool fields +
`outputs:` list) is also accepted by the loader, but the folder layout is the
convention.

### Legacy: a flat file (one output) or a folder (many)

- **Flat file** = tool fields at the root **+** an `outputs:` list.
- **Folder** = `module.yaml` (tool fields) **+** one `*.yaml` per output.

Both use the same fields; a folder just splits the outputs into files.

## Tool fields (root of a flat file, or `module.yaml`)

| Field | MUST/CAN | Type | Notes |
|---|---|---|---|
| `id` | **MUST** | str | e.g. `ivar`, `qiime2`. |
| `name` | **MUST** | str | Display name. |
| `description` | CAN | str | |
| `homepage` | CAN | str | |
| `nf_core_url` | CAN | str | Full nf-core module URL (per-output for multi-module tools like QIIME 2). |
| `biotools_url` | CAN | str | Full `https://bio.tools/<id>` URL. |
| `edam_topics` | CAN | list[str] | Full EDAM URLs. |
| `outputs` | **MUST** (flat file) | list[Output] | In a folder, these are the sibling files. |

**Keep `module.yaml` lightweight.** For an nf-core-backed tool, declare only
`id`, `name` and `nf_core_url` — the rest of the identity (`homepage`,
`biotools_url`, `edam_topics`, `description`) already lives in the module's
nf-core `meta.yml` and is derived from it, so don't duplicate it. Add an identity
field here **only** to *override* a stale `meta.yml` (e.g. MultiQC `homepage`) or
when the tool has **no** single nf-core module to derive from (QIIME 2 — identity
declared in full, `nf_core_url` set per-output). The `nf_core_url` pointer is what
existence-checking validates; the derived fields are trusted until a future
`sync-identity` reconciles them against `meta.yml`.

## `outputs[]` — Output

| Field | MUST/CAN | Type | Notes |
|---|---|---|---|
| `id` | **MUST** | str | Globally-unique. |
| `find` | **MUST** | Find | How to recognise the raw file. |
| `mode` | CAN | str | Running mode / subcommand. |
| `description` | CAN | str | |
| `recipe` | CAN | str | Reshape that **owns the output columns**. Module-owned (preferred): `<module>/<name>.py`, co-located in this catalog folder, e.g. `qiime2/ancombc.py`. Pipeline-keyed legacy still resolves (`nf-core/<pipeline>/<name>.py`) for pipeline-version-specific reshapes. |
| `columns` | CAN* | dict[str,str] | Bindable columns (polars dtype names). **MUST be set iff there is no recipe and a render binds columns; MUST be absent if `recipe` is set.** |
| `fixture` | CAN | str | A **co-located** sample filename, resolved next to the output's YAML in the module folder (e.g. `alpha_diversity.tsv`) — a small, committed, pipeline-agnostic sample of the bindable shape. Grounds renders in CI (Level-3) and feeds `preview` later. |
| `renders_as` | CAN | list[Render] | Dashboard render target(s) + binding. |
| `nf_core_url` / `biotools_url` / `edam_*` | CAN | str / list | Per-output identity overrides. |

### Find — recognise the raw file (MUST set ≥ 1)

| Field | Type | Notes |
|---|---|---|
| `filename` | str | Glob on the basename, e.g. `*.pangolin.csv`. |
| `path_glob` | str | Glob on the path under the run root, `**`-aware. |

### Render — one render target

| Field | MUST/CAN | Type | Notes |
|---|---|---|---|
| `component` | **MUST** | real `ComponentType` (`advanced_viz`/`figure`/`card`/`table`/`text`/`jbrowse`/`image`/`map`) + `multiqc` | The dashboard component. |
| `kind` | cond. | AdvancedVizKind | **Required iff** `component=advanced_viz`; forbidden otherwise. Role names MUST be valid for the kind. |
| `roles` | cond. | dict[role,column] | `advanced_viz` binding (role → column). |
| `visu_type` | cond. | `box`/`scatter`/`bar`/`histogram`/`line`/`heatmap` | `figure` **UI mode** (plotly express). |
| `dict_kwargs` | CAN | dict[str,str] | `figure` UI mode: plotly-express kwargs (`x`,`y`,`color`,`facet_col`…); column-valued ones are grounded. |
| `code` | cond. | str | `figure` **code mode**: inline Python that sets `fig` (depictio `code_content`). A figure needs `visu_type` **or** `code`. |
| `column` + `aggregation` | cond. | str / `AggregationFunction` | `card`: the metric column + **hero** aggregation. |
| `aggregations` | CAN | list[`AggregationFunction`] | `card`: **secondary** aggregations → a **multi-metric** card (e.g. `[median, min, max, std_dev]`). |
| `secondary_layout` | CAN | `vertical`/`compact`/`box_plot`/`top_n`/`coverage`/`concentration` | `card`: how the secondary strip renders. `box_plot` = a **Tukey** box-and-whisker; `top_n`/`concentration` use `breakdown_col`(+`top_n_count`); `coverage` uses `coverage_max`. |
| `breakdown_col` / `top_n_count` / `coverage_max` | CAN | str / int(1-5) / float | `card`: params for the `top_n`/`concentration`/`coverage` layouts. |
| `filter_expr` | CAN | str | `card`: optional polars pre-filter before aggregation. |
| `section` | CAN | str | e.g. the MultiQC section name. |

Figure/card/roles fields are **component-scoped** (validated): `roles`/`kind`
only for `advanced_viz`, `visu_type`/`dict_kwargs`/`code` only for `figure`,
`column`/`aggregation` only for `card`.

`AdvancedVizKind`: volcano, embedding, manhattan, stacked_taxonomy,
phylogenetic, rarefaction, da_barplot, enrichment, complex_heatmap, upset_plot,
ma, dot_plot, lollipop, qq, sunburst, oncoplot, coverage_track, sankey.

---

## The schema-ownership rule (no duplication)

- **Recipe present** → the recipe (`EXPECTED_SCHEMA`) owns the output columns;
  the YAML must **not** declare `columns`. `roles` are grounded against the
  recipe by `depictio catalog validate`.
- **No recipe** → the raw file is bindable; declare its `columns` in the YAML,
  and `roles` bind to them.
- Non-tabular / role-less renders (`table`, `multiqc_plot`, `figure`) need
  neither a recipe nor `columns`.

Use `depictio catalog columns <recipe>` to see a recipe's output column names
while writing `roles`.

## Two validation tiers

| Tier | Fields | Validation |
|---|---|---|
| **Free** | `mode`, `description` | none (free text label) |
| **Validated** | `component`/`kind`, `nf_core_url`, `biotools_url`, `edam_*`, `recipe`, `columns`, `roles` | against the real authority |

- `component` → depictio's real `ComponentType` (+ `multiqc`).
- `kind` + role names → the viz's `CANONICAL_SCHEMAS`.
- `biotools_url` → format only (the bio.tools registry is too large to vendor).
- `nf_core_url` module + `edam_*` term → **existence** against vendored indices
  in `_index/` (`nf_core_modules.txt`, `edam_terms.txt`), checked offline in CI.
  Regenerate them with `depictio catalog refresh-index` (needs network; run by a
  maintainer). A missing/empty index is skipped, so seeding stays non-breaking.

## What `validate` checks (the CI guarantee)

1. Schema / structure (Pydantic, `extra="forbid"`).
2. `kind` valid for `advanced_viz`; role names valid for the `kind`.
3. Each render's bound columns (`roles`/`dict_kwargs`/`card.column`) are
   **grounded** against the real data shape — the `fixture` (most complete) if
   set, else the recipe's `EXPECTED_SCHEMA`, else the declared `columns`.
4. Every referenced `recipe` resolves; every `fixture` reads.
5. Every `nf_core_url` module + `edam_*` term **exists** in the vendored index.

Green CI = the entry is wired correctly, no manual review needed.
