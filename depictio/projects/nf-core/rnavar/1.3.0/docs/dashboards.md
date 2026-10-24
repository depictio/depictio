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
| Variants | Genome | Where along the genome do the calls fall? |

nf-core/rnavar calls germline variants from RNA-seq with the GATK best practices: STAR aligns the
reads in two passes, Picard MarkDuplicates flags duplicates, SplitNCigarReads cuts the spliced
reads at the introns, HaplotypeCaller calls each sample on the exon intervals and
VariantFiltration marks strand bias (FS), low quality by depth (QD) and SNP clusters. With
`--tools snpeff` (or `vep`, `merge`) the filtered calls are annotated. The BAMs (14 to 21 GB per
sample on the megatest) are never read: the template reads STAR's own reports, the Picard and
samtools reports, the VCFs and the MultiQC report.

The pipeline does not publish its samplesheet, and the samplesheet has no design column anyway, so
the design is an optional table (`METADATA_FILE`, the sample id in a `sample` column, any other
column a factor). Every filter starts from the sample hub (`samples`, one row per sample): the links
carry a pick on a sample or a design group to every per-sample collection and to MultiQC.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the design table (`METADATA_FILE`, optional) | sample |
| `multiqc_data` | `reports/multiqc/multiqc_data/multiqc.parquet` | MultiQC row (STAR, Picard, samtools idxstats) |
| `star_log_final`, `star_read_fate` | `reports/star/<s>/<s>.Log.final.out` (catalog `star/*`) | sample; sample and read fate |
| `star_junctions` | `reports/star/<s>/<s>.SJ.out.tab` | sample, intron motif class and annotated / novel |
| `picard_markduplicates_metrics` | `reports/picard/<s>/<s>.md.metrics.txt` | sample |
| `samtools_stats_sections` | `reports/samtools/<s>/<s>.md.stats` | sample and histogram bin |
| `samtools_idxstats` | `reports/samtools/<s>/<s>.md.idxstats` (the `.aligned` twin is skipped) | sample and contig |
| `vcf_variants` | `variant_calling/<s>/<s>.haplotypecaller[.filtered].vcf.gz` | call |
| `vcf_callset_summary`, `vcf_substitution_spectrum`, `vcf_filter_breakdown` | `vcf_variants` (catalog `vcf/*`) | sample; sample and class; sample and FILTER value |
| `variant_windows` | `vcf_variants` | 1 Mb window of the cohort, primary contigs |
| `vcf_variant_density` | `vcf_variants` (catalog `vcf/variant_density`) | sample and 1 Mb window, primary contigs |
| `vcf_files` | the filtered VCFs and their `.tbi`, as files (`indexed_file`) | sample |
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
| `GENOME` | `hg38` | axis and gene lane of the Genome tab and the assembly of `vcf_files`; rnavar's `--genome GRCh38` is chr-prefixed, i.e. hg38 naming |

## Routes

The import prunes what depends on an absent collection (RULES section 13):

| Route | What goes |
| --- | --- |
| no `--tools snpeff` (the megatest) | the snpEff collections, the Annotation tab, the Annotate step and the tab's tile in the list |
| `--skip_tools variantfiltration` | `vcf_files` (no filtered VCF) and the file track of the Genome tab; every call is PASS |
| no design table | `metadata`; the hub carries one constant group (`__no_group__`, "All samples") |

## The Overview

- **Hero, About, The run**: what the pipeline does, how to read the page, and the run's genome,
  aligner, calling confidence, filter thresholds and annotation tools from `params.json`.
- **Six steps**: Align, Mark, Call, Filter, Annotate, Report, each with its settings and its tab.
- **Key figures** (filter bar: the group, then the sample): Samples by group, Uniquely mapped,
  PASS calls and Ts/Tv, all on the sample hub, which every route writes.
- **Findings**: four live rows (unique mapping and duplication, depth at 10x and the mitochondrial
  share, Ts/Tv and the T to C share where RNA editing folds, windows holding a call and the contig
  with most variants) and four highlights, one per analysis tab every route keeps: unique mapping
  against duplication (Alignment), the depth curves (Coverage), Ts/Tv against het/hom (Callset) and
  the variant karyotype of one sample (Genome).

## The tabs

- **MultiQC**: the general statistics first, then STAR alignment scores and summary, Picard Mark Duplicates, samtools reads per contig
  and XY counts. The megatest's report has no FastQC section.
- **Alignment**: input reads, uniquely mapped, duplication and mismatch rate; the read fate per
  sample (a stacked bar; its axis starts near the smallest unique share, a `//` marks the cut); unique mapping against duplication with the record of the picked sample (alignment,
  splicing, coverage and calls); the junctions per sample by intron motif, novel first (the level switch shows the
  annotated ones). Tables collapsed.
- **Coverage**: covered bases at 10x, mapped reads, mitochondrial reads and reads on alt and
  unplaced contigs (on GRCh38, mostly the ribosomal DNA repeats); the depth histogram of every
  sample on log axes; mapped reads by contig class; mitochondrial against unplaced-contig reads,
  one point per sample coloured by group (the tab's code figure follows Analysis mode's groups).
  Contig table collapsed.
- **Callset**: PASS calls, Ts/Tv, het/hom ratio and calls by FILTER value; Ts/Tv against het/hom
  per sample; the substitution spectrum folded onto six classes (T to C carries the A-to-I editing
  signal); allele fraction against depth for every call, coloured by FILTER. A FILTER value picked
  on the left also narrows the calls.
- **Annotation** (snpEff route): annotated calls by impact, genes hit by biotype, HIGH impact calls
  and the coding allele fraction; impact classes per sample (stacked; the level switch shows snpEff's other breakdowns); the twelve commonest consequence terms;
  allele fraction against depth by impact. Gene and call tables collapsed; a gene picked in the gene
  table narrows the call table.
- **Genome**: cards on the region in view (calls by type, distinct PASS variants, allele fraction,
  depth); the karyotype (an `ideogram` in density mode on `{GENOME}`): every chromosome drawn to
  its length and banded by one sample's distinct PASS variants per 1 Mb, the sample picked in its
  controls (eight samples are past the six karyotypes a tile draws side by side, so it does not
  facet) and narrowed by the left panel's sample filter; then the navigator over the cohort's
  windows (`default_region: first`), the calls over the gene lane with one lane per sample, and
  each sample's filtered VCF range-read from its file for the region in view (`file_window_size`
  250 Mb, so the lanes open on the whole first contig: an RNA VCF is 1 to 3 MB).
