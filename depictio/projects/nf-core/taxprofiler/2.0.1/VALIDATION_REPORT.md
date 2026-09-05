# nf-core/taxprofiler 2.0.1: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the taxprofiler 2.0.1 template plus the three catalog tools it needs (`taxpasta`,
`sylph`, `melon`) and the six new `multiqc/<module>` entries, then drive `depictio-cli run`
against the real AWS megatest output end to end.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/taxprofiler/results-70ecc15e49b4f1fcf79d876643b5d14b65c66178/`
(the 2.0.1 release tag). Three synthetic mock communities (`MOCK_001`, `MOCK_002`,
`MOCK_003`) sequenced on two platforms, Illumina HiSeq 3000 and Oxford Nanopore MinION R9,
and pushed through every profiler the pipeline offers. `MOCK_003_Illumina_Hiseq_3000` was
sequenced twice, so the samplesheet has seven rows for six samples and run merging folds the
second run in.

```bash
bash depictio/projects/nf-core/taxprofiler/2.0.1/download_test_data.sh
# or, equivalently:
python scripts/nfcore_megatest.py fetch --pipeline taxprofiler --version 2.0.1 \
  --dest ~/Data/depictio-nfcore/taxprofiler/2.0.1/megatest
# plus the two input-sheet curls the wrapper adds (see TP-D2)
```

The manifest (`megatest.yaml`) fetches 27 key globs: the params and software-versions files,
the MultiQC parquet, every taxpasta standardised table, the profilers' own combined and
per-sample reports, melon's per-rank tables, sylph's per-sample and merged tables, the
nonpareil redundancy estimates and the nanoq read stats. That is 92 files and about 1.7 MB;
the read-level outputs (per-read kaiju / diamond / ganon hits, centrifuge results, the MALT
RMA files, the kmcp search output, analysis-ready FASTQs) are roughly 3 GB and are never read
by the template.

MultiQC parquet: written by MultiQC 1.34 by the run itself, not reprocessed. 837 rows,
18 modules, 41 plots, 80 sample ids.

## Which profilers actually produced output in this run

`pipeline_info/params.json` has every `run_*` flag set to true, so this megatest is the
maximal case: bracken, centrifuge, diamond, ganon, kaiju, kmcp, kraken2, krakenuniq, MALT,
melon, metacache, metaphlan, mOTUs, sylph and Krona all ran, on top of fastp / FastQC short-read
QC, porechop_abi / nanoq long-read QC, bowtie2 host removal and nonpareil redundancy
estimation.

What reached a data collection is narrower than what ran:

| Profiler | Ran | Standardised by taxpasta | Rows in the dashboard |
|---|---|---|---|
| bracken | yes | yes | `taxpasta_*` (1 database) |
| centrifuge | yes | yes | `taxpasta_*` (1 database) |
| diamond | yes | yes | `taxpasta_*` (3 databases) |
| kaiju | yes | yes | `taxpasta_*` (3 databases) |
| kmcp | yes | yes | `taxpasta_*` (1 database) |
| kraken2 | yes | yes | `taxpasta_*` (2 databases) |
| krakenuniq | yes | yes | `taxpasta_*` (1 database) |
| MALT (`megan6`) | yes | yes | `taxpasta_*` (1 database) |
| metaphlan | yes | yes | `taxpasta_*` (1 database) |
| mOTUs | yes | yes | `taxpasta_*` (3 databases) |
| ganon | yes | yes, but every count is zero | none, see TP-D1 |
| sylph | yes | no taxpasta parser | `sylph_ani`, `sylph_profile` |
| melon | yes | no taxpasta parser | `melon_ranks` |
| metacache | yes | no taxpasta parser | none, see TP-D5 |

So the cross-profiler tiles compare **10 profilers across 17 profiler / database
combinations**, and the two containment tools and the marker-gene tool sit beside them in
their own collections.

Which template collections a differently configured run would leave empty:

| Data collection | Empty when |
|---|---|
| `taxpasta_profiles`, `taxpasta_matrix`, `taxpasta_embedding`, `taxpasta_presence`, `taxpasta_sample_summary` | `--run_profile_standardisation false`. These five are the only non-optional table collections; without taxpasta there is nothing to standardise and the run has no cross-profiler view at all. |
| `taxon_names` | none of kraken2, krakenuniq or centrifuge ran. The taxpasta tables then keep the `taxid <id>` fallback label instead of a scientific name. |
| `sylph_ani` | `--run_sylph false`. |
| `sylph_profile` | `--run_sylph false`, or sylph ran without a sylph-tax taxonomy so `sylphtax merge` wrote no combined report. |
| `melon_ranks` | `--run_melon false`, or no long-read samples: melon is a nanopore-only marker-gene profiler and taxprofiler only routes long reads to it. |
| `samplesheet`, `database_sheet` | the two input sheets were not placed under `<DATA_ROOT>/input/` (TP-D2). Losing `samplesheet` also costs the persistent sample filter and the platform annotation on every taxpasta collection. |
| `multiqc_data` | `--skip_multiqc`. |

Every one of those is declared `optional: true` except the five taxpasta collections, so a
run with a smaller profiler set ingests cleanly and simply shows fewer tiles.

## Ingestion result: 12 / 12 data collections processed

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/taxprofiler/2.0.1 \
  --data-root ~/Data/depictio-nfcore/taxprofiler/2.0.1/megatest
```

Project `Taxprofiler Metagenomic Profiling`, id `6a9bf3c291d4fed2e13bb581`. `--project-name`
was left off on purpose: the dashboard's `project_tag` is resolved by name, so a renamed
project cannot take a re-imported dashboard later.

Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 18 modules, 41 plots, 80 sample ids | (MultiQC parquet, not Delta) |
| `samplesheet` | 7 | 8 |
| `database_sheet` | 20 | 7 |
| `taxon_names` | 429 | 3 |
| `taxpasta_profiles` | 5652 | 10 |
| `taxpasta_matrix` | 60 | 63 |
| `taxpasta_embedding` | 60 | 8 |
| `taxpasta_presence` | 1871 | 15 |
| `taxpasta_sample_summary` | 60 | 11 |
| `sylph_ani` | 352 | 12 |
| `sylph_profile` | 1811 | 5 |
| `melon_ranks` | 64 | 11 |

All four dashboard tabs imported (`Read QC` + `Profiles` + `Concordance` + `Confidence`,
76 components: 16 cards, 14 MultiQC panels, 14 interactive filters, 13 text tiles, 8 advanced
visualisations, 7 tables, 4 figures). Nothing was dropped.

## Post-ingest tile verification

Every tile was executed or grounded against the Delta frames the run actually wrote:

- **84 bound-column assertions** pass. Every card `column_name`, `breakdown_col` and
  `trend_col`, every interactive `column_name`, every `selection_column`, every
  `row_selection_column`, every `custom_data` entry, every UI-figure axis / colour / symbol /
  size argument and every advanced-visualisation bound column exists in the collection its
  tile is bound to.
- **8 advanced visualisations** expand from their `use:` reference to a viz kind:
  `taxpasta/stacked_taxonomy` and `sylph/stacked_taxonomy` to `stacked_taxonomy`,
  `melon/sunburst` to `sunburst`, `taxpasta/profiler_embedding` to `embedding`,
  `taxpasta/profiler_upset` to `upset_plot`, `taxpasta/concordance_heatmap` to
  `complex_heatmap`, `sylph/ani_dot_plot` and `taxpasta/richness_dot_plot` to `dot_plot`.
- **1 code-mode figure** (the rank-abundance accumulation curve on the Confidence tab)
  executes against the real `taxpasta_profiles` frame and returns a plotly `Figure` with
  60 traces, one per profiling run. The other three figures are `mode: ui` and were checked
  through their `dict_kwargs` columns instead.
- **14 MultiQC tiles** each name a module and a plot that MultiQC's own `list_plots()`
  reports for this run's parquet: fastqc (Sequence Counts, Sequence Quality Histograms),
  fastqc-1 (Sequence Length Distribution), fastp (Filtered Reads), bowtie2 (Single-end
  alignments), samtools (Percent mapped), nanoq (Nanoq Summary), nonpareil (Redundancy
  levels), kraken / bracken / centrifuge / kaiju / metaphlan (Top taxa) and malt
  (Metagenomic Mappability).
- **16 cards** compute a non-null value through `bulk_compute_cards`, the endpoint the React
  viewer calls. Thirteen return a secondary payload with it (four `box_plot_stats`, four
  breakdowns behind a `donut` or a `top_n`, one `composition`, one `uniqueness`, two
  `threshold`); the other three are the `gauge` strips, which the viewer draws from the primary
  value and `coverage_max` and for which the endpoint returns nothing by design. Each tab's
  card row is four `w: 2` cards filling all eight grid columns with four different strips.
- The persistent `Samples` filter was exercised end to end
  (`sample = MOCK_002_Illumina_Hiseq_3000`, sent with every tab's card request the way the
  viewer sends a persistent filter): `filter_applied` is true on all four tabs and 14 of the
  16 card values narrow. The two that do not are genuine coincidences of this run and were
  checked against the frames: `Ranks reported` (`nunique(rank)` = 10) is unchanged because
  every sample carries all ten ranks, and `Widest agreement` (`max(n_profilers)` = 9) is
  unchanged because every Illumina sample already contains a taxon that all nine short-read
  profilers found.
- No FILTER MISMATCH, no 4xx and no 5xx.

### Link coverage

Both the local value-overlap check and the server's own `mapping-preview` endpoint agree:

| Link | Resolver | Source values matched | Target ids reached |
|---|---|---|---|
| `samplesheet.sample` -> `multiqc_data` | `sample_mapping` | 6 / 6 | 20 of 78, see TP-D3 |
| `samplesheet.sample` -> `taxpasta_profiles.sample` | `direct` | 6 / 6 | 6, all 5652 rows reachable |
| `samplesheet.sample` -> `taxpasta_sample_summary.sample` | `direct` | 6 / 6 | 6, all 60 rows reachable |
| `samplesheet.sample` -> `taxpasta_presence.sample` | `direct` | 6 / 6 | 6, all 1871 rows reachable |
| `samplesheet.sample` -> `sylph_ani.sample` | `direct` | 6 / 6 | 6, all 352 rows reachable |
| `taxpasta_embedding.profiler_db` -> `taxpasta_sample_summary.profiler_db` | `direct` | 17 / 17 | 17, all 60 rows reachable |
| `taxpasta_sample_summary.profiler_db` -> `taxpasta_embedding.profiler_db` | `direct` | 17 / 17 | 17, all 60 rows reachable |

The last two are the pair behind the figure / table cross-selection: the PCoA scatter on the
Concordance tab carries `selection_enabled: true` with `selection_column: profiler_db` and
`custom_data: [profiler_db]`, and the pinned per-run table carries
`row_selection_enabled: true` with the same key.

## Decisions

### TP-C1: the taxpasta hub, not one collection per profiler

taxprofiler can run fifteen profilers. Shipping one data collection per profiler would make
the template's shape depend on the run's flags, and every cross-profiler tile would then have
to union an unknown number of collections. Instead `taxpasta/profiles.py` melts every
`taxpasta/*.tsv` into one long profiler x database x sample x taxon frame, and the four
collections after it (`matrix`, `embedding`, `presence`, `sample_summary`) read that hub back
through `dc_ref`. Adding or removing a profiler changes rows, never collections.

### TP-C2: only sylph and melon get their own collections

taxpasta has no parser for sylph, melon or metacache, so those three cannot reach the hub.
sylph and melon each answer a question the read-count profilers cannot (containment ANI, and
genome copies from marker genes), so each got a catalog tool. metacache is a plain abundance
list with no equivalent question, so nothing reads it.

### TP-C3: `taxon_names` is a project-local recipe, not a catalog tool

taxprofiler runs taxpasta with `--add-name false`, so the standardised tables carry NCBI ids
only. The names are recoverable from the kraken-style reports the profilers also write, but
"read three different report layouts back to build a taxid lookup" is a taxprofiler-specific
repair, not a reusable rendering of any one tool's output. It therefore lives at
`depictio/projects/nf-core/taxprofiler/recipes/taxon_names.py` and the catalog stays clean.

### TP-C4: melon rows are pooled across samples

Melon writes one table per sample under `melon/<database>/<sample>_<database>/`, and the
sample id appears only in the path, which the recipe framework does not surface to a recipe.
`melon/ranks.py` therefore sums identical lineages across the long-read samples and
renormalises, giving a pooled community rather than a per-sample one. The tile description
says so, and the per-sample view for every profiler taxpasta does standardise is on the
Profiles tab.

### TP-C5: `taxpasta_matrix` is truncated to the top taxa

The full taxon by run matrix is 428 taxa by 60 profiling runs, which no clustered heatmap
reads usefully. `taxpasta/matrix.py` keeps the 60 taxa with the highest relative abundance
summed over every run, giving a 60-row matrix with the rank as a row annotation and the
profiler and platform of each column serialised as heatmap column strips.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, quality, GC, length, adapters | **MultiQC** (`use: multiqc/fastqc`, `use: multiqc/fastp`), 4 tiles |
| Host-genome removal | **MultiQC** (`use: multiqc/bowtie2`, `use: multiqc/samtools`), 2 tiles |
| Long-read stats and coverage redundancy | **MultiQC** (`use: multiqc/nanoq`, `use: multiqc/nonpareil`), 2 tiles |
| Each classifier's own top taxa | **MultiQC** (`use: multiqc/kraken`, `bracken`, `centrifuge`, `kaiju`, `metaphlan`; MALT untagged), 6 tiles |
| Cross-profiler composition, concordance, ordination, overlap | **Dedicated** (`taxpasta/*`): MultiQC renders each classifier in isolation and has no cross-classifier view at all |
| Containment ANI and coverage | **Dedicated** (`sylph/ani`): MultiQC has no sylph module |
| Genome-copy composition | **Dedicated** (`melon/ranks`): MultiQC has no melon module |

Six `multiqc/<module>.yaml` entries were new and were added in the shape of
`multiqc/fastqc.yaml`: `bracken`, `centrifuge`, `kaiju`, `metaphlan`, `nanoq`, `nonpareil`.
`kraken`, `fastqc`, `fastp`, `bowtie2` and `samtools` already existed and were used as is.

## Discrepancies

### TP-D1: ganon ran, taxpasta standardised it, and every count is zero

`taxpasta/ganon_ganon-db.tsv` is a 326-row table whose three sample columns sum to zero.
ganon assigned nothing to the three Illumina samples it was given in this megatest.
`taxpasta/profiles.py` drops zero-count rows, which is correct behaviour for a long profile
frame, so ganon simply has no rows anywhere in the dashboard and does not appear in the 10
profilers the concordance tiles compare. Nothing in the template is wrong; a run where ganon
does assign reads picks it up with no change.

### TP-D2: taxprofiler never copies its input sheets into the results tree

`params.json` records `input` and `databases` as public nf-core test-datasets URLs, and the
pipeline does not publish either file under `outdir`. The `samplesheet` and `database_sheet`
data collections therefore read `<DATA_ROOT>/input/`, which the megatest fetch alone does not
create: `scripts/nfcore_megatest.py` mirrors S3 keys and has no notion of an input URL.

`download_test_data.sh` was extended to curl both sheets into `<DATA_ROOT>/input/` after the
S3 fetch, so the wrapper now matches what `megatest.yaml`'s `post_fetch_help` already claimed.
Byte-identical copies also ship in the template's own `input/` directory, and both were
checked against the upstream URLs during this validation. Without that step, `samplesheet` and
`database_sheet` are skipped (both are `optional: true`), which costs the persistent sample
filter, the platform annotation on the taxpasta collections and two reference tables.

### TP-D3: the persistent sample filter reaches 20 of 78 MultiQC sample ids

`build_sample_mapping` derives a canonical id by stripping an optional `_1` / `_2` suffix and
an optional ` - <annotation>` tail. taxprofiler's MultiQC sample ids for the profiler panels
carry a database suffix instead (`MOCK_001_Illumina_Hiseq_3000_kraken2-db`,
`..._bracken-db.bracken`, `..._kaiju-db1.kaiju`, `..._metaphlan3-db.metaphlan_profile`,
`..._motus-db1`, `..._diamond-db1`), and the pre-trimming FastQC series carries a `_raw`
segment. Those do not reduce to the samplesheet's sample id, so the server's own
`mapping-preview` reports 6 / 6 source values matched but 58 orphan targets out of the 78 ids
in the aggregated mapping: the filter narrows the fastp and post-trimming FastQC panels and
leaves the six profiler top-taxa panels, the raw FastQC series and the three porechop_abi
general-statistics rows untouched. Those last three are keyed on the ENA run accession of the
nanopore FASTQ (`ERR9765780` to `ERR9765782`) rather than on the taxprofiler sample name, so
no samplesheet value can reach them at all.

This is not fixable from the template. The `regex` and `wildcard` resolvers would match the
whole prefix family, but `resolve_link` in
`depictio/api/v1/endpoints/links_endpoints/routes.py` passes `target_known_values=None`
unconditionally, so both fall back to passing the source values through unchanged, which is
strictly worse than `sample_mapping`. Only `mapping-preview` supplies the target values. The
template therefore keeps `sample_mapping`, and the tiles that stay unfiltered are exactly the
per-profiler panels the Profiles and Concordance tabs already cover from the taxpasta hub,
where the filter does apply.

### TP-D4: bracken and centrifuge are the `kraken` MultiQC module under two aliases

MultiQC 1.35 has no Bracken module and no Centrifuge module. nf-core/taxprofiler runs the
`kraken` module three times, split by `module_order` + `path_filters` in its own MultiQC
config, so the report carries `kraken`, `bracken` and `centrifuge` as three anchors of one
module. Both `multiqc/bracken.yaml` and `multiqc/centrifuge.yaml` therefore find kraken-style
report files (`*.bracken.kraken2.report.txt`, `*.centrifuge.txt`), not the tools' native
tables, which MultiQC does not read at all. The consequence for the conformance stubs is in
the final report: the six stub builders only produce all six modules when a
`multiqc_config.yaml` with that `module_order` sits next to them; without it, bracken and
centrifuge collapse back into `kraken` and only four of the six modules appear.

### TP-D5: metacache has no data collection

metacache ran on the three nanopore samples and wrote `*.abundances.txt`. taxpasta has no
metacache parser, MultiQC has no metacache module, and the file is a flat taxon / abundance
list that adds nothing the taxpasta hub does not already carry for ten other profilers. The
manifest still fetches it (3 small files) so a future collection has the data locally, but
nothing reads it today.

### TP-D6: the MALT and `fastqc-1` tiles carry no catalog badge

`multiqc/malt.yaml` does not exist and was not created: MALT is not an nf-core module with a
MultiQC entry that any other pipeline in this repo needs, and adding a catalog folder for one
tile in one template is the kind of single-use entry the catalog conventions warn against.
`fastqc-1` is MultiQC's own id for taxprofiler's second FastQC invocation, not a module, so it
has no catalog entry either. Both tiles resolve and render; they just show no `use:` badge.
The template's MultiQC data collection lists both `fastqc` and `fastqc-1` so a run with a
single FastQC invocation still binds.

### TP-D7: the main dashboard title was renamed after the first ingest

The first validated ingest titled the main dashboard `Taxprofiler metagenomic profiling`,
while every other nf-core template in the repo titles its main dashboard `nf-core/<pipeline>`.
`dashboards/base.yaml` now says `nf-core/taxprofiler`. Because `--overwrite` matches an
existing dashboard by title, the rename cannot overwrite in place: the old family was deleted
(`DELETE /dashboards/delete/<id>`, which cascades to the three child tabs) and re-imported with
`depictio dashboard import`. The project name in `template.yaml` was deliberately left as
`Taxprofiler Metagenomic Profiling`, because the dashboard's `project_tag` is resolved by name
and the two must stay consistent. Post-rename family: `6a9c2cbe30851b3fe171814b` (main, 31
components) plus `Profiles` (17), `Concordance` (14) and `Confidence` (14).
