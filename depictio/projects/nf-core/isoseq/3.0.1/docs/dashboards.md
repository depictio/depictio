# nf-core/isoseq 3.0.1: Depictio dashboards

This template turns the output of [nf-core/isoseq](https://nf-co.re/isoseq) 3.0.1 into a
four-tab Depictio dashboard. isoseq builds a full-length transcriptome from PacBio Iso-Seq
reads: `ccs` makes one consensus (HiFi) read per ZMW, `lima` keeps the reads carrying both
cDNA primers (full-length, FL), `isoseq refine` removes chimeras (FLNC reads), TAMA trims the
poly(A) tails, uLTRA or minimap2 maps the reads to the genome, TAMA collapse turns the mapped
reads into transcript models per chunk and TAMA merge joins the chunks into one annotation per
sample. The template reads the per-chunk reports of every step, the TAMA merge annotation, the
reference annotation the run indexed and the MultiQC report.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the design table (`METADATA_FILE`, optional) | sample |
| `samples` | recipe over the collections below (and `metadata`) | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` (ccs, lima) | CCS chunk |
| `pbccs_zmw_yield`, `pbccs_zmw_outcomes` | `01_PBCCS/*.report.json` | library (samplesheet row) |
| `isoseq_refine_summary` | `03_ISOSEQ_REFINE/*.filter_summary.report.json` | library |
| `isoseq_insert_length` | `03_ISOSEQ_REFINE/*.report.csv` (one line per FLNC read) | sample and 100 bp bin |
| `tama_polya_tails` | `05_GSTAMA_POLYACLEANUP/*_polya_flnc_report.txt.gz` | sample and tail length |
| `tama_merge_bed_raw` | `09_GSTAMA_MERGE/<sample>.bed` | isoform (raw BED12) |
| `tama_transcripts` | the merge BED, `*_merge.txt`, `07_GSTAMA_COLLAPSE/*_trans_report.txt`, `REFERENCE_GTF` | sample and isoform |
| `tama_transcript_blocks` | the merge BED and `REFERENCE_GTF` | exon or CDS block |
| `tama_genes`, `tama_category_composition` | recipes over `tama_transcripts` | sample and gene, sample and category |

The pipeline names every per-chunk file `<sample>_<N>.chunk<X>.*`, where `N` is the samplesheet
row and `X` the chunk. The recipes sum the chunks back into libraries (`<sample>_<N>`, one per
samplesheet row, usually one SMRT cell) and libraries into samples (the prefix without `_<N>`),
the rule TAMA merge applies before it writes one annotation per sample. The pooled annotation of
`--tama_merge_all` (`all_samples`) is left out so no isoform is counted twice.

The CCS and refine collections are optional: a samplesheet row started from `lima`, `refine` or
`mapping` skips those steps, the collections are skipped with them and the hub keeps the sample
with empty funnel columns.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset | optional design table: sample id first (or a `sample` column), one column per factor |
| `METADATA_ID_COL` | first column | design table id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column | design filter and glance card |
| `REFERENCE_GTF` | `{DATA_ROOT}/ULTRA_INDEX/genome.gtf` | annotation the isoforms are classified against |
| `SKIP_MULTIQC` | unset | set for runs with `--skip_multiqc`: drops the MultiQC collection |

isoseq publishes no samplesheet and its samplesheet has no design column, so the design is an
optional table. The reference seed ships `input/sample_metadata.tsv`, written by hand for the
megatest's single sample (`tissue`, `stage`); pass `--var METADATA_FILE=... --var
GROUP_COL=tissue` to use it. Without a design table the design filter and the group card are
removed and everything else stays.

`ULTRA_INDEX/genome.gtf` exists only on the uLTRA route (the default `--aligner`). For a minimap2
run pass the GTF the run was started with as `REFERENCE_GTF`; without one every isoform is
`unclassified`, keeps its TAMA gene and the structure view shows no reference lanes.

## Tabs

1. **MultiQC.** lima's primer filtering (reads kept and rejected) per CCS chunk; the ccs panel,
   which the Reads tab redraws per library, is folded away at the bottom. The persistent glance
   strip counts samples, design groups, FLNC reads and isoforms; the per-sample summary is
   pinned, its design factors first when a design table was given.
2. **Reads.** The read funnel as one attrition card (ZMWs, CCS reads, FL reads, FLNC reads, FLNC
   reads collapsed into a final isoform), the CCS pass rate, the non-chimeric share and the
   median insert length per sample; the CCS outcome of every ZMW per library stacked to 100 %
   (libraries ordered by their passed share), the FLNC insert length and the poly(A) tail length
   distributions, and a sample plane with its record card.
3. **Isoforms.** Read support, length and novelty of the isoforms, the structural category
   composition by isoform and by FLNC read (the Level picker), isoform length per category, both
   with one fixed colour per category, and an isoform plane (length against read support) with
   its record card. Filters on category, exon structure, support and length narrow the Genes tab
   too.
4. **Genes.** Genes by status (annotated or novel), isoforms per gene (mean and histogram, since
   most genes carry one), the read share of the dominant isoform and the NIC / NNC isoform
   count; isoforms against read support per gene; the isoform structures of one gene beside its
   reference transcripts; the gene table with its record card.

## Selection

- The sample filters (hub and design table) reach every sample-keyed collection and the
  MultiQC panels, whose samples are CCS chunks (`<sample>_<N>.chunk<X>`), matched to the hub
  by prefix.
- An isoform filter (category, exon structure, support, length) keeps the genes of the isoforms
  it keeps: the gene table and the structure lanes follow, with the reference lanes of those
  genes. A row picked in the gene table draws that gene's lanes and opens its record.
- The sample and isoform planes drive their record cards.
- The structure view is not linked to the sample hub: a sample filter would drop its reference
  lanes. With several samples it draws one lane per sample and isoform.

## Methods and assumptions

- **Read support.** TAMA merge lists, for each final isoform, the TAMA collapse models it was
  built from (`*_merge.txt`); TAMA collapse reports how many reads each model collapsed
  (`num_clusters` in `*_trans_report.txt`). The support of an isoform is the sum over its
  models, so it counts FLNC reads that mapped and survived collapse, and it sums to
  `collapsed_reads` in the hub.
- **Structural categories.** Following SQANTI3, from the exact intron chain of the isoform and
  of every reference transcript on the same strand: FSM (the whole chain matches), ISM (a
  contiguous part of a reference chain), NIC (every donor and acceptor annotated, the
  combination new), NNC (at least one new donor or acceptor, at least one annotated), then,
  for isoforms sharing no annotated splice site (mono-exonic ones included), genic (overlaps a
  gene on its strand), antisense (overlaps a gene on the other strand only) and intergenic.
  Coordinates are compared exactly; TAMA already snapped them within its splice-junction
  wobble (`--splice_junction`). SQANTI's fusion, genic-intron and mono-exon sub-categories are
  not separated.
- **Gene assignment.** FSM and ISM take the gene of the matched transcript, NIC and NNC the gene
  sharing most splice sites, the others the gene overlapping most on their strand (antisense:
  on the other strand). Unassigned isoforms keep their TAMA gene, `<sample>:<gene>`, so novel
  genes are per sample.
- **Insert length.** Binned in 100 bp steps up to 15 kb; the hub's median is the first bin
  reaching half of the reads.
- **Percent cards.** Per-sample shares are shown as a box across samples (median and Tukey
  strip), never averaged over reads of different samples. Percentages in the tables are
  rounded to 2 decimals.
