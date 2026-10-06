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
2. **Composer** (done, `depictio/cli/cli/utils/compose.py`):
   - catalog matches → collections: raw → table; recipe → `transform` with
     `source_overrides` re-rooted from the matched file; `multiqc.parquet` →
     multiqc, read off the parquet itself (`multiqc_parquet.py`);
   - a `dc_ref` a recipe needs is tagged as it expects, or synthesised from its raw
     files (mosdepth's recipes read a collection named like their own output);
   - every composed collection is `optional`, so a failed one is skipped and its
     tiles dropped by the import instead of failing the run;
   - a multi-tab dashboard (`{main_dashboard, tabs}`) with explicit layouts
     (`compose_layout.py`), validated with the lite models before it is written;
   - `depictio template compose <dir> [-o out/]`; the fallback in `run`, forced
     with `--compose`.
3. **Catalog** (done): `stage` on a tool and as an output override, `headline` on a
   card, `priority` on any render; thresholds reuse the card's `threshold_*`
   fields. Every MultiQC plot present in the report is on the dashboard. A
   cross-tool general-stats table (`general_stats.tsv` next to the composed
   template) joins each tool's headline cards per normalised sample.
4. **Unrecognised files** (done): a deterministic proposal from the Polars schema
   (sample column, numeric columns → cards, categoricals of at most 50 values →
   filters, a scatter or box figure, the table), printed by `template compose` and
   `run`, stored on `TemplateOrigin.unrecognised_files` and listed on the project
   page with the command that adds each file; `--include-unknown` /
   `--include <glob>` adds them to an "Other data" tab.
5. **Not done here**: the optional AI layer (it needs the #964 → #1045 stack on
   main: hand it the composed plan through the `plan` hook of #1032), a standalone
   HTML report, a Python API, and catalog enrichment (most outputs still render
   mostly advanced visualisations; about 31 of 183 MultiQC modules have a section,
   which only matters for their stage, since every plot of a report is shown).

Known limits:

- Composed collections are not linked, so the Overview's sample filter narrows
  the MultiQC plots only, not the other tools' tiles.
- A recipe whose inputs are other collections (`dc_ref`) is left out of the
  general statistics, which are computed before ingestion.
- A one-click "add this file" on the project page needs the server to see the
  files (local mode); the page shows the command instead.

## Validation

- Unit: `depictio/tests/cli/utils/test_compose.py` (matching against
  `match_run_dir`, determinism, the composed YAML against the lite models, full
  card rows, every MultiQC plot, recipe re-rooting, `dc_ref` providers, proposals,
  the `template compose` command).
- End to end: `depictio local up --data-root` on the catalog conformance run,
  nf-core/ampliseq 2.14.0 (with and without `--include-unknown`) and
  nf-core/viralrecon (`--compose`), then
  `depictio/tests/e2e-playwright/tests/local/composed-dashboard.spec.ts`, which
  opens every tab and the project page and fails on any server error.

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
