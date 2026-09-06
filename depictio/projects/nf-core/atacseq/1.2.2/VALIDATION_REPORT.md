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
