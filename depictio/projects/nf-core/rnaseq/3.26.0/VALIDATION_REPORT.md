# nf-core/rnaseq 3.26.0: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the rnaseq 3.26.0 template plus the `salmon` catalog tool it depends on, and drive
`depictio-cli run` against the real AWS megatest output end to end.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/rnaseq/results-e7ca46272c8f9d5ceee3f71759f4ba551d3217a4/`
(the 3.26.0 release tag). Eight libraries from four ENCODE cell lines (GM12878, H1, K562,
MCF7), two replicates each, human GRCh37, Trim Galore then STAR + Salmon.

```bash
python scripts/nfcore_megatest.py fetch --pipeline rnaseq --version 3.26.0 \
  --dest ~/Data/depictio-nfcore/rnaseq/3.26.0/megatest
# or, equivalently:
bash depictio/projects/nf-core/rnaseq/3.26.0/download_test_data.sh
```

The run publishes two aligner routes side by side (`aligner_star_salmon/` and
`aligner_star_rsem/`). `run_root` is `aligner_star_salmon/`, so **DATA_ROOT is that
sub-directory, not the megatest prefix root**. The manifest fetches 201 files, 22 MB: the
params and software-versions files, the MultiQC parquet and its exported per-module tables,
the merged Salmon gene matrices of both the STAR + Salmon and the stand-alone pseudo-aligner
route, the DESeq2 QC tables and the per-sample QC inputs MultiQC parsed. The samplesheet is
not part of the published run; `pipeline_info/params.json` names it as a GitHub raw URL and
`post_fetch_help` carries the exact curl into `{DATA_ROOT}/input/`.

## Ingestion result: 6 / 6 data collections processed, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/rnaseq/3.26.0 \
  --data-root ~/Data/depictio-nfcore/rnaseq/3.26.0/megatest
```

Project `RNA-seq Expression Analysis` (`6a9bf3b8542b3b1c0f73b5c5`). `--project-name` was left
off, so the project carries the name the template declares: the standalone
`depictio dashboard import` resolves the dashboard's `project_tag` by name, and a renamed
project cannot take a re-imported dashboard later.

Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 15 modules, 85 sample ids (24 canonical) | (MultiQC parquet, not Delta) |
| `samplesheet` | 8 | 7 |
| `sample_overview` | 8 | 9 |
| `expression_heatmap` | 500 | 10 |
| `gene_expression` | 153968 | 6 |
| `gene_counts` | 57773 | 12 |

All four dashboard tabs imported, 65 / 65 components, nothing dropped by
`_filter_unresolved_components`:

| Tab | Components | Breakdown |
|---|---|---|
| `nf-core/rnaseq` (main, QC) | 32 | 17 multiqc, 6 text, 4 card, 3 interactive, 2 table |
| `Expression overview` | 15 | 4 card, 3 text, 3 interactive, 2 multiqc, 1 advanced_viz, 1 figure, 1 table |
| `Expression heatmap` | 6 | 2 text, 2 interactive, 1 advanced_viz, 1 table |
| `Gene explorer` | 12 | 4 card, 3 text, 3 interactive, 1 figure, 1 table |

Every tile was then executed or grounded against those frames:

- **1 / 1 `mode: code` figure** executed with scope
  `{df, pl, px, go, pd, np, depictio_group_by=None, depictio_group_kwargs={}}` against the
  real `gene_expression` frame and returns a plotly `Figure` with 4 traces.
- **1 / 1 `mode: ui` figure** binds only columns `sample_overview` has.
- **37 column bindings checked**: every card `column_name` / `breakdown_col` /
  `trend_col` / `attrition_cols`, every one of the 11 interactive `column_name`s, the one
  `selection_column` (`gene_name`) and the five table `row_selection_column`s, and both
  advanced_viz role sets. No binding names a column its collection does not have.
- **2 / 2 advanced visualisations** resolve their `use:` handle against the on-disk catalog
  (`salmon/pca` → `embedding`, `salmon/top_variable_heatmap` → `complex_heatmap`) and every
  role the render declares, plus every `*_col` in the stored config, is a real column.
- **19 / 19 MultiQC tiles** name a module and a plot MultiQC's own `list_plots()` reports
  for this parquet (the nested one, see RS-D1). None is a general-statistics tile.
- **20 tiles carry a `use:` handle**: 14 MultiQC (`multiqc/fastqc` x4, `multiqc/qualimap` x2,
  `multiqc/rseqc` x2, and one each of `cutadapt`, `star`, `samtools`, `picard`, `salmon`,
  `dupradar`), 4 tables (`salmon/sample_pca`, `salmon/expression_heatmap`,
  `salmon/gene_expression`, `salmon/merged_gene_counts`) and 2 advanced visualisations.

Links were replayed against the real frames, hub values against target values:

| Link | Result |
|---|---|
| `samplesheet.sample` → `multiqc_data` (sample_mapping) | 8 hub values expand to 69 / 85 report sample ids (81%) |
| `samplesheet.sample` → `sample_overview.sample_id` | 8 / 8 matched, 8 / 8 rows |
| `samplesheet.sample` → `gene_expression.sample` | 8 / 8 matched, 153968 / 153968 rows |
| `samplesheet.sample` → `expression_heatmap` (wide) | 8 / 8 hub values are columns of the matrix |
| `samplesheet.sample` → `gene_counts` (wide) | 8 / 8 hub values are columns of the matrix |
| `sample_overview.sample_id` → `gene_expression.sample` | 8 / 8 matched, 153968 / 153968 rows |
| `sample_overview.sample_id` → `expression_heatmap` (wide) | 8 / 8 hub values are columns of the matrix |
| `sample_overview.sample_id` → `multiqc_data` (sample_mapping) | 8 hub values expand to 69 / 85 report sample ids |

The three wide-matrix links were a genuine FILTER MISMATCH on the first pass and were fixed;
see RS-D2. After the fix: no FILTER MISMATCH, no 4xx and no 5xx.

`depictio/tests/models/test_shipped_dashboard_yamls.py` and
`depictio/tests/models/test_catalog.py`: 7 passed with `-k "rnaseq or salmon"`, 535 passed
over both whole files. `depictio dev catalog validate`: 31 catalog tools valid.

## Decisions

### RS-C1: DATA_ROOT is the aligner sub-directory, not the megatest prefix

The megatest publishes `aligner_star_salmon/` and `aligner_star_rsem/` side by side, each a
complete pipeline output tree with its own `multiqc/`, `star_salmon/` and `salmon/`. A
DATA_ROOT at the prefix root would make every scan ambiguous between the two routes, and the
MultiQC scan in particular would attach whichever report the walk reached first. The manifest
therefore sets `run_root: aligner_star_salmon/` and mirrors the keys below the destination, so
the fetched directory is itself a valid DATA_ROOT for the default route.

### RS-C2: one merged TPM matrix, three shapes

`star_salmon/salmon.merged.gene_tpm.tsv` is the only expression input the template reads, and
three catalog recipes reshape it: `sample_pca.py` (one row per sample: PCA coordinates plus
detection counts and median TPM), `top_variable_genes.py` (the 500 most variable genes, wide,
with a condition annotation strip) and `gene_expression_long.py` (one row per gene and sample,
expressed genes only). Each shape feeds a different tab, and no tile reads the per-sample
`quant.sf` files. The merged count matrix ships as rows only, under `Reference tables`.

### RS-C3: the recipes default to `salmon/`, the template repoints them

The catalog recipes are pipeline-agnostic: their `SOURCES` point at
`salmon/salmon.merged.gene_tpm.tsv`, which is where a bare salmon/tximport run and the
nf-core `--skip_alignment` route both write it. nf-core/rnaseq's default route writes the same
file under `star_salmon/`, so each DC carries a `transform.source_overrides` pointing there.
The `PSEUDOALIGNER_ONLY` conditional undoes exactly that repointing, which is why it is an
`override_dcs` block rather than a second set of collections.

### RS-C4: the condition is read off the sample name

The nf-core/rnaseq samplesheet schema is `sample,fastq_1,fastq_2,strandedness` and carries no
condition column. `nf-core/rnaseq/samplesheet.py` derives `condition` and `replicate` from the
`<condition>_REP<n>` names nf-core RNA-seq uses throughout its test data and docs, and
`read_type` from whether a second FASTQ is declared. Everything the dashboard groups or
colours by (`condition` on the hub, `group` on the expression collections) comes from that,
so no `GROUP_COL` variable is exposed and no `--var` is needed for the common case. A run
whose sample names do not follow that convention gets one condition per sample, which
degrades the colouring but breaks nothing.

### RS-C5: no general-statistics tile

Every other nf-core template opens with MultiQC's general statistics table. This one does not,
because for rnaseq that table is the widest in the report (FastQC per read, Trim Galore, STAR,
Salmon, samtools, Picard, RSeQC, Qualimap and dupRadar columns for every library) and it is
also the only place the `<sample> Read 1` / `Read 2` sample ids appear, which the sample
filter cannot reach (RS-D4). The QC tab opens on the four design cards and the raw-read panels
instead.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Raw and trimmed read counts, quality, GC, length, duplication, adapters, status | **MultiQC** (`use: multiqc/fastqc`, `use: multiqc/cutadapt`), 5 tiles |
| STAR alignment summary, percent mapped, duplicate marking | **MultiQC** (`use: multiqc/star`, `use: multiqc/samtools`, `use: multiqc/picard`), 3 tiles |
| Salmon fragment length / library type | **MultiQC** (`use: multiqc/salmon`), 1 tile |
| Read distribution, inner distance, genomic origin, gene body coverage, duplication against expression | **MultiQC** (`use: multiqc/rseqc`, `use: multiqc/qualimap`, `use: multiqc/dupradar`), 5 tiles |
| Strandedness inference, DESeq2 PCA and sample similarity, biotype composition | **MultiQC**, 5 tiles, but as pipeline custom content with no catalog entry (RS-D5) |
| Sample PCA, correlation and top-variable-gene structure over the merged TPM matrix | **Dedicated** (`salmon/sample_pca`, `salmon/expression_heatmap`): MultiQC's DESeq2 QC panels are static images of the pipeline's own run, not a filterable embedding, and carry no per-sample expression columns to card or filter on |
| Per-gene expression across libraries | **Dedicated** (`salmon/gene_expression`): MultiQC has no gene-level module at all |
| The merged count matrix as rows | **Dedicated** (`salmon/merged_gene_counts`), table only |

## Discrepancies

### RS-D1: MultiQC 1.33 wrote a nested report directory

This run's MultiQC data dir is `multiqc/star_salmon/multiqc_report_data/`, not the
`multiqc/multiqc_data/` every other shipped template sees. Two places have to agree on that,
and they were the reason PR A added a second matching path:

- The template's data collection pins the literal layout with a scan regex,
  `pattern: "multiqc/star_salmon/multiqc_report_data/multiqc\\.parquet"`. A bare basename
  pattern would also match the RSEM route's report if a DATA_ROOT ever spanned both, and
  would attach whichever the walk reached first.
- The catalog side is matched by `find.path_glob_alt`, not `find.path_glob`. Every
  `depictio/catalog/multiqc/<module>.yaml` carries
  `path_glob: "**/multiqc/multiqc_data/multiqc.parquet"` plus
  `path_glob_alt: ["**/multiqc/*_data/multiqc.parquet", "**/multiqc/*/*_data/multiqc.parquet"]`.
  The **second** alternative is the one that matches here: it is the only pattern with a
  directory level between `multiqc/` and the `*_data/` report dir. Without it the compose
  matcher and the `use: multiqc/<module>` badges would find nothing for this pipeline.

### RS-D2: a wide matrix needs a `target_field` that is *not* one of its columns

`expression_heatmap` and `gene_counts` are wide: the sample ids are column names, not row
values, so a sample filter has no row to match. `_narrow_wide_matrix_columns`
(`depictio/api/v1/celery_tasks.py`) mirrors the filter onto the column set by matching its
VALUES against the column names, which is what makes the link work, but only if the row
filter is skipped first. `apply_filters_to_scan` skips a filter whose column is not in the
frame, so `target_field` there must name a column the wide matrix does **not** have; the
convention the other templates follow is to repeat the hub's own column name.

The first pass pointed those three links at `gene_name` / `gene_id`, which *are* columns of
those matrices. The row filter was therefore applied, comparing sample names against gene
names and gene ids, and every selection emptied both panels. The verification pass caught it
as a FILTER MISMATCH (0 of 8 hub values present in the target); the links now carry
`target_field: sample` and `target_field: sample_id`, neither of which is a column of either
matrix, and all 8 hub values are confirmed to be columns.

### RS-D3: the stored advanced_viz tiles carry `viz_kind: null`

`load_catalog_entries()` is `@lru_cache(maxsize=1)`, so a long-lived API process holds
whatever the catalog looked like the first time it was asked. This stack's API process warmed
that cache before `depictio/catalog/salmon/` existed, so the server cannot resolve
`use: salmon/pca` or `use: salmon/top_variable_heatmap` and
`DashboardDataLite.to_full()` stores `viz_kind: null` with only the four config keys the YAML
spells out, instead of the expanded `embedding` / `complex_heatmap` config. The React renderer
dispatches on `viz_kind`, so both tiles would draw as "advanced_viz (unknown kind)".

This is the process cache, not the template: the same `to_full()` run against the on-disk
catalog in this worktree expands `salmon/pca` to `embedding` (29 config keys) and
`salmon/top_variable_heatmap` to `complex_heatmap` (14). Confirmed on the server by
`GET /depictio/api/v1/catalog/output/salmon_sample_pca/preview-payload` → 404 while
`enchantr_sequence_fates` and `hamronization_report` (tools created earlier the same day)
→ 200. `arriba`, `taxpasta` and `macs2` are 404 for the same reason. An API restart clears it;
this workstream does not restart the shared stack, so it is recorded rather than fixed.

### RS-D4: the sample filter does not reach the `<sample> Read 1` / `Read 2` ids

`build_sample_mapping` derives a canonical id with
`^([A-Za-z0-9_-]+?)(?:_[12])?(?:\s+-\s+.+)?$`: it strips a `_1` / `_2` suffix and MultiQC's
`" - "` annotation delimiter, but a space-delimited suffix with no hyphen does not match the
character class at all, so `"GM12878_REP1 Read 1"` becomes its own canonical id. The report
has 24 canonical ids for 8 libraries (the bare name plus `Read 1` and `Read 2`), and the eight
samplesheet values expand to 69 of the 85 report sample ids; the 16 unreached ones are exactly
the per-read entries.

They appear only in `general_stats_table`'s `plot_input_data`, and no tile on this dashboard is
a general-statistics tile (RS-C5), so no shipped panel loses a series. It is recorded because
any template that does add one for this pipeline will see the per-read rows disappear under a
sample filter.

### RS-D5: rnaseq's five custom-content MultiQC sections carry no `use:` badge

nf-core/rnaseq injects `strandedness`, `sample-relationships` (the DESeq2 PCA and sample
similarity panels) and `biotype_counts` as MultiQC custom content, so the module ids are the
pipeline's own, not a tool's. `depictio/catalog/multiqc/featurecounts.yaml` renders
`section: featurecounts`, which does not match the `biotype_counts` module id this report
writes, and there is no catalog entry for the other two. Those five tiles are therefore
authored without `use:` and show no catalog badge. Adding a `use:` whose `section` does not
match the module would be worse: it would badge the tile with a provenance the report does not
have.

### RS-D6: rnaseq's route flags are not auto-detected

The template exposes `PSEUDOALIGNER_ONLY`, `SKIP_MULTIQC` and `SKIP_QUANTIFICATION_MERGE` so a
run that skipped a step prunes the matching data collections. `pipeline_info/params.json`
already carries `skip_alignment`, `skip_multiqc`, `skip_qc` and `skip_quantification_merge`,
but `_introspect_pipeline_params` in `depictio/cli/cli/utils/templates.py` only maps the
ampliseq and viralrecon flags, so these must be passed by hand
(`--var PSEUDOALIGNER_ONLY=true`). The megatest run has all four false, so the default route
ingests with no `--var`.

### RS-D7: re-running `run` over an existing project needs three flags, and says so late

Re-ingesting to pick up an edited `template.yaml` fails at step 4 with
`Project configuration already exists on server, use --update flag to update` (the flag is
actually spelled `--update-config`), and then again at step 6 with one
`DeltaTableAggregated ... already exists` per collection until `--overwrite` is added. The
working incantation is `run --update-config --overwrite`; with it, step 8 updates the four
dashboards in place rather than accumulating new ones, because the main dashboard's title
matches the one already stored.
