# nf-core/nanoseq 3.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the raw
reads to the genes and isoforms that differ between conditions. The template follows the
family rules in `depictio/projects/nf-core/RULES.md`.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did every library sequence and align as expected? |
| Data & QC | Reads | How long and how good are the reads of each library? |
| Data & QC | Alignment | How much of each library aligned, and how accurately? |
| Expression | Quantification | Do the libraries group by condition, or by preparation? |
| Expression | Gene expression | Which genes differ between the two conditions? |
| Expression | Isoform usage | Which transcripts change their share of their gene? |

The template was validated against the AWS megatest run
`results-1e60482a2c4621234393a6eef8e9a104309c20ae` (the 3.0.0 release tag).

> **This template reads an already reprocessed MultiQC report.**
> nanoseq 3.0.0 published MultiQC 1.11, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later); reprocess the run's own raw
> tool outputs with the pinned MultiQC 1.35 first. See `VALIDATION_REPORT.md` for the command.

The `samples` hub (one row per library) is the source of every sample link, so a filter on it
reaches NanoStat, samtools stats, the melted Bambu counts and the sample-structure
collections. DESeq2 and DEXSeq compare the conditions once over the whole run: their tables
carry no sample column, so the sample filters do not narrow those two tabs.

The design comes from an optional table declared through `METADATA_FILE` (sample name, or
samplesheet group, in `METADATA_ID_COL`; one column per factor). `condition` is its
`GROUP_COL` column; its columns named `protocol`, `source_replicate` and `run_id` feed the
library preparation, source replicate and flow-cell run filters. Without a table, `condition`
is the samplesheet group and the three others read `unknown`. The group and replicate are
recovered from the sample name nanoseq itself builds, `<group>_R<replicate>`; nothing else is
read out of a sample or FASTQ name.

| Variable | Default | Role |
|---|---|---|
| `METADATA_FILE` | none | Optional design table (TSV). The bundled reference sets the vendored `input/sample_metadata.tsv`. |
| `METADATA_ID_COL` | first column | Design table id column. |
| `GROUP_COL` | first factor of `METADATA_FILE` | The factor carried as `condition`. |

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters (the software versions: the run
  ships no `params.json`).
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts, read from its
  data: libraries, conditions, library preparations and reads.
- **Pipeline**: five steps (QC, align, count, genes, isoforms). Each step opens the version of
  its tool and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Libraries
  (split by condition), the median read length N50 (with its spread), the median share of
  reads placed (of 100%) and the DESeq2 calls at a 5% FDR and a two-fold change (split up and
  down). A condition and a library filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the median share of a library's reads at Q10 or above, the share of the expression
  variance on the first principal component, the genes DESeq2 calls up and down, and the
  transcripts DEXSeq calls. Below them, four figures in two rows, each linking its tab: length
  against quality per library beside the library PCA, then the DESeq2 volcano beside the
  DEXSeq volcano. The bar of this section filters by condition and library.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, library, then the library preparation, flow-cell
run and source replicate) sit in the collapsed left panel and narrow every tab with a sample
column. The `Sample sheet` section, the library design table, is pinned to the bottom of every
child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary that
reads it, then at most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, FastQC sequence counts and quality
histograms, samtools flagstat and mapped reads per contig. Collapsed: the other FastQC panels,
then the samtools percentages and XY counts. The NanoStat panels are left out: the Reads tab
draws the NanoStat summary and its quality ladder from the data. Its own sample filter reads
the MultiQC report.

**Reads.** Strip: reads basecalled (with their distribution over the libraries), the median
read length N50 (with its spread), the median mean read quality (libraries against Q10,
failing under Q7) and the median share of reads at Q10 or above (a gauge). Then mean read
length against mean quality, one point per library (nanoseq publishes no per-read table),
with the library record card beside it, and the two ladders side by side: the Nx ladder
recomputed from the samtools read-length histogram (N50 marked) and the share of reads above
each Phred floor (Q10 marked). The NanoStat and per-floor tables are collapsed. Filters: a
mean-quality floor and an N50 range.

**Alignment.** Strip, from the `samtools stats` summary rows: the median share of reads placed
(a gauge), the median per-base identity (with its spread), reads mapped (with their
distribution) and supplementary alignments (the share the three libraries with the most
hold). Then the coverage depth distribution, the indel length spectrum beside the aligned
read-length profile. The distributions table is collapsed. Filter: a library picker.

**Quantification.** Strip: reads Bambu assigned (by condition), the median genes detected
(with its spread), the median protein-coding share (a gauge) and the median share of the 50 top
genes (with its distribution). Then the PCA on log CPM over the 500 most variable genes, the
Spearman correlation heatmap (full width: library ids on both axes) and the 100 most variable
genes, row-standardised. Collapsed: depth against complexity, the libraries by preparation and
by flow-cell run, the per-library gene expression distribution, then the tables. Filters:
biotype (it also narrows the variable-gene heatmap) and a log-CPM range on the gene counts.

**Gene expression.** DESeq2 on Bambu's gene counts. Strip: the significant genes (ranked up
and down), the median log2 fold change of the up calls (with its spread) and of the down calls
(with its distribution), each direction on its own card so neither cancels the other, and the
strongest significance (rows against padj 0.05). Then one volcano tile with three views (MA
from `log2_base_mean`, QQ from the raw p-values), without point labels (the labels are Ensembl
ids), and the twenty largest fold changes. The 200 best-measured rows are collapsed. Filters:
adjusted p-value, log2 fold change, biotype and mean expression; no direction filter, which
would empty one of the two direction cards.

**Isoform usage.** DEXSeq on Bambu's transcript counts: whether a transcript is used more or
less relative to its gene's other transcripts. Strip: the transcripts tested (a ring by
direction), the median usage gain and the median usage loss, each on its own card, and the
reads on isoforms (by condition). Then the volcano (QQ view; DEXSeq writes no mean intensity,
so no MA view), without point labels, and the per-library transcript shares of the top genes.
Collapsed: the per-library transcript expression distribution, the isoform lane view (it reads
`bambu/extended_annotations.gtf` and is dropped on a quantification-only run), then the tables.
No sashimi view: nanoseq publishes no splice-junction table. Filters: biotype and a log-CPM
range on the transcript counts.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | The condition is the samplesheet group; preparation, flow-cell run and source replicate read `unknown`, so their filters and cards hold one value. |
| No `bambu/extended_annotations.gtf` | No isoform lane view. |

The flow-cell views (yield over time, channel map) need pycoQC, which nanoseq runs only when a
`sequencing_summary.txt` is supplied; the template has no tile for them.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the condition is
coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a re-import),
as are the preparation and the flow-cell run (`unknown` grey). The DE direction is written out
(up red, down blue, not significant grey), and gene biotypes are coloured
`auto:count`: the eight with the most reads take the palette. Code figures read the same map
and follow Analysis mode's groups when it has some.

## Cross-selection

Every per-library plot (length against quality, the ladders, the coverage, indel and
read-length curves, the PCA, depth against complexity) and every per-library table selects on
the library, which the hub links to every sample-keyed collection, so a pick narrows the rest
of the tab. The length against quality scatter drives the library record card, which waits for
a pick. The gene and transcript count tables and the DESeq2 table are not selectable: their
feature ids link to no other collection.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

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

depictio-cli ingest --template nf-core/nanoseq/3.0.0 \
  --data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest \
  --var METADATA_FILE=~/Data/depictio-nfcore/nanoseq/3.0.0/megatest/input/sample_metadata.tsv \
  --dry-run
```
