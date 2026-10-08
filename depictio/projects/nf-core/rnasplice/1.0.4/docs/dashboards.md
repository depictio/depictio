# nf-core/rnasplice 1.0.4: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the
run to the genes whose splicing changes between conditions. It follows the family rules in
`depictio/projects/nf-core/RULES.md`; nf-core/ampliseq 2.18.0 is the reference.
nf-core/rnaseq 3.26.0 shares its `Data & QC` group and its Sample Space strip.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did trimming, alignment and quantification work for every library? |
| Data & QC | Sample Space | Do the replicates of each condition sit together? |
| Splicing | Tool Agreement | Which genes does each tool call, and where do the tools agree? |
| Splicing | Exon Usage | Which genes use their exons differently, per DEXSeq and edgeR? |
| Splicing | Transcript Usage | Which transcripts change their share of the gene, per DEXSeq DTU? |
| Splicing | Splicing Events | Which event types change, and by how much inclusion? |

nf-core/rnasplice trims reads with Trim Galore, aligns them with STAR, quantifies
transcripts with Salmon, and tests differential splicing per contrast with up to five
tests: DEXSeq on exonic bins, edgeR `diffSpliceDGE` on exons, DEXSeq on transcripts (DTU),
rMATS on junction-supported events and SUPPA2 on local events from transcript TPMs. The
design comes from the sample sheet's condition, or from the design table (`METADATA_FILE`)
when the run has one; `GROUP_COL` names the column (`GROUP_COL_DISPLAY` is the reader
label). Validated against a `-profile test_full` run on the EMBL cluster, since no AWS
megatest results are published for 1.0.4.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  contrasts, genome, aligner), read from the sample sheet, the contrast sheet and the run
  parameters.
- **Pipeline**: six steps (trim, align, exons, transcripts, events, compare). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by group), the median number of genes a library expresses (with its spread), the
  genes called by two tests or more (split by contrast) and the rMATS events called (split
  by direction of inclusion). A group and a sample filter above them narrow these four only;
  the splicing cards follow the contrast and gene filters of the left panel.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: genes called by two tests or more out of those called by any, genes with an
  exon usage call (DEXSeq), genes with a transcript switch (DEXSeq DTU) and the event type
  most rMATS calls fall in, with its share. Below them, four figures in two rows, each
  linking its tab: the UpSet of tool combinations beside the DEXSeq exon volcano, then the
  DTU volcano beside the called rMATS events per type. The bar of this section filters by
  contrast and rMATS event type.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

Two persistent filter sections sit in the collapsed left panel. `Sample filters` (group,
then sample) narrow every tab through the sample hub. `Splicing filters` (one contrast,
then genes) narrow every splicing tab through the contrast and gene links; MultiQC and
Sample Space carry no contrast and leave them out. Pick one contrast first: rnasplice
often runs a contrast and its mirror, and a gene called in both counts twice. The `Sample
sheet` section (the samples and the contrasts) is pinned to the bottom of every child tab,
collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it (a box plot, a distribution, a gauge, a ranking or a share), then at
most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only, no key-number strip. Open: general statistics, FastQC
sequence counts beside the reads Trim Galore kept, STAR's summary beside samtools' percent
mapped, then featureCounts assignments (the exon-level tests' input) beside Salmon's
fragment lengths (the transcript-level tests' input). Collapsed: adapter content, quality,
duplication and status from FastQC, STAR alignment scores, samtools stats and flagstat. Its
own sample filter reads the MultiQC report, whose library names carry read suffixes.

**Sample Space.** Strip: libraries in the TPM matrix (a ring by group), genes expressed
with their spread, genes detected with their distribution and the median TPM (the highest
libraries), the same four cards as the Sample Space tab of nf-core/rnaseq. Then the Salmon
TPM PCA, with centroids per group, beside the sample record card it fills on a pick, and
the most variable genes as a clustered, row z-scored heatmap. Collapsed: the per-sample
summary table. Filters: genes expressed and median TPM ranges.

**Tool Agreement.** Strip: genes tested (ranked by contrast), genes called by any test
(ranked by the combination of tests that call them), genes called by two or more (split by
contrast) and the median number of tests calling a called gene, on a 0 to 5 gauge. Then the
UpSet of called genes across the five tests; a test the run skipped shows an empty set.
Collapsed: the cross-tool gene table with the gene record card beside it (each test's call
and strongest evidence, the gene id linked to Ensembl). Filter: how many tests must call a
gene, which reaches the per-tool tabs through the gene links.

**Exon Usage.** Strip: DEXSeq calls (split by the direction of the gene's top bin), their
absolute fold change (a box plot), edgeR calls (a ring by direction) and their absolute
fold change (a distribution). Then the DEXSeq and edgeR gene volcanoes, one point per gene
at its most significant bin or exon. Collapsed: the two per-gene tables. Filters: call
direction and absolute fold change, per tool.

**Transcript Usage.** Strip: called transcripts (split by direction), genes with a switch
(ranked by contrast), the usage fold change of the called transcripts (a box plot, both
directions) and their mean count (a distribution). Then the DTU volcano, its View switch
drawing a QQ plot of the raw p-values. Collapsed: the transcript table. Filters: call
direction and usage fold change.

**Splicing Events.** Strip: rMATS events tested (a ring by type), rMATS calls (split by
direction of inclusion), their absolute PSI change on a 0 to 1 gauge and the event types
SUPPA2 calls most. Then the called events per type and direction for each tool, and the
rMATS and SUPPA2 volcanoes (each with a QQ view). Collapsed: the rMATS event table with the
event record card beside it (inclusion and junction reads per condition, the locus linked to
the UCSC browser on `GENOME`), and the SUPPA2 event table. Filters: event type, call and
absolute PSI change for rMATS; event type and call for SUPPA2.

## Routes and pruning

Every per-tool splicing collection is optional. A tool the run skipped prunes its cards,
figures, filters, findings row and highlight; a tab left without data is dropped, and so is
its tile under How to read. The cross-tool gene table is always built, so Tool Agreement,
the agreement key figure and the agreement row survive any combination of tools.

| Route | What changes |
|---|---|
| No `METADATA_FILE` | The sample hub keeps the sheet's condition, which `GROUP_COL` defaults to. |
| DEXSeq exon usage and edgeR both skipped | No Exon Usage tab, DEXSeq row or exon volcano highlight. |
| DEXSeq DTU skipped | No Transcript Usage tab, DTU row or DTU highlight. |
| rMATS and SUPPA2 both skipped | No Splicing Events tab, rMATS key figure, event row or event-type highlight. |
| Pseudo-alignment only (`QUANT_ROUTE=salmon`) | The PCA, the heatmap, DTU and SUPPA2 read the `salmon/` copy; STAR-based panels and tools have nothing to show. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. The group
column, the PCA's `group` and the contrast are coloured `auto` (each value takes a
colour-blind-safe colour at import, kept on a re-import). The seven event types and the
three call directions (up red, down blue, not significant grey) are written out, so the
volcanoes, the event-type bars and the cards draw a type or a direction in one colour. The
two event-type figures are code figures: they read the same map.

## Cross-selection

Tables select rows and the PCA selects points; a pick becomes a dashboard filter that
narrows the other tiles of the same collection and, through the project links, the
collections downstream of it. Row selection is on `sample` and `contrast` in the sample
sheet, `sample_id` in the sample summary (shared with the PCA), `gene_id` in the gene,
exon and transcript tables and `event_id` in the event tables. The three record cards wait
for a pick: the sample record reads the PCA, the gene record the cross-tool table, the
event record the rMATS table.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Data collections

| DC | Source | Recipe |
| --- | --- | --- |
| multiqc_data | `multiqc/multiqc_data/multiqc.parquet` (reprocessed, MultiQC 1.18 writes none) | MultiQC |
| samples | `pipeline_info/samplesheet.valid.csv` (+ `metadata`) | `recipes/samples.py` |
| metadata (optional) | `METADATA_FILE` | none (table scan) |
| contrasts | `contrastsheet/contrastsheet.valid.csv` | none (table scan) |
| sample_pca, expression_heatmap | `{QUANT_ROUTE}/tximport/salmon.merged.gene_tpm.tsv` | `salmon/sample_pca`, `salmon/top_variable_genes` |
| dexseq_exon_genes (optional) | `**/DEXSeqResults.*.csv`, `**/perGeneQValue.*.csv` | `dexseq/exon_genes` |
| edger_genes (optional) | `**/contrast_*.usage.{gene,simes,exon}.csv` | `edger/diffsplice_genes` |
| dexseq_dtu (optional) | `{QUANT_ROUTE}/**/DEXSeqResults.*.tsv`, `perGeneQValue.*.tsv` | `dexseq/dtu` |
| rmats_events (optional) | `**/*.MATS.JCEC.txt` | `rmats/events` |
| suppa_events (optional) | `{QUANT_ROUTE}/**/*_local_diffsplice.dpsi` | `suppa/local_events` |
| splicing_genes | the five tool DCs | `recipes/splicing_genes.py` |

## Variables

| Variable | Default | Role |
| --- | --- | --- |
| `METADATA_FILE` | none | optional design table; its columns join the sample hub |
| `METADATA_ID_COL` | `sample` | sample column of the design table |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `condition`, `Condition` | grouping column of the sample filter and cards |
| `QUANT_ROUTE` | `star_salmon` | which Salmon copy feeds the PCA, DTU and SUPPA2 (`salmon` for pseudo-alignment-only runs) |
| `GENOME` | `hg38` | UCSC assembly for the event locus link |
| `SPLICING_FDR` | `0.05` | FDR / q-value cut-off of every tool's call (SUPPA2 uses it on its p-value) |
| `MIN_DPSI` | `0.1` | minimal absolute PSI change of an rMATS or SUPPA2 call |
| `RMATS_MIN_READS` | `10` | mean junction reads per replicate required in both conditions |

## Method notes

- **One sign for every tool: treatment minus control.** DEXSeq reports `log2fold_<A>_<B>`
  with the control first in rnasplice, so the sign is flipped when the contrast is
  `<treatment>-<control>`. SUPPA2 reports the second condition minus the first and is
  negated. rMATS (`--b1` is the treatment) and edgeR are already oriented. Mirrored
  contrasts give mirrored effects.
- **Gene-level calls.** DEXSeq exon usage and DTU use the per-gene q-value
  (`perGeneQValue`); edgeR uses the gene F-test FDR; rMATS and SUPPA2 call a gene when at
  least one of its events is significant with an absolute PSI change of at least
  `MIN_DPSI`. The volcano x axis of the gene-level tools is the fold change of the gene's
  most significant bin or exon.
- **Composite genes.** DEXSeq (`ENSG1+ENSG2`) and SUPPA2 (`ENSG1_and_ENSG2`) merge
  overlapping genes; the cross-tool table counts such a row for each gene it names.
- **Gene symbols** come from rMATS, the only tool that reports them; other genes keep their
  Ensembl id as name.
- **Coordinates.** rMATS uses `chr`-prefixed chromosome names, the other tools the bare
  names of the annotation; the UCSC link uses the rMATS locus.

## Running it

```bash
bash download_test_data.sh            # tables only
python -m depictio.dev_scripts.multiqc_reprocess --src <dest> --dest <dest>/multiqc/multiqc_data
depictio-cli ingest --template nf-core/rnasplice/1.0.4 --data-root <dest> \
  --var METADATA_FILE=<dest>/input/metadata.tsv --var GENOME=hg19
```
