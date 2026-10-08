# nf-core/funcscan 4.0.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
what the run executed to what each screen found. The template follows the family rules in
`depictio/projects/nf-core/RULES.md`; `ampliseq/2.18.0` is the reference implementation.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | Run report | Which screens and tools did the run execute? |
| Data & QC | Samples | What did each assembly yield across the four screens? |
| Data & QC | Contigs | Which contigs carry the screens' findings, and how densely? |
| Antimicrobials | Resistome | Which resistance genes do the assemblies carry, and which tools agree? |
| Antimicrobials | AMPs | Which peptide candidates look antimicrobial, and how do they cluster? |
| Metabolism | BGCs | Which biosynthetic gene clusters do the assemblies carry, and where? |
| Metabolism | CAZymes | Which carbohydrate-active enzymes do the assemblies carry, and for which substrates? |

nf-core/funcscan screens (meta)genome assemblies with four independent arms, each
aggregated into one report:

| Screen | Tools | Aggregator |
|---|---|---|
| ARG (resistance genes) | ABRicate, AMRFinderPlus, DeepARG, fARGene, RGI | hAMRonization |
| AMP (antimicrobial peptides) | ampir, Macrel, AMPlify, hmmsearch | AMPcombi |
| BGC (biosynthetic gene clusters) | antiSMASH, DeepBGC, GECCO, hmmsearch | comBGC |
| CAZyme (carbohydrate-active enzymes) | HMMER, dbCAN-sub, DIAMOND | run_dbCAN |

The funcscan samplesheet is `sample,fasta`: no experimental factor, so the template has no
`GROUP_COL` and the sample id is the only sample filter. `screening_summary`, one row per
assembly with the headline count of every screen, is the hub: every screen's collection
links to it on `sample`, so the sample filter reaches every tab. The run's MultiQC report
carries software versions only (no general statistics, no plot sections), so there is no
MultiQC tab; the versions are read back out of it on the Run report tab.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (assemblies,
  screens that ran, the gene caller and the AMP reference database), read from the run
  parameters and the screening hub.
- **Pipeline**: five steps (annotate, resistance, peptides, clusters, CAZymes). Each step
  opens the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, one per screen, each opening its tab: ARG hits, AMP
  candidates, BGC regions and CAZyme genes, each the run total with a box of the
  per-assembly counts. All four read `screening_summary`, which every route writes (a
  screen that did not run reads 0), so a route never leaves a gap in the row. A sample
  filter and an ARG-hits range above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link
  to its tab: the distinct resistance gene names and the number of ARG tools behind them,
  the peptide candidates with a best probability of at least 0.8, the leading BGC product
  class and its share of the classified regions, and the leading CAZyme substrate and its
  share of the genes with a substrate call. Below them, four figures in two rows, one per
  screen tab: the resistome sunburst beside the AMP property plane, then the BGC caller
  sunburst beside the CAZy classes per assembly. The bar of this section filters by sample
  and ARG tool.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (sample id) sit in the collapsed left panel and narrow
every tab. The `Sample sheet` section is pinned to the bottom of every child tab,
collapsed, and absent from the Overview: the screening hub table (row selection on
`sample`) above the sample sheet.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of key numbers, each card with its own colour and a secondary
that reads it (a box plot, a distribution, a gauge, a threshold, a ranking or a share), then
at most three open sections; tables and details follow, collapsed.

**Run report.** Strip: the screens that ran (a gauge out of four) and the distinct tools,
ranked by screen. Then the tool versions per screen as a bar; a screen missing there did
not run, the first thing to check when a tab is empty. The versions table is collapsed.
Filters: screen and tool.

**Samples.** Strip: the median assembly's resistance genes, high-confidence AMPs, BGC
product classes and CAZy families, each with its spread or distribution. Then the findings
per assembly and screen as grouped bars on a log axis (the screens differ by two orders of
magnitude; with Analysis mode groups, one panel per group), and the resistance load against
CAZyme capacity as a scatter (colour the AMP candidates, size the BGC regions, the four
largest labelled; a lasso picks assemblies for every tab). Filters: a range per screen.

**Contigs.** The locus layer the screens share: every screen names the contig its feature
sits on, so `contig_annotation` rebuilds it, one row per contig carrying at least one
feature. The length comes from the contig name when the assembler wrote it there (SPAdes or
MEGAHIT); other names keep the contig off the length axis. Strip: annotated contigs (a ring
by leading screen), the median contig length (with the median per leading screen) and
feature density, and the contigs where two screens or more found something. Then features against contig length (log x, no point
labels: contig ids say nothing) and the feature-density histogram. The contig table is
collapsed. Filters: leading screen, screens on the contig, length and density.

**Resistome.** Strip: ARG hits (a ring by tool), distinct gene names (the tools naming
most), the median identity of aligned hits and their median reference coverage against
ABRicate's 80% floor; HMM-based hits (fARGene) carry neither and are left out of both. Then
the gene support dot plot per assembly (the 25 genes whose identity differs most between
assemblies, ordered by tool share; size the share of tools calling the gene, colour the
mean identity), the sunburst from tool to drug class to gene (it starts at the tool
because the tools do not share a drug-class vocabulary) and the UpSet of tool agreement,
counted on the contig. Collapsed: the drug class by assembly heatmap, then the hit quality
scatter, the contig track of resistance islands and the hit table. Filters: tool, drug
class, identity and the number of tools calling a gene.

**AMPs.** Strip: AMP candidates (a ring by charge class), the median best probability
against 0.8, the median peptide length and the largest peptide cluster with the sizes of
all clusters. Then the property plane (hydrophobicity against the isoelectric point,
coloured by charge, a line at pI 7) beside the candidate record card, which waits for a
picked peptide; the physicochemistry PCA; and the cluster sizes on a log count axis. The candidate and cluster
tables are collapsed. Filters: charge class, best probability and length.

**BGCs.** Strip: BGC regions (a bar by completeness on the contig), distinct product
classes (the callers naming most, Unknown left out), the median region length and CDS
count. Then the caller to product class sunburst beside the regions per assembly, and the
region arrows, one lane per contig with the contigs carrying most regions first. A genome
view would lay every draft contig end to end, so the tab has none. Collapsed: the region
coordinates, and the caller concordance UpSet, counted on the contig because the callers
draw region boundaries differently. Filters: caller, product class and size, plus a map
section on the region-track collection.

**CAZymes.** Strip: CAZyme genes (a ring by CAZy class), the mean number of tools agreeing
(a gauge out of three), the genes with a substrate call (split by substrate) and the median
dbCAN-PUL bitscore of the gene clusters. Then the class to family to substrate sunburst,
the CAZy classes per assembly and the 15 substrates with the most gene clusters (long
dbCAN-PUL names cut at 40 characters). Collapsed: the
annotation concordance UpSet with the gene table, and the substrate table. Filters: CAZy
class, substrate and tools agreeing.

## Routes and pruning

Every screening arm is optional. A run that switched an arm off prunes that arm's data
collections, either because the files are absent or explicitly with `--var SKIP_ARG=true`,
`SKIP_AMP`, `SKIP_BGC` or `SKIP_CAZYME`.

| Route | What changes |
|---|---|
| ARG screen off | No Resistome tab, ARG tool filter, resistance row or resistome highlight. The ARG hits card reads 0. |
| AMP screen off | No AMPs tab, peptide row or property highlight. The AMP candidates card reads 0. |
| BGC screen off | No BGCs tab, product-class row or caller highlight. The BGC regions card reads 0. |
| CAZyme screen off | No CAZymes tab, substrate row or class highlight. The CAZyme genes card reads 0. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. The four
screens are written out (`screen` and `top_screen`), as are the five ARG tools and the
three BGC callers (`tool`), the charge classes and the completeness calls. Drug classes,
product classes, CAZy classes and substrates have more values than the palette: each takes
`auto:<abundance column>`, so the eight largest of the run take the palette, largest first.
Unknown product classes and unassigned substrates are grey. The code figures read the same
map: the composition bars colour by screen, and the hit quality scatter by tool, or by
Analysis mode's groups when it has some. The substrate bars take the groups' colours.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The screening hub
table and scatter select on `sample`, the contig tiles on `contig`, the hit quality scatter
and hit table on `gene_symbol`, the AMP plane and candidate table on `cds_id`, the cluster
table on `cluster_id`, the BGC region table on `contig`, the CAZyme gene
table on `family`, the substrate table on `cgc_id` and the versions table on `tool`.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline funcscan --version 4.0.0 --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/funcscan/4.0.0 --data-root <DATA_ROOT>
```
