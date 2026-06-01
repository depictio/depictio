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
  multiqc/               # multi-output tool → a folder
    module.yaml          #   the `module` identity block
    aggregate.yaml       #   the native multiqc.parquet
    fastqc.yaml          #   FastQC surfaced *via* MultiQC (multiqc_module: fastqc)
  qiime2/
    module.yaml
    taxa_barplot.yaml
    ...
```

- **Flat file** = a whole `CatalogEntry`: a `module:` block + an `outputs:` list.
- **Folder** = the same `CatalogEntry` split across files: `module.yaml` holds
  the `module` fields directly; every other `*.yaml` is one output (the
  `Output` fields directly, no wrapper).
- **MultiQC-covered tools** (FastQC, Cutadapt, samtools stats…) are not
  standalone modules — they live as outputs under `multiqc/` with
  `multiqc_module:` set, because depictio reads them from the MultiQC report.

---

## `module`

The tool. Identity is stored as **directly-clickable URLs** (no IDs to resolve).

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **MUST** | str | — | e.g. `qiime2`, `pangolin`. |
| `name` | **MUST** | str | — | Display name. |
| `description` | CAN | str | `""` | |
| `homepage` | CAN | str \| null | `null` | |
| `nf_core_url` | CAN | str \| null | `null` | Full nf-core module URL; default for outputs. |
| `biotools_url` | CAN | str \| null | `null` | Full `https://bio.tools/<id>` URL. |
| `edam_topics` | CAN | list[str] | `[]` | Full EDAM URLs, e.g. `http://edamontology.org/topic_3174`. |

## `outputs[]` — `Output`

One file the tool emits (one running mode) → one visualisation mapping.

| Field | MUST/CAN | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **MUST** | str | — | Globally-unique producer id. |
| `find` | **MUST** | `Find` | — | How depictio-cli recognises the file. |
| `description` | CAN | str | `""` | |
| `mode` | CAN | str \| null | `null` | Running mode / subcommand (`taxa-barplot`, `composition/ancombc`, …). |
| `multiqc_module` | CAN | str \| null | `null` | If surfaced via MultiQC, the MultiQC module name (e.g. `fastqc`). |
| `nf_core_url` | CAN | str \| null | `null` | Per-output override (QIIME 2 subcommands are separate modules). |
| `biotools_url` | CAN | str \| null | `null` | Per-output override. |
| `edam_operations` | CAN | list[str] | `[]` | Full EDAM URLs. |
| `edam_formats` | CAN | list[str] | `[]` | Full EDAM URLs. |
| `read_options` | CAN | `ReadOptions` | csv defaults | How to parse the file. |
| `file_schema` | CAN | dict[str,str] | `{}` | **The columns + dtypes the tool writes** (raw, as-emitted). |
| `recipe` | CAN | str \| null | `null` | Pipeline recipe that reshapes the raw file (`nf-core/ampliseq/ancombc.py`). Omit when the raw file is already bindable. |
| `feeds_viz` | CAN | list[`AdvancedVizKind`] | `[]` | Viz kinds this output maps to (post-recipe). |
| `role_mapping` | CAN | dict[viz → dict[role → column]] | `{}` | Pre-fills the viz binding. |

### `find` — recognition (MUST set ≥ 1 condition)

A file matches when **all** declared conditions hold (like MultiQC's
`search_patterns`: `fn` + `contents`).

| Field | MUST/CAN | Type | Notes |
|---|---|---|---|
| `filename` | cond. | str \| null | Glob on the basename, e.g. `*.pangolin.csv`. |
| `path_glob` | cond. | str \| null | Glob on the path under the run root, `**`-aware, e.g. `**/mosdepth/genome/*.tsv`. |
| `content_contains` | cond. | str \| null | Substring in the file head (text files). |
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

### `recipe` — the only reshape mechanism

Real tool→viz reshapes are pipeline-specific (join slice files, melt wide
matrices, derive columns) and are written as Python recipes, so `recipe` is
just an **optional reference** to one. The value is a pipeline-qualified name
`<pipeline>/<name>.py` (e.g. `nf-core/ampliseq/ancombc.py`), resolved by
`depictio.recipes.resolve_recipe_path` to
`depictio/projects/<pipeline>/recipes/<name>.py` (with a `{version}/` override
tried first). `depictio catalog validate` checks every `recipe` resolves.
There is no declarative `melt`/`pivot` mini-language: either the raw file is
already bindable (omit `recipe`) or it needs real code (point `recipe` at it).

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
