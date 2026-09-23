# nf-core/atacseq 1.2.2: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the atacseq 1.2.2 template plus the `ataqv` catalog tool and the `multiqc/ataqv`
catalog entry, reuse the `macs2` and `homer` tools the chipseq workstream built and the
`deseq2` tool the differentialabundance workstream built, and drive `depictio-cli run`
against the real AWS megatest output end to end. atacseq is the second pipeline in this lot
whose MultiQC report predates the parquet era, so the run also exercises the reprocess path
a second time, on a different report layout.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/atacseq/results-f327c86324427c64716be09c98634ae0bc8165f6/`
(the 1.2.2 release tag). Six GM12878 ATAC libraries: three transposition protocols, FAST,
OMNI and STD, two biological replicates each. All six reach every collection; there is no
control library in an ATAC design, so the sample count is the same everywhere.

```bash
python scripts/nfcore_megatest.py fetch --pipeline atacseq --version 1.2.2 \
  --dest ~/Data/depictio-nfcore/atacseq/1.2.2/megatest
# or, equivalently:
bash depictio/projects/nf-core/atacseq/1.2.2/download_test_data.sh
```

The manifest (`megatest.yaml`) fetches 147 files, 215.0 MB: the design sheet, the software
versions, the original MultiQC 1.9 report's provenance files, every raw MultiQC input of the
broadPeak merged-library path (FastQC zips raw and trimmed, Trim Galore reports, Picard
CollectMultipleMetrics and MarkDuplicates, samtools stats, flagstat and idxstats at both
filtering levels, preseq curves, deepTools fingerprint and profile tables, all `*_mqc.tsv`),
the six ataqv JSON reports, the MACS2 broad peak calls and their HOMER annotation, the
consensus boolean matrix and the three DESeq2 result tables. No BAM, no FASTQ, no bigWig.

## MultiQC was reprocessed: 1.9 to 1.35

Like chipseq, this template's QC tab does **not** read the report the pipeline published.

atacseq 1.2.2 is a DSL1 pipeline and this run shipped MultiQC 1.9, which writes
`multiqc_data.json` and no parquet at all, nested one level deeper than chipseq's:
`multiqc/broadPeak/multiqc_data/`, because the peak branch is part of the report path.
Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the report bound here is
produced by re-running the pinned MultiQC 1.35 over the run's own raw tool outputs:

```bash
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/atacseq/1.2.2/megatest \
  --dest ~/Data/depictio-nfcore/atacseq/1.2.2/megatest
```

181 inputs were staged. `megatest.yaml` records `multiqc: {version: "1.9", reprocess: true}`.

**What came back.** The parquet holds 48 sample ids and, read back through
`multiqc.parse_logs()` + `multiqc.list_plots()`, 14 modules:

| Module | Plots | Module | Plots |
|---|---|---|---|
| `fastqc` | 11 | `deepTools` | 3 |
| `picard` | 16 | `preseq` | 1 |
| `samtools` | 10 | `featurecounts` | 1 |
| `cutadapt` | 4 | `macs` | 0 (general stats only) |
| `ataqv` | 10 | `mlib_frip_score` | 1 |
| `mlib_peak_count` | 1 | `mlib_peak_annotation` | 1 |
| `mlib_deseq2_pca` | 1 | `mlib_deseq2_clustering` | 1 |

Two consequences are specific to this pipeline and both are visible in the numbers above:

* **MultiQC 1.35 has an `ataqv` module the 1.9 report had no idea about.** It contributes
  four plot sections (fragment-length distribution, peak percentiles, MAPQ distribution,
  chromosome distribution). The reprocess is therefore not only a format upgrade here: it
  adds the ATAC-specific QC panels outright. This is what motivated the new
  `depictio/catalog/multiqc/ataqv.yaml` entry (see the overlap policy below).
* **48 sample ids for six libraries.** The manifest fetches samtools output at both
  filtering levels the run published, `mLb.mkD` (duplicate-marked, unfiltered) and
  `mLb.clN` (filtered, what the peak callers see), so a library appears twice in the
  alignment panels. That is deliberate: the pair is what says how much ATAC filtering
  removed. FastQC contributes raw and trimmed entries per read pair on top. The persistent
  sample filter reaches the six design ids and leaves the derived spellings alone.

The anchors and plot names above are MultiQC 1.35's. `template.yaml`'s
`dc_specific_properties.modules` and `plots` and every `selected_module` / `selected_plot`
in `dashboards/base.yaml` are authored against this list and were verified against it, not
against the published report.

## Ingestion result: 14 / 14 data collections processed, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/atacseq/1.2.2 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest
```

`--project-name` was deliberately left off, so the project carries the name the template
declares (`ATAC-seq Chromatin Accessibility`, id `6a9c37713c27af379925c3bd`, dashboard
`6a9c378b30851b3fe171833d`). Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 14 modules, 48 sample ids | (MultiQC parquet, not Delta) |
| `sample_design` | 6 | 6 |
| `design_reads` | 6 | 5 |
| `ataqv_metrics` | 6 | 24 |
| `ataqv_fragment_length` | 6,006 | 5 |
| `ataqv_tss_coverage` | 12,006 | 3 |
| `ataqv_chromosome_counts` | 132 | 5 |
| `macs2_peak_summary` | 6 | 10 |
| `macs2_broad_peaks` | 224,137 | 11 |
| `homer_annotated_peaks` | 224,137 | 13 |
| `macs2_consensus_boolean` | 104,657 | 14 |
| `macs2_consensus_fc` | 250 | 12 |
| `deseq2_results_raw` | 313,971 | 27 |
| `deseq2_results` | 313,971 | 12 |

`deseq2_results_raw` exists only so `deseq2_results` can read it back through `dc_ref`: the
contrast id lives in the file NAME and only a scan carries the path into the frame. The
referenced collection is therefore declared **before** the collection that reads it and
ingestion stays sequential.

All five dashboard tabs imported (`Library QC` + `ATAC signal` + `Peaks` + `Consensus` +
`Differential accessibility`, 27 + 20 + 22 + 15 + 18 = 102 components across 28 sections:
24 cards, 22 text tiles, 17 interactive filters, 14 MultiQC panels, 9 figures, 8 tables and
8 advanced visualisations). 47 of those tiles carry a `use:` catalog reference that resolved
(`multiqc/*` 12, `macs2/*` 10, `ataqv/*` 10, `deseq2/*` 9, `homer/annotated_peaks` 6).

**Those counts are the tree as it was validated, and the YAML has moved on since.** The first
tab is now called `MultiQC`, and the shipped file holds 110 components across 30 sections: 23
cards (one fewer, AT-D11), 26 text tiles, 17 interactive filters, 15 MultiQC panels (the
General Statistics tile is bound again, AT-D8), 12 advanced visualisations, 9 figures and 8
tables, 64 of them carrying a `use:`. Nothing after this line was re-run against that tree.

## Post-ingest verification

Every collection was read back from its Delta table in MinIO and every tile grounded against
the real frame. No FILTER MISMATCH, no 4xx, no 5xx.

**Code-mode figures (6/6).** All six exec against their frame with the viewer's scope
(`df, pl, px, go, pd, np, depictio_group_by, depictio_group_kwargs`) and return a plotly
`Figure`: TSS coverage 6 traces (one per library), signal against specificity 6, fragment
length ladder 6, enrichment against significance 2, distance to the nearest TSS 5 (one per
annotation class), significant intervals per contrast 2. The remaining three figures are UI
mode, where a plain express call suffices.

**Column bindings.** All 24 card `column_name` / `breakdown_col`, all 17 interactive
`column_name`, both `selection_column`s, all 6 `row_selection_column`s and every
advanced_viz column binding exist in the bound collection.

**MultiQC tiles (14/14).** Every tile names a module and a plot that
`multiqc.list_plots()` reports for the reprocessed parquet, and every one of them also
renders server-side through `POST /dashboards/render_multiqc`.

**Links (14/14).** Replayed as real joins between the Delta frames:

| Link | Source keys hit | Target |
|---|---|---|
| `sample_design.sample` -> `multiqc_data.sample_name` (sample_mapping) | 6 / 6 | MultiQC report |
| `sample_design.sample` -> `macs2_peak_summary.sample` | 6 / 6 | |
| `sample_design.sample` -> `ataqv_metrics.sample` | 6 / 6 | |
| `sample_design.sample` -> `ataqv_fragment_length.sample` | 6 / 6 | |
| `sample_design.sample` -> `ataqv_tss_coverage.sample` | 6 / 6 | |
| `sample_design.sample` -> `ataqv_chromosome_counts.sample` | 6 / 6 | |
| `sample_design.merged_library` -> `macs2_broad_peaks.sample` | 6 / 6 | |
| `sample_design.merged_library` -> `homer_annotated_peaks.sample` | 6 / 6 | |
| `macs2_broad_peaks.peak_id` <-> `homer_annotated_peaks.peak_id` | 224137 / 224137 both ways | |
| `macs2_consensus_boolean.peak_id` -> `macs2_consensus_fc.peak_id` | 250 / 104657 | |
| `macs2_consensus_fc.peak_id` -> `macs2_consensus_boolean.peak_id` | 250 / 250 | |
| `macs2_consensus_boolean.interval_id` <-> `deseq2_results.gene_id` | 104657 / 104657 both ways | |

The two asymmetric rows are by construction, not by accident: `macs2_consensus_fc` keeps only
the 250 most strongly accessible intervals, because the complex heatmap plots one row per
interval (AT-D6).

**Unit tests.** `depictio/tests/models/test_catalog.py` and
`depictio/tests/models/test_shipped_dashboard_yamls.py` pass on the staged tree.
`python -m depictio.cli dev catalog validate`: 33 catalog tools valid.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, quality, GC, adapters, trimming | **MultiQC** (`use: multiqc/fastqc`, `use: multiqc/cutadapt`) |
| Alignment, duplication, insert size, library complexity | **MultiQC** (`use: multiqc/samtools`, `use: multiqc/picard`, `use: multiqc/preseq`) |
| Signal concentration over background, read distribution around genes | **MultiQC** (`use: multiqc/deeptools`) |
| Reads assigned to consensus peaks | **MultiQC** (`use: multiqc/featurecounts`) |
| Fragment ladder and MAPQ spread, as MultiQC renders them | **MultiQC** (`use: multiqc/ataqv`, new here) |
| TSS enrichment, HQAA fractions, mitochondrial fraction, per-library ataqv rows | **Dedicated** (`ataqv/*`): MultiQC's ataqv module plots four distributions and contributes three general-statistics columns; it exposes neither the per-library metric table the cards read nor the TSS coverage curve, and it has no view that ranks libraries against each other |
| FRiP, peak count, peak annotation summary, DESeq2 PCA and clustering | **MultiQC**, pipeline custom content, no catalog entry (AT-D9) |
| Per-peak coordinates, width, enrichment, significance | **Dedicated** (`macs2/*`, reused from chipseq): the MultiQC `macs` module exposes no plot, only general-statistics columns |
| Peak annotation against gene structure | **Dedicated** (`homer/annotate_peaks`, reused from chipseq) |
| Differential accessibility | **Dedicated** (`deseq2/*`, reused from differentialabundance) |

New catalog entries created here: the `ataqv` tool (`metrics`, `fragment_length`,
`tss_coverage`, `chromosome_counts`) and `multiqc/ataqv.yaml`. Both are pipeline-agnostic:
every ataqv output is matched on file name, so any ATAC pipeline that runs ataqv lands in the
same collections.

## Discrepancies

### AT-D1: no `pipeline_info/params.json`, so nothing is auto-detected from the run

atacseq 1.2.2 is DSL1 and writes no `params*.json`; the run's parameters survive only inside
`execution_report.html`. `_introspect_pipeline_params` therefore sets no template variable and
the template exposes `DATA_ROOT` alone. Provenance is collected from the tab-separated
`pipeline_info/software_versions.csv` and nothing else. Identical to chipseq's CS-D1, and for
the same reason: both are the last DSL1 release of their pipeline.

### AT-D2: the samplesheet is an output, not an input

There is no samplesheet to curl from GitHub. The pipeline derives
`pipeline_info/design_reads.csv` (six libraries with their protocol group and replicate
number) and publishes it, so the manifest fetches it and the template scans it in place. A
copy lives in the template's `input/` directory so the template is self-describing. The
recipe `recipes/sample_design.py` turns it into the hub collection.

### AT-D3: this is the broadPeak route, and it needs its own reader

The run was called with `--narrow_peak false`, so the peak tree lives under
`bwa/mergedLibrary/macs/broadPeak/` and the calls are `*_peaks.broadPeak`: BED6+3, with no
summit column. The catalog's `macs2/peaks` output reads the narrowPeak shape (BED6+4, summit
offset last) and does not fit.

This first shipped as a pipeline-local `recipes/broad_peaks.py`, which was the honest MVP
answer but not the right one: broadPeak is a MACS2 output shape, not an atacseq specific,
and chipseq's own broadPeak twin (CS-D8) would have needed the same recipe again. It is now
`macs2/broad_peaks` in the catalog, globbing `**/*_peaks.broadPeak` where its narrow sibling
globs `**/*_peaks.narrowPeak`, so a run matches exactly one of the two and both pipelines
read the same output. Release 1.2.1 is the narrowPeak twin of this exact run, which makes
the pairing directly testable.

### AT-D4: merged libraries only, merged replicates deferred

The run publishes the whole peak / consensus / DESeq2 tree twice: once per merged library
(`bwa/mergedLibrary/`, `mLb`, six samples) and once per merged replicate
(`bwa/mergedReplicate/`, `mRp`, three protocol-level samples). Every recipe matches on file
name, so fetching both would concatenate two different levels of the same analysis into one
table with no column saying which. The manifest fetches the mergedLibrary branch only. The
replicate level is a genuine second view of the same run and is deferred with the
conditionals, consistent with the lot's "main pipeline path first" decision.

### AT-D5: two spellings of the same sample, and the hub carries both

atacseq names the merged, filtered library `<sample>.mLb.clN`, and MACS2 stamps that string
into every peak name. So the peak calls, the HOMER annotation and the consensus matrix all
speak `GM12878_FAST_R1.mLb.clN` while the peak QC summary, the ataqv reports and MultiQC
speak `GM12878_FAST_R1`. `sample_design` carries both columns (`sample` and
`merged_library`) and each link starts from whichever one the target collection uses, which
is why the links table above has two source columns. A single-column hub would have left half
the collections unreachable from the persistent sample filter.

### AT-D6: `macs2_consensus_fc` is a top-N view, so its link back is 250 of 104657

`macs2/consensus_fc.py` keeps the most strongly accessible intervals of the consensus set
(250 rows here) because the complex heatmap plots one row per interval and 104657 rows is not
a heatmap. Selecting an interval on the overlap panel narrows the heatmap when the interval
is in the top set and clears it otherwise; the reverse link matches 250 of 250. Same shape as
chipseq's CS-D4.

### AT-D7: the reprocess is not idempotent for source-version detection

`detect_source_multiqc_version()` probes the parquet first. Once the reprocess has written
`multiqc/multiqc_data/multiqc.parquet`, a second run over the same `--src` reports the source
as 1.35 and overwrites `REPROCESSED.json` with that wrong source version. The parquet itself
is unaffected, because `plan_inputs()` skips every `multiqc*/` directory; only the provenance
record degrades. The copy on this machine has been overwritten that way and now reads
`source_version: "1.35"`; the true source is 1.9, recorded in `megatest.yaml`. Keep the first
`REPROCESSED.json`, or delete `multiqc/multiqc_data/` before re-running. Identical to
chipseq's CS-D7, and seeing it a second time is the argument for fixing it in
`multiqc_reprocess.py` rather than documenting it again.

### AT-D8: the MultiQC General Statistics table cannot be rendered for this run either

`_process_multiqc_data` raises on this parquet as it does on chipseq's (CS-D3), here with
`ValueError: The truth value of a DataFrame is ambiguous`. Same root cause: atacseq runs
`samtools stats` and `samtools flagstat` over the same BAMs, both contribute a general-stats
column whose MultiQC display title is `Reads mapped`, the de-duplication loop in
`general_stats_payload._process_multiqc_data` keys `sanitized_columns` on that display title,
and the second pass overwrites the first mapping so `rename()` gives both columns the same
name. `df[column]` then returns a DataFrame instead of a Series.

That makes three of the megatest parquets on this machine (chipseq, rnaseq, atacseq) that
cannot bind a General Statistics tile, against one that can (airrflow). The template does not
bind one; `general_stats` stays in the data collection's `modules` list because the
underlying data is present and the tile becomes usable as soon as the API is fixed. The fix
belongs in `depictio/api/v1/services/multiqc/general_stats_payload.py` and is outside this
workstream's owned paths.

**Since fixed, and the tile is bound again.** `general_stats_payload.py` now resolves the
display titles in two passes and qualifies only the ones that actually repeat, so
`reads_mapped` from `samtools stats` and `mapped_passed` from `samtools flagstat` land in two
columns instead of collapsing onto one. The template binds a General Statistics tile, and
AT-D11 makes it the panel the MultiQC tab opens on. The paragraphs above are the state at
validation time; the tile has not been re-rendered against this run's parquet since the fix.

### AT-D9: five MultiQC tiles carry no `use:` badge

`mlib_frip_score`, `mlib_peak_count`, `mlib_peak_annotation`, `mlib_deseq2_pca` and
`mlib_deseq2_clustering` are atacseq's own custom content, written by the pipeline as
`*_mqc.tsv`, not MultiQC tool modules. A `depictio/catalog/multiqc/<module>.yaml` entry
describes a tool module that recurs across pipelines, so creating one for a pipeline-only
section would put a pipeline specific into the catalog. Two of these are bound as plain
MultiQC tiles (FRiP score, peaks per library) because they answer the QC tab's question
directly; the other three are not bound at all, because the dedicated `macs2`, `homer` and
`deseq2` collections say the same thing with per-peak detail.

The `macs` module is a different case: MultiQC 1.35 recognises it and it contributes
general-statistics columns, but `list_plots()` reports zero plots for it, so no tile can bind
it and no `multiqc/macs.yaml` entry was created. Identical to chipseq's CS-D5.

### AT-D10: a Delta write large enough to go multipart failed twice against the local MinIO

Two consecutive ingests failed on `deseq2_results_raw` (313,971 rows x 27 columns, the
largest write in this template) with

```
Failed to parse parquet: External: The operation lacked the necessary privileges to
complete ... Error performing DELETE http://localhost:9101/depictio-bucket/<id>/part-...
?uploadId=... 403 Forbidden: AccessDenied
```

This is **not** a depictio bug and not a template problem. Reproduced with a raw boto3
multipart upload of random bytes against the same MinIO, with the same root credentials and
no depictio code in the path: `UploadPart` answers 403 `AccessDenied` after two to six 5 MB
parts, non-deterministically, on a freshly created bucket as well as on `depictio-bucket`,
while a single-part `PutObject` of 120 MB succeeds every time. The MinIO container's data
volume is 94 % full. The reported error is misleading twice over: the DELETE in the message
is object_store aborting the upload it could not finish, and MinIO answers a failed part
write with `AccessDenied` rather than a storage error.

The third ingest of the identical tree went green 8/8 with all 14 collections, which is the
run this report describes. Worth knowing for anyone validating a template with a collection
above roughly 50 MB on a nearly full disk: retry before believing the recipe.

### AT-D11: the MultiQC tab carried four cards no MultiQC module reports

A tab named `MultiQC` is a promise that what is on it is the MultiQC report. The intro text,
the left-panel filters and the two persistent pinned sections are the agreed exceptions; the
`Run at a glance` grid section was not. It held four cards read from Delta tables: peaks
called (`macs2/peak_summary.num_peaks`) and TSS enrichment, mitochondrial fraction and reads
inside peaks (all three `ataqv/metrics`). Everything else on the tab was already clean.

**The three ataqv cards moved to `ATAC signal`**, the tab that owns `ataqv_metrics` and
`ataqv_fragment_length`, and none of them repeats a card that was already there.
`Library quality at a glance` now holds seven cards in two rows that each fill the 8-column
grid:

| Row | Cards |
|---|---|
| `y: 1`, four at `w: 2` | TSS enrichment (gauge), Reads inside peaks (threshold), Mitochondrial fraction (Tukey box), Duplicate fraction (histogram) |
| `y: 3`, one at `w: 4` and two at `w: 2` | Peaks ataqv scored (top 3 libraries), Fragment length (Tukey box), Fragment windows (donut) |

Row one is the quartet an ATAC library is accepted or rejected on, which is what the section
name has always claimed and what the moved cards complete. Row two is what the library's peaks
and fragments look like. Seven cards cannot be dealt into rows of four, so the top-N card takes
the wide slot of row two rather than leaving a gap: its strip spells out merged-library names,
which is the card of the seven that gains the most from the extra width.

**The fourth card was deleted rather than moved.** `macs2/peak_summary.num_peaks` summed over
the six libraries and broken down by sample is the same statement as `at-pk-card-count` on the
`Peaks` tab, which counts `peak_id` over `macs2/broad_peaks` and breaks down by sample:
`peak_summary.py` documents `num_peaks` as "peaks MACS2 called for the sample", which is the
row count of the calls the other card counts. The `Peaks` card is the better of the two,
because it sits behind that tab's significance, width and feature-class filters and so reads
"peaks in view" rather than a constant; moving the summary card there would also have left a
row built for four cards holding five. The peak count still reaches the MultiQC tab in MultiQC
form, as the `mlib_peak_count` panel ("Peaks per library") in `Accessibility signal`.

**What `Run at a glance` holds now.** Its intro, and the MultiQC General Statistics table
moved up from `Read quality`. That table pools FastQC, Trim Galore, samtools, Picard, MACS2
and ataqv columns, so it is the run at a glance rather than a read-quality panel, and it is
the one MultiQC panel about the run instead of about a single tool. The tab therefore still
opens on something that speaks for every library, every declared section still has components,
and `Read quality` compacts onto its three FastQC and Trim Galore panels. The section keeps its
name, takes the overview icon and now describes what it shows.

Both intros were rewritten: the MultiQC one no longer announces four cards and says where the
ataqv measures went, and the `ATAC signal` one names the acceptance quartet its section now
opens with. `index` is preserved on all three moved cards (`at-qc-card-tss`,
`at-qc-card-mito`, `at-qc-card-inpeaks`) because saved filters and stored metadata key on it,
and their `at-qc-` tags were left alone for the same reason, so three tags on `ATAC signal`
carry the prefix of the tab they came from.

`docs/dashboards.md` still describes `Run at a glance` as a four-card strip, `Library quality
at a glance` as a four-card strip and the General Statistics table as unbound. It is outside
this change's owned paths and needs the same pass.

---

# 2026-09-22 remediation pass

Run against the same megatest mirror
(`~/Data/depictio-nfcore/atacseq/1.2.2/megatest`, 185 files) on the lot 2 stack
(API `localhost:8112`, viewer `localhost:5612`, Mongo `localhost:27112`). The sections above
are the state at the original build; this one is the delta and supersedes the counts in
"Those counts are the tree as it was validated".

## Version decision: stays on 1.2.2

Not revisited here. Every atacseq release from 2.x on publishes an empty or truncated megatest
prefix, so 1.2.2 from 2022 is still the newest complete run in the bucket. The consequence is
worth stating plainly: this template is pinned to a DSL1 pipeline that shipped MultiQC 1.9 and
whose tool versions (BWA 0.7.17, MACS2 2.2.7.1, Picard 2.23.1, R 3.6.3) are four years old.
The bump to 2.1.2 is blocked on data, not on the template, and should be re-checked whenever
the 2.x prefix is republished (AT-D19).

## What changed

**Layout.** The single highest-volume defect: 26 text tiles were `h: 1` with a rendered body
over 120 characters, which the shipped-YAML test tolerates (its budget is 300 characters per
row) but which overflows the tile on first paint. All 26 are now `h: 2`, and the `y` of every
tile below them in their section was recomputed, so every grid row of every section still
covers all eight columns exactly once, with no gap and no overlap.

Table heights were sized to the rows the collections really hold: `ataqv_metrics` was `h: 6`
for a 6-row table and is now `h: 3`, and `sample_design` and `macs2_peak_summary` (6 rows
each) went from `h: 4` to `h: 3`.

**Portability (lint F7).** Two patterns were anchored on a directory that only this run
happens to write.

| Before | After |
|---|---|
| `bwa/mergedLibrary/macs/*/*_peaks.annotatePeaks.txt` | `**/mergedLibrary/macs/*/*_peaks.annotatePeaks.txt` |
| `multiqc/multiqc_data/multiqc\.parquet$` | `(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$` |

The first drops the `bwa/` aligner directory, which is `bowtie2/`, `chromap/` or `star/` on a
run launched with another `--aligner`, and keeps `mergedLibrary/macs/`, which is the merge
level and peak route the template deliberately binds. The second is the shared MultiQC regex:
this mirror carries the reprocessed report at `multiqc/multiqc_data/`, while a real run writes
it one level deeper under the peak route it called. Both were re-run against the real files
and produce exactly the frames the old patterns did (HOMER 224137 rows, one MultiQC parquet).

**Filters.** Every tab now carries both halves of the rule.

* The persistent `Sample filters` section gained `Replicate`, the second real factor of the
  design sheet (2 distinct values; `group` has 3, `sample` 6). `n_libraries` is constant at 1
  in this run and is deliberately not offered.
* The MultiQC tab had no tab-local filter section: it now declares `Peak QC scope`
  (`num_peaks`, `width_median` on `macs2_peak_summary`), non-persistent, so it narrows the peak
  QC rows pinned under the report without riding the other tabs.
* The Peaks tab gained `Reference sequence` (`chr` on `macs2_broad_peaks`) in its existing
  `Peak filters` section, which is the control the two new genome tiles are read with.

**New content.**

* `Peak intervals on the genome`, a new section on the Peaks tab. A broad call is a region and
  the Manhattan panel above it collapses that region to its midpoint, which is the one thing a
  broad run should not be read as. `at-pk-av-genome` binds `chr / start / end /
  neg_log10_qvalue` with `mark: rect`, `facet_by_sample` and `max_facets: 6`, so each of the
  six libraries gets a lane on a shared chromosome-aware axis. `at-pk-av-coverage` reads the
  same rows as a `coverage_track`, so the section still answers the question if the GenomeSpy
  renderer is unavailable. Neither pins an assembly: the contig list is derived from the data,
  which keeps the pair working on a run aligned against a non-human reference.
* `Sample space`, a new section on the Consensus tab, binding the two DESeq2 QC tables the
  pipeline writes beside the contrast results and that nothing read before:
  `deseq2_qc_pca` (6 rows x 5 columns) through `use: deseq2/qc_pca_embedding`, and
  `deseq2_qc_sample_dists` (6 rows x 7 columns) through `use: deseq2/qc_distance_heatmap`,
  with both tables added to the collapsed `Consensus tables` section. Two links from the
  sample hub were added with them.

**Docs.** `docs/dashboards.md` was rewritten for all of the above and the stale note closing
the previous section is now settled: it no longer describes `Run at a glance` or `Library
quality at a glance` as four-card strips, and it no longer calls the General Statistics table
unbound.

**Checked and found already correct**, so not touched: the fragment-size distribution and TSS
enrichment panels all render from real frames (`ataqv_fragment_length` 6006 rows,
`ataqv_tss_coverage` 12006 rows, `ataqv_metrics` 6 rows with `tss_enrichment` populated for
all six libraries), and every non-MultiQC tab already opened on a four-card, multi-metric
`w: 2 h: 2` strip at x 0/2/4/6.

## Counts after this pass

122 components across 33 sections and 5 tabs: 28 text tiles, 21 interactive filters, 23 cards,
16 advanced visualisations, 15 MultiQC panels, 10 tables and 9 figures. 68 of the 73
renderable tiles carry a `use:` (93%); the 49 text and interactive tiles never do. 21 data
collections, 20 links.

## Commands run

```bash
# every recipe the template binds, on the real megatest, through resolve_sources + transform
uv run python <scratch>/atacseq_recipes.py
```

| Recipe | Rows | Columns |
|---|---|---|
| `nf-core/atacseq/sample_design.py` | 6 | 6 |
| `ataqv/metrics.py` | 6 | 24 |
| `ataqv/fragment_length.py` | 6006 | 5 |
| `ataqv/tss_coverage.py` | 12006 | 3 |
| `ataqv/chromosome_counts.py` | 132 | 5 |
| `deeptools/fingerprint_metrics.py` | 6 | 9 |
| `deeptools/plot_profile.py` | 4200 | 5 |
| `macs2/peak_summary.py` | 6 | 10 |
| `macs2/broad_peaks.py` | 224137 | 11 |
| `homer/annotate_peaks.py` (portable glob) | 224137 | 13 |
| `macs2/consensus_boolean.py` | 104657 | 14 |
| `macs2/consensus_fc.py` | 250 | 12 |
| `deseq2/qc_pca.py` (new) | 6 | 5 |
| `deseq2/qc_sample_dists.py` (new) | 6 | 7 |

`preseq/complexity_curve.py`, `homer/tss_distance_profile.py` and `deseq2/results_long.py`
read a `dc_ref` source and can only run through the CLI two-step; the ingest below covers them.

```bash
uv run python -m depictio.cli run --template nf-core/atacseq/1.2.2 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest --dry-run     # 8/8 steps passed
uv run python -m depictio.cli run --template nf-core/atacseq/1.2.2 \
  --data-root ~/Data/depictio-nfcore/atacseq/1.2.2/megatest \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml
```

No `ATAC-seq Chromatin Accessibility` project existed on the stack, so nothing was deleted
first. Scan, processing and joins all passed; every one of the 20 table collections has rows,
read back from `/deltatables/shape/{dc_id}`:

| Collection | Rows x columns |
|---|---|
| `sample_design` | 6 x 6 |
| `design_reads` | 6 x 5 |
| `ataqv_metrics` | 6 x 24 |
| `ataqv_fragment_length` | 6006 x 5 |
| `ataqv_tss_coverage` | 12006 x 3 |
| `ataqv_chromosome_counts` | 132 x 5 |
| `preseq_ccurve_raw` | 60000 x 7 |
| `preseq_complexity_curve` | 1008 x 6 |
| `deeptools_fingerprint_metrics` | 6 x 9 |
| `deeptools_plot_profile` | 4200 x 5 |
| `macs2_peak_summary` | 6 x 10 |
| `macs2_broad_peaks` | 224137 x 11 |
| `homer_annotated_peaks` | 224137 x 13 |
| `homer_tss_distance_profile` | 482 x 4 |
| `macs2_consensus_boolean` | 104657 x 14 |
| `macs2_consensus_fc` | 250 x 12 |
| `deseq2_results_raw` | 313971 x 27 |
| `deseq2_results` | 313971 x 12 |
| `deseq2_qc_pca` | 6 x 5 |
| `deseq2_qc_sample_dists` | 6 x 7 |

`multiqc_data` is a MultiQC collection and has no Delta table by design.

Step 8 of that run (dashboard import) returned HTTP 500 the first time, because another
catalog tool directory was half-written at that moment and catalog loading is
all-or-nothing across `depictio/catalog/`. Nothing in this template was implicated. Once the
shared catalog loaded again the import was replayed on its own and all five tabs landed:

```bash
uv run python -m depictio.cli dashboard import \
  depictio/projects/nf-core/atacseq/1.2.2/dashboards/base.yaml \
  --config ~/.depictio/CLI.feat-nfcore-templates-lot2-112.yaml \
  --api http://localhost:8112 --overwrite
```

Tests, each run once on the final tree:

* `uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -q -k atacseq`:
  10 passed.
* `uv run pytest depictio/tests/models/test_catalog.py -q`: 93 passed, 6 failed. None of the
  six names a tool this template owns or binds: they are `cellbender`, `kallisto`, `qcatch`,
  `simpleaf`, `funcscan`, `cooltools` and `gtdbtk` (other pipelines' directories, written in
  parallel with this pass) plus the two committed JSON schemas, which the main session
  regenerates.
* `uv run pre-commit run --files <the six changed files>`: passed (no Python changed, so the
  ruff and ty hooks had nothing to check).

The distance matrix reproduces the design: the two replicates of a protocol sit at 32 (OMNI),
86 (FAST) and 91 (STD) from each other, and at 101 to 119 from any library of another
protocol, so the three transposition protocols separate cleanly and the contrasts on the last
tab are worth reading.

## Discrepancies

### AT-D12: 26 text tiles were a single grid row for a body over 120 characters

The shipped-YAML test budgets 300 rendered characters per grid row, so none of them failed it,
but a `h: 1` tile fits its title plus about two lines and `TextRenderer` applies no
`maxHeight`, `overflow` or line clamp. Every text tile in the file was affected. All 26 are now
`h: 2` and every section below them was shifted. Fixed.

### AT-D13: three tables were taller than their collection

`ataqv_metrics` is 6 rows and was `h: 6`; `sample_design` and `macs2_peak_summary` are 6 rows
and were `h: 4`. All three are `h: 3` now, the size for a 1 to 10 row table. The peak and
annotation tables stay at `h: 5`: they hold 224137 rows and are in a collapsed section.
Fixed.

### AT-D14: two patterns were anchored on this run's own directory layout

See the table under "What changed". Both are portable now, and both were re-run against the
real files. Fixed.

### AT-D15: no narrowPeak route variant, and one cannot be added cleanly yet

The template is hard-bound to the broad-peak route. The mechanism for a variant exists:
`template.conditional` with `if_var_present: NARROW_PEAK` and an `override_dcs` entry
repointing `macs2_broad_peaks` at `macs2/peaks.py`. What blocks it is the schema, not the
mechanism: `macs2/broad_peaks.py` emits `midpoint` (a broad call has no summit) where
`macs2/peaks.py` emits `summit`, and `dashboards/base.yaml` binds the broad catalog render
`macs2/broad_peak_significance`, whose `pos` role is `midpoint`. A narrow route would therefore
also need a `dashboards:` override, i.e. a second copy of a 2200-line dashboard that differs in
one column name. Left unbuilt on purpose. The clean fix is upstream of this template: either
one MACS2 catalog output that reads both file shapes and emits a common position column, or a
dashboard-level column alias. Everything else in the template already takes both routes, because
the HOMER, consensus and DESeq2 globs match `macs/*/` and not `macs/broadPeak/`. Open.

### AT-D16: the two genome tiles carry no `use:`

`depictio/catalog/macs2/broad_peaks.yaml` has one advanced_viz render id,
`broad_peak_significance` (kind `manhattan`). It has no genome-track render, so the two new
tiles are declared inline with an explicit `config:` rather than through `use:`, which is what
drops the coverage from 95% to 93%. `depictio/catalog/macs2/` is owned by another pipeline this
wave, so it was read but not edited. The snippet its owner would add to `renders_as` is in the
handback report. Open, cosmetic: the tiles render either way, they just carry no catalog badge.

### AT-D17: the MultiQC tab has no glance strip, by design

The maintainer rule is that every tab opens with four multi-metric cards.
`test_multiqc_tabs_hold_only_multiqc_panels` forbids exactly that on a tab called MultiQC: only
text, interactive, floating and persistent-pinned tiles are exempt, and a card is none of
those. The tab opens on the General Statistics table instead, which is the one panel in the
report that speaks for the run rather than for a single tool. The other four tabs each open on
a four-card `w: 2 h: 2` strip at x 0/2/4/6, all multi-metric (gauge, threshold, box plot,
histogram, top-N, donut). Accepted, the two rules are in direct conflict and the test wins.

### AT-D18: the persistent sample filters reach the Consensus tab only through the new QC tables

`macs2_consensus_boolean` and `macs2_consensus_fc` carry the libraries as COLUMNS (one 0/1 or
fold-change column per library), not as a row key, so no `sample`-resolver link can reach them
and the left-rail sample scope could not narrow the Consensus tab at all. The same holds for
`deseq2_results`, which is keyed on contrast and interval. Adding `deseq2_qc_pca` and
`deseq2_qc_sample_dists`, which ARE sample-keyed, gives the Consensus tab its first link from
the hub. The consensus and differential panels themselves still rely on their tab-local
sections (`Consensus scope`, `Contrast`), which is inherent to what those collections are.
Accepted.

### AT-D19: the template is pinned to a four-year-old pipeline release

See "Version decision" above. Not a defect of the template, a property of the bucket. Re-check
whenever an atacseq 2.x megatest prefix is republished. Open.

### AT-D20: the kind was renamed mid-wave

The GenomeSpy kind was spelled `genomespy_track` when this pass started and is
`genome_view` in `depictio/models/components/types.py` by the end of it. The new track tile
binds `genome_view`, which is the name the model accepts; its `coverage_track` fallback was
unaffected. `depictio/projects/init/advanced_viz_showcase/
dashboards/genomespy_track.yaml` still says `genomespy_track` and belongs to the kind's owner.
Reported, not this template's to fix.

### AT-D21: only the MultiQC tab could be screenshotted

The five tabs imported (`nf-core/atacseq` plus `ATAC signal`, `Peaks`, `Consensus`,
`Differential accessibility` as child dashboards) and every tile validated, but the shared dev
viewer on `localhost:5612` was serving a Vite overlay for most of this pass:

```
[plugin:vite:import-analysis] Failed to resolve import "@genome-spy/core/genome/genomes.js"
from ".../advanced_viz/genomespy/useGenomeSpy.ts"
```

That module is imported on the advanced-viz path, so every tab that holds an advanced
visualisation rendered the overlay instead of the dashboard, while the MultiQC tab, which
holds none, rendered fine.

The cause is not the package: `@genome-spy/core@0.88.1` is installed and symlinked into both
`packages/depictio-react-core/node_modules/@genome-spy/` and
`depictio/viewer/node_modules/@genome-spy/`, and its `exports` map resolves
`./genome/genomes.js` to `dist/src/genome/genomes.js`, which exists. The dev server on 5612
simply predates that install and has not re-resolved it. A second Vite dev server on the host
(port 5799), started after the install, serves the same tree and the same API and renders every
tab correctly, which is where the five shipped screenshots come from:

```
/tmp/claude-502/shots-atacseq/tab1-multiqc.png
/tmp/claude-502/shots-atacseq/tab2-atac-signal.png
/tmp/claude-502/shots-atacseq/tab3-peaks.png
/tmp/claude-502/shots-atacseq/tab4-consensus.png
/tmp/claude-502/shots-atacseq/tab5-differential.png
```

The fix for the 5612 viewer is a restart of `depictio-viewer-dev` (or `vite --force` to drop
the dep-optimizer cache); it is not a template change and was deliberately not attempted from
here. Open, and owned by the stack rather than by this template.

### AT-D22: the Consensus intervals card broke its count down by a constant column

The `macs2/consensus_intervals` catalog card breaks the interval count down by
`consensus_set`, which is the right axis on a ChIP run with one consensus table per
antibody. atacseq writes one consensus table per merge level and only the merged-library
level is bound here, so on this run the column holds a single value and the top-N strip
read "GM12878 104,657 (100%)". The dashboard now overrides `breakdown_col: chr` on
`at-cons-card-intervals` (the catalog file was not touched); the strip lists the three
largest chromosomes instead. Fixed in `dashboards/base.yaml`; the dashboard was re-imported
afterwards (`--overwrite`, dashboard id unchanged at `6ab2a948fbe776a1a573e1e4`) and
`test_shipped_dashboard_yamls.py -k atacseq` re-run: 10 passed.

## 2026-09-22 review fixes

MAIN tab now opens on a pinned persistent `Cohort at a glance` strip (never collapsed):
libraries by protocol (`sample_design`, donut on `group`), replicate depth (box plot),
peaks called (`macs2/peak_summary`, top 3 by sample) and mean FRiP (gauge). The ATAC
signal tab's second card row is four `w: 2` cards (`Peaks ataqv scored` shrunk to `w: 2`,
new `TSS coverage` box plot on `ataqv/tss_coverage`). Prose no longer counts the run's
libraries. Links: `sample_design.group -> deseq2_results.contrast` (wildcard, the chipseq
shape). Not done: group links onto `macs2_consensus_boolean` / `macs2_consensus_fc`.
atacseq 1.2.2 builds one consensus set across every library, so `consensus_set` holds a
single value no group name prefixes, and both matrices have samples as columns; the link
would resolve to nothing and blank the tiles. Documented in template.yaml.

## 2026-09-23 wave 2b (locus section, header controls, switchable views)

What changed:

- **Peak locus tab (new, tab_order 4).** The locus section of the wave 2 design on three
  collections: a `genome_view` navigator on `macs2_broad_peaks` (`mark: bar`, one lane per
  library, `controls_placement: header`, `assembly: hg19`, `default_region:
  chr6:26,000,000-26,300,000`), `macs2_consensus_boolean` as a `coverage_track` (`view:
  track`, `num_samples` per interval) and `homer_annotated_peaks` as a second `genome_view`
  with `follow_region_filter: true`. Two region links (`resolver: region`, `columns: {chrom:
  chr, pos: start}`) in `template.yaml` carry the navigator's region to the other two. Glance
  strip of four region-scoped cards, tab-local `Locus scope` filters (chromosome, consensus
  support slider, HOMER feature class). Consensus and Differential accessibility move to
  tab_order 5 and 6.
- **Double binding fixed (AT-D23).** The Peaks tab bound `genome_view` and `coverage_track`
  on `macs2_broad_peaks`; both are gone from that tab (the interval view lives on the Peak
  locus tab, where the coverage track reads a different collection).
  `test_no_double_track_binding --runxfail` no longer lists atacseq.
- **Peaks tab.** New `Reads in peaks per library` section: FRiP and peak count bars from
  `macs2/peak_summary`.
- **Differential accessibility.** The `deseq2/ma` and `deseq2/qq` tiles are folded into the
  `deseq2/volcano` tile: `views: [volcano, ma, qq]`, `controls_placement: header`,
  `avg_log_intensity_col: log2_base_mean`, `p_value_col: pvalue`. Sections renamed `Volcano,
  MA and QQ` and `Direction of change`.
- **Header controls** on the fingerprint `scatter_xy`, the read-distribution `dot_plot`, the
  consensus PCA `embedding`, the volcano and the locus navigator.
- **`show_histogram: true`** on the 11 threshold RangeSliders (every one but `replicate`).

### AT-D23: the Peaks tab bound genome_view and coverage_track on one collection

Fixed as above. The region filter is also why the interval view left the Peaks tab: a
`genome_selection` filter narrows every tile of its collection on a tab, which would have
shrunk the genome-wide Manhattan, the glance strip and the HOMER panels to 300 kb.

### AT-D24: the run is hg19, so the locus section has no gene lane

GAPDH promoter calls sit at chr12:6.64 Mb, the hg19 coordinate. The bundled gene tables
(`annotation`) are hg38 and mm10 only, so the navigator sets `assembly: hg19` for the
chromosome sizes and the HOMER track (nearest gene per call) stands in for the gene lane.
Gene symbol search in the locus field needs hg38 or mm10 and is not available here; locus
coordinates work.

### AT-D25: no summit-centred profile on this run

T-chipseq's `macs2/summit_profile` exists, but it reads narrowPeak summits through the
`macs2_peaks` collection. This megatest was called with `--narrow_peak false`: the
`*_peaks.broadPeak` files carry no summit column, so there is nothing honest to centre on.
The tile is left out (the region midpoint is not a summit). No computeMatrix output is
mirrored either, so no read-coverage metagene around TSS beyond the existing deepTools
plotProfile panel.

Commands and results (2026-09-23):

- `uv run pytest -q depictio/tests/models/test_shipped_dashboard_yamls.py -k atacseq`: 10 passed.
- `uv run pytest -q depictio/tests/models/test_catalog.py`: 99 passed.
- `--runxfail -k double`: atacseq absent from the hit list (chipseq, sarek remain).
- `depictio.cli run --template nf-core/atacseq/1.2.2 ... --dry-run`: 8/8 steps.
- Re-ingest (old project deleted): project `6ab3ca22dc9db1d257758b63`, dashboard
  `6ab3ca6de8b8ace33d32c80a`, 20 table DCs with rows (macs2_broad_peaks 224,137,
  homer_annotated_peaks 224,137, macs2_consensus_boolean 104,657, deseq2_results 313,971),
  both region links stored. Dashboard re-imported with `--overwrite` after the mark fix.
- Live on :5612: the Peak locus tab opened with the two region filters in force (chr6,
  26,000,000-26,300,000); the glance strip read 114 calls, 3.18 libraries per consensus
  interval and 30 nearest genes; the consensus track drew 34 intervals clamped to
  26.0-26.3 Mb.
- Live pass 2 (stack back up, same project and dashboard ids). The consensus track is now a
  `genome_view` (`mark: bar`, `follow_region_filter`), not a `coverage_track`: the Plotly
  track fetched all 104,657 intervals before the default region landed and in one run
  froze the page. At the default region the followers read 34 consensus intervals and 114
  HOMER calls. Typing `chr12:6,550,000-6,700,000` (GAPDH) in the navigator's locus field
  moved both: 14 intervals and 37 calls, and the glance cards followed (37 calls, 10 genes).
  Header chips seen on the volcano (Volcano/MA/QQ, padj, effect, top-N, search), the PCA
  (2D/3D, colour by), the fingerprint scatter (Points/Density, log axes, reference line)
  and the read-distribution dot plot (sort, max genes).
- Navigator: `mark: bar` stored, `h: 6`. It reads its own collection without its own region,
  and the server caps that at 9,728 of 224,137 rows by q-value, so only the strongest calls
  of each library show at the region (3 to 4 bars at HIST1). The followers are exact.
  Viewer behaviour, reported, not worked around.

### AT-D26: range filters on macs2_broad_peaks emptied every HOMER tile

`extend_filters_via_links` walks every filter on a source collection through each value
link from it, whatever the filter's column. The direct `peak_id` link
`macs2_broad_peaks -> homer_annotated_peaks` therefore received the navigator's position
range `[26000000, 26300000]` as two peak ids, matched nothing and returned LINK_NO_MATCH: 0
HOMER rows at the region. The same happens to the Peaks tab's q-value and width sliders
(checked: a q-value range of 5 to 100 gave 0 HOMER rows). The link is `enabled: false` in
`template.yaml` and was disabled on the live project (PUT /links/{project}/{link}); HOMER
then returns 114 rows at the region. Cost: a peak lasso on the Peaks tab no longer narrows
the HOMER tables. Platform fix wanted in `depictio/api/v1/filter_links.py` (skip range
filters, or filters not on the link's source column, when walking value links); then
re-enable the link.

Screenshots (1600x1000, /tmp/claude-502/shots-atacseq/): w2b-locus-nav.png and
w2b-locus-tracks.png (default region), w2b-locus-typed-nav.png and
w2b-locus-typed-tracks.png (chr12 locus typed), w2b-tab5-consensus.png, w2b-0e-0.png (PCA
header), w2b-tab6-differential.png, w2b-0f-0.png (volcano header), w2b-0b-0.png and
w2b-0b-1.png (fingerprint and dot plot headers).
