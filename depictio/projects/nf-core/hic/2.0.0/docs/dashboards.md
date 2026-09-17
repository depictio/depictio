# nf-core/hic 2.0.0: Depictio dashboards

This template turns the output of [nf-core/hic](https://nf-co.re/hic) 2.0.0 into a
four-tab Depictio dashboard. hic maps Hi-C read pairs with HiC-Pro, bins and
ICE-balances them into a contact matrix with cooler, reads the A/B compartment
track and the TAD insulation score off that matrix with cooltools, and plots how
contact frequency falls off with genomic distance with hicexplorer. The dashboard
follows that chain from left to right: sequencing and mapping QC, then the
contact matrix, then compartments, then TADs.

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

- **One funnel, four tabs.** MultiQC, then Contact matrix, then Compartments,
  then TADs and insulation. Each tab reads the output built on top of the
  previous one: the matrix comes from valid pairs, the compartment track and
  the insulation score both come from the matrix, at their own resolutions.
- **HiC-Pro's own stats stay in MultiQC.** HiC-Pro ships a full native MultiQC
  module (mapping, pairing, filtering, contact statistics), so the MultiQC tab
  carries those numbers directly rather than through a second, dedicated
  collection built from `hicpro/stats/<sample>/*`. Only the outputs with no
  MultiQC module of their own, the contact matrix (cooler), the compartment
  track and eigenvalues (cooltools eigs-cis), the insulation score (cooltools
  insulation) and the distance-decay curve (hicexplorer), get their own tab.
- **The sample hub is the hub.** `samples` is one row per Hi-C sample
  (`HIC_ES_4` here) with how many FASTQ pairs HiC-Pro merged into it. A
  persistent `Sample filters` section is pinned to the top of every tab, and
  the template's links fan a pick there out to the MultiQC panels, the contact
  matrix, the compartment and insulation tracks and the distance-decay curve
  at once. This run has one sample, so the filter has one value today; the
  links are ready for a cohort without any change.
- **Resolution is a filter, not a fixed choice.** The run computed compartments
  at two resolutions and TADs at two others (with three insulation window
  sizes each), so both tabs carry a local `Select` on `resolution` (and, on the
  TADs tab, one on `window`) rather than picking one for the whole dashboard.
  The contact matrix is the one exception: `cooler/contact_matrix.py` keeps
  only the finest resolution the run dumped, because a whole-genome matrix at
  two bin sizes is not drawn on the same axes.
- **Catalog provenance.** Nearly every tile carries a `use:` catalog
  reference: `cooler/*` for the contact matrix, `cooltools/*` for compartments
  and TADs, `hicexplorer/*` for the distance-decay curve, and
  `multiqc/<module>` for the tool-module QC panels.
- **Everything matches on file name.** No data collection or recipe glob
  spells out `contact_maps/`, `compartments/`, `tads/` or `distance_decay/`, so
  a run with a different `--outdir` layout lands in the same collections.

---

## MultiQC

The main tab, and the one reading the reprocessed report.

`Sample sheet`, collapsed at the top of every tab, holds the sample hub with
how many FASTQ pairs were merged into it.

`Run at a glance` opens the report with the general statistics table: one row
per sample, pooling the FastQC and HiC-Pro headline numbers.

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

## Contact matrix

`Genome architecture` is the binned, ICE-balanced intra-chromosomal contact
matrix `cooler/contact_matrix.py` builds by joining the sparse `cooler dump`
triplet to its bins, at the finest resolution the run dumped (500 kb here).
Trans (cross-chromosome) contacts are dropped: a whole-genome matrix is
dominated by them, and they would swamp the per-chromosome checkerboard the
compartments are read out of. `use: cooler/contact_matrix` binds the
`contact_map` kind (lot 2 of the advanced-viz build; see `VALIDATION_REPORT.md`
for the config caveat this carries until that kind's Pydantic config lands).

`Distance decay` is hicexplorer's `hicPlotDistVsCounts` curve: mean contact
frequency against genomic distance, pooled across the matrix, the standard
Hi-C library-quality signature. A smooth, monotonic decay is a clean library; a
plateau or a bump signals trans-contamination or a large structural artefact.
Only 250 kb was computed for this curve, one resolution finer than the
contact-matrix tab's, because `hicPlotDistVsCounts` ran on a third cooler file
the megatest manifest fetches for exactly this curve.

---

## Compartments

`The A/B track` is `cooltools/eigenvector.py`'s per-bin E1 track: sign, not
magnitude, marks the two compartments (conventionally A positive / gene-dense,
B negative), and its zero-crossings are compartment boundaries. Blacklisted
bins carry no value and break the line. The `Resolution` filter on the left
switches between the two resolutions the run scanned (250 kb / 500 kb).

`Compartment table`, collapsed, holds every bin's weight and its three
eigenvectors. The pinned `Reference tables` section, on every tab, carries the
per-chromosome eigenvalues behind the track: how much of each chromosome's
correlation structure E1 actually explains.

---

## TADs and insulation

`Insulation score` is `cooltools/insulation.py`'s per-bin log2 insulation
score: a bin whose neighbourhood is depleted of contacts crossing it is a TAD
boundary, and `is_boundary` is cooltools' own threshold call on the score's
local minima. The run scanned two resolutions (20 kb / 40 kb) with three
window sizes each, and the two files use *different* window-size suffixes at
the two resolutions (300 kb/500 kb/1 Mb vs 600 kb/1 Mb/2 Mb), the recipe
discovers which windows are actually present rather than assuming a fixed set,
and the `Window` and `Resolution` filters on the left narrow to one
combination.

`Insulation table`, collapsed, holds every bin's score and boundary call at
every resolution and window scanned.

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
