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
loses its length, in absolute bases and as a fraction of its own total.

**Contigs.** Every contig of at least 1 kbp, once per sample whose reads were
mapped back onto its assembly. Length against depth is the plot a binner sees
before it decides anything: contigs of one organism sit in a band of constant
depth, and a contig deep in one sample and flat in another belongs to something
only that sample carries.

**Bins.** Completeness against contamination, the canonical MAG plot, with the
5 percent MIMAG contamination line drawn. Contiguity against completeness sits
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
real state of the run. Selecting a bin opens its locus map, the genes drawn in
the order they sit on the contig.

## Filters

Two filter sections and three grid sections are persistent and pinned, so they
ride every tab: the sample scope, the assembler and binner scope, the run's
headline numbers, the samplesheet and the per-assembly reference table. Each
tab then adds its own filters on its own columns: the MIMAG tier of the pinned
bin strip on the MultiQC tab, the ladder rung and N50 on
Assembly, the read sample and depth on Contigs, completeness, contamination and
the quality band on Bins, phylum, rank and placement method on Taxonomy, gene
density and the RNA counts on Annotation, and the MIMAG tier, the bin and the
feature class on Bin detail.

## Reproducing

```bash
bash depictio/projects/nf-core/mag/5.5.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli run --template nf-core/mag/5.5.0 --data-root <DATA_ROOT>
```

The fetch is 673 files and 65 MB. Only METAMDBG's Prokka GFFs are pulled: all
449 would be 1.1 GB, because each GFF carries the bin's whole sequence.
