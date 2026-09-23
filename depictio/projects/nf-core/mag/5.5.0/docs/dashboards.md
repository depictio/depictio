# nf-core/mag 5.5.0: Depictio dashboards

One dashboard, seven tabs, read as a funnel: **MultiQC -> Assembly -> Contigs
-> Bins -> Taxonomy -> Annotation -> Bin detail**. Each tab narrows the one
before it, and the filters compose forward.

The unit here is the bin, not the sample. Three samples, four assemblers and
five binners give 479 metagenome-assembled genomes over 74 055 contigs, so the
controls that matter are the assembler, the binner, the phylum and the quality
thresholds. The sample filter is the widest of them.

## Tabs

**MultiQC.** The landing tab. This megatest publishes no `multiqc/` directory
at all, so the report is re-generated with MultiQC 1.35 from the run's own raw
outputs; eight modules parse. Read QC lives here because fastp writes JSON and
NanoPlot writes free text, neither of which a table data collection can read,
so there is no read-level table anywhere in this run and no Reads tab.

**Assembly.** Ten assemblies, one per assembler and sample. Assembled length
against contig N50 separates the two routes: the short-read assemblers produce
more bases in many more pieces, the long-read assemblers fewer bases in far
longer ones. Underneath, the contig-length ladder shows where each assembly
loses its length, in absolute bases and as a fraction of its own total, and
the Nx curve reads the whole function N50 and N75 are two points of, one curve
per assembly with the N50 marked. Its lengths come from the depth tables (the
run publishes no assembly FASTA) with QUAST's 500 bp floor, so the curve crosses
x = 50 at the QUAST N50.

**Contigs.** Every contig of at least 1 kbp, once per sample whose reads were
mapped back onto its assembly. Length against depth is the plot a binner sees
before it decides anything: contigs of one organism sit in a band of constant
depth, and a contig deep in one sample and flat in another belongs to something
only that sample carries. The scatter draws a hash sample of about 9 500 of
the 222 000 contig and sample pairs. The recruitment heatmap below it is one row per
assembly and one column per read sample, coloured by the assembly's
length-weighted mean depth: the assembly-level stand-in for the bin by sample
depth heatmap, whose input this run does not publish.

**Bins.** Completeness against contamination, the canonical MAG plot, cut into
quadrants at the MIMAG high-quality thresholds (90 percent complete, under 5
percent contaminated). Contiguity against completeness sits
below it, because a bin with a high completeness and a low N50 carries the
right genes on hundreds of fragments. The QUAST section widens the set from the
427 bins CheckM2 scored to the 479 it measured.

**Taxonomy.** GTDB-Tk only runs on the bins that pass its own thresholds, so
150 bins are placed. The sunburst reads the lineage from domain outwards, the
stacked bars read the recovered community per binning run at the rank you pick,
and the Sankey traces assembler to binner to phylum so a recovery that only one
route managed is visible directly.

**Annotation.** Prokka's per-bin feature counts. Gene density against bin size,
with the roughly 900 coding sequences per megabase a prokaryotic genome carries
drawn as a reference, is the sanity check on a bin's gene content. Transfer
RNAs against ribosomal RNAs is the half of the MIMAG standard a completeness
estimate cannot see: rRNA operons are repetitive and assemble badly, so bins
that look finished on the completeness axis routinely fail here.

**Bin detail.** The four tools joined into one row per bin. nf-core/mag has a
process that writes exactly this table and this run did not publish it, so
Depictio rebuilds it as a four-way outer join and carries a `sources_present`
column rather than dropping rows: a bin with a taxon and no CheckM2 score is a
real state of the run. The MIMAG scatter carries the same quadrants as the Bins
tab; clicking a bin fills the record card beside it (quality, assembly, genes
and lineage, with genus and species linked to GTDB), which opens on a
high-quality Klebsiella pneumoniae draft until a bin is picked. Selecting a bin
also opens its locus map, the genes drawn in the order they sit on the contig.

## Filters

Two filter sections and three grid sections are persistent and pinned, so they
ride every tab: the sample scope, the assembler and binner scope, the run's
headline numbers, the samplesheet and the per-assembly reference table. Each
tab then adds its own filters on its own columns: the MIMAG tier of the pinned
bin strip on the MultiQC tab, the ladder rung, N50 and the Nx curves on
Assembly, the read sample and depth on Contigs, completeness, contamination and
the quality band on Bins, phylum, rank and placement method on Taxonomy, gene
density and the RNA counts on Annotation, and the MIMAG tier, the bin and the
feature class on Bin detail. Every threshold slider draws its column's
distribution above it.

## Controls

The analysis controls of every scatter (axes, colour-by, reference lines), the
rank of the stacked community bars and the view switches sit in the tile header
rather than behind the settings icon.

## Reproducing

```bash
bash depictio/projects/nf-core/mag/5.5.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli run --template nf-core/mag/5.5.0 --data-root <DATA_ROOT>
```

The fetch is 673 files and 65 MB. Only METAMDBG's Prokka GFFs are pulled: all
449 would be 1.1 GB, because each GFF carries the bin's whole sequence.
