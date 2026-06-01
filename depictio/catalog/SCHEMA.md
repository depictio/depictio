# Catalog schema reference

The authoritative, machine-readable contract is **`catalog.schema.json`** (JSON
Schema; regenerate with `depictio catalog schema -o depictio/catalog/catalog.schema.json`).
Editors that honour the `# yaml-language-server: $schema=` header get live
validation + autocomplete. This page is the human-readable companion.

Legend: **MUST** = required · **CAN** = optional (default shown). Unknown keys
are rejected (`extra="forbid"`).

---

## Layout: a file (single output) or a folder (many outputs)

```
depictio/catalog/
  pangolin.yaml          # single-output tool → one flat file (module + outputs)
  qiime2/                # multi-output tool → a folder
    module.yaml          #   the `module` identity block
    taxa_barplot.yaml    #   one output per file (the CatalogOutput fields)
    ancombc.yaml
    ...
```

- **Flat file** = a whole `CatalogEntry`: a `module:` block + an `outputs:` list.
- **Folder** = the same `CatalogEntry` split across files: `module.yaml` holds
  the `module` fields directly; every other `*.yaml` is one output (the
  `Output` fields directly, no wrapper).

---

## `module`

The tool, with resolvable identity (`biotools_id` → `https://bio.tools/<id>`,
`nf_core_module` → the nf-core/modules tree, `edam_topics` → edamontology.org).

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **MUST** | str | — | e.g. `qiime2`, `pangolin`. |
| `name` | **MUST** | str | — | Display name. |
| `description` | CAN | str | `""` | |
| `homepage` | CAN | str \| null | `null` | |
| `nf_core_module` | CAN | str \| null | `null` | Default nf-core module for outputs, e.g. `mosdepth`. |
| `biotools_id` | CAN | str \| null | `null` | bio.tools id. |
| `edam_topics` | CAN | list[str] | `[]` | e.g. `topic_3174` (Metagenomics). |

## `outputs[]` — `Output`

One file the tool emits (one running mode) → one visualisation mapping.

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **MUST** | str | — | Globally-unique producer id. |
| `find` | **MUST** | `Find` | — | How depictio-cli recognises the file. |
| `description` | CAN | str | `""` | |
| `mode` | CAN | str \| null | `null` | Running mode / subcommand (`taxa-barplot`, `composition/ancombc`, …). |
| `nf_core_module` | CAN | str \| null | `null` | Per-output override (QIIME 2 subcommands are separate modules). |
| `biotools_id` | CAN | str \| null | `null` | Per-output override. |
| `edam_operations` | CAN | list[str] | `[]` | e.g. `operation_3223` (differential abundance). |
| `edam_formats` | CAN | list[str] | `[]` | e.g. `format_3475` (TSV). |
| `pipelines` | CAN | list[str] | `[]` | Which pipeline(s) emit this, e.g. `nf-core/viralrecon`. |
| `read_options` | CAN | `ReadOptions` | csv defaults | How to parse the file. |
| `file_schema` | CAN | dict[str,str] | `{}` | **The columns + dtypes the tool writes** (raw, pre-reshape). Documents the file as-emitted. |
| `reshape` | CAN | `Reshape` | `{kind: identity}` | Raw file → viz-ready shape. |
| `feeds_viz` | CAN | list[`AdvancedVizKind`] | `[]` | Viz kinds this output maps to (post-reshape). |
| `role_mapping` | CAN | dict[viz → dict[role → column]] | `{}` | Pre-fills the viz binding. |

### `find` — recognition (MUST set ≥ 1 condition)

A file matches when **all** declared conditions hold (like MultiQC's
`search_patterns`: `fn` + `contents`).

| Field | MUST/CAN | Type | Notes |
|---|---|---|---|
| `filename` | cond. | str \| null | Glob on the basename, e.g. `*.pangolin.csv`. |
| `path_glob` | cond. | str \| null | Glob on the path under the run root, `**`-aware, e.g. `**/mosdepth/genome/*.tsv`. |
| `content_contains` | cond. | str \| null | Substring in the file head (text files), e.g. `##FastQC`. |
| `required_columns` | cond. | list[str] | All must be present (tabular). Also becomes the column fingerprint for the suggestion engine. |

> ≥ 1 of the four MUST be set. `filename`/`path_glob` locate the file;
> `content_contains`/`required_columns` confirm it.

### `read_options` — `ReadOptions`

| Field | MUST/CAN | Type | Default |
|---|---|---|---|
| `format` | CAN | `csv` \| `tsv` \| `parquet` | `csv` |
| `separator` | CAN | str \| null | `null` |
| `comment_prefix` | CAN | str \| null | `null` |
| `skip_rows` | CAN | int | `0` |
| `has_header` | CAN | bool | `true` |

### `reshape` — `Reshape`

`kind` selects the reshape; its params are validated (a `melt` without
`id_vars` is rejected).

| Field | Used by | Notes |
|---|---|---|
| `kind` | — | `identity` (default) \| `melt` \| `pivot` \| `aggregate` \| `recipe`. |
| `id_vars` | `melt` | **Required for melt.** |
| `value_vars`, `variable_name`, `value_name` | `melt` | Optional melt params. |
| `on`, `values` | `pivot` | **Required for pivot.** `index` optional. |
| `group_by`, `agg` | `aggregate` | **Required for aggregate.** `agg` ∈ sum/mean/median/max/min/count. |
| `recipe` | `recipe` | **Required for recipe.** e.g. `nf-core/ampliseq/ancombc.py`. |

### `AdvancedVizKind` (allowed `feeds_viz` / `role_mapping` keys)

`volcano`, `embedding`, `manhattan`, `stacked_taxonomy`, `phylogenetic`,
`rarefaction`, `da_barplot`, `enrichment`, `complex_heatmap`, `upset_plot`,
`ma`, `dot_plot`, `lollipop`, `qq`, `sunburst`, `oncoplot`, `coverage_track`,
`sankey`.

---

## How depictio-cli recognises files

`depictio catalog match <run_dir>` walks the directory and reports every file a
module output's `find` rules recognise — the catalog analogue of MultiQC's
`find_log_files()`. Each hit carries `module / output → feeds_viz`, so the same
data drives both ingest-time recognition and the editor's viz suggestions.
