# nf-core/hic 2.0.0: Depictio dashboards

This template turns the output of [nf-core/hic](https://nf-co.re/hic) 2.0.0 into a
five-tab Depictio dashboard. hic maps Hi-C read pairs with HiC-Pro, bins and
ICE-balances them into a contact matrix with cooler, reads the A/B compartment
track and the TAD insulation score off that matrix with cooltools, and plots how
contact frequency falls off with genomic distance with hicexplorer. The dashboard
follows that chain from left to right: the MultiQC report, then the valid-pair
funnel, then the shape of the library, then the contact matrix with its 1D tracks
at one locus, then domains and compartments genome-wide.

Data comes from the AWS megatest run
`results-b4d89cfacf97a5835fba804887cf0fc7e0449e8d` (the 2.0.0 release tag): one
single sample made of three FASTQ pairs HiC-Pro merges before mapping, on the
mouse mm10 assembly (the reference dataset sets `GENOME=mm10`).

> **This template reads a REPROCESSED MultiQC report.**
> hic 2.0.0 published MultiQC 1.13, which writes `mqc_*.txt` plot-data files and
> no parquet. Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later), so
> the MultiQC tab is bound to a report this repository generates by re-running
> the pinned MultiQC 1.35 over the run's own raw tool outputs. Only `fastqc` and
> `hicpro` contributed a section to this run. See the Reproducing section below
> and `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **One funnel, five tabs.** MultiQC, Run QC, Library shape, Contact maps,
  Domains and compartments. Each tab reads the output
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
  with how many FASTQ pairs HiC-Pro merged into it. A
  persistent `Sample filters` section is pinned to the top of every tab, and
  the template's links fan a pick there out to the funnel, the contact matrix,
  the compartment, insulation and domain tracks and both distance curves at
  once. This run has one sample, so the filter has one value today; the links
  are ready for a cohort without any change.
- **One region across collections.** The Contact maps tab is a locus section:
  a `genome_view` on the TAD domains is the navigator, and three `region` links
  in `template.yaml` rename the chromosome and position it emits onto the
  contact matrix (`chrom1` / `start1`), the insulation track and the
  compartment track. The tracks live on that tab only; Domains and
  compartments is the genome-wide reading, with no track, no region and no
  chromosome filter.
- **The assembly is a variable.** `GENOME` (default `hg38`, UCSC spelling)
  lays out the Contact maps axis (`assembly` / `locus_assembly`). The domain
  navigator draws no gene lane: the viz `annotation` field only accepts the
  bundled gene tables, so a template-wide variable cannot drive it yet.
- **Resolution and window are filters, not fixed choices.** The run computed
  compartments at two resolutions and insulation at two others (with three
  window sizes each), so the Contact maps and Domains and compartments tabs
  carry local sliders rather than picking one
  for the whole dashboard. The contact matrix keeps every resolution the run
  dumped as partitions of one table and reads the one that
  fits the visible span; only P(s) keeps the finest resolution alone, because
  a curve at two bin sizes is not drawn on the same axes.
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
pairs were merged into it. The tab-local `Glance scope` filter (valid-pair
rate) narrows the pinned funnel cards.

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
and the three levels reconcile exactly with the totals HiC-Pro reports.

`The funnel in numbers`, collapsed, is the same statistics pivoted the other
way: one row per sample, one column per stage, plus the derived rates the card
strips read.

Tab-local filters narrow the flow to one mapping fate or one contact fate.

---

## Library shape

`Shape at a glance` carries the log-log slope, the trans share, the long-range
cis share and the long-range cis contact count.

`Contact probability` is P(s), the probability that two loci a distance s
apart are in contact, recomputed by `cooltools/distance_profile.py` from the
balanced contact dump. It is recomputed rather than read from a tool output
because nf-core/hic never runs `cooltools expected-cis`, and the curve the
pipeline does publish is a short pooled series. The denominator at each
separation is every bin pair that could have been observed, not the non-zero
pixels the sparse dump wrote, which is what keeps the tail from flattening
artificially. One curve per chromosome plus the pooled genome-wide curve, over
40 log-spaced distance bins.

The tile carries its own derivative panel (`profile` `derivative: true`): the
local slope d log P / d log s under the curves, on its own y axis. A slope near
-1 is the usual interphase range, a fall to -1.5 and steeper a more compact
polymer, and a bump or a plateau points to trans contamination or a large
rearrangement.

`P(s) tables`, collapsed, holds the recomputed bins and hicexplorer's
`hicPlotDistVsCounts` output as the run wrote it (pooled, one chromosome value
`all`, so it carries no chromosome filter). The hicexplorer curve is no longer
drawn: it is the same angle as the recomputed curve at a coarser grain.

---

## Contact maps

The locus tab. `Matrix at a glance` carries the balanced contact value, the
insulation score, E1 and the A/B bin split, all read on the region in view
(titled "in this region"; the genome-wide versions are on Domains and
compartments).

`Genome architecture` stacks four collections on one genomic axis, opening on
a documented default region, chr2:65-85 Mb, chosen on the reference run
because domains, insulation dips and an A/B switch all fall inside it. Type a
locus or a gene symbol in the navigator header to move it.

1. The navigator is the TAD domain track (`genome_view` on `tad_domains`, one
   rectangle per domain coloured by the insulation window it was called at,
   on the `{GENOME}` axis). Its header carries the locus field; a brush on
   its axis does the same. Either one emits a chromosome and position filter,
   and the `region` links carry it to the three tiles below.
2. The contact triangle is the binned, ICE-balanced intra-chromosomal matrix
   `cooler/contact_matrix.py` builds by joining the sparse `cooler dump`
   triplet to its bins. Every resolution the run dumped is a partition on the
   `resolution` column, and the tile reads the finest one that fits the span,
   so zooming re-bins it. Trans contacts are dropped. In triangle mode x is
   genomic position over the region the navigator shows, on the same scale as
   the tracks, and y is the separation between the two bins. Domains smaller
   than the coarsest dumped bin show in the tracks but not as triangles.
3. The insulation score, one line per window, whose dips are the boundaries
   the domains above are cut at.
4. The phased first eigenvector, one line per eigs-cis resolution: above zero
   is A.

The two 1D tracks are single `coverage_track` tiles with a `track | locus`
switch in their header. Tab-local filters choose which calls each track draws:
domain window, insulation window, compartment resolution. There is no sidebar
chromosome filter: the locus field is the section's chromosome, and a sidebar
chromosome would not travel the region links.

---

## Domains and compartments

Genome-wide, no tracks. `Domains at a glance` carries the median domain size,
the domain count broken down by chromosome, the mappable share of a domain and
the share of bins called a boundary; `Compartments at a glance` the A/B split,
the E1 spread and the first two eigenvalues. `Domain and compartment
distributions` draws domain size per insulation window (box per window) and
the A and B bins per chromosome. `Domain, insulation and compartment tables`,
collapsed, holds the domain intervals, the insulation bins, the compartment
bins and the per-chromosome eigenvalues (the latter used to be pinned on every
tab). Tab-local filters: domain window, insulation window, compartment
resolution and compartment; no chromosome filter.

**TAD domains** are the interval list `cooltools/domains.py` derives.
cooltools calls boundaries, not domains: it flags the individual bins whose
neighbourhood is depleted of crossing contacts. No module in nf-core/hic 2.x
emits an interval list (`HICEXPLORER_HICFINDTADS` never runs), so the recipe
merges runs of adjacent flagged bins into one boundary and calls a domain
everything between the end of one boundary and the start of the next, inside
one cooltools region so a domain never spans the gap between two scanned
arms. Domains are scored on how much of their span is mappable, and one that
is mostly unmappable is dropped rather than reported as an enormous TAD. The
insulation files use different window-size suffixes at the two resolutions;
the recipe discovers which windows are present rather than assuming a fixed
set.

**E1 is phased.** `cooltools eigs-cis` without a `--phasing-track` (nf-core/hic
2.0.0 passes none) returns each chromosome's E1 with an arbitrary sign,
independently per chromosome and per resolution, so the A/B call could flip
between two resolutions of the same run. `cooltools/eigenvector.py` orients E1
per sample, resolution and chromosome so that it correlates positively with
bin coverage (`1 / weight`, the inverse of cooler's balancing weight): the
open, gene-dense compartment collects more contacts, so the better-covered
side is A. The rule needs no GC or gene track and no assembly, and it gives
every resolution the same orientation because they share one coverage
profile. A chromosome whose E1 does not correlate with coverage (chrY,
typically) keeps the solver's sign.

---

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The pinned sample
sheet selects on `sample_id`; the pair statistics, pair flow, P(s) and eigenvalue tables
select on `sample`; the P(s) curve selects on `chrom`, narrowing the P(s) table and card to
the chromosome picked. The domain, insulation and compartment tables do not select: their
rows are bins and domains with no identifier column, and the arm label would select a whole
chromosome arm. The distance decay table and the domain navigator have no sibling tile to
narrow.

## What a multi-sample run would add

The reference run is a single library, so the template ships no sample
comparison tab. Nothing in it hard-codes one sample: the hub carries the
sample filter, every collection carries a sample column and the project links
route that filter to all of them, so a multi-sample run fills every card and
curve per sample without an edit. A future `Group comparison` tab (with a
`GROUP_COL` design variable, the ampliseq convention) would add replicate
correlation (the contact-matrix collection already stores the matrices side by
side), P(s) overlaid by sample or condition (the curve collection is keyed on
sample and chromosome) and compartment or boundary changes joined on bin
coordinates, which the collections carry but no tile joins yet.

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
