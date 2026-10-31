# nf-core/rnavar 1.3.0: Depictio dashboards

One dashboard: an **Overview**, then six child tabs in two groups, read as a funnel from the
reads to where the calls fall on the genome. The template follows the family rules in
`depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | What does the MultiQC report say about the alignments? |
| Data & QC | Alignment | How well did the reads align, splice and deduplicate? |
| Data & QC | Coverage | How deep do the reads cover the genome, and where? |
| Variants | Callset | How many calls does each sample yield, and how clean are they? |
| Variants | Annotation | What do the calls change in the genes they hit? (snpEff route only) |
| Variants | Genome | Are PASS variants shared between replicates, and do the reads support them? |

nf-core/rnavar calls germline variants from RNA-seq with the GATK best practices: STAR aligns the
reads in two passes, Picard MarkDuplicates flags duplicates, SplitNCigarReads cuts the spliced
reads at the introns, HaplotypeCaller calls each sample on the exon intervals and
VariantFiltration marks strand bias (FS), low quality by depth (QD) and SNP clusters. With
`--tools snpeff` (or `vep`, `merge`) the filtered calls are annotated. The BAMs (14 to 21 GB per
sample on the megatest) are never ingested as tables: the template reads STAR's own reports, the
Picard and samtools reports, the VCFs and the MultiQC report, and only the genome browser opens
the BAMs, in place (`TRACKS_URI`) or uploaded.

The pipeline does not publish its samplesheet, and the samplesheet has no design column anyway, so
the design is an optional table (`METADATA_FILE`, the sample id in a `sample` column, any other
column a factor). Every filter starts from the sample hub (`samples`, one row per sample): the links
carry a pick on a sample or a design group to every per-sample collection and to MultiQC.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the design table (`METADATA_FILE`, optional) | sample |
| `multiqc_data` | `reports/multiqc/multiqc_data/multiqc.parquet` | MultiQC row (STAR, Picard, samtools idxstats) |
| `star_log_final` | `reports/star/<s>/<s>.Log.final.out` (catalog `star/*`) | sample |
| `star_junctions` | `reports/star/<s>/<s>.SJ.out.tab` | sample, intron motif class and annotated / novel |
| `picard_markduplicates_metrics` | `reports/picard/<s>/<s>.md.metrics.txt` | sample |
| `samtools_stats_sections` | `reports/samtools/<s>/<s>.md.stats` | sample and histogram bin |
| `samtools_idxstats` | `reports/samtools/<s>/<s>.md.idxstats` (the `.aligned` twin is skipped) | sample and contig |
| `vcf_variants` | `variant_calling/<s>/<s>.haplotypecaller[.filtered].vcf.gz` | call |
| `vcf_callset_summary`, `vcf_substitution_spectrum`, `vcf_filter_breakdown` | `vcf_variants` (catalog `vcf/*`) | sample; sample and class; sample and FILTER value |
| `shared_variants` | `vcf_variants` and the hub's design group (`nf-core/rnavar/shared_variants.py`) | design group and PASS site on the primary contigs: replicates calling it, the weakest call's read depth, a `support_score` the browser opens by |
| `variant_windows` | `vcf_variants` and the hub's design group (`nf-core/rnavar/variant_windows.py`) | 1 Mb window and design group, primary contigs |
| `replicate_sharing` | `vcf_variants` and the hub (`nf-core/rnavar/replicate_sharing.py`) | design group: its PASS sites and the share every sample calls |
| `sample_concordance` | `vcf_variants` (`nf-core/rnavar/sample_concordance.py`) | square sample-by-sample matrix of shared PASS genotype calls |
| `vcf_allele_fractions` | `vcf_variants` and the hub (`nf-core/rnavar/allele_fractions.py`) | sample, variant type, read-depth class (10-19, 20-49, 50-99, 100+) and 0.05 bin of allele fraction, PASS calls read at least 10 times |
| `vcf_callset_nodesign` | `vcf_variants` (catalog `vcf/callset_summary`, a second copy) | sample; read only on a run with no design table, by the Overview's Ts/Tv card |
| `tracks` | the HaplotypeCaller VCF of each sample (filtered when VariantFiltration ran, through its `.tbi`) and its duplicate-marked BAM `preprocessing/<s>/<s>.md.bam` (through its `.bai`), each with the sample's design group (`genomic_tracks`, recipe `nf-core/rnavar/tracks.py`, declared after the hub). The rows open on the VCFs of the replicates of the group that holds the top shared variant, then their BAMs, so the reads sit under the calls; one VCF per other group, the remaining VCFs and the other BAMs follow | file |
| `snpeff_ann_variants`, `snpeff_csv_stats`, `snpeff_genes` | `annotation/<s>/*_snpEff.ann.vcf.gz`, `reports/snpeff/<s>/*_snpEff.{csv,genes.txt}` (optional) | call; sample and class; sample and gene |
| `samples` | the collections above | sample |

rnavar writes each sample's calls twice, as called and after VariantFiltration, with the same
records. `vcf_variants` reads the filtered VCF of a sample, or the unfiltered one when the run
skipped filtration, so no call is counted twice. The calls of one sample keep every record:
`is_pass` and `filter_status` say what the filters made of it.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `DATA_ROOT` | required | root of one run (`reports/`, `variant_calling/`, `annotation/`, `pipeline_info/`) |
| `METADATA_FILE` | unset (the bundled reference reads `{DATA_ROOT}/input/sample_metadata.tsv`) | design table; without it the group filter, group colours and group splits fall away |
| `METADATA_ID_COL`, `GROUP_COL`, `GROUP_COL_DISPLAY` | `sample`, first factor column | the group the filters, the Samples card and the colours use |
| `TRACKS_URI` | unset | `s3://` or `https://` folder holding the run's results: the browser then reads the VCFs and BAMs in place; unset, the files found under `DATA_ROOT` are uploaded and a tables-only run lists them all |
| `GENOME` | `hg38` | axis and gene lane of the Genome tab and the assembly of `tracks`; rnavar's `--genome GRCh38` is chr-prefixed, i.e. hg38 naming |

## Routes

The import prunes what depends on an absent collection (RULES section 13):

| Route | What goes |
| --- | --- |
| no `--tools snpeff` (the megatest) | the snpEff collections, the Annotation tab, the Annotate step and the tab's tile in the list |
| `--skip_tools variantfiltration` | nothing: `vcf_variants` and `tracks` read the unfiltered VCFs; every call is PASS |
| no design table | `metadata` and `replicate_sharing`; the hub carries one constant group (`__no_group__`, "All samples"), so the navigator draws one lane, `shared_variants` treats the whole cohort as one group, the replicate-agreement card gives its Overview slot to a Ts/Tv card (`vcf_callset_nodesign`), and the Findings row and the table on that collection go. A run with a design drops `vcf_callset_nodesign` |

## The Overview

- **Hero, About, The run**: what the pipeline does, how to read the page, and the run's genome,
  aligner, calling confidence, filter thresholds and annotation tools from `params.json`.
- **Six steps**: Align, Mark, Call, Filter, Annotate, Report, each with its settings and its tab.
- **Key figures** (filter bar: the group, then the sample): four readings of the callset. PASS
  variants (distinct sites over the samples, ranked by type), replicate agreement (the share of a
  group's PASS sites that every one of its replicates calls, a median over the groups on a gauge;
  on a run with no design table a Ts/Tv card takes its slot, with a threshold at the exonic 2.5),
  the T to C share of the PASS SNVs (the A-to-I editing signal, with its spread over the samples,
  and the 17% an even spread over six classes would give) and the calls failing a filter (median
  per sample). Each opens the Callset tab.
- **Findings**: four live rows (distinct PASS variants and the failing share, the replicate
  agreement, the T to C share, the uniquely mapped share with the duplicates beside it) and three
  highlights: unique mapping and duplication per sample from the Alignment tab (red under 60%
  uniquely mapped, amber over 80% duplicates), the substitution spectrum per sample and the
  sample-by-sample genotype concordance on a full row (a matrix labelled with sample ids needs
  the width and the height), both from the Callset tab.

## The tabs

- **MultiQC**: the general statistics first, then STAR alignment scores and summary, Picard Mark Duplicates, samtools reads per contig
  and XY counts. The megatest's report has no FastQC section.
- **Alignment**: input reads (a box over the samples), uniquely mapped, duplication and mismatch
  rate, each with a line on what a bad value means; unique mapping and duplication per sample as a sorted dot plot, the weakest unique mapping on top, with the median dashed, a red band under 60% uniquely mapped, an amber one over 80% duplicates, and the record of the picked sample (alignment,
  splicing, coverage and calls); the junctions per sample by intron motif, novel first (the level switch shows the
  annotated ones). Where each sample's reads went is on the MultiQC tab (STAR alignment scores).
  Tables collapsed.
- **Coverage**: covered bases at 10x, mapped reads (a box over the samples), mitochondrial reads
  (a threshold at 5% with a warning to 10%) and reads on alt and unplaced contigs (on GRCh38, mostly the ribosomal DNA repeats); the depth histogram of every
  sample on log axes; mapped reads by contig class. Contig table collapsed.
- **Callset**: PASS calls, Ts/Tv, het/hom ratio and calls by FILTER value, the first two with a
  working range (Ts/Tv 2.5 to 3, where exonic callsets sit; het/hom 1.5 to 2, the range outbred
  exomes report; the edges are the template's, not pipeline thresholds) and a Ts/Tv warning under 2; the genotype concordance of every pair of samples
  (the share of PASS genotype calls they have in common, clustered, with the group as a top strip),
  where replicates should sit together; the substitution spectrum per sample as stacked shares
  over six folded classes (T to C carries the A-to-I editing signal); Ts/Tv and het/hom per
  sample as sorted bars with that range shaded in green (the tab's code figure follows Analysis
  mode's groups), where a het/hom ratio below the band is often allele-specific expression, which
  RNA shows and DNA does not. Collapsed: PASS SNVs and indels per sample, the replicates of a
  group together; the allele-fraction distribution, one panel per sample, the share of the
  sample's PASS calls (read at least 10 times) in each 0.05 bin, with the heterozygous band
  (0.3 to 0.7, around the 0.5 of an even split) and the homozygous-alternate one (0.9 to 1) shaded, coloured by group; a het peak
  off 0.5 or a broad low-fraction shoulder flags contamination, allelic imbalance or artefacts.
  The read depth (class) and variant type filters on the left narrow it. The tables include the
  replicate agreement per group (with a design). A FILTER value picked on the left also narrows
  the calls.
- **Annotation** (snpEff route): annotated calls by impact, genes hit by biotype, HIGH impact calls
  and the coding allele fraction; impact classes per sample (stacked; the level switch shows snpEff's other breakdowns); the twelve commonest consequence terms, coloured by the impact class snpEff gives each term
  (a Sequence Ontology term map in the figure code; an unlisted term reads MODIFIER).
  Gene and call tables collapsed; a gene picked in the gene
  table narrows the call table.
- **Genome**: one question, "are PASS variants shared between the replicates of a cell line, and
  do the reads support them?". Cards on the shared sites first (PASS sites by the replicates
  calling them, the sites every replicate calls, the median depth of the weakest call with a
  threshold at 10 reads and a warning from 5, and the median allele fraction); then cards on the
  region in view (calls by type, distinct variants by FILTER value, allele fraction, and depth
  with the same threshold: under 10 reads an allele fraction is too coarse to tell zygosity);
  then a linked section with the navigator and the browser. Two tables are collapsed: the shared
  PASS variants (best supported first; a click frames the site) and the calls of the region.
  The Sharing filter narrows the shared variants.

### How GenomeSpy and JBrowse are connected on the Genome tab

- The **navigator** (GenomeSpy) is a summary: one lane per design group, each window the group's
  distinct PASS variants per megabase, coloured by the group as the browser colours its tracks.
  Its windows are bars, and the lane or lanes fit the tile. It does not show individual samples. A brush or a locus typed in its header sets the region of
  the tab: the cards, the call table and the browser follow it.
- The **browser** (JBrowse) is the detail: VCF lanes (calls coloured by FILTER) and the
  duplicate-marked BAMs with splice-junction arcs over the coverage, plus common dbSNP sites and
  ClinVar from UCSC. Tracks are coloured and grouped by the design group, so replicates share a
  hue. It opens on the best supported shared variant (see below) with four tracks: the calls of
  the replicates of that variant's group, then their alignments, so the reads and the arcs sit
  under the calls; the other groups and samples are in the track menu. VCFs are single-sample
  files, one lane each, not a multi-sample matrix.
- The link runs both ways. The browser follows the navigator's window (`follow_window`, on by
  default; the toolbar switch "Follow other genome tiles" turns it off), and the window of the
  browser comes back on the navigator as a dashed band when you zoom or pan it. A row clicked in
  the call table centres the browser on that call, and a click on a track picks its sample in
  the left panel.
- The stepper in the browser walks the rows of `shared_variants` by `support_score`: sites every
  replicate of a group calls come first, then sites some replicates call, then sites one replicate
  calls; inside a tier the deeper the weakest call (depth capped at 200 reads), then the higher the
  best QUAL, the higher. The first row names the group whose replicates open. Picking a cell line
  in the left panel narrows the stepper and the tracks to it. The browser's header is on, so the
  stepper and the region picker are there. `end` is the last base of the reference allele, so
  an indel is framed whole. A site shared by two lines is two rows, one per line.

The UCSC tracks are hg38 ones: on another assembly they are reported as missing and the browser opens without them.

## Changes from the third review

- Genome: the tab now asks one question (shared between replicates, supported by reads). A new
  `shared_variants` collection ranks the PASS sites of each group; the browser opens on its best row
  and `tracks` opens the replicates of that row's group, VCFs first and their BAMs under them.
  Re-ingest the run (the template gains a collection) and re-import the dashboard in place.
- Callset: the Ts/Tv and het/hom bands, the allele-fraction bands and the threshold cards say what
  the value is and where it comes from.
- Annotation: the commonest consequence terms are coloured by impact class.

## Changes from the second review

- Callset: the genotype concordance matrix (sample ids on both axes, dendrograms around it) was
  squeezed into a strip (rows 12 px tall, as for a long list); its rows are now 40 px (`min_cell_px`)
  and its tile takes nine grid rows, eight as an Overview highlight.
- Genome: the navigator draws bars instead of rectangles and no longer fixes its lane height, so its
  lanes fit the tile (4 grid rows).
