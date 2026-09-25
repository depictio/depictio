# nf-core/viralrecon 3.0.0: Depictio dashboards

One dashboard, five tabs, read as a funnel: **MultiQC -> Coverage & Depth ->
Lineage & Clustering -> Sample QC -> Variants**. `summary_metrics` (one row per
sample) is the source of every project link, so a filter on it reaches every
tab. The template names no virus, primer scheme or reference: texts describe
what to read, not what the reference run found.

A pinned strip of four cards (samples by lineage, median reads mapped, median
genome breadth at 10x against the 80% default floor, lineages) opens every tab
and is never repeated as a tab card. Under it, the collapsed `Sample sheet`
section holds the `summary_metrics` table.

## Tabs

**MultiQC.** MultiQC panels only. QC overview: general statistics, samples that
failed mapping, fastp, bowtie2 and mosdepth. Two collapsed sections hold the
read, alignment, variant and assembly panels, including the nf-core variant
summary panel (the fallback when a route prunes `summary_metrics`).

**Coverage & Depth.** Cards: amplicons tracked, median amplicon depth, median
genome depth, and the number of amplicon measurements under 20x (the template's
default depth floor) with the samples that carry them. Then the per-position
genome track (linear axis), the per-amplicon track (log axis) and the clustered
amplicon heatmap.

**Lineage & Clustering.** Pangolin lineage and Nextclade clade counts, the
classification flow from QC verdict to lineage to clade, and the variant-profile
PCA. In the collapsed typing tables, a lineage record card sits beside the
Pangolin table and shows the ticked sample's full call, scorpio notes included.

**Sample QC.** Cards: breadth at 1x, variants per sample, reads mapped and
missing consensus bases (medians with box plots). Coverage against variant
count and the Nextclade substitution and deletion scatter separate divergent
samples from under-sequenced ones. The sample record card sits beside the
coverage scatter and shows the sample picked there, in the Nextclade scatter
or in the Sample sheet (no default record). Below, breadth at 1x and 10x per
sample, with the 80% default floor dashed.

**Variants.** Cards on the call set, the allele frequency along the genome
(0.75, the default consensus threshold, drawn as the score line) and the
per-gene lollipops, the allele-frequency histogram and read support, calls per
gene and per sample, and the co-occurrence matrix and lineage UpSet.

## Selection

Every per-sample table (sample sheet, amplicon coverage, Pangolin, Nextclade,
variant calls) selects rows on `sample`, and the coverage and Nextclade
scatters, the variant-profile PCA, the allele-frequency track and the read
support scatter select points on it. `summary_metrics` links `sample` to every
per-sample collection, so a pick narrows the rest of the tab. Record cards sit
beside the tile that drives them and stay a thin rail until something is
picked. The coverage tracks, heatmaps, oncoplot, UpSet and bar charts do not
emit a selection.

## Filters

Persistent: the sample and lineage filters (`Sample filters`, pinned top) and
the coverage and yield floors (`QC thresholds`, pinned bottom), all on
`summary_metrics`. A non-persistent `MultiQC report` section keeps a sample list
read from the MultiQC report for the routes without `summary_metrics`. Each tab
adds its own: genome depth, amplicon and amplicon depth on Coverage, lineage,
clade and the two QC verdicts on Lineage, variant yield and missing bases on
Sample QC, gene, effect, functional class, allele frequency and depth on
Variants.

## Controls

`advanced_viz_controls: header` on every tab.

## Reproducing

```bash
bash depictio/projects/nf-core/viralrecon/3.0.0/download_test_data.sh <DATA_ROOT>
depictio-cli run --template nf-core/viralrecon/3.0.0 --data-root <DATA_ROOT>
```
