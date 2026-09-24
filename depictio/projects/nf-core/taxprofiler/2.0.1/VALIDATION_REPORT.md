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
  card row was four `w: 2` cards filling all eight grid columns with four different strips;
  one of the sixteen is no longer shipped and the rows were repacked afterwards, see TP-C6.
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

### TP-C6: the tab named MultiQC carries MultiQC panels only

The main tab is called `MultiQC`, so it ships the panels MultiQC drew and nothing else,
alongside the text tiles and the two pinned sections every tab carries by design. The four
run-level cards each moved to the data they are computed from:

- `Samples` reads the samplesheet, so it moved into the pinned `Sample sheet` section, above
  the sheet itself. Tables span all eight columns (TP-C7), so nothing can sit beside one, and
  a single `w: 2` card in an otherwise empty row is a hole rather than a layout: the card takes
  the full width of its own row. The section is `persistent: true, pin: top`, so the sample
  count and its per-platform donut still open every tab.
- `Profiling runs` and `Evenness` read `taxpasta_sample_summary`, the hub the Profiles tab is
  built on, so they joined that tab's `Composition` card grid. `Profiling runs` heads the
  existing row of four `w: 2` cards, which is where a reader asks how many runs the bars stand
  for, and `Evenness` sits beside `Most dominant taxon` in a second row of two `w: 4` cards:
  the gauge and the threshold are the two readings of how concentrated a community is. Both
  rows fill all eight columns. Their icons and colours were changed to stay distinct from the
  cards they now sit next to, using ids this file already ships.
- `Taxa per run` was deleted rather than moved. `Composition` already carries `Distinct taxa`
  over the same profiles, and two cards counting taxa in one section is a repetition rather
  than a second reading. Dropping it is also what makes both destination rows come out full.

`Run at a glance` held nothing else once the cards left, so the section is gone rather than
left as a heading over an intro: a declared section with no tiles renders as an empty box. Its
framing moved into the `Read quality` intro, which now opens the tab by saying that every
classifier ran over the same reads and that the tabs after it compare what they made of them.
The tab therefore opens on the general-statistics table under that intro.

One consequence is recorded rather than fixed: the `Read stats` filter section (taxa observed,
Shannon) is on the main tab and is not persistent, so it now narrows only the per-run table in
the pinned `Reference tables` section, and the two cards it used to move sit on a tab whose
left panel filters `taxpasta_profiles` instead. Making that section persistent would put a
`taxpasta_sample_summary` filter on every request of every tab, which is a wider change than
this one and is not made here.

The file now ships 75 components: 15 MultiQC panels, 15 cards, 14 interactive filters, 12 text
tiles, 8 advanced visualisations, 7 tables and 4 figures. Against the 76 recorded above that is
the general-statistics panel added after this ingest, less the deleted card and the folded-away
intro. No data collection, column binding or link changed, so the run was not replayed.

### TP-C7: the containment table spans the grid

`sylph containment table` shared a row with the ANI scatter, each at `w: 4`. AG Grid keeps its
columns at their natural width and scrolls horizontally, so a half-width table showed two of
its twelve columns and spent part of its height on a scrollbar. Both tiles now own a full-width
row in the order they already had, the scatter first and the table under it, with the four
containment cards after them. Every table in this file is `w: 8`, which
`test_tables_are_full_width` now enforces repo-wide.

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

---

# Remediation pass, 2026-09-22

**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2` (`feat/nfcore-templates-lot2`, PR #1102)
**Validator:** `uv run python -m depictio.cli` against the lot 2 docker stack
(API `:8112`, viewer `:5612`, Mongo `:27112`,
config `~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml`).

## What the audit found, and what changed

| Finding | Fix |
|---|---|
| `Samples` was `persistent: true` with no `pin`, so it stayed on the landing tab | `pin: top` added; the section now rides every tab |
| `database_sheet`, `melon_ranks`, `sylph_profile`, `taxpasta_matrix` were orphans: no `links:` reached them, so no filter applied | four new links (see below), except `melon_ranks`, which genuinely cannot take one (TP-D8) |
| No glance strip: the only two cards were both broken down by `instrument_platform` and sat inside a collapsed section | a persistent pinned `Run at a glance` section of four cards, four different shapes; the duplicate `Sequencing runs` card is gone (its reading is now the `Sequencing run` slider) |
| Tabs carried no tab-local filter section | every tab declares one on its own columns |
| No diversity section although `shannon` was already ingested | a new `Depth and diversity` tab with `Coverage redundancy` and `Alpha diversity` |
| `nonpareil/nonpareil_all_samples.tsv` was fetched and never read | a new `nonpareil` catalog module with two outputs |

### New links in `template.yaml`

| Source | Target | Resolver | Why |
|---|---|---|---|
| `samplesheet.sample` | `taxpasta_lineage.sample` | direct | the new hierarchy collection |
| `samplesheet.sample` | `sylph_profile.sample_id` | direct | sylph's merged profile names its samples `sample_id`, not `sample`, which is why the persistent filter used to stop at the containment table |
| `samplesheet.sample` | `nonpareil_summary.sample`, `nonpareil_curves.sample` | direct | the Nonpareil collections |
| `taxpasta_profiles.database` | `database_sheet.db_name` | direct | no sample column exists on the sheet; the profiling scope is what can narrow it |
| `taxpasta_profiles.name` | `taxpasta_matrix.taxon` | direct | the matrix is wide, its columns are the runs; its rows are taxa, which is what the profile filters select |

### New content

* **`depictio/catalog/nonpareil/`** (new module): `summary` (one row per sequencing library:
  redundancy, coverage, effort sequenced, effort projected for 95 percent coverage, diversity
  index, and the derived depth multiple) and `curves` (the coverage curve that library's fitted
  model describes, 200 points per series, bound to the `profile` kind).
* **`depictio/recipes/lib/nonpareil.py`**: the arithmetic behind the curve. See TP-D9.
* **`depictio/catalog/taxpasta/lineage.{yaml,py,tsv}`**: the hub rows with the seven NCBI ranks
  widened into their own columns, ancestry recovered from the indented kraken2 / krakenuniq
  reports. Binds `sunburst` (Profiles / `Lineage rings`) and `sankey` (Concordance /
  `Taxonomic flow`, root to species with the unclassified branch as its own flow).
* **`taxpasta/sample_summary.yaml`**: two renders added, an `assigned_count` box-plot card and
  a top-taxon-share bar figure.
* **Five tabs** instead of four: MultiQC, Depth and diversity, Profiles, Concordance,
  Confidence. Every tab opens with a four-card strip (`w: 2`, `h: 2`, x 0/2/4/6) and carries a
  non-persistent filter section on its own columns, on top of the pinned `Samples` section.

## Commands run

```bash
uv run pytest depictio/tests/recipes/test_nonpareil_curves.py -q          # 10 passed
uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k taxprofiler
                                                                          # 10 passed
uv run pytest depictio/tests/models/test_catalog.py -q                    # 93 passed, 6 failed
#   the six failures name cellbender / kallisto / qcatch / simpleaf / cooltools / gtdbtk /
#   funcscan and the two regenerated JSON schemas: other agents' half-written dirs on the
#   same branch, none of them nonpareil or taxpasta.
uv run python -m depictio.cli run --template nf-core/taxprofiler/2.0.1 \
  --data-root ~/Data/depictio-nfcore/taxprofiler/2.0.1/megatest --dry-run  # 8/8 steps
uv run ruff format <new .py> && uv run ruff check <new .py>                # clean
```

## Ingestion result: 15 / 15 data collections processed

Project `Taxprofiler Metagenomic Profiling`, id `6ab2aa1a15d579800f73d51b`; dashboard family
`6ab2aa40fbe776a1a573e26f`. Row counts read back from
`GET /depictio/api/v1/deltatables/shape/{dc_id}`:

| Data collection | Rows | Columns |
|---|---|---|
| `samplesheet` | 7 | 8 |
| `database_sheet` | 20 | 7 |
| `taxon_names` | 429 | 3 |
| `taxpasta_profiles` | 5652 | 10 |
| `taxpasta_lineage` | 5652 | 18 |
| `taxpasta_matrix` | 60 | 63 |
| `taxpasta_embedding` | 60 | 8 |
| `taxpasta_presence` | 1871 | 15 |
| `taxpasta_sample_summary` | 60 | 11 |
| `sylph_ani` | 352 | 12 |
| `sylph_profile` | 1811 | 5 |
| `melon_ranks` | 64 | 11 |
| `nonpareil_summary` | 4 | 10 |
| `nonpareil_curves` | 800 | 8 |
| `multiqc_data` | MultiQC report, no Delta table | 1 report |

Screenshots, one per tab, viewport 1600x1000, written to
`/tmp/claude-502/shots-taxprofiler/{0-multiqc,1-depth-diversity,2-profiles,3-concordance,4-confidence}.png`.
Only `0-multiqc.png` shows the dashboard. The four other tabs each hold at least one
advanced visualisation, and on the day of this pass the lot 2 dev viewer could not load the
advanced visualisation chunk at all, so those four captures show the viewer error card
instead of the tiles (TP-D13). The dashboards themselves were validated through the API.

| Tab | Dashboard id | Title |
|---|---|---|
| 0 | `6ab2aa40fbe776a1a573e26f` | MultiQC (main tab) |
| 1 | `6ab2aa40fbe776a1a573e270` | Depth and diversity |
| 2 | `6ab2aa40fbe776a1a573e271` | Profiles |
| 3 | `6ab2aa40fbe776a1a573e272` | Concordance |
| 4 | `6ab2aa40fbe776a1a573e273` | Confidence |

## New discrepancies

### TP-D8: `melon_ranks` cannot be linked to the sample scope

Melon writes one table per sample under `melon/<database>/<sample>_<database>/`, and the
sample id lives only in that path. `melon/ranks.py` reads the glob without
`include_file_paths`, so the rows arrive pooled and the collection has no sample, library or
run column for a link to resolve against. A `samplesheet.sample` link would therefore either
match nothing or, worse, silently empty the Genome copies section whenever a short-read-only
classifier is selected, so none was added. The section instead declares its own `Melon phylum`
filter in `Profile scope`, which is the only control that reaches it, and the section's text
tile says so. Making melon per-sample is a one-line change to a recipe this template does not
own (`read_kwargs={"include_file_paths": "source_path"}` plus the sample recovery
`taxpasta/profiles.py` already does); it is reported rather than made here.

### TP-D9: the Nonpareil curve is reconstructed from the summary, not read from a `.npo`

`NONPAREIL_SET` merges the per-library `.npo` files into `nonpareil_all_samples.tsv`, six
fitted numbers per library, and nf-core/taxprofiler does not publish the `.npo` files
themselves, so the per-effort redundancy samples are not on disk. The curve is therefore
rebuilt from Nonpareil's own model: coverage against sequencing effort is the CDF of a gamma
distribution on `ln(effort)`, whose mean is the published `diversity` (Nd) and whose 95th
percentile is `ln(LRstar)`. Two equations, two unknowns; `depictio/recipes/lib/nonpareil.py`
solves them and samples the result over a log-spaced effort axis.

The check that this is a reconstruction and not an invention is the third number, `C`, which
the fit never sees: evaluating the fitted model at each library's own `LR` reproduces the
published coverage to +0.024, +0.027, +0.032 and +0.043 absolute. The sign is the expected
one, because `C` is the last coverage actually observed and the model is the smooth curve
fitted through it. `depictio/tests/recipes/test_nonpareil_curves.py` pins all of this against
the real megatest rows. The incomplete gamma is written out (series plus continued fraction)
rather than imported from scipy, which reaches the environment only as a transitive
dependency of `umap-learn`.

Consequence for the tile: only the four Illumina libraries appear. taxprofiler routes
Nonpareil at short reads only, so the three nanopore samples have no curve, and `MOCK_003`
contributes two curves because it was sequenced over two runs.

### TP-D10: 6 percent of the hub rows have no lineage, and all of kmcp's do

`taxpasta/lineage.py` recovers ancestry by walking the indentation of the kraken2 and
krakenuniq reports, then joins it onto the hub by NCBI taxonomy id. Measured on this run:
5268 of 5652 rows (93.2 percent) get a lineage, 51 are the profilers' explicit `unclassified`
rows (taxonomy id 0) and 333 resolve to `unresolved`. Per profiler the unresolved share is 0
for bracken, kaiju and krakenuniq, under 1 percent for centrifuge and kraken2, 2 to 11 percent
for megan6, diamond, metaphlan and mOTUs, and **100 percent for kmcp**, whose database is
keyed on identifiers no kraken-style report in the run names. The three fills are kept
distinct on purpose (`unclassified` for reads no taxon was assigned, `unresolved` for a taxon
no report placed, nearest-known-ancestor carried forward for a gap inside an otherwise known
lineage) so the rings and the flow do not pool three different kinds of absence into one arc.

### TP-D11: `megatest.yaml` still says twelve profiler / database combinations

The header comment of `megatest.yaml` describes the run as "12 profiler x database
combinations". The database sheet declares 20, taxpasta writes 18 tables and 17 of them carry
rows (ganon's are all zero, TP-D1). The keys themselves are correct and fetch everything the
template reads, including `nonpareil/nonpareil_all_samples.tsv`, so the file was left alone
under the "only when the keys change" rule; the comment is wrong and should be corrected in a
pass that is allowed to touch it.

### TP-D12: the landing tab's tab-local filter section reads a taxpasta collection

Every other tab's non-persistent filter section is declared on that tab's own data
collections. The MultiQC landing tab cannot do the same: its own collection is
`multiqc_data`, a MultiQC-type collection that hosts no `interactive` component, so its
`Read stats` section filters `taxpasta_sample_summary` instead. The section is still
tab-local and still non-persistent; it just narrows the run set rather than the MultiQC
panels, which the `Samples` section already reaches through the `sample_mapping` link.

### TP-D13: four of the five tab screenshots could not be taken

The lot 2 dev viewer answered every dashboard that holds an advanced visualisation with
"Viewer crashed: Failed to fetch dynamically imported module". The lazy advanced visualisation
chunk imports the GenomeSpy renderer, and the viewer process could not resolve
`@genome-spy/core/genome/genomes.js`, a dependency added to the repository after that process
had started. It is an environment state, not a template defect: nothing in this template
references GenomeSpy, the landing tab renders, and every collection the four tabs bind was
verified through the API instead. The four captures should be retaken once the viewer is
rebuilt, against the dashboard ids listed above.

## 2026-09-22 review fixes

MultiQC scan regex brought to the mandated form
(`(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$`) and the database sheet
pattern un-anchored from `input/` (`(?:.*/)?database.*\.csv$`, description reworded).
Not done: a `samplesheet -> melon_ranks` link. The melon recipe pools the long-read samples
and emits no sample column (the sample name lives only in the file path), so there is no
target field to link on; the tile intro already says the sample scope stops there. Adding
one would need a catalog recipe change outside this template.

## 2026-09-23: wave 2b (Krona rings per classifier, header controls, histograms)

What changed (dashboard only):

- Profiles, `Lineage rings`: new tile `tp-av-krona-profiler`, the Krona reading of the
  lineage table. Same render (`taxpasta/lineage_sunburst`) with `rank_cols` overridden to
  `[profiler, superkingdom, ..., species]`, so the innermost ring is one wedge per
  classifier; phyla keep one colour across wedges. `controls_placement: header` puts the
  ring window pickers on the tile. The lineage table moves down to y 20.
- `controls_placement: header` on both stacked taxonomy panels (rank, sort, top-N,
  normalise), the profiler PCoA and the two dot plots.
- `show_histogram: true` on 11 threshold sliders (not on the sequencing-run slider, which
  is an identifier).

Discrepancies:

- TP-D14: a wedge's width is the number of profiling runs the classifier made (each run's
  relative abundances sum to one), so classifiers that ran on fewer samples draw narrower
  wedges. Documented in the tile description rather than renormalised.

Commands and results:

| command | result |
| --- | --- |
| `uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py -k taxprofiler` | 10 passed |
| `depictio.cli run --template nf-core/taxprofiler/2.0.1 ... --dry-run` | 8/8 steps |
| delete + re-ingest | project `6ab3c9f1ac5a3f0e26e7bf89`, dashboard `6ab3ca0be8b8ace33d32c77e`; 14/14 table DCs have rows (taxpasta_lineage 5,652) |
| Playwright, 1600x1000 | `/tmp/claude-502/shots-taxprofiler/` (tabs + `verify-profiles-0.png`, Krona with wedges for kaiju, diamond, motus, ...) |

# Wave 3 (family rework, 2026-09-23)

Source: `_reviews_wave3/review-metagenomics.md` and the consolidated review. Offline only
(no ingest, no live check).

## What changed

- **Composition bars, one per profiling run.** `catalog/taxpasta/profiles.yaml` now maps the
  stacked render's `sample_id` role to `profiler_db`, so `tp-av-stacked` draws one bar per
  classifier and database instead of pooling every classifier into one bar per sample (which
  mixed naming vocabularies). Family defaults: `default_rank: genus`, `top_n: 12`,
  `sort_by: abundance`, percentages; the platform strip became a classifier strip (constant
  within a bar). `tp-comp-intro` rewritten to match.
- **Links.** Added `taxpasta_profiles.profiler -> taxpasta_lineage.profiler`,
  `taxpasta_profiles.database -> taxpasta_lineage.database` (Profiles filters reach the Krona
  rings), `samplesheet.sample -> taxpasta_embedding.sample` and
  `taxpasta_embedding.profiler_db -> taxpasta_lineage.profiler_db` (the lasso reaches the
  taxonomic flow). The embedding's `sample_id` is the composite `sample | profiler / database`,
  so the sample link targets its plain `sample` column.
- **Ordination.** `tp-av-pcoa` carries `selection_enabled: true, selection_column: profiler_db`;
  the duplicate `tp-fig-pcoa-select` was removed.
- **Removed duplicates.** `tp-av-lineage-sunburst` (Krona kept), the second 4-card strip
  `tp-lin-card-*`, `tp-comp-card-runs` and `tp-div-card-runs` (both repeated the glance card),
  the `Read stats` filter section and its two sliders, `tp-filter-rank` (header picker only).
- **Confidence = sylph only.** `Profile shape` dissolved: `tp-av-richness-dot` moved to Alpha
  diversity, `tp-fig-top-share` and `tp-filter-top-share` removed. `tp-card-containment`
  (average of a fraction) replaced by `tp-card-low-ani`, genomes below 95 percent adjusted ANI.
- **Cards.** Shannon, evenness and Nonpareil coverage are medians with box plots (no gauge max 6,
  no 0.6/0.4 thresholds, no average of a fraction). `tp-card-shared-frac` lost its
  `coverage_max: 12` gauge (plain value). New `tp-comp-card-species` (species named, top_n by
  classifier, `filter_expr` on rank) and `tp-div-card-top-share`.
- **Tables.** Pinned tables are now the samplesheet (top) and the database sheet (bottom). The
  per-run statistics and Nonpareil tables close Depth and diversity (`Depth tables`, collapsed);
  the profiles, lineage and sylph clade tables close Profiles (`Profile tables`, collapsed).
- **Sequencing run filter.** `tp-filter-run` is a MultiSelect on `object`; the samplesheet is
  read with `polars_kwargs: {infer_schema_length: 0}` so accessions stay strings.
- **Texts.** Intros at most 2 to 3 short sentences, no "mock", no counts, no run claims;
  `tp-qc-general-stats` description is one generic sentence. `advanced_viz_controls: header`
  on every tab. Melon sunburst uses `tab20` + `colour_by_rank: phylum`.
- **Lint.** `forbidden_terms` added to `megatest.yaml`; all convention rules pass.

## Still open

- `tp-av-lineage-sankey` row badge "5,000 rows" for 5,652 (P25, platform): not verified here.
- `tp-qc-general-stats` live height (204 px vs YAML `h: 5`): not re-checked live.
- Live behaviour of the new links and the PCoA lasso (selection on `profiler_db` narrowing the
  sankey) is unverified until the main session re-ingests the project.
- Melon still cannot take the sample filter (no sample column in its pooled output).
