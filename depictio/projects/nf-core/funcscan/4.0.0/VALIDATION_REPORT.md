# nf-core/funcscan 4.0.0: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`, Mongo `:27101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the funcscan 4.0.0 template plus the four catalog tools it depends on
(hAMRonization, AMPcombi, comBGC, run_dbCAN) and drive `depictio-cli run` against the real
AWS megatest output end to end.

## Data used

AWS megatest run `s3://nf-core-awsmegatests/funcscan/results-aee3dc965eb0c77267435544dda30da858763913/`
(the 4.0.0 release tag): a 19-sample metagenome-assembly screen of MGnify assemblies
(`ERZ166450x`) with all four screening arms enabled. The manifest
(`megatest.yaml`) fetches the aggregated reports plus the small per-sample dbCAN tables
only, 47 files / 6.5 MB, out of the run's 3769 files and roughly 2.8 GB. The per-tool raw
outputs (`bgc/` 1.2 GB, `annotation/` 1.1 GB, `amp/` 431 MB, `arg/` 55 MB) are not read by
any data collection.

```bash
python scripts/nfcore_megatest.py fetch --pipeline funcscan --version 4.0.0 \
  --dest ~/Data/depictio-nfcore/funcscan/4.0.0/megatest
# the run publishes no input/ directory, so the samplesheet is fetched separately:
mkdir -p ~/Data/depictio-nfcore/funcscan/4.0.0/megatest/input
curl -fsSL -o ~/Data/depictio-nfcore/funcscan/4.0.0/megatest/input/samplesheet_full.csv \
  https://raw.githubusercontent.com/nf-core/test-datasets/funcscan/samplesheet_full.csv
```

## Ingestion result: 15 / 15 data collections processed, exit 0

```bash
depictio-cli run --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/funcscan/4.0.0 \
  --data-root ~/Data/depictio-nfcore/funcscan/4.0.0/megatest
```

The final validated run left `--project-name` off, so the project carries the name the
template declares. That matters only for a later standalone `depictio dashboard import`,
which resolves the dashboard's `project_tag` by name; `run` itself accepts any project
name because step 8 passes the id of the project it just created.

Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | (versions only, see FS-D1) | |
| `samplesheet` | 19 | 4 |
| `hamronization_report` | 6160 | 18 |
| `hamronization_gene_presence` | 926 | 8 |
| `hamronization_gene_matrix` | 119 | 21 |
| `hamronization_tool_overlap` | 5232 | 7 |
| `ampcombi_summary` | 8442 | 26 |
| `ampcombi_embedding` | 8442 | 9 |
| `ampcombi_clusters` | 678 | 4 |
| `combgc_summary` | 155 | 14 |
| `combgc_tool_overlap` | 144 | 4 |
| `dbcan_overview` | 17235 | 12 |
| `dbcan_tool_overlap` | 17235 | 5 |
| `dbcan_substrates` | 164 | 9 |
| `screening_summary` | 19 | 11 |

All 74 non-text dashboard tiles were then executed against those frames: every code-mode
figure returns a plotly `Figure` with at least one trace, every card column and breakdown
column exists, every interactive column exists with a non-degenerate value set, every
`row_selection_column` and `selection_column` exists, and every advanced visualisation
binds only columns the collection actually has.

## Discrepancies

### FS-D1: funcscan feeds MultiQC nothing but software versions

The run wrote a MultiQC 1.34 report, but its parquet holds a single `run_metadata` row:
`report_general_stats_data` and `report_plot_data` are both empty, and there are no module
sections. There is nothing to render.

**Decision:** the `multiqc_data` data collection stays in the template (a later funcscan
release may add modules) but is `optional: true`, and the dashboard ships **no QC tab**. The
tool versions reach the UI through the template's `provenance` block, which reads
`pipeline_info/*software*versions.yml` into a `Software versions` group.

### FS-D2: the comBGC per-sample summaries hold the antiSMASH branch only

comBGC writes `reports/combgc/<sample>/combgc_summary.tsv` next to a run-level
`reports/combgc/combgc_complete_summary.tsv`. In this run the per-sample files carry 137
regions, all antiSMASH; GECCO's 18 regions exist only in the complete summary (155 rows).
Globbing the per-sample files therefore produced a caller-overlap panel with exactly one
set.

**Decision:** `combgc/summary.py` and `combgc/tool_overlap.py` both read the run-level
complete summary, and the per-sample glob was dropped from `megatest.yaml`. The BGC UpSet
now shows a real two-set overlap (126 antiSMASH-only contigs, 11 shared, 7 GECCO-only).

### FS-D3: run_dbCAN writes one file per sample with no sample column

`cazyme/dbcan/cazyme_annotation/<sample>/<sample>_overview.tsv` identifies the sample only
through the directory name. The recipe harness resolves a glob source by reading each match
and concatenating with `pl.concat(..., how="diagonal_relaxed")` **without the file paths**,
and polars `read_csv` has no `include_file_paths` argument, so the sample cannot be
recovered from the harness.

**Workaround (in `dbcan/overview.py` and `dbcan/tool_overlap.py`):** the sample is derived
from the gene identifier, which carries the assembly accession as its prefix
(`ERZ1664501.10-NODE-...` gives `ERZ1664501`), with a single `run` pseudo-sample as the
fallback when no prefix is present. This is correct for funcscan because the assembly
accession is the sample id, but it is a per-pipeline workaround, not a general one.

**Infrastructure gap:** a recipe that needs per-file provenance has no supported way to get
it. Either `_resolve_glob_source` should offer to add a path or stem column, or
`RecipeSource` should grow a `file_column` option.

### FS-D4: `optional: true` is not honoured on a glob source

`RecipeSource(optional=True)` is respected for `path` and `dc_ref` sources but not for
`glob_pattern`: `_resolve_glob_source` raises unconditionally when nothing matches. A
recipe whose optional inputs are globs therefore hard-fails instead of degrading. Not hit by
this template (the screening data collections are pruned at the template level instead), but
it constrains how optional a recipe can be.

### FS-D5: a `dc_ref` hub must be declared after its dependencies

`screening_summary` reads the four screening collections through `dc_ref`. The CLI resolves
a `dc_ref` source by reading the referenced collection back from **its Delta table in S3**
(`depictio/cli/cli/utils/deltatables.py`), which only exists once that collection has been
processed. Declaring the hub first made the run fail with

```
Failed to process data collection 'screening_summary':
screening_summary: none of the four screening collections is available
```

**Fix:** the `screening_summary` block is declared **last** in `data_collections`, with a
comment saying why. Declaration order in `template.yaml` is load-bearing whenever `dc_ref`
is used.

### FS-D6: three planned panels were degenerate against the real data

- The ARG sunburst was planned as `drug_class` to `antimicrobial_agent` to `gene_symbol`.
  `antimicrobial_agent` is null for about 90% of the 6160 hits and the five ARG tools do not
  share a drug-class vocabulary, so most of the disc collapsed into one wedge. It is now
  `tool` to `drug_class` to `gene_symbol`, which reads as "what each tool called and how it
  classified it".
- The AMP scatter was planned as ampir versus Macrel probability. `prob_macrel` is 0.0 for
  8421 of the 8442 candidates, so the y axis was a line. It is now hydrophobicity versus
  isoelectric point, coloured by charge class, which is the property space AMPcombi is
  actually reporting.
- The BGC caller overlap did not exist in the draft. `combgc/tool_overlap.py` was added so
  the BGCs tab has a real concordance panel; it scores agreement on the **contig**, not on
  region coordinates, because the callers disagree on boundaries by design and a coordinate
  join reports no overlap where the biology is the same cluster.

### FS-D7: `_introspect_pipeline_params` does not know funcscan's screen flags

The template exposes `SKIP_ARG` / `SKIP_AMP` / `SKIP_BGC` / `SKIP_CAZYME` so a run with one
arm switched off prunes that arm's data collections and tab. `params.json` already carries
`run_arg_screening`, `run_amp_screening`, `run_bgc_screening` and `run_cazyme_screening`,
but `_introspect_pipeline_params` in `depictio/cli/cli/utils/templates.py` does not map them,
so the variables must be passed by hand (`--var SKIP_ARG=true`). The screening collections
are all `optional: true`, so a run that just omits the flag still ingests: the arm's
collections skip themselves and only the tab stays present but empty.

## Open blocker: dashboard import

Steps 1 to 7 of the CLI run succeed and every data collection is populated, but step 8
(dashboard import) fails server-side with

```
ValueError: invalid catalog entry /app/depictio/catalog/homer:
tool folder /app/depictio/catalog/homer is missing module.yaml
```

raised from `catalog_source_for_use` to `load_catalog_entries()`. The catalog loader is
all-or-nothing: one malformed tool folder anywhere under `depictio/catalog/` makes every
`use:` reference in every dashboard unresolvable. `depictio/catalog/homer` and
`depictio/catalog/macs2` are unfinished folders belonging to a different workstream in the
same worktree (`.py` recipes, no `module.yaml`). The same failure hits the pre-existing
ampliseq, viralrecon, differentialabundance and variantbenchmarking dashboards, so it is not
specific to funcscan.

The import succeeds as soon as those folders are completed or removed. Nothing in the
funcscan template needs to change: `dashboard validate` passes, and validating the YAML with
the catalog loader patched to skip incomplete folders resolves every tab, every `use:` and
every component.

---

# 2026-09-22 remediation pass

**Date:** 2026-09-22
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Validator:** local `uv run python -m depictio.cli` against the lot2 docker stack
(API `:8112`, viewer `:5612`, Mongo `:27112`,
config `~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml`), same DATA_ROOT
(`~/Data/depictio-nfcore/funcscan/4.0.0/megatest`, 19 MGnify metagenome assemblies).

## What this pass changed

The 2026-09-05 report validated the data path. This pass closes the dashboard-side
findings that audit raised: a filter that could not filter, tiles with no catalog home,
grid rows that did not add up, a declared data collection nothing read, and a missing
layer between the assembly and the four screens.

- **A new hub collection with a catalog home.** `screening_summary.py` moved out of
  `depictio/projects/nf-core/funcscan/recipes/` into a new catalog module,
  `depictio/catalog/funcscan/`, together with the eleven tiles that used to be written
  inline on the dashboard. `use:` coverage on the shipped YAML went from 77 % to
  **73 / 73 non-text tiles**. The module carries no `nf_core_url`: funcscan's aggregation
  is pipeline-local, so it declares `source_url: https://github.com/nf-core/funcscan`
  the way `depictio/catalog/combgc/module.yaml` does.
- **Three new catalog outputs.** `funcscan/contig_annotation` (the locus layer, rebuilt
  from the four screens), `funcscan/software_versions` (the only payload funcscan's
  MultiQC report holds) and `combgc/region_track` (BGC regions in coordinates).
- **Two new views on existing collections.** `hamronization/class_matrix` is the ARG
  matrix one aggregation level above `gene_matrix`, drug class against sample, drawn as
  a `complex_heatmap`; `ampcombi/summary` gained an `amp_property_scatter`
  (`scatter_xy`) over the physicochemical plane AMPcombi actually reports.
- **Two new tabs.** `Annotation` (tab_order 1) sits between the overview and the four
  screens; `Run report` (tab_order 6) is where `multiqc_data` finally surfaces, through
  `software_versions`. Existing tabs renumbered 2 to 5.
- **Filters and layout.** The dead `screens` control is gone, every one of the seven tabs
  now carries the pinned persistent sample section plus a tab-local, non-persistent
  section on its own collection's columns, seven `links:` entries were added so the
  persistent filters reach the new collections, every tab opens on a four-card glance
  strip (`w: 2 h: 2` at x 0/2/4/6), and every grid row sums to 8.

## Ingestion result: 19 / 19 data collections processed, exit 0

```bash
uv run python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml \
  --template nf-core/funcscan/4.0.0 \
  --data-root ~/Data/depictio-nfcore/funcscan/4.0.0/megatest
```

Delta tables read back through `GET /depictio/api/v1/deltatables/shape/{dc_id}` after the
run. The four rows marked **new** did not exist in the 2026-09-05 pass.

| Data collection | Rows | Columns | |
|---|---|---|---|
| `multiqc_data` | (versions only, see FS-D1) | | |
| `software_versions` | 50 | 5 | new |
| `samplesheet` | 19 | 4 | |
| `hamronization_report` | 6160 | 18 | |
| `hamronization_gene_presence` | 926 | 8 | |
| `hamronization_gene_matrix` | 119 | 22 | |
| `hamronization_class_matrix` | 34 | 22 | new |
| `hamronization_tool_overlap` | 5232 | 7 | |
| `ampcombi_summary` | 8442 | 26 | |
| `ampcombi_embedding` | 8442 | 9 | |
| `ampcombi_clusters` | 678 | 4 | |
| `combgc_summary` | 155 | 14 | |
| `combgc_region_track` | 155 | 11 | new |
| `combgc_tool_overlap` | 144 | 4 | |
| `dbcan_overview` | 17235 | 12 | |
| `dbcan_tool_overlap` | 17235 | 5 | |
| `dbcan_substrates` | 164 | 9 | |
| `screening_summary` | 19 | 11 | |
| `contig_annotation` | 29348 | 12 | new |

The open blocker recorded on 2026-09-05 is closed: `GET /dashboards/tabs/{id}` reports the
main tab plus six children, 126 components in total, every tab carrying two filter sections
and a four-card glance strip.

| Tab | Components | Grid sections | Filter sections |
|---|---|---|---|
| Screening overview (0) | 28 | 5 | 2 |
| Annotation (1) | 13 | 2 | 2 |
| Resistome (2) | 20 | 4 | 2 |
| AMPs (3) | 15 | 3 | 2 |
| BGCs (4) | 22 | 4 | 2 |
| CAZymes (5) | 17 | 4 | 2 |
| Run report (6) | 11 | 2 | 2 |

## Commands run

| Command | Result |
|---|---|
| `uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -k funcscan` | 10 passed |
| `uv run pytest depictio/tests/recipes/test_funcscan_screens.py` | 7 passed |
| `uv run pytest depictio/tests/models/test_catalog.py` | 95 passed, 4 failed, none in a funcscan tool (see FS-D14) |
| `uv run python -m depictio.cli run --template nf-core/funcscan/4.0.0 --data-root ... --dry-run` | 8 / 8 steps |
| `uv run python -m depictio.cli run --template nf-core/funcscan/4.0.0 --data-root ...` | 8 / 8 steps, 19 / 19 collections |
| `ruff format` and `ruff check` on the touched files | clean |
| `uv run pre-commit run --files ...` | Passed or Skipped throughout |

## Discrepancies

### FS-D8: the `screens` control could never filter anything

The samplesheet the megatest ran on is `sample,fasta` and nothing else, so the template
had no experimental variable to filter on and the dashboard fell back to filtering on
`screening_summary.screens`. All four screening arms were on for every sample, so that
column is the constant 4: `nunique == 1`, which makes both the RangeSlider and the
`fs-card-screens` threshold card inert. Neither was hidden, both were removed. The sample
scope now filters on `sample`, `arg_hits`, `amp_candidates` and `cazymes`, and a second,
tab-local `Cohort thresholds` section covers `bgc_regions`, `bgc_classes` and
`cazyme_families`. Every tab got the same treatment on its own collection's columns.
A run whose samplesheet does carry metadata columns is unaffected: the samplesheet
collection is separate and its columns are not what these controls read.

### FS-D9: funcscan's MultiQC parquet has no panel to bind, so the versions are the panel

FS-D1 recorded that funcscan feeds MultiQC nothing but software versions. This pass
confirmed it from the report itself (`multiqc.list_plots()` returns
`nf-core-funcscan-methods-description: 0 plots` and `nf-core-funcscan-summary: 0 plots`,
`list_samples()` is empty) and the ingest agreed: `0 samples, 2 modules, 0 plots`. The
declared-but-unbound `multiqc_data` collection is therefore not bound to a `multiqc`
tile, because that tile would render blank. Instead `funcscan/software_versions.py` reads
the `software_versions` JSON back out of the same parquet and the Run report tab shows it
as a table, a bar figure and four cards. The tab is deliberately not named after MultiQC,
so the shipped-dashboard rule that a MultiQC tab may hold only MultiQC panels does not
apply to it. `multiqc_data` stays declared, and its path regex was widened to
`(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$` so a run that nests the
report one directory deeper still matches.

### FS-D10: AMPcombi reports no net charge

The brief asked for a hydrophobicity against charge scatter. The shipped
`Ampcombi_summary.tsv` carries `hydrophobicity`, `isoelectric_point`, `molecular_weight`
and the helix / turn / sheet fractions, but **no net-charge column at pH 7**, so no such
column was invented. `amp_property_scatter` plots hydrophobicity against isoelectric
point, which is the charge-related quantity AMPcombi does report, with a pI 7 reference
line; the YAML comment says so, and so does `docs/dashboards.md`.

### FS-D11: comBGC reports no region orientation

`combgc_complete_summary.tsv` has `BGC_start` and `BGC_end` but no strand. The
`gene_arrow_track` binding needs one, so `combgc/region_track.py` emits GFF's `.`
("no strand") for every region. The renderer only reverses an arrow on `-`, so every BGC
is drawn left to right; that is a drawing convention, not a claim about the locus.

### FS-D12: `complex_heatmap` names its row-label field `index_column`

`validate_binding` reads the `<role>_col` naming convention, and `ComplexHeatmapConfig`
calls its row-label field `index_column`, so `validate_binding` reports the `index` role
as unbound even on a correct config. The `class_matrix` test checks what the renderer
actually needs instead: the index column is a String column and every remaining matrix
column is Float64. Worth aligning the field name, in `depictio/models/`, which is outside
this template's partition.

### FS-D13: `execute_recipe(extra_sources=...)` is keyed by source ref, not by `dc_ref`

A recipe whose sources are `dc_ref` handles still declares a `ref` per source, and
`extra_sources` is matched on the `ref`. Passing the `dc_ref` tag (`hamronization_report`)
instead of the ref (`arg`) silently injects nothing, and the recipe fails with its own
"no source available" error rather than with a keying error. Only a documentation gap, but
it cost a debugging round here.

### FS-D14: the advanced-viz kind registry is mid-rename in this worktree

HEAD registers the GenomeSpy kind as `genomespy_track`; the working tree registers it as
`genome_view`. `combgc/region_track.yaml` names `genome_view`, which is the only place in
the funcscan work that names the kind at all (the dashboard reaches it through
`use: combgc/bgc_genome_track`), so a single line has to follow whichever name lands. The
four `test_catalog.py` failures in this pass are all in other workstreams' tools
(cellbender, kallisto, qcatch, simpleaf cards; cooltools and gtdbtk string aggregations)
plus the two generated JSON schemas that the same rename left stale.

### FS-D15: `scatter_xy`'s optional `color` role is String-only

`funcscan/screen_scatter` wanted to colour points by `amp_candidates`, an Int64.
`ground_render_dtypes` rejects that, because the `color` role on `scatter_xy` is `_STRING`.
The catalog render therefore binds no `color` role and the dashboard tile carries
`color_col: amp_candidates` with a continuous scale in its own `config:` instead. A
numeric colour role on `scatter_xy` would remove the need for that split.
