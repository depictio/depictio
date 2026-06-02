# Catalog schema reference

Machine-readable contract: **`catalog.schema.json`** (regenerate with
`depictio catalog schema -o depictio/catalog/catalog.schema.json`). The
`# yaml-language-server: $schema=` header gives editors live validation +
autocomplete. This page is the human companion.

Legend: **MUST** = required · **CAN** = optional (default shown). Unknown keys
are rejected (`extra="forbid"`).

---

## Layout: a flat file (one output) or a folder (many)

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

## `outputs[]` — Output

| Field | MUST/CAN | Type | Notes |
|---|---|---|---|
| `id` | **MUST** | str | Globally-unique. |
| `find` | **MUST** | Find | How to recognise the raw file. |
| `mode` | CAN | str | Running mode / subcommand. |
| `description` | CAN | str | |
| `recipe` | CAN | str | Pipeline-qualified reshape, e.g. `nf-core/ampliseq/ancombc.py`. **Owns the output columns.** |
| `columns` | CAN* | dict[str,str] | Bindable columns (polars dtype names). **MUST be set iff there is no recipe and a render uses roles; MUST be absent if `recipe` is set.** |
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
| `component` | **MUST** | `advanced_viz` \| `multiqc_plot` \| `table` \| `figure` | The dashboard component. |
| `kind` | cond. | AdvancedVizKind | **Required iff** `component=advanced_viz`; forbidden otherwise. |
| `roles` | CAN | dict[role,column] | Pre-fills the binding. Role names MUST be valid for the viz `kind`; columns MUST exist (in `columns`, or in the recipe's output). |
| `section` | CAN | str | e.g. the MultiQC section name. |

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
3. `roles` columns grounded — against declared `columns`, or against the
   **recipe's real output columns** (the recipe is imported and its
   `EXPECTED_SCHEMA` read).
4. Every referenced `recipe` resolves.
5. Every `nf_core_url` module + `edam_*` term **exists** in the vendored index.

Green CI = the entry is wired correctly, no manual review needed.
