# nf-core/cutandrun 3.1: Depictio dashboards

This template turns the output of [nf-core/cutandrun](https://nf-co.re/cutandrun) 3.1 into a
single six-tab Depictio dashboard. cutandrun trims and aligns CUT&RUN libraries against both
the target genome and a spike-in, converts the alignments to fragment coverage, calls
enriched regions with SEACR against the IgG control (and, optionally, with MACS2 over the
same fragments), and merges the calls of each target into a consensus set. The dashboard
follows that chain from left to right, with one tab in the middle devoted to what the two
callers disagree about.

Data comes from the AWS megatest run
`results-42502fb44975e930eec865353c5481f472bcf766` (the 3.1 release tag): H3K4me3 and
H3K27me3 in two replicates each, plus two IgG controls.

> **This template reads a REPROCESSED MultiQC report.**
> cutandrun 3.1 published MultiQC 1.14, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so the MultiQC tab is bound
> to a report this repository generates by re-running the pinned MultiQC 1.35 over the run's
> own raw tool outputs. Unlike chipseq and atacseq, 1.14 already parsed every module 1.35
> does for this run, so the reprocess buys the format and not new panels. It is still
> mandatory: without it the MultiQC tab is empty. See the Reproducing section below and
> `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **One funnel, six tabs.** MultiQC, then Signal, then Peaks, then Caller agreement, then
  Locus, then Consensus. Each tab answers the question the previous one raises: are the
  libraries clean and is the target enriched over its control, what the signal underneath
  that looks like, what did each caller call, how much of that the two callers share, what
  the calls look like on one region, and how much of it both replicates of a target support.
- **Genome build is a variable.** `GENOME` (default `hg38`) feeds the `assembly` of every
  genome track on the Locus tab; pass `--var GENOME=mm10` (or any other build) for a run
  aligned elsewhere. The gene lane (`annotation`) is still fixed to `hg38`, because that
  field only takes a literal build name.
- **Controls in the tile header.** Every advanced visualisation draws its encoding controls
  as chips under the title (`controls_placement: header`) rather than behind the settings
  icon. Every threshold `RangeSlider` draws the column histogram above
  it (`show_histogram: true`).
- **The sample hub is the hub.** `samples` is one row per library with its target, its
  replicate number and its role (target or control). A persistent `Sample filters` section
  (sample, target, replicate, role; replicate and role are MultiSelects) is pinned to the top of every tab, and the template's
  links fan a pick there out to the MultiQC panels, both peak collections, the peak summary,
  the fragment-length tables, the nucleosome classes, the spike-in factors, the signal budget
  and the caller comparison at once. `replicate` is the second real samplesheet factor and is
  filtered through `replicate_label`, its categorical twin, because an Int64 column only takes
  a slider.
- **Every tab carries filters on two levels.** The pinned persistent `Sample filters` section
  above, plus a tab-local, non-persistent section on that tab's own columns: `Alignment scope`
  on the MultiQC tab (target alignment rate, spike-in scale factor), `Signal scope` on Signal
  (nucleosome class, fragment length, coverage concentration), `Peak scope` on Peaks (region
  width, coverage per base, contig), `Caller scope` on Caller agreement (caller, share
  reproduced), `Locus scope` on Locus (SEACR coverage per base, MACS2 q-value, replicate
  support) and `Consensus scope` on Consensus (replicate support, interval width, member
  peaks).
- **A glance strip on every tab.** `Cohort at a glance` is a pinned persistent four-card
  strip, open on every tab: samples by role (the donut that makes the IgG controls visible),
  samples by target, peaks called (top 3 by sample) and FRiP (box plot). A pinned persistent
  section is the one exemption that lets non-MultiQC tiles ride the MultiQC tab.
- **Pinned sample sheet, tables and thresholds.** The sample hub sits in a collapsed `Sample
  sheet` section pinned under the glance strip, and the per-sample SEACR
  summary in a collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the yield and coverage floors.
- **Selection, both ways.** Both peak tables on the Peaks tab carry `row_selection_enabled`
  on `peak_id`, and the sample hub table does the same on `sample_id`; the caller scatter on the Caller agreement tab
  and the comparison table do the same on `sample`. Lassoing narrows the tables, ticking rows
  narrows the panels.
- **Catalog provenance, on every bindable tile.** Every non-text, non-filter tile carries a
  `use:` catalog reference, so the tile chrome always says where the panel comes from:
  `seacr/*` for the SEACR panels and the nucleosome classes, `macs2/*` for the MACS2
  comparison panels, `deeptools/*` for the three tables on the Signal tab, `bowtie2/*` for the
  spike-in factors, `cutandrun/*` for the three roll-ups the pipeline assembles itself (the
  sample hub, the caller agreement and the signal budget) and `multiqc/<module>` for the
  tool-module QC panels.
- **Nothing is anchored on the stage layout.** No data collection regex, recipe glob or fetch
  key spells out the numbered `01_prealign/ 02_alignment/ 03_peak_calling/ 04_reporting/`
  prefixes; the MultiQC collection matches
  `(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$`, which finds the report whether
  a run nests it under an aligner directory or the reprocess writes it at the root.

---

## MultiQC

The main tab, and the one reading the reprocessed report.

`Cohort at a glance` and the collapsed `Sample sheet` open the tab, as they open every tab.

`Run at a glance` opens the report itself with the general statistics table: one row per
sample, pooling the FastQC, Trim Galore, bowtie2, samtools and MACS2 headline numbers, with a
read toggle for the two reads of a pair.

`Read quality` carries FastQC sequence counts, quality histograms and GC content, then the
cutadapt kept reads.

`Alignment and spike-in` is CUT&RUN specific: bowtie2 paired-end alignment rates for the
target genome and the spike-in side by side, then samtools percent mapped, insert size and
per-contig distribution. The spike-in rate is what a normalisation factor is derived from, so
a library whose spike-in alignment collapses is not comparable to the others even if its
target alignment looks fine. The two `Alignment scope` sliders in the left rail read the
spike-in table and reach these panels through a reverse link, so a rate or factor threshold
narrows the report rather than only the Signal tab.

`Enrichment over the control` is the tab's point: the deepTools fingerprint curve and its
quality metrics, which separate an enriched target from a flat IgG control, then the sample
PCA and the sample correlation matrix. Those four panels are pictures MultiQC redraws from
its own parquet; the three tables nf-core publishes behind them are read on the Signal tab.
MultiQC panels that only restated a tile on another tab were removed.

---

![MultiQC](screenshots/sequencing-and-enrichment-qc.png)

## Signal

What the run published as a table beside the report. None of it reaches a MultiQC panel: the
fragment histogram, the Bowtie 2 logs and the three deepTools tables are files of their own.

`Signal at a glance` opens the tab with four numbers about the material itself, before any
peak is called: the per-sample median fragment length (read-weighted over the fragment
histogram, `seacr/fragment_classes.sample_median_length`), the fragments measured, the
spike-in scale factor and the target alignment rate.

`Fragment length structure` is the nucleosomal ladder: a code-mode distribution figure and its
cumulative twin, with the sub-nucleosomal (0 to 120 bp) and mononucleosomal (120 to 250 bp)
windows shaded and labelled. A sharp mark shows a clear mononucleosome peak; a flat
distribution means the digestion did not work.

`Nucleosome classes` bins that same histogram at the conventional MNase boundaries:
sub-nucleosomal below 120 bp, mononucleosomal to 250 bp, dinucleosomal to 450 bp and
multi-nucleosomal above it. The cards give the class median length and `mono_to_sub`, the
sharp-against-broad contrast as one number per sample (median, box plot), and the stacked
bar is the class split per sample.

`Spike-in normalisation` is what the coverage was divided by. Every library is aligned twice
and the carrier depth of the second alignment says how much material it really held; the
pipeline turns that into `normalisation_c / spikein_aligned_pairs` and applies it to the
bedGraph every caller reads. The run publishes no scale-factor table, so these rows are
recomputed from the two Bowtie 2 logs.

`Library duplication` reads samtools flagstat on the marked-duplicate BAMs (the shared
`samtools/flagstat` recipe) and draws the duplicate share per library and against depth. The
pipeline flags duplicates in the target BAMs rather than removing them, so the share inflates
every coverage number downstream.

`Coverage concentration and sample similarity` reads the three tables behind the deepTools
panels on the MultiQC tab. `use: deeptools/fingerprint_scatter` puts every library on one
plane, coverage concentration against divergence from a uniform library, so the targets
separate from the IgG controls; `use: deeptools/pca_embedding` reads the `plotPCA` loadings
with the variance each component explains; and `use: deeptools/correlation_heatmap` reads the
correlation matrix itself, clustered on both axes.

`Signal tables`, collapsed, holds the fragment-class and spike-in rows.

---

## Peaks

`SEACR peak yield` counts the regions in view, their width distribution (histogram), the
total coverage they carry and the coverage per base, then the region-width histogram on a log
x axis.

`Fragment pile-up around the peaks` is the deepTools heatmap of a CUT&RUN run rebuilt from the
fragment BEDs the pipeline publishes (`*.frags.cut.bed`), since no bigWig or computeMatrix
output is mirrored. The catalog output `seacr/frags_profile` keeps, per sample, the 500
strongest SEACR regions whose 6 kb windows do not overlap, and counts the fragments over
every 100 bp bin of each window, per million fragments of the sample. The `signal_matrix` tile
draws regions down and offsets across, one panel per sample with the mean profile on top; a
code-mode line figure puts the mean profiles on one axis. It sits here rather than on the
Locus tab on purpose: the navigator's region reaches `seacr_frags_profile` through its region
link, which would narrow the matrix to the handful of regions on screen.

`Signal budget` is the fraction of reads in peaks, first-class rather than inferred. SEACR
reports no read count, so the fraction is built in base pairs of fragment coverage: the summed
region signal, de-scaled by the spike-in factor, over the total the fragment-length histogram
accounts for. The de-scaling is what makes it a fraction at all. The cards give the coverage
in peaks and the lowest FRiP in view.

`MACS2 alongside` is the same fragments through a background-model caller: four cards (peaks,
width, fold enrichment, best q-value against a threshold of 1.3) and a manhattan panel over
`-log10(q)`. It does not share a y axis with the SEACR panels: SEACR has no p-value and no
fold enrichment at all.

`Peak tables`, collapsed, holds both callers' rows with row selection on `peak_id`, and the
per-sample FRiP rows.

The left rail filters on region width and coverage per base (both sliders draw the column
histogram) and on contig.

---

![Peaks](screenshots/peak-calls.png)

## Caller agreement

The tab that exists because this pipeline runs two callers over one set of fragments.

`Agreement at a glance` counts the peaks each caller made, their median width, the worst
agreement in view on a gauge, and the calls only one of the two made.

`Caller against caller` puts a code-mode scatter of MACS2 yield against SEACR yield per
sample, carrying `selection_enabled` on `sample`, beside a bar of the calls the other caller
did not make.

`Comparison table`, collapsed, holds one row per sample and caller with row selection on
`sample`. The whole tab reads the `cutandrun/caller_agreement` catalog output, so every tile
on it carries provenance.

`macs2_peaks` is the template's only `optional: true` collection, so a SEACR-only run keeps
every other tile. This tab is the part that degrades least gracefully in that case: with one
caller present the comparison reads as complete agreement rather than as missing data. See
`VALIDATION_REPORT.md`, CR-D3.

---

![Caller agreement](screenshots/caller-agreement.png)

## Locus

Four tracks on one genomic region and one x axis.

`Region at a glance` counts what sits in the region in view: the SEACR regions, their
coverage per base, the MACS2 peaks and the consensus intervals. The cards follow the region
like the tracks do.

`One region, four tracks` puts the navigator on top, a `genome_view` of every SEACR region
(`use: seacr/seacr_peak_track`, rect marks, locus field in the header, `assembly:
{GENOME}`), opening on a `default_region` chosen so that every track has data there. Under
it, three tracks follow the region through the `region` links declared in `template.yaml`
(`seacr_peaks -> seacr_frags_profile`, `-> macs2_peaks`, `-> seacr_consensus_peaks`): the
fragment pile-up (`coverage_track`, one lane per sample, header switch between the Plotly
track and the GenomeSpy locus view), the MACS2 calls and the consensus intervals
(`genome_view` with `follow_region_filter`; the consensus track carries the hg38 gene lane).
With a built-in assembly a navigator fetches only the chromosome of its region, so calls on
alt and unplaced contigs are simply not drawn until the reader navigates there.

The `Locus scope` rail filters SEACR coverage per base, the MACS2 q-value and the consensus
replicate support.

---

## Consensus

`Consensus at a glance` counts the merged intervals per target, the replicates per interval,
the interval width and the coverage per interval.

`Replicate agreement` is the UpSet panel over the replicate columns of the consensus table:
which combinations of replicates call each interval.

`How reproducible` holds a code-mode bar of the reproducible share per target and a histogram
of interval width (log x axis) by replicate support.

The `Replicate support` filter defaults to showing every value rather than the reproducible
subset, so the cards average over single-replicate intervals too unless you narrow it. A
broad mark whose replicates overlap poorly shows that as a large single-replicate share.

`Consensus table`, collapsed, holds the merged intervals with row selection on `peak_id`.

---

![Consensus](screenshots/consensus-and-reproducibility.png)

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The sample tables
(pinned sample sheet and peak summary, fragment classes, spike-in factors, FRiP, caller
agreement) and the spike-in and duplication scatters select on `sample`; the peak tables,
the manhattan panel and every Locus track select on `peak_id`. The deepTools PCA emits a
selection, but its collection has no outgoing link, so it narrows no other tile.

## Reproducing

```bash
# 1. Fetch the megatest subset (107 files, about 250 MB with the four fragment BEDs)
bash depictio/projects/nf-core/cutandrun/3.1/download_test_data.sh \
  ~/Data/depictio-nfcore/cutandrun/3.1/megatest

# 2. Regenerate the MultiQC report Depictio reads (the run wrote 1.14)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/cutandrun/3.1/megatest \
  --dest ~/Data/depictio-nfcore/cutandrun/3.1/megatest

# 3. Dry run, then ingest
python -m depictio.cli run --template nf-core/cutandrun/3.1 \
  --data-root ~/Data/depictio-nfcore/cutandrun/3.1/megatest --dry-run
python -m depictio.cli run --template nf-core/cutandrun/3.1 \
  --data-root ~/Data/depictio-nfcore/cutandrun/3.1/megatest
```

Step 2 is mandatory, not optional: without it `multiqc_data` finds no parquet and the whole
MultiQC tab is empty. Keep the first `REPROCESSED.json` or delete `multiqc/multiqc_data/`
before re-running, because the source-version probe reads the parquet it just wrote.
