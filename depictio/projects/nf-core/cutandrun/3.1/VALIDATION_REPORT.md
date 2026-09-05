# nf-core/cutandrun 3.1: template ingestion validation report

**Date:** 2026-09-05
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot1`
**Validator:** local depictio-cli (`depictio/cli/.venv`) against the local docker stack
(instance `feat-nfcore-templates-lot1`, API `:8101`, MinIO `:9101`,
config `~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`).

## Goal

Build the cutandrun 3.1 template plus the `seacr` catalog tool it needs, reuse the `macs2`
tool the chipseq workstream built, and drive `depictio-cli run` against the real AWS megatest
output end to end. cutandrun is the third and last pipeline in this lot whose MultiQC report
predates the parquet era, and the only one that runs two peak callers over the same
fragments, which is what the template's middle tab is about.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/cutandrun/results-42502fb44975e930eec865353c5481f472bcf766/`
(the 3.1 release tag). Six samples: H3K4me3 and H3K27me3 in two replicates each, plus two IgG
controls. All six reach the read QC panels; the four target samples reach the peak
collections, because SEACR calls the targets against the controls and a control has no peaks
of its own.

```bash
python scripts/nfcore_megatest.py fetch --pipeline cutandrun --version 3.1 \
  --dest ~/Data/depictio-nfcore/cutandrun/3.1/megatest
# or, equivalently:
bash depictio/projects/nf-core/cutandrun/3.1/download_test_data.sh
```

The manifest (`megatest.yaml`) fetches 103 files, 89.8 MB: the samplesheet, the software
versions, the original MultiQC 1.14 report's provenance files, every raw MultiQC input
(FastQC zips, Trim Galore reports, bowtie2 logs for both the target genome and the spike-in,
samtools stats, flagstat and idxstats, deepTools fingerprint, PCA and correlation tables),
the SEACR stringent peak calls, the MACS2 peak calls, the per-target consensus peak counts
and the fragment-length tables. No BAM, no FASTQ, no bigWig.

## MultiQC was reprocessed: 1.14 to 1.35

cutandrun 3.1 published MultiQC 1.14, which writes `multiqc_data.json` and no parquet.
Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the QC tab is bound to a
report this repository generates:

```bash
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/cutandrun/3.1/megatest \
  --dest ~/Data/depictio-nfcore/cutandrun/3.1/megatest
```

102 inputs were staged. `REPROCESSED.json` records `source_version 1.14`, `reprocessed_with
1.35` and seven modules: `bowtie2`, `cutadapt`, `deepTools`, `fastqc`, `macs`, `samtools` and
the software-versions section.

Unlike chipseq and atacseq, whose reports predate the parquet by a whole major era, 1.14 is
close enough to 1.35 that the module set is unchanged by the upgrade: the reprocess here buys
the format, not new panels. `template.yaml`'s `dc_specific_properties.modules` and `plots` and
every `selected_module` / `selected_plot` in `dashboards/base.yaml` are nonetheless authored
against the 1.35 anchors and were verified against them, not against the published report.

## Ingestion result: 11 / 11 data collections processed, exit 0

```bash
depictio/cli/.venv/bin/python -m depictio.cli run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml \
  --template nf-core/cutandrun/3.1 \
  --data-root ~/Data/depictio-nfcore/cutandrun/3.1/megatest
```

`--project-name` was deliberately left off, so the project carries the name the template
declares (`CUT&RUN Chromatin Profiling`, id `6a9c3854f6eeff965a1052d8`, dashboard
`6a9c386430851b3fe1718358`). Delta tables read back from MinIO after the run:

| Data collection | Rows | Columns |
|---|---|---|
| `multiqc_data` | 1 report, 7 modules | (MultiQC parquet, not Delta) |
| `samples` | 6 | 9 |
| `samplesheet` | 6 | 10 |
| `seacr_peaks_raw` | 433,629 | 9 |
| `seacr_peaks` | 433,629 | 12 |
| `seacr_peak_summary` | 4 | 11 |
| `macs2_peaks` | 17,486 | 11 |
| `seacr_consensus_peaks` | 274,445 | 16 |
| `seacr_fragment_lengths_raw` | 2,713 | 5 |
| `seacr_fragment_lengths` | 2,713 | 6 |
| `caller_agreement` | 8 | 13 |

Two collections exist only so another can read them back through `dc_ref`
(`seacr_peaks_raw` -> `seacr_peaks`, `seacr_fragment_lengths_raw` ->
`seacr_fragment_lengths`): the sample id lives in the file NAME and only a scan carries the
path into the frame. Each referenced collection is declared **before** the collection that
reads it and ingestion stays sequential.

All four dashboard tabs imported (`Sequencing and enrichment QC` + `Peak calls` + `Caller
agreement` + `Consensus and reproducibility`, 35 + 20 + 13 + 13 = 81 components across 23
sections: 24 cards, 15 text tiles, 12 MultiQC panels, 11 interactive filters, 9 figures, 6
tables and 4 advanced visualisations). 41 of those tiles carry a `use:` catalog reference
that resolved (`seacr/*` 23, `multiqc/*` 12, `macs2/*` 6).

## Post-ingest verification

Every collection was read back from its Delta table in MinIO and every tile grounded against
the real frame. No FILTER MISMATCH, no 4xx, no 5xx.

**Components (81/81).** Every component resolved, all 122 named columns exist in the bound
collection, and the six catalog render roles bind columns that are present.

**Code-mode figures (4/4).** All four exec against their frame with the viewer's scope and
return a plotly `Figure`: fragment length distribution 4 traces, signal along the genome 3,
MACS2 against SEACR per sample 2, reproducible share per target 2. The other five figures are
UI mode, where a plain express call suffices.

**Cards (24/24).** `bulk_compute_cards` returns a non-null value for every card unfiltered
and a different value under the persistent sample filter, with one exception that was checked
and is genuine: `Best q-value` is `max(neg_log10_qvalue)` over the MACS2 calls and the
strongest peak (407.14) survives the filter. Headline numbers: 433629 SEACR regions, median
width 623 bp, 17486 MACS2 peaks, median MACS2 width 1069 bp, mean fold enrichment 10.9, 54.6 %
of calls reproduced by the other caller, 274445 consensus intervals, 1.37 replicates per
interval.

**Advanced visualisations (4/4).** All four project their bound columns through
`POST /advanced_viz/data`, unfiltered and with the sample filter applied: SEACR signal
manhattan 9800 of 433629 rows (sampled), MACS2 significance manhattan 8763 of 17486
(sampled), the caller dot plot 8 of 8 (not sampled), the consensus UpSet 274445 of 274445
(not sampled, as the kind demands).

**Unit tests.** `depictio/tests/models/test_catalog.py` and
`depictio/tests/models/test_shipped_dashboard_yamls.py` pass on the staged tree.
`python -m depictio.cli dev catalog validate`: 33 catalog tools valid.

## MultiQC overlap policy

| Signal | Decision |
|---|---|
| Read counts, quality, GC, adapters, trimming | **MultiQC** (`use: multiqc/fastqc`, `use: multiqc/cutadapt`) |
| Alignment to the target genome and to the spike-in | **MultiQC** (`use: multiqc/bowtie2`) |
| Mapping rate, insert size, per-contig distribution | **MultiQC** (`use: multiqc/samtools`) |
| Enrichment over the IgG control, sample PCA and correlation | **MultiQC** (`use: multiqc/deeptools`) |
| Per-region coordinates, width, total and maximum coverage | **Dedicated** (`seacr/peaks`): MultiQC has no SEACR module at all, in any version |
| Per-sample SEACR yield and coverage summary | **Dedicated** (`seacr/peak_summary`) |
| Consensus intervals and replicate support | **Dedicated** (`seacr/consensus_peaks`): MultiQC has no set-intersection view |
| Fragment length ladder | **Dedicated** (`seacr/fragment_lengths`): cutandrun writes `*.frags.len.txt` that no MultiQC module reads |
| MACS2 peak coordinates and significance | **Dedicated** (`macs2/peaks`, reused from chipseq): the MultiQC `macs` module exposes no plot, only general-statistics columns |
| Agreement between the two callers | **Dashboard-side** (`recipes/caller_agreement.py`): a composition across two collections, which the catalog policy keeps out of the catalog |

New catalog entries created here: the `seacr` tool (`peaks`, `peak_summary`,
`consensus_peaks`, `fragment_lengths`). All four are pipeline-agnostic and matched on file
name, so any CUT&RUN-family pipeline that runs SEACR lands in the same collections.

## Discrepancies

### CR-D1: the run root is a numbered stage tree, and the template pins it

cutandrun 3.1 publishes its output under `01_prealign/`, `02_alignment/`, `03_peak_calling/`
and `04_reporting/`. The manifest's keys spell those prefixes out, because the alternative
(matching on file name alone across the whole tree) would pull the spike-in alignment
statistics into the target-genome collections. Every recipe still matches on file NAME, so
the collections themselves are layout-independent; only `megatest.yaml` knows about the
numbering. A 3.2 or later run that reorganises the tree needs the manifest updated and
nothing else. This is the first thing to check before bumping the template version.

### CR-D2: MultiQC 1.14 is above the reprocess floor for modules but below it for the parquet

1.14 already parses every module 1.35 does for this run, so unlike chipseq (which gained
nothing but the format) and atacseq (which gained a whole `ataqv` module), the reprocess here
changes only the on-disk format. It is still mandatory: without it `multiqc_data` finds no
parquet and the whole QC tab is empty. Recorded because it is the counter-example that keeps
"reprocessing adds panels" from being read as a general rule.

### CR-D3: `macs2_peaks` is the only optional collection, and the agreement tile is not covered by it

`--peakcaller seacr` is a legitimate cutandrun run and produces no `macs2/` tree, so
`macs2_peaks` is declared `optional: true` and its four cards, its manhattan panel and its
table prune cleanly. `caller_agreement` is different: it is a join of the two callers per
sample, and with one caller present it degrades to a table saying each caller agrees with
itself, which reads as 100 % agreement rather than as missing data. The optional flag covers
the collection but not the derived comparison. A run with `--peakcaller seacr` is the
scenario to check (see `VALIDATION_SCENARIOS.md`, C2).

### CR-D4: SEACR's schema is not MACS2's, which is why it needed its own tool

SEACR calls regions from fragment coverage rather than from a background model, so a SEACR
row carries a total signal, a maximum signal and the sub-interval where that maximum was
reached, and no p-value and no fold enrichment at all. `macs2/peaks` cannot read it and a
shared output would have to make half its columns nullable. The `seacr` tool therefore
declares its own schema, and the two callers meet only in `caller_agreement`, which joins
them on `sample`.

That difference is also why the two manhattan panels on the Peak calls tab bind different
scores: the SEACR panel plots `log10(total signal)` at the maximum-signal position, the MACS2
panel plots `-log10(q)`. They are not comparable on the y axis and the tab's text tiles say
so.

### CR-D5: the IgG controls are samples everywhere except in the peak collections

`samples` and `samplesheet` hold six rows; `seacr_peak_summary` holds four. The two IgG
controls are what SEACR calls the targets *against*, so they have no peaks of their own. The
persistent sample filter is on the hub, which carries all six, and the `Role` control in the
left rail is a single-choice `Select` so that picking `control` visibly empties the peak
panels rather than silently showing the targets.

### CR-D6: two thirds of the consensus intervals are called by one replicate only

174048 of the 274445 consensus intervals (63 %) have `support = 1`. That is a property of
this megatest, not of the template: H3K27me3 is a broad mark and its two replicates overlap
poorly. It matters when reading the dashboard, because the consensus cards average over a set
that is mostly single-replicate, and it is why the `Replicate support` filter defaults to
showing all values rather than to the reproducible subset. The UpSet panel is the tile that
shows the split directly.

### CR-D7: the UpSet compute is asynchronous and can answer empty on first read

`POST /advanced_viz/data` returns the projected columns for the consensus UpSet immediately
(274445 of 274445 rows), but the intersection computation itself is a background job:
`/compute_upset` answered `upset job pending: 0 intersections` on the first probe after
ingest. Re-reading once the job completes returns the intersections. Nothing to fix in the
template, but a verification script that asserts on the intersection count has to wait for
the job rather than read once.

### CR-D8: no `params.json`, so nothing is auto-detected from the run

The fetched `pipeline_info/` carries the software versions (both
`software_versions.yml` and the pipeline's own `local_versions.yml`) but no `params*.json`,
so `_introspect_pipeline_params` sets no template variable and the template exposes
`DATA_ROOT` alone. Provenance is collected from the two version files. Nothing degrades:
there is no metadata-gated conditional in this template.
