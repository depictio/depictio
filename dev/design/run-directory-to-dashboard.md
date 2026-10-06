# A results directory in, a dashboard out (MultiQC-like)

Goal: `uv tool install "depictio[local]"`, point Depictio at a results directory, and
get a dashboard built for it: the files recognised, KPIs, plots, tabs and their
order, the way MultiQC builds its report.

Decisions: a dashboard served locally (no standalone HTML in a first version); a
deterministic core, with the AI generation stack (#964 → #1028 → #1032 → #1045) as an
optional layer on top; nf-core runs with a bundled template plus anything the
catalog recognises, with every other file **proposed**, never added silently; an
Overview tab, then one tab per pipeline stage.

## What exists, mapped onto MultiQC

| MultiQC | Depictio | State |
|---|---|---|
| search patterns | catalog `find:` + `match_run_dir()` (`models/components/advanced_viz/catalog.py`) | exists; not wired into ingestion (`catalog/TODO.md`, "Guided mode") |
| a module's parsing | recipes (`depictio/recipes/`) | exists; the matched path is not handed to the recipe |
| a module's sections | `renders_as` | exists; mostly advanced_viz, few figures and cards |
| General Stats across tools | `multiqc/general_stats.yaml`, MultiQC only | missing |
| `module_order`, sample-name cleaning | — | missing: a `Render` has no order or priority |
| report assembly | `compose_run_dir()`: "a preview only" | missing |
| custom content, user config | catalog and templates read from the package only | missing |
| pipeline detection | `select_template_for_run()` from `pipeline_info/` | exists in `run`, and in `local up` since phase 1 |

## Where composition lives

Every entry point already ends in `depictio run`: `depictio local up --data-root`
(a person, locally), the Nextflow completion hook (`cli/configs/nextflow/depictio.config`,
the closest thing to MultiQC as a pipeline's last step), `depictio run --data-root`
against a shared server, and later `POST /projects/from_run` (#1047). A separate
`report` command would serve only the first. So composition is one more level of
template resolution inside `run`:

```
--template  >  --pipeline-id  >  bundled template detected from the run  >  template COMPOSED from the catalog
```

The composed result is an ordinary template (`template.yaml` with `{DATA_ROOT}`,
plus `dashboards/*.yaml`), so everything downstream is reused as is:
`resolve_template`, pruning of missing collections, conditionals, recipe seeds,
dashboard import, `--update-config`. The one new command is `depictio template
compose <dir> [-o out/]`: offline, no server. It prints the proposal (collections,
tabs, KPIs, unrecognised files with what they could become) and writes an editable
template, run back with `run --template ./out/`. Composition must be deterministic
(sorted, stable tags), and the composed template is kept with the project so a
re-run does not reshuffle the dashboard.

## Phases

1. **Plumbing** (done): `local up --data-root` without `--template`, a second `up`
   on the same directory opens the existing project instead of failing, `--refresh`
   to ingest again, the ingested dashboard opened rather than the list,
   `run --template <path>`, `run --result-json`, and `run` using a running local
   server's CLI config when there is no `~/.depictio/CLI.yaml`.
2. **Composer** (`depictio/cli/cli/utils/compose.py`): catalog matches → collections
   (raw → table, recipe → `transform` with `source_overrides` on the matched path,
   `multiqc.parquet` → multiqc; promote the helpers of
   `projects/init/catalog_conformance/scripts/generate_project.py`) and a multi-tab
   dashboard YAML (`{main_dashboard, tabs}`); `template compose`; the fallback in
   `run` where it now reports "Could not tell which pipeline produced …".
3. **Catalog**: `headline`, `priority`, `stage` and optional `warn`/`fail` thresholds on
   a render (`catalog.py`, the JSON schemas, `SCHEMA.md`, `dev catalog validate`);
   MultiQC sections kept only when the parquet has them (shared out of
   `catalog_endpoints/routes.py::_multiqc_sections`); every plot of a MultiQC module,
   not only the first; a cross-tool general-stats table joined on a normalised
   sample id (`recipes/lib/sample_ids.py`).
4. **Unrecognised files**: a deterministic proposal from the Polars schema (sample
   column, numeric metrics → cards, categoricals of at most 50 values → MultiSelect,
   `suggest_viz_kinds`); reported by `template compose` and at the end of `run`,
   added with `--include-unknown` / `--include <glob>` into an "Other data" tab;
   listed on the project page (v1: the command to copy; v2: one click in local
   mode, where the server shares the file system).
5. **Optional AI**, then a standalone HTML report, a Python API and catalog
   enrichment.

## Layout of a composed dashboard

- **Overview** (main tab): sample count and headline KPIs (#1145 `headline` cards),
  the general-stats table, one `[Stage](tab:…)` tile per tab.
- **One tab per stage present**, ordered by a fixed vocabulary
  (`qc → preprocessing → alignment → quantification → variants → taxonomy →
  downstream → other`), one section per tool: cards → figures → advanced_viz →
  collapsed table.
- **MultiQC**: one tab, every plot present.
- **Other data**: only when asked for.

The deterministic layout of #1028 (`ai_endpoints/dashboard_layout.py`: 8-column grid,
full card rows, figures in pairs) moves out of `ai_endpoints` so the CLI can use
it, and learns tabs.
