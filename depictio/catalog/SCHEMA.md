# Catalog YAML schema reference

The authoritative, machine-readable contract is **`catalog.schema.json`** (JSON
Schema, regenerate with `depictio catalog schema -o depictio/catalog/catalog.schema.json`).
Editors that honour `# yaml-language-server: $schema=./catalog.schema.json`
(the first line of each catalog file) get live validation + autocomplete.

This page is the human-readable companion: every field, whether it's **required
(MUST)** or **optional (CAN)**, its type, allowed values, and default.

Legend: **MUST** = required · **CAN** = optional (default shown). Unknown keys
are rejected (`extra="forbid"`) — a typo fails validation rather than being
silently ignored.

---

## Top level — `CatalogEntry` (one file)

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `schema_version` | CAN | int | `1` | Bump only on a breaking schema change. |
| `tool` | **MUST** | `Tool` | — | The producing entity (a tool or a pipeline). |
| `outputs` | **MUST** | list[`Output`] | — | ≥ 1 entry; each `id` must be unique within the file. |

## `tool`

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **MUST** | str | — | Stable id. Tool: `qiime2`. Pipeline: `nf-core/viralrecon`. |
| `name` | **MUST** | str | — | Display name. |
| `kind` | CAN | `"tool"` \| `"pipeline"` | `"tool"` | `pipeline` = a composition; identity then lives per-output. |
| `description` | CAN | str | `""` | One/two lines. |
| `homepage` | CAN | str \| null | `null` | |
| `biotools_id` | CAN | str \| null | `null` | bio.tools id (tool-scoped files). e.g. `metaphlan`. |
| `edam_topics` | CAN | list[str] | `[]` | EDAM topic ids, e.g. `topic_3174` (Metagenomics). |

## `outputs[]` — `Output`

The unit that answers *"this artefact → these visualisations (after this reshape)"*.

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **MUST** | str | — | Globally-unique producer id (used in API + tests). |
| `description` | CAN | str | `""` | |
| `mode` | CAN | str \| null | `null` | Running mode / subcommand (`diversity`, `composition/ancombc`, …). The key that lets one tool fan out into many outputs. |
| `tool` | CAN | str \| null | `null` | **Pipeline files:** the upstream tool that emits this output. Falls back to `tool.name`. |
| `biotools_id` | CAN | str \| null | `null` | **Pipeline files:** per-output bio.tools id. Falls back to `tool.biotools_id`. |
| `nf_core_module` | CAN | str \| null | `null` | e.g. `qiime2/ancombc`, `mosdepth`. |
| `edam_operations` | CAN | list[str] | `[]` | EDAM operation ids, e.g. `operation_3223` (differential abundance). |
| `edam_formats` | CAN | list[str] | `[]` | EDAM format ids, e.g. `format_3475` (TSV). |
| `pipelines` | CAN | list[str] | `[]` | Which pipeline(s) emit this, e.g. `nf-core/viralrecon@3.0.0`. Provenance + coverage. |
| `file_patterns` | CAN | list[str] | `[]` | Globs relative to the run root. Empty when the output is derived (see `depends_on`). |
| `read_options` | CAN | `ReadOptions` | identity | How to parse the file. |
| `depends_on` | CAN | list[str] | `[]` | Other output `id`s this is derived from (the recipe `dc_ref` chain). |
| `reshape` | CAN | `Reshape` | `{kind: identity}` | Raw file → bindable shape. |
| `fingerprint` | CAN | `Fingerprint` \| null | `null` | Column-name signature. **Null** = not matched from columns (non-tabular, derived, or covered by a curated producer). |
| `feeds_viz` | CAN | list[`AdvancedVizKind`] | `[]` | Viz kinds this output (post-reshape) can drive. |
| `role_mapping` | CAN | dict[viz → dict[role → column]] | `{}` | Pre-fills the viz binding so the user doesn't name columns by hand. |

### `read_options` — `ReadOptions`

| Field | MUST/CAN | Type | Default |
|---|---|---|---|
| `format` | CAN | `"csv"` \| `"tsv"` \| `"parquet"` | `"csv"` |
| `separator` | CAN | str \| null | `null` |
| `comment_prefix` | CAN | str \| null | `null` |
| `skip_rows` | CAN | int | `0` |
| `has_header` | CAN | bool | `true` |

### `reshape` — `Reshape`

`kind` selects the reshape; the other fields are the parameters for that kind
(validated — a `melt` without `id_vars` is rejected).

| Field | MUST/CAN | Type | Used by | Notes |
|---|---|---|---|---|
| `kind` | CAN | `identity` \| `melt` \| `pivot` \| `aggregate` \| `recipe` | — | Default `identity` (no reshape). |
| `id_vars` | cond. | list[str] | `melt` | **Required for melt.** Columns to keep. |
| `value_vars` | CAN | list[str] \| null | `melt` | Columns to unpivot (default: all others). |
| `variable_name` | CAN | str \| null | `melt` | Name for the melted key column. |
| `value_name` | CAN | str \| null | `melt` | Name for the melted value column. |
| `index` | CAN | list[str] \| null | `pivot` | Row index columns. |
| `on` | cond. | str \| null | `pivot` | **Required for pivot.** Column whose values become new columns. |
| `values` | cond. | str \| null | `pivot` | **Required for pivot.** Column to fill the matrix. |
| `group_by` | cond. | list[str] \| null | `aggregate` | **Required for aggregate.** |
| `agg` | cond. | `sum`\|`mean`\|`median`\|`max`\|`min`\|`count` \| null | `aggregate` | **Required for aggregate.** |
| `recipe` | cond. | str \| null | `recipe` | **Required for recipe.** Pipeline-qualified recipe path, e.g. `nf-core/ampliseq/ancombc.py`. |

### `fingerprint` — `Fingerprint`

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `required_columns` | CAN | list[str] | `[]` | All must be present for the fingerprint to match. Describes the **post-reshape / post-read** column set. |
| `optional_columns` | CAN | list[str] | `[]` | Recorded for docs; not required to match. |

> An output with `fingerprint: null` (or no `required_columns`) is **not**
> compiled to a column-matching `Producer` — it still carries provenance + its
> recipe link, but its viz is reached via the recipe producing an
> already-known canonical shape.

### `AdvancedVizKind` (allowed `feeds_viz` / `role_mapping` keys)

`volcano`, `embedding`, `manhattan`, `stacked_taxonomy`, `phylogenetic`,
`rarefaction`, `da_barplot`, `enrichment`, `complex_heatmap`, `upset_plot`,
`ma`, `dot_plot`, `lollipop`, `qq`, `sunburst`, `oncoplot`, `coverage_track`,
`sankey`.

---

## Two shapes of catalog file

- **Tool-scoped** (`kind: tool`) — one tool, identity at the top. Outputs omit
  `tool`/`biotools_id` (they inherit). See `metaphlan.yaml`.
- **Pipeline-scoped** (`kind: pipeline`) — a composition; each output names its
  upstream `tool` + `biotools_id`. See `viralrecon.yaml`, `ampliseq.yaml`.
