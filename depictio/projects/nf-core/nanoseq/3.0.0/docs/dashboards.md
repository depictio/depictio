# nf-core/nanoseq 3.0.0: Depictio dashboards

This template turns the output of [nf-core/nanoseq](https://nf-co.re/nanoseq) 3.0.0 into a
single six-tab Depictio dashboard. nanoseq QCs Nanopore long reads, aligns them with minimap2,
quantifies gene and transcript expression with Bambu, and (when the samplesheet asks for it)
runs DESeq2 and DEXSeq on top of those counts. The tabs follow that chain: what MultiQC
reports, how long and how good the reads are, how they aligned, what Bambu counted and whether
the libraries group by condition, which genes moved, and which transcripts changed their share
of their gene.

The template was validated against the AWS megatest run
`results-1e60482a2c4621234393a6eef8e9a104309c20ae` (the 3.0.0 release tag).

> **This template reads an ALREADY-REPROCESSED MultiQC report.**
> nanoseq 3.0.0 published MultiQC 1.11, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later); reprocess the run's own raw
> tool outputs with the pinned MultiQC 1.35 first. See `VALIDATION_REPORT.md` for the command.

---

## How the dashboard is built

- **A pinned glance strip.** Four cards open every tab: libraries by condition, reads
  basecalled, gigabases sequenced and read length N50. They are not repeated as tab cards.
- **Every tab has a scope.** A persistent `Sample filters` section (sample, condition, library
  preparation) is pinned to the top of every tab, and the template's links fan a pick out to
  NanoStat, the samtools distributions, the melted Bambu counts, the sample-structure
  collections and the MultiQC panels. Each tab adds an open, non-persistent filter section on
  its own columns.
- **MultiQC panels live on the MultiQC tab only**, minus the panels a data-collection tile
  already draws: the NanoStat summary and reads-by-quality panels (the Reads tab reads NanoStat
  itself), FastQC's length distribution (the samtools read-length profile), and samtools'
  Percent mapped and Alignment stats (the Alignment tab reads the same SN block).
- **Cards read one reading per library.** The NanoStat quality ladder has one row per library
  and Phred cutoff, so its cards are scoped to the Q10 rung with `filter_expr` and name Q10 in
  their title; the samtools percentage cards are scoped to the SN summary row. Per-library
  maxima (longest read) use a box-plot secondary, not a top-N strip.
- **Bambu's wide matrices are read long.** The `bambu/counts_gene_long` and
  `bambu/counts_transcript_long` catalog recipes melt Bambu's feature-by-sample matrices into
  one row per sample and feature (count, CPM, log CPM), so the sample picker reaches them.
- **Feature ids are readable.** When Bambu's rows are GTF attribute strings, every collection
  derived from them, including the DESeq2 results, extracts the `ENSG` / `ENST` id and promotes
  the biotype to its own filterable column, keeping the original string in `feature_label`.
- **Run-level statistics say so.** DESeq2 and DEXSeq collapse the run into one comparison, so
  their collections carry no `sample` column and the sample picker does not narrow them. The
  DESeq2 tab says so and points to the per-library counts on the Quantification tab.
- **Cross-selection on the library.** Every per-library plot (length against quality, Nx
  ladder, read-length, quality-ladder, coverage and indel curves, PCA, depth against
  complexity) and every per-library table selects on the sample column, which the sample hub
  links to every sample-keyed collection, so a pick narrows the rest of the tab. The length
  against quality scatter drives a library record card beside it, which stays a thin rail until
  a library is picked. The long gene and transcript count tables and the DESeq2 table are not
  selectable: their feature ids link to no other collection on their tab.
- **Design columns.** The design comes from an optional table declared through `METADATA_FILE`
  (sample name, or samplesheet group, in `METADATA_ID_COL`; one column per factor).
  `condition` is its `GROUP_COL` column; its columns named `protocol`, `source_replicate` and
  `run_id` feed the library preparation, source replicate and flow-cell run filters; any
  other factor rides along as an extra hub column. Without a table, `condition` is the
  samplesheet group and the three confounders read `unknown`. `replicate` and the group are
  recovered from the sample name nanoseq itself builds, `<group>_R<replicate>`; nothing else
  is read out of a sample or FASTQ name.

| Variable | Default | Role |
|---|---|---|
| `METADATA_FILE` | none | Optional design table (TSV). The bundled reference sets the vendored `input/sample_metadata.tsv`. |
| `METADATA_ID_COL` | first column | Design table id column. |
| `GROUP_COL` | first factor of `METADATA_FILE` | The factor carried as `condition`. |

## Tabs

### MultiQC

The general-statistics table, the FastQC panels (counts, per-base and per-sequence quality, GC,
N content, duplication, overrepresented sequences, status) and the samtools flagstat and
idxstats panels. The pinned `Sample sheet` section (collapsed) holds the sample hub every filter
is sourced on. A tab-local `Run scope` section narrows by flow-cell run and source replicate.

### Reads and read length

NanoStat's summary of the raw FASTQ: mean, median and spread of read length and the longest
read per library, a length-against-quality scatter (one point per library: nanoseq publishes no
per-read table) with a library record card beside it, the Nx ladder recomputed from the samtools read-length histogram (N50 marked),
and the aligned read-length profile. The quality ladder follows: the Q10 cards (share, reads,
megabases) and mean read quality, then the yield above each Phred cutoff as one curve per
library. A 2-sentence note says the flow-cell views (yield over time, channel map) need pycoQC,
which nanoseq runs only when a `sequencing_summary.txt` is supplied. Tables are collapsed at
the bottom. Filters: a mean-quality floor and an N50 range on the NanoStat summary.

### Alignment and coverage

Placement rate, per-base identity, mapped reads and supplementary alignments from the
`samtools stats` SN block, then the coverage-depth histogram and the indel length spectrum
(insertions and deletions as separate curves). The full distributions table is collapsed.
Filter: a library picker on the samtools collection.

### Quantification and sample structure

Library size, genes detected, protein-coding share and top-50 gene share; then whether the
libraries group by condition or by preparation: libraries by preparation and by flow-cell run,
a PCA on log CPM over the 500 most variable genes, a depth-against-complexity scatter and a
Spearman correlation heatmap (ward, Blues). Then the gene counts: detected-gene cards, the
per-library log-CPM distribution and the 100 most variable genes as a row-standardised heatmap.
Tables are collapsed at the bottom. Filters: biotype and a log-CPM range.

### Gene expression (DESeq2)

DESeq2 on Bambu's gene counts: direction counts, effect size, genes tested and the strongest
adjusted p-value, then one tile with three views switched from its header (volcano, MA, QQ) and
a barplot of the twenty largest effects. The 200 best-measured rows are in a collapsed table.
One `DE scope` section holds the adjusted p-value, log2 fold change, direction, biotype and
mean-expression filters.

### Isoform usage and expression

DEXSeq first: whether a transcript is used more or less relative to its siblings, with its
volcano (QQ view in the header; DEXSeq writes no mean intensity, so no MA view) and the
per-library transcript shares of the top genes, recomputed from Bambu's transcript counts. Then
isoform expression from the melted transcript matrix, and the isoform lane view, which reads
`bambu/extended_annotations.gtf` and stays empty on a quantification-only run. No sashimi view:
nanoseq publishes no splice-junction table. Filters: biotype and a log-CPM range on the
transcript counts.

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline nanoseq --version 3.0.0 \
  --dest ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest
# or, equivalently:
bash depictio/projects/nf-core/nanoseq/3.0.0/download_test_data.sh

# MultiQC reprocess (skip if multiqc/multiqc_data/multiqc.parquet + REPROCESSED.json already exist):
python -m depictio.dev_scripts.multiqc_reprocess \
  --src  ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest \
  --dest ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest

# Copy the vendored design table next to the run.
mkdir -p ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest/input
cp depictio/projects/nf-core/nanoseq/3.0.0/input/sample_metadata.tsv \
  ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest/input/

depictio-cli run --template nf-core/nanoseq/3.0.0 \
  --data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest \
  --var METADATA_FILE=~/Data/depictio-nfcore/nanoseq/3.0.0/megatest/input/sample_metadata.tsv \
  --dry-run
```
