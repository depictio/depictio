# nf-core/hic 2.0.0: Depictio dashboards

This template turns the output of [nf-core/hic](https://nf-co.re/hic) 2.0.0 into a
seven-tab Depictio dashboard. hic maps Hi-C read pairs with HiC-Pro, bins and
ICE-balances them into a contact matrix with cooler, reads the A/B compartment
track and the TAD insulation score off that matrix with cooltools, and plots how
contact frequency falls off with genomic distance with hicexplorer. The dashboard
follows that chain from left to right: the MultiQC report, then the valid-pair
funnel, then the shape of the library, then the contact matrix with its 1D tracks,
then compartments, then TADs, then what a multi-sample run would add.

Data comes from the AWS megatest run
`results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d` (the 2.0.0 release tag): one
mouse ES-cell sample, `HIC_ES_4`, three FASTQ pairs HiC-Pro merges before
mapping.

> **This template reads a REPROCESSED MultiQC report.**
> hic 2.0.0 published MultiQC 1.13, which writes `mqc_*.txt` plot-data files and
> no parquet. Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so
> the MultiQC tab is bound to a report this repository generates by re-running
> the pinned MultiQC 1.35 over the run's own raw tool outputs. Only `fastqc` and
> `hicpro` contributed a section to this run. See the Reproducing section below
> and `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **One funnel, seven tabs.** MultiQC, Run QC, Library shape, Contact maps,
  Compartments, TADs and boundaries, Compare samples. Each tab reads the output
  built on top of the previous one: the matrix comes from valid pairs, the
  compartment track, the insulation score and P(s) all come from the matrix.
- **HiC-Pro's numbers are read twice, on purpose.** HiC-Pro ships a full native
  MultiQC module, and those panels stay on the MultiQC tab because that is the
  report a reader may already know. But a MultiQC panel is an image: it cannot
  be filtered, its numbers cannot go in a card and nothing can join to it, so
  the valid-pair rate and the cis/trans split were invisible outside it.
  `hicpro/stats/<sample>/*` is therefore also read directly, into `pair_stats`
  (one wide funnel row per sample) and `pair_flow` (one weighted row per
  read-pair fate).
- **Four numbers ride every tab.** A pinned persistent `Run at a glance`
  section carries the pairs sequenced with the whole funnel as its strip, the
  valid-pair rate, the cis share and the cis/trans/duplicate composition, so
  the question "is this library any good?" is answered wherever the reader
  lands. Each tab then opens with its own four-card strip on its own numbers.
- **The sample hub is the hub.** `samples` is one row per Hi-C sample
  (`HIC_ES_4` here) with how many FASTQ pairs HiC-Pro merged into it. A
  persistent `Sample filters` section is pinned to the top of every tab, and
  the template's links fan a pick there out to the funnel, the contact matrix,
  the compartment, insulation and domain tracks and both distance curves at
  once. This run has one sample, so the filter has one value today; the links
  are ready for a cohort without any change.
- **Every tab that has coordinates has a chromosome filter.** Project links
  carry the sample, not the chromosome, so each coordinate collection on a tab
  gets its own `Select` on its chromosome column, grouped in one tab-local
  filter section.
- **Resolution and window are filters, not fixed choices.** The run computed
  compartments at two resolutions and insulation at two others (with three
  window sizes each), so those tabs carry local sliders rather than picking one
  for the whole dashboard. The contact matrix and P(s) are the exception: both
  keep only the finest resolution the run dumped, because a matrix or a curve
  at two bin sizes is not drawn on the same axes.
- **Catalog provenance.** Nearly every tile carries a `use:` catalog
  reference: `hicpro/*` for the funnel, `cooler/*` for the contact matrix,
  `cooltools/*` for P(s), compartments, insulation and domains,
  `hicexplorer/*` for the published distance-decay curve, and
  `multiqc/<module>` for the tool-module QC panels.
- **Everything matches on file name.** No data collection or recipe glob
  spells out `contact_maps/`, `compartments/`, `tads/`, `hicpro/stats/` or
  `distance_decay/`, so a run with a different `--outdir` layout lands in the
  same collections.

---

## MultiQC

The main tab, and the one reading the reprocessed report.

`Run at a glance`, pinned to the top of every tab, holds the four funnel cards.
`Sample sheet`, collapsed under it, holds the sample hub with how many FASTQ
pairs were merged into it.

`MultiQC general statistics` opens the report with the general statistics
table: one row per sample, pooling the FastQC and HiC-Pro headline numbers.

`Read quality` is FastQC on the two merged FASTQ files HiC-Pro maps in
two-step mode: sequence counts, per-base quality, per-sequence quality,
GC content, N content, duplication levels and the status-check heatmap. There
is no adapter-trimming module in this run, HiC-Pro's own mapping step does
the trimming.

`HiC-Pro processing` is the pipeline's signature QC: read mapping (the
two-step global/local alignment rate), read pairing, valid-pair filtering
(dangling ends, self-circles, re-ligations dropped) and the cis/trans contact
split of what survives filtering.

---

## Run QC

The same HiC-Pro statistics as numbers rather than images.

`Funnel at a glance` carries the low-quality pair rate, the duplicate rate,
the mapping-fate composition and the unique valid pairs per sample.

`Where the pairs go` is the Sankey: HiC-Pro's three decisions, one ribbon per
path, weighted by read pairs. Does the pair map uniquely at both ends? Do its
two ends sit on restriction fragments a real ligation could have joined, or is
it a dangling end, a re-ligation or a self circle? And is the surviving contact
cis or trans? Losses peel off into a `Lost` lane at the step they stopped at,
and the three levels reconcile exactly with the totals HiC-Pro reports
(536,273,614 pairs processed on this run).

`The funnel in numbers`, collapsed, is the same statistics pivoted the other
way: one row per sample, one column per stage, plus the derived rates the card
strips read.

Tab-local filters narrow the flow to one mapping fate or one contact fate.

---

## Library shape

`Shape at a glance` carries the log-log slope, the peak contact probability,
the long-range cis share and the long-range cis contact count.

`Contact probability` is P(s), the probability that two loci a distance s
apart are in contact, recomputed by `cooltools/distance_profile.py` from the
balanced contact dump. It is recomputed rather than read from a tool output
because nf-core/hic never runs `cooltools expected-cis`, and the curve the
pipeline does publish stops at 3 Mb with a single pooled series. The
denominator at each separation is every bin pair that could have been
observed, not the non-zero pixels the sparse dump wrote, which is what keeps
the tail from flattening artificially. One curve per chromosome plus the
pooled genome-wide curve, over 40 log-spaced distance bins.

Under it, the same curve differentiated in log-log space. A fractal globule
sits near -1, an equilibrium globule falls to -1.5 and steeper, and a genome
whose loop extrusion has been removed flattens out. It is its own tile rather
than a second series because a slope near -1 and a probability near 0.1 share
no scale.

`The published curve`, collapsed, keeps hicexplorer's `hicPlotDistVsCounts`
output as the run wrote it, for comparison: 13 points, pooled, from the 250 kb
matrix.

---

## Contact maps

`Matrix at a glance` carries the balanced contact value, the insulation score,
the E1 spread and the A/B bin split.

`Genome architecture` is the binned, ICE-balanced intra-chromosomal contact
matrix `cooler/contact_matrix.py` builds by joining the sparse `cooler dump`
triplet to its bins, at the finest resolution the run dumped (500 kb here).
Trans contacts are dropped: a whole-genome matrix is dominated by them, and
they would swamp the per-chromosome checkerboard the compartments are read out
of.

Stacked underneath it, on a chromosome-aware locus axis, sit the two 1D tracks
derived from the same matrix: the insulation score, whose dips are TAD
boundaries, and the first eigenvector, whose sign is the A/B compartment. This
is the layout pyGenomeTracks and FAN-C use, and it is why they share a section:
brushing a region on either track emits a chromosome and position filter the
other follows.

`Plotly fallback tracks`, collapsed, carries the same two tracks on the Plotly
coverage renderer, one chromosome at a time, smoothed.

---

## Compartments

`Compartments at a glance` carries the A/B split, the E1 spread and the first
two eigenvalues.

`The A/B track` is `cooltools/eigenvector.py`'s per-bin E1: sign, not
magnitude, marks the two compartments (conventionally A positive and
gene-dense, B negative), and its zero-crossings are compartment boundaries.
The recipe stores that sign as a `compartment` column of its own, so a reader
can filter to one compartment and colour by it instead of re-deriving the
threshold in every tile; blacklisted bins carry no value and appear in
neither. The locus track draws it over the bundled mm10 gene lane; the Plotly
track below reads one chromosome at a time.

`Compartment table`, collapsed, holds every bin's weight, its compartment call
and its three eigenvectors. The pinned `Reference tables` section, on every
tab, carries the per-chromosome eigenvalues behind the track: how much of each
chromosome's correlation structure E1 actually explains.

Tab-local filters: chromosome, compartment and resolution.

---

## TADs and boundaries

`Domains at a glance` carries the median domain size, the domain count broken
down by chromosome, the mappable share of a domain and the share of bins
called a boundary.

`TAD domains` is the interval list `cooltools/domains.py` derives. cooltools
calls boundaries, not domains: it flags the individual bins whose
neighbourhood is depleted of crossing contacts. No module in nf-core/hic 2.x
emits an interval list (`HICEXPLORER_HICFINDTADS` never runs, as the execution
trace confirms), so the recipe merges runs of adjacent flagged bins into one
boundary (a boundary at 20 kb resolution is usually two or three bins wide)
and calls a domain everything between the end of one boundary and the start of
the next, inside one cooltools region so a domain never spans the gap between
two scanned arms. Domains are scored on how much of their span is mappable,
and one that is mostly unmappable is dropped rather than reported as an
enormous TAD. On this run that turns a 30.8 Mb artefact into a 2.5 Mb
maximum, with a median domain of 160 kb at 20 kb resolution and a 300 kb
window.

The domains are drawn as rectangles on the genome axis over the mm10 gene
lane, with the same intervals on the Plotly renderer underneath.

`Insulation score` is `cooltools/insulation.py`'s per-bin log2 insulation
score, on the same axis as the domains and then one chromosome at a time. The
run scanned two resolutions (20 kb / 40 kb) with three window sizes each, and
the two files use *different* window-size suffixes at the two resolutions
(300 kb/500 kb/1 Mb vs 600 kb/1 Mb/2 Mb); the recipe discovers which windows
are actually present rather than assuming a fixed set. The window matters: a
wider window calls fewer, larger domains.

`Domain and insulation tables`, collapsed, holds both row sets.

---

## Compare samples

The run this template was validated against is a single library, so this tab
says so and shows what is already in place for a cohort: the four per-sample
numbers a Hi-C experiment is ranked on and the full per-sample funnel table.
Nothing in the dashboard hard-codes one sample. The hub carries the sample
filter, every collection carries a sample column and the project links route
that filter to all of them, so the same template run against a multi-sample
experiment fills these cards and the strips on every other tab without an
edit.

---

## Reproducing

```bash
# 1. Fetch the megatest subset (144 files, ~60 GB is the full release; the
#    manifest keeps this to the tables + raw MultiQC inputs)
bash depictio/projects/nf-core/hic/2.0.0/download_test_data.sh \
  ~/Data/depictio-nfcore/hic/2.0.0/megatest

# 2. Regenerate the MultiQC report Depictio reads (the run wrote 1.13)
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/hic/2.0.0/megatest \
  --dest ~/Data/depictio-nfcore/hic/2.0.0/megatest

# 3. Dry run, then ingest
python -m depictio.cli run --template nf-core/hic/2.0.0 \
  --data-root ~/Data/depictio-nfcore/hic/2.0.0/megatest --dry-run
python -m depictio.cli run --template nf-core/hic/2.0.0 \
  --data-root ~/Data/depictio-nfcore/hic/2.0.0/megatest
```

Step 2 is mandatory, not optional: without it `multiqc_data` finds no parquet
and the whole MultiQC tab is empty. Keep the first `REPROCESSED.json` or delete
`multiqc/multiqc_data/` before re-running, because the source-version probe
reads the parquet it just wrote.
