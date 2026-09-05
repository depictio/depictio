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
