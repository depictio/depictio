# nf-core/cutandrun 3.1: Depictio dashboards

This template turns the output of [nf-core/cutandrun](https://nf-co.re/cutandrun) 3.1 into a
single five-tab Depictio dashboard. cutandrun trims and aligns CUT&RUN libraries against both
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

- **One funnel, five tabs.** MultiQC, then Signal, then Peak calls, then Caller agreement,
  then Consensus and reproducibility. Each tab answers the question the previous one raises:
  are the libraries clean and is the target enriched over its control, what the signal
  underneath that looks like, what did each caller call, how much of that the two callers
  share, and how much of it both replicates of a target support.
- **The sample hub is the hub.** `samples` is one row per library with its target, its
  replicate number and its role (target or control). A persistent `Sample filters` section
  (sample, target, replicate, role) is pinned to the top of every tab, and the template's
  links fan a pick there out to the MultiQC panels, both peak collections, the peak summary,
  the fragment-length tables, the nucleosome classes, the spike-in factors, the signal budget
  and the caller comparison at once. `replicate` is the second real samplesheet factor and is
  filtered through `replicate_label`, its categorical twin, because an Int64 column only takes
  a slider.
- **Every tab carries filters on two levels.** The pinned persistent `Sample filters` section
  above, plus a tab-local, non-persistent section on that tab's own columns: `Alignment scope`
  on the MultiQC tab (target alignment rate, spike-in scale factor), `Signal scope` on Signal
  (nucleosome class, fragment length, coverage concentration), `Peak scope` on Peak calls
  (region width, coverage per base, contig), `Caller scope` on Caller agreement (caller, share
  reproduced) and `Consensus scope` on Consensus (replicate support, interval width, member
  peaks).
- **Every tab opens with four cards.** A `w: 2` glance strip across the full width, mostly
  multi-metric (donut, box plot, top-n, gauge). On the MultiQC tab that strip lives in the
  pinned `Sample sheet` section rather than in a grid section of its own, because a MultiQC
  tab holds MultiQC panels only and a pinned persistent section is the one exemption; it rides
  every other tab too, open rather than collapsed, so the four cards are the first row
  wherever the reader lands.
- **Pinned sample sheet, tables and thresholds.** The glance strip and the sample hub sit in
  an open `Sample sheet` section pinned to the top of every tab, and the per-sample SEACR
  summary in a collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the yield and coverage floors.
- **Selection, both ways.** The total-against-maximum-coverage scatter on the Peak calls tab
  carries `selection_enabled` on `peak_id` and both peak tables carry
  `row_selection_enabled` on the same column; the caller scatter on the Caller agreement tab
  and the comparison table do the same on `sample`. Lassoing narrows the tables, ticking rows
  narrows the panels.
- **Catalog provenance, on every bindable tile.** All 75 non-text, non-filter tiles carry a
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

`Sample sheet`, pinned open at the top of every tab, opens on the dashboard's glance strip
over the sample hub: samples by role (the donut that makes the IgG controls visible), samples
by target, the libraries behind them and the replicate depth, then the hub table itself.

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

---

![MultiQC](screenshots/sequencing-and-enrichment-qc.png)

## Signal

What the run published as a table beside the report. None of it reaches a MultiQC panel: the
fragment histogram, the Bowtie 2 logs and the three deepTools tables are files of their own.

`Signal at a glance` opens the tab with four numbers about the material itself, before any
peak is called: the fragment-length spread, the fragments measured, the spike-in scale factor
and the target alignment rate.

`Fragment length structure` is the nucleosomal ladder: a code-mode distribution figure and its
cumulative twin. For H3K4me3 the ladder should show a clear mononucleosome peak; a flat
distribution means the digestion did not work.

`Nucleosome classes` bins that same histogram at the conventional MNase boundaries:
sub-nucleosomal below 120 bp, mononucleosomal to 250 bp, dinucleosomal to 450 bp and
multi-nucleosomal above it. The donut is the composition over the libraries in view, the
stacked bar is the same split per sample, and `mono_to_sub` is the sharp-against-broad
contrast as one number per sample. On this megatest H3K27me3_R1 is the most nucleosome-heavy
library at a ratio of 8.5 and H3K4me3_R2 the least at 3.1, which is the direction a broad mark
against a sharp one should give.

`Spike-in normalisation` is what the coverage was divided by. Every library is aligned twice
and the carrier depth of the second alignment says how much material it really held; the
pipeline turns that into `normalisation_c / spikein_aligned_pairs` and applies it to the
bedGraph every caller reads. The run publishes no scale-factor table, so these rows are
recomputed from the two Bowtie 2 logs. The spread is large and meaningful: the IgG controls
carry 3 % carrier DNA and get a factor near 0.16, while H3K27me3_R1 carries 0.006 % and gets
55.9.

`Coverage concentration and sample similarity` reads the three tables behind the deepTools
panels on the MultiQC tab. `use: deeptools/fingerprint_scatter` puts every library on one
plane, coverage concentration against divergence from a uniform library, so the targets
separate from the IgG controls; `use: deeptools/pca_embedding` reads the `plotPCA` loadings
with the variance each component explains; and `use: deeptools/correlation_heatmap` reads the
correlation matrix itself, clustered on both axes, where a block spanning two targets is a
swap or a contamination.

---

## Peak calls

`SEACR peak yield` counts the regions in view, their width distribution, the total coverage
they carry and the coverage per base.

`Signal budget` is the fraction of reads in peaks, first-class rather than inferred. SEACR
reports no read count, so the fraction is built in base pairs of fragment coverage: the summed
region signal, de-scaled by the spike-in factor, over the total the fragment-length histogram
accounts for. The de-scaling is what makes it a fraction at all, and the numbers say so: the
raw ratios span 2.3 to 48 across the four targets, whose factors span 2.9 to 55.9, and
dividing the factor back out collapses them to 0.67 to 0.86. The donut is the in-peaks against
outside-peaks composition, the stacked bar is the same split per sample.

`Signal along the genome` draws every region as the interval it is on a chromosome-aware
`genome_view` axis with height `log10(total signal)`, with a `coverage_track` below it reading
the same columns through the Plotly renderer so the section still answers the question if the
genome canvas is unavailable. Under them sit a code-mode scatter of total against maximum
coverage carrying `selection_enabled` on `peak_id`, and a width histogram.

`MACS2 alongside` is the same fragments through a background-model caller: four cards (peaks,
width, fold enrichment, best q-value) and a manhattan panel over `-log10(q)`. Note that it
does not share a y axis with the SEACR genome panels above: SEACR has no p-value and no fold
enrichment at all, so its track plots coverage while the MACS2 panel plots significance.

`Peak tables`, collapsed, holds both callers' rows with row selection on `peak_id`.

The left rail filters on region width, coverage per base and contig.

---

![Peak calls](screenshots/peak-calls.png)

## Caller agreement

The tab that exists because this pipeline runs two callers over one set of fragments.

`Agreement at a glance` counts the peaks each caller made, the share each caller's calls the
other reproduced, the worst agreement in view on a gauge, and the calls only one of the two
made.

`Caller against caller` places every sample as a point with the two callers as rows in a dot
plot, next to a code-mode scatter of MACS2 yield against SEACR yield per sample, carrying
`selection_enabled` on `sample`.

`Where they diverge` holds two bars: the calls the other caller did not make, and the share
of calls the other caller reproduced.

`Comparison table` holds the eight rows (four samples times two callers) with row selection
on `sample`. The whole tab now reads the `cutandrun/caller_agreement` catalog output rather
than an inline recipe, so every tile on it carries provenance.

`macs2_peaks` is the template's only `optional: true` collection, so a SEACR-only run keeps
every other tile. This tab is the part that degrades least gracefully in that case: with one
caller present the comparison reads as complete agreement rather than as missing data. See
`VALIDATION_REPORT.md`, CR-D3.

---

![Caller agreement](screenshots/caller-agreement.png)

## Consensus and reproducibility

`Consensus at a glance` counts the merged intervals per target, the replicates per interval,
the split by support as a donut and the coverage per interval.

`Replicate agreement` is the UpSet panel over the four replicate columns of the consensus
table: which combinations of replicates call each interval.

`How reproducible` holds a code-mode bar of the reproducible share per target and a histogram
of interval width by replicate support.

Read the donut before the rest: on this megatest 63 % of the consensus intervals are called
by a single replicate, because H3K27me3 is a broad mark whose replicates overlap poorly. The
`Replicate support` filter defaults to showing every value rather than the reproducible
subset, so the cards above average over that mostly single-replicate set unless you narrow
it.

`Consensus table`, collapsed, holds the merged intervals with row selection on `peak_id`.

---

![Consensus and reproducibility](screenshots/consensus-and-reproducibility.png)

## Reproducing

```bash
# 1. Fetch the megatest subset (103 files, 90 MB)
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
