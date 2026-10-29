# nf-core/raredisease 3.1.2: Depictio dashboards

One dashboard: an **Overview**, then eight child tabs in two groups, read as a funnel from the
reads to what the calls and alignments show at one locus. The template follows the family rules
in `depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | What does the MultiQC report say about reads and alignments? |
| Data & QC | Alignment | How well did the reads align, and how deep do they cover? |
| Data & QC | Family | Are the samples the family the pedigree says they are? |
| Variants | Callset | How many calls does each sample yield, and how clean are they? |
| Variants | Ranked | Which variants rank first, and which inheritance model do they fit? |
| Variants | Mitochondria | How heteroplasmic are the mitochondrial calls, and how rare? (optional branch) |
| Variants | Repeats | Do any repeat expansions or mobile element insertions stand out? (optional branches) |
| Variants | Locus | What do the calls and alignments show at one locus? |

nf-core/raredisease analyses a family, usually a trio, from short reads. The reads are aligned
(bwa-mem2 by default) and duplicates are marked; each sample is called (DeepVariant by default) and
the family is genotyped together; VEP annotates the calls and GENMOD ranks them against the pedigree,
which writes a clinical set (the gene list the run was given) inside a research set. Branches of
their own call the mitochondrial genome, repeat expansions (ExpansionHunter, annotated by Stranger),
mobile element insertions and the SMN copy number. The template reads the pipeline's own reports and
VCFs and the MultiQC report; the alignments and signal tracks are never loaded as tables, only
opened by the genome browser through their indexes.

The pipeline publishes its pedigree as a `.ped` file, so the group the filters use is the **role**
(proband, father, mother, sibling), read from it, and the affected status colours the pedigree. Every
filter starts from the sample hub (`samples`, one row per sample): the links carry a pick on a
sample, a role or a family to every per-sample collection, to MultiQC and to the genome browser's
tracks.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC row (FastQC, fastp, Picard, mosdepth) |
| `alignment_qc` | Picard alignment summary, insert size, WGS or hybrid-selection metrics, MarkDuplicates and the mosdepth summary | sample |
| `contig_depth` | mosdepth summary | sample and contig |
| `vcf_variants` | `call_snv/genome/<family>_snv.vcf.gz`, one row per call a sample carries (`variants.py`) | call |
| `vcf_callset_summary`, `vcf_substitution_spectrum`, `vcf_filter_breakdown` | `vcf_variants` (catalog `vcf/*`) | sample; sample and class; sample and FILTER value |
| `vcf_variant_density` | `vcf_variants` (catalog `vcf/variant_density`) | sample and 1 Mb window |
| `ranked_variants` | `rank_and_filter/<family>_snv_ranked_*.vcf.gz`, clinical and research sets merged; carries the family's `rank_score_min` and `rank_score_max` and a `genotypes` column (`sample|GT` for every individual) | variant |
| `ranked_genotypes` | `ranked_variants` | variant and sample |
| `family_checks` | the family callset and the pedigree | pair of samples, both directions |
| `mt_variants` | `rank_and_filter/<family>_mt_ranked_*.vcf.gz` (optional) | call |
| `repeat_expansions` | `repeat_expansions/<family>_repeat_expansion_stranger.vcf.gz` (optional) | locus and sample |
| `mobile_elements` | `call_mobile_elements/<family>_mobile_elements.vcf.gz` (optional) | insertion and sample |
| `smn` | `smncopynumbercaller/out/<family>_smncopynumbercaller.tsv` (optional) | sample |
| `tracks` | the ranked, repeat and mobile element VCFs of the family and, per sample, the alignment and the signal tracks (`genomic_tracks`, recipe `tracks.py`) | file |
| `samples` | the collections above and the pedigree | sample |

The ranked VCFs hold every variant of the research set, and the clinical set is a subset of it:
`ranked_variants` merges the two files and flags the clinical rows in `variant_set` and
`is_clinical`, so no variant is counted twice. The callset summary, the substitution spectrum and the
FILTER breakdown count the calls a sample carries (a genotype with an alternate allele), not the
sites of the joint file.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `DATA_ROOT` | required | root of one run (`alignment/`, `call_snv/`, `rank_and_filter/`, `qc_bam/`, `pedigree/`, `pipeline_info/`) |
| `GENOME` | `hg19` | the axis of the navigator and the karyotype, and the assembly of `tracks`; `hg19` is the GRCh37 naming, `hg38` that of GRCh38 |
| `TRACKS_URI` | unset | the folder (`s3://` or `https://`) holding the run's results, to read the browser's tracks in place instead of uploading them from `DATA_ROOT` |

## Routes

The import prunes what depends on an absent collection (RULES section 13):

| Route | What goes |
| --- | --- |
| mitochondrial branch skipped | `mt_variants`, the Mitochondria tab, its pipeline step and its tile in the list |
| no repeat expansion calling | `repeat_expansions`: its card, figure and table, the Repeats step and its source in the browser |
| no SMN calling | `smn`: its card and table |
| no mobile element calling | `mobile_elements`: its card, figure, table and its source in the browser |
| no pedigree | the hub keys on the QC and callset samples, every role reads Other, the pedigree figure draws one row |
| a target capture (exome) run | the whole-genome coverage columns of `alignment_qc` stay empty and the tiles that read them draw a dash; the hybrid-selection columns fill instead |
| no alignments or signal files in `DATA_ROOT` and no `TRACKS_URI` | the manifest keeps only the files it finds; the browser opens on the rest |
| peddy, GENS, the germline CNV caller and structural variant calling | not read: no collection of this template depends on their outputs |

## The Overview

- **Hero, About, The run**: what the pipeline does, how to read the page, and the run's genome,
  analysis type, aligner, caller, VEP cache and skipped tools from `params.json`.
- **Six steps**: Align, Call, Rank, Mitochondria, Repeats, Report, each with its settings and its tab.
  The Mitochondria and Repeats steps cite a value of their branch's collection, so a run without
  the branch shows only the steps it took.
- **Key figures** (filter bar: the role, then the sample): Clinical variants by inheritance model, the
  top rank score, Samples by role and Mean coverage.
- **Findings**: live rows led by the top candidate (its gene, change and rank score), then the variants
  that fit a model with the clinical set, the parent-child IBS0 share, and PASS calls with the Ts/Tv
  range expected for a genome or an exome and the coverage. Below them, a compact leaderboard of
  the eight best-ranked variants (the same tile as the top candidates of the Ranked tab, linked to
  it), then two highlights: the genotypes of the 20 best variants across the family (Ranked) and
  the pedigree (Family).

## The tabs

- **MultiQC**: general statistics, FastQC counts and fastp filtered reads, Picard alignment summary,
  duplicates, insert size and the coverage histogram. Base quality, adapter content and the mosdepth
  curves are collapsed.
- **Alignment**: reads, aligned share, mean coverage, duplication and the mitochondrial to nuclear
  depth ratio; one table of the samples with the record of the picked sample beside it. The contig
  depth and the full tables are collapsed.
- **Family**: samples by affected status, the parent-child IBS0 share and the sex check; the pedigree
  as a pedigree figure from the sample sheet (squares male, circles female, filled marks affected),
  beside the opposite homozygous share of every pair of samples, one bar each, coloured by the
  verdict. The pair table is collapsed.
- **Callset**: PASS calls, Ts/Tv, het/hom ratio and calls by FILTER value; Ts/Tv and het/hom ratio
  per sample as two sorted bars, with the usual range shaded (a click on a bar narrows the dashboard
  to that sample). The descriptions say what the values mean: Ts/Tv about 2.0 to 2.1 for a genome and
  2.8 to 3.0 for an exome, a lower value pointing to false positives; het/hom 1.5 to 2 for outbred
  samples, lower with consanguinity or loss of heterozygosity, higher with contamination. The
  substitution spectrum is folded onto six classes. The karyotype of one sample (a brush on it
  filters the dashboard to that region; only the contigs that carry calls are drawn) and the
  allele fraction per sample are collapsed, with the tables. The allele fraction is the share of
  each sample's PASS calls read at least 10 times in each 0.05 bin, split by variant type, with the
  heterozygous band (0.3 to 0.7) and the homozygous-alternate one (0.9 to 1) shaded: a germline
  sample peaks at 0.5 and near 1, and a peak off 0.5 or a broad low shoulder flags contamination,
  mosaicism or artefacts.
- **Ranked**: ranked variants by set, those that fit a model, high and moderate impact variants and
  the top rank score; the 50 best candidates as a leaderboard, best first (gold, silver and bronze
  on the first three), with the gene and protein change, the inheritance model and impact as
  coloured badges and the rank score as a bar. Hovering a row lists its consequence, coding change,
  variant set, gnomAD frequency, CADD, pLI, position, alleles and carriers; a click pins that
  popover, picks the variant for the record beside it (gene links go to GeneCards) and opens a
  Family section: the pedigree of the sample sheet, labelled by role, with the proband marked by an
  arrow and a P beside its label and each member filled by genotype (solid homozygous alternate,
  half heterozygous, open not carrying, grey no call). The leaderboard's controls sit behind its
  settings icon, and the record shows the top-ranked variant until a row is picked
  (`default_record_by: rank_score`).
  Then the rank score of the 50 best variants as one bar each, coloured by inheritance model, where
  a click narrows the leaderboard. Why they rank: the 20 best variants as stacked bars, best first,
  one segment per GENMOD score component, each bar labelled with its total and the axis running to
  the family's maximum possible score (read from the `RankScoreMinMax` of the VCF), with a dotted
  line at that bound. Who carries them: a grid of the genotype of every individual at the same 20
  variants (homozygous reference grey, heterozygous blue, homozygous alternate red, half call
  orange, no call dark grey). The rank score by inheritance model, the carriers of each sample, the plain table of every ranked variant
  (to sort, search and export) and the genotype table are collapsed.
- **Mitochondria** (optional): calls by heteroplasmy class, median heteroplasmy, impact and depth;
  heteroplasmy along the mitochondrial genome; heteroplasmy against the gnomAD frequency (large
  markers, a little transparent, so clustered calls stay readable). The
  mitochondrion is not on the navigator's axis, so this tab has no genome view.
- **Repeats** (optional): repeat calls by status, pathogenic-range calls by inheritance, mobile
  element insertions by family and SMN calls; one row per repeat locus (with its disease), each
  call placed by its repeat count as a multiple of the pathogenic threshold, over shaded normal,
  intermediate and pathogenic zones and coloured by status, with the individuals of a locus
  jittered apart; insertions per sample by element family. The tables, SMN included, are
  collapsed.
- **Locus**: cards on the region in view (ranked variants, calls, top rank score, depth); the
  navigator draws every ranked variant at its position, higher for a higher rank score and coloured
  by the inheritance model it fits, opening on the chromosome the browser shows
  (`open_on_view_window`), and, linked to it, a JBrowse browser.
  The browser opens on the span of the three best-ranked variants when they sit on one contig within
  1 Mb of each other (otherwise on the best one), padded on both sides. It shows the research ranked
  VCF first, with variants coloured by inheritance model like the navigator and named by their gene
  (`variant_label_by`, VEP CSQ SYMBOL), then the proband
  alignment and its coverage and the parents' alignments, plus the UCSC ClinVar and dbSNP common
  tracks of the assembly; the clinical VCF, the repeat and mobile element VCFs, the other samples and
  the signal tracks are in its track menu. Each sample's track names carry its role, e.g.
  `<sample> (proband) reads`. A brush or a locus on the navigator moves the browser, and the browser's
  window shows as a band on the navigator; a sample picked in its menu filters the dashboard. The ranked variants inside
  the region are listed below it.

## Colours

`category_colors` is declared on the Overview. The role takes the server's palette; the affected
status, impact, inheritance model (`model_class` for the navigator and `genetic_model` for the
browser's variant track), variant set, zygosity (`gt_class`: homozygous reference, heterozygous,
homozygous alternate, half call and no call each have a colour), contig class, heteroplasmy class, repeat
status, element family and the check verdicts are written out, and the FILTER values keep PASS green
beside the palette. Code figures read these through `depictio_category_colors`.
