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
| Expression | Locus | Which transcript shifts its usage, and what do its reads show? |

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
is the samplesheet group and the three others read `unknown`; the `design` collection that
holds those three columns apart from the hub is then dropped, and with it the three filters, the
two rings that count by them and the Preparations line of The run. The group and replicate are
recovered from the sample name nanoseq itself builds, `<group>_R<replicate>`; nothing else is
read out of a sample or FASTQ name. The About card says so, so a library name reads as its
condition and replicate, and the Libraries card splits the libraries by condition.

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
  reads placed (of 100%) and the significant genes (split up and down). DESeq2 tests one row
  per annotation entry (an exon, several per gene), so the card counts the distinct genes with
  a call at a 5% FDR and a two-fold change, the same number as the Gene expression tab's. A
  condition and a library filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the median share of a library's reads at Q7 or above (the basecaller's pass
  floor), the share of the expression variance on the first principal component, the genes
  DESeq2 calls up and down (distinct genes, as the Key figure counts them), and the
  transcripts DEXSeq calls. Below them, four figures in two rows, each linking its tab: the
  share of reads above each quality floor beside the library PCA, then the DESeq2 volcano
  (one point per tested annotation entry) beside the DEXSeq volcano. The narrow figures take
  a short title, the source's being cut at that width. The bar of this section filters by
  condition and library.
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
draws the NanoStat summary and its quality ladder from the data. The pinned sample filters
narrow its panels.

**Reads.** Strip: reads basecalled (with their distribution over the libraries), the median
read length N50 (with its spread), the median mean read quality (libraries against Q7, the
basecaller's pass floor) and the median share of reads at Q7 or above (a gauge). Q10 is the
good mark, drawn beside the pass floor in the figures. Then mean read length, mean quality and
yield per library as three sorted bars (nanoseq publishes no per-read table, so a scatter would
hold one point per library), a solid line at Q7 and a dashed one at Q10 on the quality panel,
with the library record card beside it, and the two ladders side by side: the Nx ladder
recomputed from the samtools read-length histogram (N50 marked) and the share of reads above
each Phred floor (Q7 marked). The NanoStat and per-floor tables are collapsed. Filters: a
mean-quality floor and an N50 range.

**Alignment.** Strip, from the `samtools stats` summary rows: the median share of reads placed
(a gauge), the median per-base identity (with its spread), reads mapped (with their
distribution) and supplementary alignments (per library, with its spread). Then the coverage
depth distribution, the indel length spectrum (no legend: two curves per library pass eight
entries, a hover names each) beside the aligned read-length profile. The distributions table is collapsed. Filter: a library picker.

**Quantification.** Strip: reads Bambu assigned (by condition), the median genes detected
(with its spread), the median protein-coding share (a gauge) and the median share of the 50 top
genes (with its distribution). Then the PCA on log CPM over the 500 most variable genes and
the Spearman correlation heatmap (two thirds of the width, cells at least 40 px, so the library
ids on both axes read; the libraries only, not the mean-correlation column). Collapsed: the 100 most variable genes, row-standardised (the
libraries only, not the variance they were ranked by; its hundred rows outgrow the tab's
budget), the libraries by preparation and by flow-cell run, the
per-library gene expression distribution, then the tables. Filters:
biotype (it also narrows the variable-gene heatmap) and a log-CPM range on the gene counts.

**Gene expression.** DESeq2 on Bambu's gene counts. The intro names the contrast the run
compares (read from the data) and says that up means higher in its first condition. Strip: the
significant genes (ranked up and down), the median log2 fold change of the up calls (with its
spread) and of the down calls (with its distribution), each direction on its own card so
neither cancels the other, and the strong effects: the genes with a call at four-fold or more
either way, ranked by biotype (a maximum significance against the 5% cut-off would always pass).
Then one volcano tile with three views (MA
from `log2_base_mean`, QQ from the raw p-values). Its dotted lines are the 0.05 adjusted p-value
and the two-fold change (log2 fold change of plus and minus 1) that colour the calls. It has no point labels (the labels are Ensembl
ids), and the twenty largest fold changes. The 200 best-measured rows are collapsed. Filters:
adjusted p-value, log2 fold change, biotype and mean expression; no direction filter, which
would empty one of the two direction cards.

**Isoform usage.** DEXSeq on Bambu's transcript counts: whether a transcript is used more or
less relative to its gene's other transcripts. Strip: the transcripts tested (against a 5%
gene-level q-value: a ring by direction would be all "not significant"), the median usage gain
and the median usage loss over the significant transcripts (a median over every tested
transcript would be noise: most are not significant), each on its own card, and the reads on
isoforms (by condition). The intro names the contrast; a gain is a higher share in its first
condition. Then
the volcano (QQ view; DEXSeq writes no mean intensity, so no MA view), without point labels and
with no fold-change cut, so its colours are DEXSeq's own calls and its dotted horizontal line is the
0.05 gene-level q-value. The per-library transcript shares of a gene's transcripts (no legend: a
hover names the transcript) are open under the filters, with the `Gene` filter first in the
filter bar: they open on the six best DEXSeq genes, and the filter picks any of the forty
best-ranked ones (up to twelve are drawn at once). The intro points at the filter and at the
Locus tab.

**Locus.** The last Expression tab, reached from the Overview and the Isoform usage intro.
Filters: direction and gene (on the DEXSeq results). Strip: the transcripts tested, the genes
they belong to, the genes with a usage gain and the transcripts the extended annotation locates.
Then, open, the DEXSeq table with the transcript record card beside it and the genome browser
right under them; the isoform lanes beside the weighted introns sit in a collapsed section of
their own under it. The table is the picker. A picked transcript fills the record card (its id
links to Ensembl), narrows the lanes to its exons (`gtf_transcripts`, through a link on the
transcript id), narrows the weighted introns the same way and frames the browser on its span.

The browser takes its calls from `isoform_loci`
(`depictio/projects/nf-core/nanoseq/recipes/isoform_loci.py`): one row per transcript DEXSeq
tested, with its span from the extended annotation and a score, `rank_score`, made of the
gene-level q-value (`-log10`, capped at 300) plus `|log2fc| / 1000`, so the transcripts of one
gene, which share their q-value, are ordered by effect size. The browser opens on the strongest
shift of usage, the header steps through the next ones (the picker lists the gene name, the
fold change and the q-value), and a transcript picked in the table frames its span. It opens on
the alignments of one library of each condition before their coverage (four tracks: the
conditions of the comparison, replicate 1 first), so the splice arcs drawn from the long reads
show at once; the `tracks` manifest lists a sample's BAM before its bigWig for that reason, and
the assembly's gene track (`show_annotation`) names the genes. The tracks wear the condition's
colour of the dashboard (`color_by: condition`, the manifest writes no colour of its own). The
Locus tab labels the loci by gene symbol (`label_column: gene_name`).
Without the extended annotation the transcripts carry no span: there is no call to frame or
step through, and the browser opens on the first region its tracks hold (a gene symbol can be
searched in its header).

Collapsed: the per-library transcript expression distribution and the transcript counts.
Filters: biotype and a log-CPM range on the transcript counts.

**Weighted introns.** The `sashimi` kind exists, and its table is built here:
`depictio/projects/nf-core/nanoseq/recipes/junctions.py` reads the exon blocks of
`bambu/extended_annotations.gtf` (`gtf_transcripts`) and Bambu's melted transcript counts
(`bambu_counts_transcript_long`) and writes one row per condition, transcript and intron:
the intron's donor and acceptor, the transcript's reads averaged over the libraries of the
condition (the arc's weight), the condition (the lane) and `known` or `novel` from Bambu's
novelty class. A transcript with one exon has no intron. Two transcripts that share an intron
each keep a row, so the arc of a shared intron is drawn once per transcript until a table pick
narrows the tile to one; that pick, read as one lane per condition, is the tile's point: the
same isoform, used at different depth in the two conditions. The collection is optional and,
like the lanes, empty on a run that let Bambu extend nothing.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | The condition is the samplesheet group; the `design` collection goes with `metadata`, and with it the preparation, source replicate and flow-cell run filters, the two rings that count by them and the Preparations line of The run (they would hold one `unknown` value). |
| No `bambu/extended_annotations.gtf` | No isoform lane view and no weighted introns; `isoform_loci` is still written but its rows have no span, so the genome browser opens on the first region that holds data instead of the strongest shift or the picked transcript. |

The flow-cell views (yield over time, channel map) need pycoQC, which nanoseq runs only when a
`sequencing_summary.txt` is supplied; the template has no tile for them.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the condition is
coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a re-import),
as are the preparation and the flow-cell run (`unknown` grey). The genome browser colours its
tracks by the manifest's `condition` column with that same map, so a bar, a table row and a
track share one hue per condition. The DE direction is written out
(up red, down blue, not significant grey), and gene biotypes are coloured
`auto:count`: the eight with the most reads take the palette. Code figures read the same map
and follow Analysis mode's groups when it has some.

## Cross-selection

Every per-library plot (the length, quality and yield bars, the ladders, the coverage, indel and
read-length curves, the PCA) and every per-library table selects on
the library, which the hub links to every sample-keyed collection, so a pick narrows the rest
of the tab. The length, quality and yield bars, coloured by condition, drive the library record card, which
waits for a pick; the picked library stays full and the others dim. The gene and transcript count tables and the DESeq2 table are not selectable: their
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

## Changes from the second review

- Quantification: the correlation heatmap is two thirds wide with cells of at least 40 px.
- Locus: the DEXSeq table, the record card and the genome browser moved from Isoform usage to a
  Locus tab of their own, linked from the Overview and the Isoform usage intro; the lanes and
  weighted introns went with them.
- Isoform usage: the `Gene` filter is the first control of the filter bar, and its description
  says what it picks.
- Volcanoes: the descriptions state the dotted lines (0.05 adjusted p-value and q-value, plus
  and minus 1 log2 fold change for DESeq2).
- Reads: the Q7 and Q10 lines, the N50 ladder and the 0.05 bar cut-off say what they are and
  where the value comes from.
- Not done: the `condition` column is written by the Bambu catalog recipes under that name, so
  the dashboard cannot read `GROUP_COL` until those recipes take a `group_col` parameter.

## Changes from the first review

- Isoform usage: the browser sat alone in a collapsed `Isoform structures` section, below the
  lanes, with the DEXSeq table that drives it in another collapsed section. The detail is now
  one open section, table and record card first, the browser under them. The manifest opened on
  coverage with four tracks and the BAMs last, so the junction arcs never showed: alignments now
  come first within each sample.
- New weighted-intron sashimi on the DEXSeq pick (recipe `junctions.py`).
- Quantification: the depth against complexity scatter (one point per library, a handful of
  points, collapsed) was dropped; the per-library readings table and cards carry the same numbers.
- Reads: the length against quality scatter (one point per library, six or so) is now three sorted
  bars with a Q7 pass line and a Q10 good line; a click on a bar still picks the library for the
  record card. Q7, the basecaller's default pass floor, replaces Q10 as the cut-off of the strip
  card, the share card, the quality ladder and the Findings row (every library of a run fell
  under Q10).
- Isoform usage: the open rows were 34 against a budget of 20. The per-library usage bars and the
  isoform lanes with the weighted introns are collapsed; the table, record card and browser stay
  open.
- Reads: the length, quality and yield bars were one colour with no mark on the picked library;
  they now take the condition's colour and dim the bars that are not picked.
- Isoform usage: the usage bars drew six fixed genes; the recipe now keeps the forty best-ranked
  and a `Gene` filter picks which are drawn. The PCA drops its explicit point size and plot style
  so the embedding's own defaults apply.
- Tab hue: each key figure card takes a shade (4, 6, 8 and 9) of its tab's colour.
- Genome tracks: the manifest dropped its fixed colour column (it won over the dashboard's
  palette) and carries the hub's `condition`; the browser colours by it. The browser opens on
  the strongest DEXSeq shift through `isoform_loci` instead of a column the annotation does not
  fill, and no longer depends on an optional collection for its locus.
- Overview and Isoform usage: the significant-gene count is the same number on the Overview, the
  Findings row and the Gene expression tab (distinct genes, not exon rows); the usage gain and
  loss cards read the significant transcripts only; both intros name the contrast; the
  strongest-significance card, trivially above its own cut-off, became the strong-effects card.
- Findings: the QC length/quality bars, squeezed into three facets at a third of the row, gave
  way to the quality ladder, which reads at that width.
- No design table: the preparation, source replicate and flow-cell run filters and rings are
  pruned with the `design` collection instead of drawing one-option controls.
