# nf-core/atacseq 2.1.2: template validation report

**Dates:** 2026-09-14 (port of the 1.2.2 template to 2.1.2), 2026-10-09 (templates v2: dashboard
rebuilt on `depictio/projects/nf-core/RULES.md`, collections brought level with the current
1.2.2 template)
**Scope:** offline checks only: recipe execution against local copies of EMBL HPC runs, link
replay, MultiQC tile pruning and rendering, `dashboard validate --offline` and the template
unit tests. **No ingest was run**, so nothing here was read back from Delta, rendered by the
API or imported into a live dashboard.

## Data used

No usable AWS megatest exists for 2.x: the 2.1.2 and 2.1.1 release prefixes each hold a
single 12 GB object (see `megatest.yaml` and `depictio/projects/nf-core/MEGATEST_STATUS.md`).
The template was validated on EMBL HPC runs made with `scripts/nfcore_validation_hpc.py`
(keys `atacseq2-*`), copied to `~/Data/depictio-nfcore/atacseq/2.1.2/`:

| Tree | Run | Libraries |
|---|---|---|
| `test` | `test` profile, bwa | 6 merged libraries of one yeast time course, 3 paired-end and 3 single-end |
| `test_bowtie2` | `test`, `--aligner bowtie2` | same 6 |
| `test_chromap` | `test`, `--aligner chromap` | same 6 |
| `test_star` | `test`, `--aligner star` | same 6 |
| `test_controls` | `test_controls` profile, bwa | 4 libraries called against 2 input controls |
| `test_full` | `test_full` megatest profile, bwa, hg19 | 6 human libraries, three transposition protocols of two replicates, paired-end |

Every run used the release's MultiQC 1.13, which writes no parquet, so each local tree
carries a report regenerated with `python -m depictio.dev_scripts.multiqc_reprocess` at
`multiqc/multiqc_data/multiqc.parquet`. Separately, the `test` run was resumed on the cluster
with MultiQC 1.35 swapped in and the pipeline's own `multiqc_config.yml`; its
`multiqc/broad_peak/multiqc_data/` was copied to
`~/Data/depictio-nfcore/_mqc135/atacseq-2.1.2-test/multiqc_data/`. That is the report the
Nextflow completion trigger ingests.

No tree holds a preseq curve: 2.x skips preseq by default.

## 1.x to 2.x layout

| 1.2.2 | 2.1.2 |
|---|---|
| `pipeline_info/design_reads.csv` | `pipeline_info/samplesheet.valid.csv` |
| `pipeline_info/software_versions.csv` | `pipeline_info/software_versions.yml` |
| `bwa/mergedLibrary/` | `ALIGNER/merged_library/` (bwa, bowtie2, chromap, star) |
| `bwa/mergedReplicate/` | `ALIGNER/merged_replicate/` |
| `bwa/mergedLibrary/macs/broadPeak/` | `ALIGNER/merged_library/macs2/broad_peak/` |
| peak QC summary `*peak.summary.txt` | `macs2/broad_peak/qc/macs2_peak.mLb.clN.summary.txt` |
| consensus under `macs/broadPeak/consensus/` | `macs2/broad_peak/consensus/consensus_peaks.mLb.clN.boolean.txt` |
| DESeq2 contrasts `*.deseq2.results.txt` | not published (removed in 2.0) |
| DESeq2 QC `*.pca.vals_mqc.tsv` only | `consensus/deseq2/*.pca.vals.txt` and `*.sample.dists.txt`, plus the `_mqc.tsv` copies |
| ataqv reports under `bwa/mergedLibrary/` | `ALIGNER/merged_library/ataqv/broad_peak/*.ataqv.json` |
| deepTools under `bwa/mergedLibrary/` | `ALIGNER/merged_library/deeptools/plotfingerprint/`, `plotprofile/` |
| preseq `*.ccurve.txt` | `ALIGNER/merged_library/preseq/*.lc_extrap.txt` (only with `--skip_preseq false`) |
| Picard MarkDuplicates under `bwa/mergedLibrary/picard_metrics/` | `ALIGNER/merged_library/picard_metrics/*.mLb.mkD.sorted.MarkDuplicates.metrics.txt` |
| `trim_galore/` | `trimgalore/` |
| `multiqc/broadPeak/multiqc_data/` (MultiQC 1.9) | `multiqc/broad_peak/multiqc_data/` (MultiQC 1.13, or 1.35 when swapped in) |
| no `params.json` | no `params.json` |

Every key of `megatest.yaml` matches at least one file of the `test_full` tree (re-checked
2026-10-09, including the two DESeq2 QC keys added then).

## Template

### Carried over from the current 1.2.2 template (2026-10-09)

The September port started from an older 1.2.2 `template.yaml`. Every 1.x change made since
was diffed (`diff -u` of the September-era 1.2.2 against the current one) and carried over
where 2.x has the data:

| 1.2.2 change | 2.1.2 |
|---|---|
| Header calls `depictio ingest` | carried |
| `GENOME` variable (default `hg38`), `reference.vars: {GENOME: hg19}` | carried; the megatest profile aligns to hg19 |
| `replicate_label` hub column, recipe on `input_schema` / `OUTPUT_SCHEMA` | carried (`REP1`, `REP2`, ... in 2.x) |
| Shared MultiQC scan pattern `(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$` | carried; it matches both 2.x parquet locations |
| `median_fragment_length` described on `ataqv_metrics` | carried |
| HOMER override starts with `**/` (any aligner) | already so in 2.1.2 |
| `design_reads` scan collection and its sample-mapping link to MultiQC | carried as `samplesheet` on `samplesheet.valid.csv` |
| Optional `deseq2_qc_pca` / `deseq2_qc_sample_dists` and their hub links | carried, repointed at the 2.x plain-text tables |
| Region links from the broad calls to the consensus and HOMER tables | carried |
| AT-D26 note on the `peak_id` link (range filters travel as a span) | carried |
| Wildcard group link to `deseq2_results` | skipped: 2.x publishes no contrasts |
| narrowPeak note | kept as a one-line pointer to the 1.2.2 reason |

### Collections

21 collections (16 in September). Against the September port: `samplesheet`, `picard_markduplicates_metrics_raw`,
`picard_markduplicates_metrics`, `deseq2_qc_pca` and `deseq2_qc_sample_dists` were added, and
`macs2_peak_summary` moved to a version recipe. Order respects `dc_ref` (raw scans before the
recipes that read them; `test_template_dc_order.py` passes).

- **Hub.** `recipes/sample_design.py` reads `samplesheet.valid.csv`: it strips the `_T<n>`
  technical-replicate suffix, derives group and replicate from `<group>_REP<n>`, coalesces
  the `control` columns (the 2.1.2 validator writes that header twice on the control route,
  the first copy empty, which the reader keeps as `control` and `control_duplicated_0`), sets
  `role`, reports `read_type` and counts the libraries merged into each sample. Its output
  schema starts with the 1.x columns, `replicate_label` included.
- **Peak QC summary (version recipe).** `recipes/peak_summary.py` replaces the catalog's
  `macs2/peak_summary` (AT2-D7). Same output schema; it keys the table on the bare sample, so
  the hub links it on `sample`, no longer on `merged_library`.
- **Picard.** MarkDuplicates runs on every merged library whatever the aligner, so it gives
  the Signal tab a complexity reading on every route (preseq is off by default). The raw scan
  takes the merged-library reports only (`.*\.mLb\.mkD\.sorted\.MarkDuplicates\.metrics\.txt$`).
  The catalog recipe names the library after the report (`<sample>.mLb.mkD.sorted`), so the
  hub reaches it with a `pattern` link, `{sample}.mLb.mkD.sorted` (AT2-D8).
- **DESeq2 QC.** The plain `*.pca.vals.txt` and `*.sample.dists.txt` of the merged-library
  consensus. Optional: `--skip_deseq2_qc` and designs without replicated groups skip them.
- **preseq.** Both collections optional and unvalidated on 2.x data; the curve's sample id
  (`<sample>.mLb.mkD.lc_extrap.txt`) strips to the hub's `sample` with `strip_stage_suffixes`.
- **Source overrides.** Unchanged from September: the peak, HOMER and consensus globs are
  pinned to the merged-library files, because the catalog globs also match the
  merged-replicate copy of the peak tree.

## Results

### Recipes with the template's own overrides

Every transformed collection was executed through `depictio.recipes.execute_recipe` with the
`source_overrides` of `template.yaml`, scan collections emulated with their regex and
`polars_kwargs`. Rows per tree, no merged-replicate file matched by any glob:

| Collection | `test` | `test_controls` | `test_bowtie2` | `test_chromap` | `test_star` | `test_full` |
|---|---|---|---|---|---|---|
| `sample_design` | 6 | 6 | 6 | 6 | 6 | 6 |
| `samplesheet` (scan) | 8 | 6 | 8 | 8 | 8 | 6 |
| `ataqv_metrics` | 6 | 6 | 6 | 6 | 6 | 6 |
| `ataqv_fragment_length` | 6,006 | 6,006 | 6,006 | 6,006 | 6,006 | 6,006 |
| `ataqv_tss_coverage` | 12,006 | 12,006 | 12,006 | 12,006 | 12,006 | 12,006 |
| `ataqv_chromosome_counts` | 48 (3 samples) | 96 | 48 (3 samples) | 48 (3 samples) | 48 (3 samples) | 132 |
| `picard_markduplicates_metrics` | 8 | 6 | 8 | 6 | 6 | 6 |
| `deeptools_fingerprint_metrics` | 6 | 6 | 6 | 6 | 6 | 6 |
| `deeptools_plot_profile` | 4,200 | 4,200 | 4,200 | 4,200 | 4,200 | 4,200 |
| `macs2_peak_summary` | 6 | 6 | 6 | 6 | 6 | 6 |
| `macs2_broad_peaks` | 6,183 | 3,505 | 5,060 | 6,064 | 5,765 | 224,140 |
| `homer_annotated_peaks` | 6,183 | 3,505 | 5,060 | 6,064 | 5,765 | 224,140 |
| `homer_tss_distance_profile` | 107 | 71 | 107 | 98 | 110 | 482 |
| `macs2_consensus_boolean` | 1,902 | 1,566 | 1,521 | 1,865 | 1,790 | 104,659 |
| `macs2_consensus_fc` | 250 | 250 | 250 | 250 | 250 | 250 |
| `deseq2_qc_pca` | 6 | 6 | 6 | 6 | 6 | 6 |
| `deseq2_qc_sample_dists` | 6 | 6 | 6 | 6 | 6 | 6 |

`frip_score` is now filled on every row of every tree (it was null on all of them in
September, AT2-D7). On the `test` trees Picard writes two rows for the samples merged from
two sequencing libraries (8 rows, 6 samples), and `estimated_library_size` is null on the
single-end rows (4 of 8 on `test` and `test_bowtie2`, 3 of 6 on `test_chromap` and
`test_star`). The ataqv metrics of the three single-end libraries carry no TSS enrichment,
reads-in-peaks or fragment-length values (AT2-D2). `preseq_complexity_curve` was not run: no
tree holds a curve.

### Links replayed as joins

On every tree, `sample_design.sample` reaches 6 / 6 samples of the ataqv, deepTools,
`macs2_peak_summary` and DESeq2 QC collections, and through `{sample}.mLb.mkD.sorted` 6 / 6
of `picard_markduplicates_metrics`; `sample_design.merged_library` reaches 6 / 6 of
`macs2_broad_peaks`, `homer_annotated_peaks` and `homer_tss_distance_profile`. The
`ataqv_chromosome_counts` link reaches 3 / 6 on the four `test` trees (AT2-D2).

### Recipe unit tests

`depictio/tests/recipes/test_atacseq_2_1_2_sample_design.py` (5 tests: version resolution and
column order, technical replicates and read type, the duplicated `control` header, a name off
the convention, the output schema) and `test_atacseq_2_1_2_peak_summary.py` (2 tests: the
FRiP join on the bare sample with merged-replicate files present, the catalog schema) pass.

## MultiQC

**One pattern, both layouts.** The shared pattern matches
`multiqc/broad_peak/multiqc_data/multiqc.parquet` (pipeline-written) and
`multiqc/multiqc_data/multiqc.parquet` (reprocessed). The processor ingests every parquet it
finds as its own report, so a tree must hold exactly one; the template header says so.

**Both reports bound.** In September the tiles followed the pipeline-written report only, and
4 of 13 were empty on a reprocessed one. The `modules` / `plots` lists are now the union of
both reports, and the tab binds:

| Tile | Pipeline-written (`_mqc135` `test`) | Reprocessed (`test_full`, `test_controls`) |
|---|---|---|
| General statistics | pruned (no table) | kept |
| FastQC counts and quality, cutadapt, Picard duplicates, FRiP, peak count, samtools mapped and per contig | kept | kept |
| Fingerprint | `mlib_deeptools` kept, `deepTools` pruned | `deepTools` kept, `mlib_deeptools` pruned |
| Insert sizes | `picard-1` kept, `picard` pruned (Mark Duplicates only) | `picard` kept, `picard-1` pruned |
| featureCounts assignments, ataqv mapping quality | pruned | kept |

Kept means the module and plot are in the report, the import's pruning rule. Every kept tile
was rendered with `multiqc.get_plot(module, plot).get_figure(0)` and drew traces on all three
parquets. The two alternate pairs share one slot, so one tile survives per report. `samtools`
is the library level on the pipeline-written report and the merged libraries before and
after filtering on a reprocessed one; both read as percent mapped.

## Dashboard (2026-10-09)

Rebuilt from the v2 1.2.2 dashboard: eight tabs become seven, with the 1.2.2 tags kept for
every surviving component.

- **Removed.** The Differential accessibility tab and every tile reading `deseq2_results`:
  the Overview's differential calls card, the significant-calls result row and the volcano
  highlight, the `direction` colours.
- **Overview.** Key figures: Samples, Peaks called, Consensus intervals (new,
  `at-ov-kf-consensus`, strip at two libraries or more) and FRiP. Findings: four rows in
  funnel order (fragment window share, peak fold enrichment, top HOMER class, reproducible
  consensus intervals) and four w4 figures in two rows: the fragment ladder highlight (new,
  `at-ov-hl-ladder`, from the ATAC quality tab) beside the significance along the genome, then
  the TSS distance beside the consensus support summary. Steps go from six to five, the align
  step naming Picard rather than an aligner. The run card counts libraries from `samplesheet`.
- **MultiQC.** Library scope filter on `samplesheet.sample`; same-slot alternates
  `at-mqc-fingerprint-mlib` and `at-mqc-picard-insert-1`.
- **Signal.** The preseq card of 1.2.2 (`at-sig-card-distinct`) is replaced in its strip slot
  by Picard's library size (`at-sig-card-libsize`); the preseq ribbon moved to a collapsed
  `Complexity curve` section that only a preseq run keeps, and Picard's duplication against
  depth (`at-sig-dup-depth`) takes its place beside the metagene. A Picard duplication slider
  joins the filters.
- **Locus.** `default_region: first`: the trees span a human and a yeast genome.
- **Consensus.** A `Sample space` section with the PCA and the distance heatmap, both full
  width, keeping their 1.2.2 tags (`at-diff-pca`, `at-diff-dists`), and their two tables in
  `Consensus tables`.

The resolved template validates as a `Project` (`resolve_template` then
`validate_model_config`, the import's step 3) on `test`, `test_controls` and `test_full`: 1
workflow, 21 data collections, 22 links, 1 dashboard. `ingest --dry-run` completes its 8
steps on `test_full` and `test_controls`. `dashboard validate --offline` passes, and the atacseq cases of
`test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py`
and `test_nfcore_megatest.py` pass, `megatest.yaml` now carrying `forbidden_terms`.

## Live check (2026-10-09)

`test_full` (`--var GENOME=hg19`) ingested 8/8 on a local stack; preseq did not run, so its
two optional collections were skipped. The Overview and the seven child tabs render with
values. The Consensus tab's PCA first drew every point in one colour: the catalog
`deseq2/qc_pca.py` output has no group. The version recipe `recipes/deseq2_qc_pca.py` now
adds `group` (the sample id without its `_REP<n>`), and the tile colours by it, in the
family's `group: auto` colours.

## Discrepancies and open items

### AT2-D1: MultiQC tiles are checked against the `test` run's report only

The pipeline-written parquet comes from the `test` profile. No trigger-path report exists
locally for `test_controls`, the other aligners or `test_full`, and no tile was rendered by
the API. The module numbering depends on which `module_order` entries receive files, so a
run that skips a level could shift the suffixes (`picard-1`).

### AT2-D2: ataqv writes no per-reference counts or TSS values for single-end libraries

The three single-end libraries of the `test` profile carry `chromosome_counts: null` and no
TSS enrichment or reads-in-peaks values in their ataqv JSON. The read-distribution matrix
shows three libraries on the `test` trees and six on `test_controls` and `test_full`. Not a
template defect.

### AT2-D3: preseq, ataqv, consensus and HOMER skips

preseq and the DESeq2 QC are `optional: true`. A run made with `--skip_ataqv`,
`--skip_consensus_peaks` or `--skip_peak_annotation` would leave the corresponding
collections without input; they stay required because the validated runs all publish them.

### AT2-D4: the merged-replicate level and narrow peaks are not bound

Both are complete second views of the run. The overrides exclude merged replicates, and no
collection reads `narrow_peak/`.

### AT2-D5: no seeds and no screenshots for 2.1.2

`.db_seeds/` holds nothing for this version, and no screenshot shows the 2.1.2 dashboard.
Both need an ingest of a 2.1.2 run.

### AT2-D6: the reprocessed `test_full` report logs an ataqv module error

MultiQC 1.35's ataqv module logged "Error adding FLD distance plot:
'fragment_length_distance'" while reprocessing `test_full`. The one ataqv MultiQC tile
(mapping quality) renders on that report.

### AT2-D7: the catalog peak summary leaves every FRiP score null on 2.x (fixed locally)

2.x names the summary rows `<sample>.mLb.clN` and the FRiP files' rows `<sample>`, and the
catalog's `macs2/peak_summary` joins on the raw name, so `frip_score` was null on every row
of every tree; the September report listed the collection as validated by row count only.
Fixed with the version recipe `recipes/peak_summary.py`, which strips the merge suffix from
both sides. A catalog fix (strip both join keys) would let the template go back to the
catalog recipe.

### AT2-D8: Picard names the library after the BAM

The catalog's `picard/markduplicates_metrics` keeps `<sample>.mLb.mkD.sorted` as the sample,
so the hub reaches it with a `pattern` link and the Picard table and scatter show that name.
Picard estimates no library size for single-end reads, so the Signal tab's library-size card
is the median of the paired-end libraries and prints a dash on an all single-end run.
