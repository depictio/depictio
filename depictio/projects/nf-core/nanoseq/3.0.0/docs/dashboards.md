# nf-core/nanoseq 3.0.0: Depictio dashboards

This template turns the output of [nf-core/nanoseq](https://nf-co.re/nanoseq) 3.0.0 into a
single seven-tab Depictio dashboard. nanoseq QCs Nanopore long reads, aligns them with
minimap2, quantifies gene and transcript expression with Bambu, and (when the samplesheet asks
for it) runs DESeq2 and DEXSeq on top of those counts. The dashboard follows that chain left to
right: what the run is, what the basecaller produced, how the library behaved, how it aligned,
what Bambu counted and whether the samples sit where the design says, what moved between the
conditions, and which isoforms carry it.

Data comes from the AWS megatest run `results-1e60482a2c4621234393a6eef8e9a104309c20ae` (the
3.0.0 release tag): SG-NEx A549 and K562 cell lines, cDNA and direct cDNA Nanopore RNA-seq,
3 libraries each.

> **This template reads an ALREADY-REPROCESSED MultiQC report.**
> nanoseq 3.0.0 published MultiQC 1.11, which writes `multiqc_data.json` and no parquet.
> Depictio reads only `multiqc.parquet` (MultiQC 1.31 and later); the megatest data directory
> this template was built against already carries the reprocessed report
> (`multiqc/multiqc_data/multiqc.parquet` + `REPROCESSED.json`), produced by re-running the
> pinned MultiQC 1.35 over the run's own raw tool outputs. See `VALIDATION_REPORT.md` if you
> need to reproduce that step from a fresh fetch.

---

## How the dashboard is built

- **Every tab has a scope.** A persistent `Sample filters` section is pinned to the top of every
  tab with a sample, condition and library-preparation picker, and the template's links fan a
  pick there out to NanoStat, the samtools distributions, the melted Bambu counts, the
  sample-structure collections and the MultiQC panels. Each tab then adds a non-persistent
  filter section on its own columns: a quality cutoff on read QC, a stats section and an axis
  range on the two distribution tabs, a biotype and an expression floor on quantification and
  isoforms, a direction and a mean-expression floor on the DE tab.
- **Bambu's wide matrices are read long.** Bambu writes one row per feature with a column per
  sample, which is the shape that made the earlier build of this template a single link deep.
  The `bambu/counts_gene_long` and `bambu/counts_transcript_long` catalog recipes melt those
  matrices into one row per sample and feature, with the raw count, CPM and log CPM, so every
  downstream collection carries a `sample` column and the sample picker reaches it.
- **Feature ids are readable.** The megatest's minimal test GTF makes Bambu's "gene" rows
  exon-granular (`ccds_id CCDS...; exon_id ENSE...; gene_biotype X; ENSGxxxxx`) rather than one
  row per gene. Every collection derived from Bambu here, including the DESeq2 results, is read
  through a wrapper that extracts the `ENSG` / `ENST` id and promotes the biotype to its own
  filterable column, keeping the original descriptor in `feature_label`. Volcano and MA labels
  are Ensembl ids, and biotype is a filter rather than a substring.
- **The run-level statistics say so.** DESeq2 and DEXSeq collapse the whole run into a single
  A549-vs-K562 comparison, so those three collections carry no `sample` column and the sample
  picker does not narrow them. The DE tab says this in its opening text and puts the per-library
  counts the statistics were computed from in a section of its own directly underneath, which
  does filter.
- **The pinned reference table is a view, not the whole table.** The full DESeq2 table is
  208 722 rows; pinning it to seven tabs put an unscrollable grid on every one of them. The
  `Reference tables` section now holds the 200 best-measured rows (highest mean normalised
  count), and the full table is what the volcano, MA, barplot and QQ tiles on the DE tab read.
- **Bambu, not a genome aligner's per-region output.** nanoseq's megatest run is a
  transcript-quantification run (minimap2 against a transcriptome/genome, Bambu counting), not a
  variant-calling or fusion-detection run: the samplesheet's `is_transcripts` and
  `nanopolish_fast5` columns are empty for every sample here, so no JAFFAL fusion calls and no
  nanopolish methylation output exist to show. See `VALIDATION_REPORT.md` for what the real
  megatest layout does and does not carry.

## Tabs

### Run hub

What the run is. Four NanoStat cards (reads, gigabases, N50, mean quality) over the MultiQC
general-statistics table, then the cohort design: six libraries, two cell lines, two library
preparations and three flow-cell runs. The library preparation matters here, which is why it is
a persistent filter rather than a footnote. The samplesheet names the libraries `A549_R1..R3`
and `K562_R1..R3`, but the input FASTQ names say one cDNA library and two direct-cDNA ones per
cell line, off three different flow-cell runs, so what looks like three replicates is three
preparations. A bar of Bambu library sizes closes the tab.

### Basecall and read QC

NanoStat's summary of the raw FASTQ, read straight from the report rather than through MultiQC,
so it filters and cards like any other collection: mean and median read length, the spread and
the longest read, a length-against-quality scatter of the six libraries and an N50 bar. Under
it, the quality ladder: how many reads, what share of the library and how many megabases survive
each Phred floor, as a profile with a Q10 marker, a grouped bar and a table. A collapsed
`MultiQC read panels` section carries the eight FastQC panels and NanoStat's summary table.

### Run dynamics

The flow-cell views a Nanopore run is usually watched through (cumulative yield over the
sequencing hours, quality drift as the pores age, the channel map) all read pycoQC's summary of
`sequencing_summary.txt`. nanoseq produces it when a run supplies that file and `--skip_pycoqc`
is not set; this megatest started from FASTQ, so neither exists, and the tab opens by saying so.
What the run does carry is the read-length histogram `samtools stats` records per BAM and
MultiQC never surfaces: a profile of length against read count, both axes logarithmic,
decimated to 200 geometric bins per library, beside FastQC's pre-alignment length distribution
and NanoStat's reads-by-quality panel.

### Alignment and coverage

Placement rate, per-base identity and mapped reads and bases, read out of the `samtools stats`
summary block rather than MultiQC so they filter with the rest of the dashboard. Then the two
distributions that block also carries and that nothing else shows: the coverage-depth histogram
(how evenly the reference was hit) and the indel length spectrum with insertions and deletions
as separate curves per library, which is the characteristic Nanopore error mode. A collapsed
`MultiQC alignment panels` section carries the six samtools panels.

### Quantification and sample structure

Library size, genes detected, protein-coding share and the share the top 50 genes take, then the
question the preparation filter exists for: do the libraries group by condition or by
preparation. A PCA on log CPM over the 500 most variable genes (the way DESeq2's `plotPCA` does
it), a depth-against-complexity scatter, and a Spearman correlation heatmap on the same values,
which is the plot that catches a swapped label. Under them the gene counts themselves: the 100
most variable genes as a row-standardised heatmap, the 50 highest-count genes for reference, a
box of the per-library expression distribution and the full melted matrix.

### DE and usage

DESeq2 on Bambu's gene counts: direction counts, effect size, the strongest adjusted p-value as
a gauge, then volcano, MA, a differential-abundance barplot of the twenty largest effects and a
QQ plot of the raw p-values. The adjusted p-value and log2 fold-change floors live in this tab's
own `Significance thresholds` section, next to the direction, biotype and expression controls,
because `deseq2_results` is rendered here and nowhere else. The section below it is the per-library expression those statistics
were computed from, which does follow the sample picker. Last, DEXSeq: whether one of a gene's
transcripts is used more or less relative to its siblings, holding the gene's total expression
constant. 419 features were testable and four clear the cut-off, so it gets one volcano and a
table sized to its rows rather than the two large tiles the earlier build gave it.

### Isoforms

The same matrix one level down: the transcript-level counts, the 50 highest-count transcripts as
a heatmap annotated by the gene they belong to, the per-library distribution and the full melted
transcript table. The isoform lane view underneath needs the exon coordinates, which live in
`bambu/extended_annotations.gtf`, written whenever Bambu is allowed to extend the annotation
rather than only quantify against it. This megatest was quantification-only, so the collection
behind that tile is optional and the tile is empty here; a run with the file fills it with no
change to the template.

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

depictio-cli run --template nf-core/nanoseq/3.0.0 \
  --data-root ~/Data/depictio-nfcore/nanoseq/3.0.0/megatest --dry-run
```
