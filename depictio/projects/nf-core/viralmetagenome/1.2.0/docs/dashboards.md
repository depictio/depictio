# nf-core/viralmetagenome 1.2.0: Depictio dashboards

This template turns the output of [nf-core/viralmetagenome](https://nf-co.re/viralmetagenome) 1.2.0
into an Overview and six tabs in three groups. viralmetagenome rebuilds viral genomes from
metagenomic reads: fastp trims the reads, prinseq removes low-complexity ones and Kraken2 against a
host database removes the host; the assemblers (MEGAHIT, SPAdes, Trinity) build contigs, Kraken2
and Kaiju classify them, and CD-HIT-EST (or another `--cluster_method`) groups them with a
reference pool into clusters, one per genome to rebuild. Each kept cluster is scaffolded on its
centroid and refined by mapping the reads back (`--iterative_refinement_cycles`), then called into
a consensus with iVar; in parallel the reads are mapped to the references of a mapping constraint
sheet (`--mapping_constraints`). Every consensus is compared with an annotation database and the
pool (BLAST, MMseqs2), scored by CheckV and QUAST, and its reads are measured with samtools,
Picard and mosdepth. The family rules the template follows are in
`depictio/projects/nf-core/RULES.md`.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `metadata` | the sample metadata table (`METADATA_FILE`, optional) | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet`, rebuilt with MultiQC 1.35 | MultiQC report row |
| `vmg_samples_overview` | `overview-tables/*samples_overview.tsv` | sample |
| `samples` | recipe over `vmg_samples_overview` and `metadata` | sample |
| `read_funnel` | recipe over `samples` | sample and preprocessing stage |
| `vmg_contig_classes` | `assembly/polishing/intermediate/precluster/merged_classifications/*.resolved.txt` | contig |
| `vmg_clusters` | `assembly/polishing/intermediate/cluster/<sample>/*.clusters.tsv` (and the kept `*_cluster.json`) | cluster |
| `vmg_contigs` | `assembly/assemblers/<assembler>/idxstats/*.idxstats`, joined with the two above | contig |
| `vmg_contigs_overview` | `overview-tables/*contigs_overview.tsv` | final de novo consensus |
| `vmg_contig_iterations` | `overview-tables/*contigs_overview-with-iterations.tsv` | de novo consensus and refinement step |
| `vmg_mapping_overview` | `overview-tables/*mapping_overview.tsv` | constraint mapping |
| `checkv_quality` | `consensus/quality_control/checkv/<sample>/<genome>/quality_summary.tsv` | consensus sequence |
| `genomes` | recipe over the two overviews, `checkv_quality`, `vmg_clusters` and `samples` | consensus genome (one per segment) |
| `genome_matrix` | recipe over `genomes` | virus segment, one column per sample |
| `route_comparison` | recipe over `genomes` | sample and virus segment |
| `ivar_variants` | `variants/ivar/<sample>/*.tsv` (raw iVar tables) | variant call |
| `variants` | `ivar_variants`, else `variants/<caller>/<sample>/*.filtered.vcf.gz` | variant call |
| `intrahost_diversity` | `ivar_variants`, else `variants/bcftools/<sample>/*.norm.vcf.gz` | genome position |
| `coverage_bins` | `variants/mapping-info/metrics/mosdepth/<sample>/*.per-base.bed.gz` | mapping and depth bin |
| `coverage_profile` | recipe over `coverage_bins` and `genomes` | mapping and depth bin |
| `genome_ends` | the same per-base files, first and last 200 bp | mapping, end and 10 bp bin |
| `coverage_cumulative` | `variants/mapping-info/metrics/mosdepth/<sample>/*.mosdepth.global.dist.txt` | mapping and depth |
| `genome_loci` | recipe over `coverage_bins` (`MAPPING_REFERENCES_FASTA` only) | genome and region |
| `tracks` | the BAMs, per-base depth and plain VCFs of each genome (`MAPPING_REFERENCES_FASTA` only) | track file |
| `umi_stats` | `preprocessing/umi/umitools/log/*.log`, `variants/mapping-info/deduplicate/log/<sample>/*.log` | sample or mapping |

Every file name carries the run's `--global_prefix` (`<prefix>_<date>_<version>_<run name>-`):
the globs match on the suffix and the recipes strip the prefix, so the template reads any run
whatever its prefix, or none. A consensus genome is a sample and a reference, a constraint id of
the sheet or a de novo cluster id, and every per-genome collection keys it `<sample>_<reference>`
(`genome_id`).

The overview tables are the pipeline's own merge of its MultiQC sections, named by MultiQC label
(`(checkv) checkv_quality`, `(quast) % N's`). The recipes give them stable names, read fastp's Q30
rate and the annotation identity as percentages, and take the longest assembly across assemblers.
CheckV's completeness is not in them; the genome hub reads it from `checkv_quality`, for the
consensus each genome ended with.

Segments. A segmented virus (Lassa S and L, CCHFV S, M and L, influenza A's eight) is one genome
per segment. `virus` is the annotation's acronym; `segment` is the annotation's segment, else the
constraint sheet's, and `virus_segment` names the genome, so two segments of one virus are never
counted as one. Completeness is read segment by segment off the genome's BLAST hit:
`ref_cover_pct = (|send - sstart| + 1) / slen` and `len_minus_ref = qlen - slen`, from the
overview's `(blast)` columns. `completeness_call` reads Complete (95 % or more), Partial (50 % or
more), Fragment, No BLAST hit, or Shorter than reference: a genome that aligns along 90 % of itself
or more but is under 60 % of its hit's length. BLAST cannot tell whether that hit is longer than the
segment (an influenza segment 8 of ~890 nt against a 2349 nt reference reads 38 %) or the genome
stops short of both ends, so the call asks for a look rather than calling it truncated. CheckV
estimates completeness against whole genomes, so one segment reads as the share of the genome it
carries; it stays in the record as a second opinion. The cover is read off the best HSP only, a
lower bound for a genome whose alignment BLAST splits.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset | optional metadata table, the one given to `--metadata`: sample id first (or a `sample` column), one column per factor |
| `METADATA_ID_COL` | first column | metadata id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column | group filter, Samples card breakdown and colours |
| `MAPPING_REFERENCES_FASTA` | unset | indexed FASTA (`.fai`, and `.gzi` when bgzipped) of every reference the run mapped reads to, under DATA_ROOT; enables the Genome browser section of the Variants tab |

The pipeline merges its `--metadata` table into the samples overview but does not publish it, so
the template takes it as an optional table. The reference dataset ships `input/metadata.tsv`, the
nf-core/test-datasets `metadata_testfull.tsv` reduced to a few columns plus one design column
added for the demo (`specimen`, cell culture or clinical sample); `download_test_data.sh` copies
it under `input/`. Without a metadata table the hub carries one constant group (`__no_group__`,
"All samples") and the factor columns of the overview's metadata block (a column with at least two
values and fewer than the samples), so `--var GROUP_COL=<column>` still finds one.

There are no route flags to set: every collection a route may not write is optional, and the
import prunes the tiles that read a missing one.

## Tabs

The Overview follows the family layout (`RULES.md` section 3): hero, About and run cards, a six
step pipeline flow, four key figures with a group and sample filter bar (samples, clean read
pairs, consensus genomes, breadth at 10X), four findings with a highlight each (contigs, consensus,
mapping, variants) and a link list of the tabs. The persistent sample filters and the collapsed
sample sheet sit in the left panel and at the bottom of every other tab.

**Data & QC**

1. **MultiQC.** *What does the MultiQC report say about reads and mappings?* FastQC reads per run,
   fastp's kept and removed reads, base quality and the Kraken2 host taxa; samtools percent
   mapped, Picard duplicates, mosdepth cumulative coverage and the bcftools substitution types,
   one row per mapping. The report is rebuilt with MultiQC 1.35 from the published tool outputs,
   because the run's own MultiQC (1.27) wrote no parquet; the pipeline's custom-content sections
   are not published and are absent.
2. **Samples.** *How many reads of each sample reach assembly?* Four cards: the read funnel
   (raw read pairs, then kept after trimming and after host removal), the host share, Q30 bases
   against Illumina's 80 % floor, and FastQC's duplicate share. The read pairs of every sample at
   each stage, and a sample plane (raw read pairs against the share retained, coloured by the group, with a 90 % line and the samples that lose most named). The per-stage table is collapsed.

**Assembly**

3. **Contigs.** *Which contigs did the assembly build, and what are they?* Four cards: contigs by
   taxonomic call, assembled bases by length band, reads on contigs by cluster role and clusters
   refined or filtered out. Every contig by length and the reads that map back to it (log axes, coloured by its call and sized by its read share, with a 1 kb line and the largest contigs named), and the read depth share of the clusters per sample. Contig and cluster
   tables are collapsed. The tab exists only on the de novo route.
4. **Consensus.** *How close to a reference and how complete is each genome?* Route, Virus and
   Segment (virus and segment) filters. The sample x segment matrix, coloured by reference cover,
   sits under the scatter. Four cards: genomes by route, ambiguous bases (5 % N passes, 20 % warns),
   BLAST reference cover (95 % passes, 50 % warns) and genomes by completeness call. Every genome by its ambiguous bases and reference cover, coloured by its completeness call, cut at 5 % N and 95 % cover, the genomes with the lowest cover named, and the record of the picked one (genome, cluster type and segment; completeness with the reference length and qlen - slen; BLAST, annotation and Mash references with their identity; CheckV with its caveat for segmented viruses); the ambiguous bases of each de novo consensus along
   its refinement (scaffold, mapping iterations, variant-calling round), a code figure with markers on every step, a 5 % N line and a log axis floored at 0.1 %, since the share of N can be exactly 0. A line that ends before the others is labelled "no later step recorded": the pipeline's table holds no later iteration for that genome. A late rise in the share of N is expected, because the variant-calling round masks
   the positions too shallow to call. A Constraint route section plots the Mash identity of each
   picked reference against its breadth at 10X, beside a table that lines up the best de novo and
   constraint genome of every sample and segment. The genome and CheckV tables are collapsed.
5. **Mapping.** *How deep and how evenly do the reads cover each genome?* Four cards: reads
   mapped, mean depth, breadth at 10X (90 % passes, 50 % warns) and duplicate pairs. The depth
   along each genome in bins, one panel per virus segment (a code figure on a log axis with a 10X line and the stretches under it shaded), the depth over the first and last 200 bp of each genome in 10 bp bins, read from each tip inwards, then depth against breadth per genome (cut at 10X and 90 %, the thinnest genomes named) beside the cumulative
   coverage curves. The genome ends, a UMI table (`--with_umi` runs) and the mapping table are collapsed.

**Variants**

6. **Variants.** *Which variants does each genome carry, and how fixed are they?* Read from
   `variants`, the iVar table or, with `--variant_caller bcftools`, the filtered bcftools VCFs, so
   the tab stays with either caller. Variant type, Route and Segment filters. Four cards:
   passing calls by allele frequency band (fixed at 0.9 or more, major from 0.5, minor below),
   minor calls kept or filtered, call depth and the genomes carrying a passing call. Every call on
   a genome view, one lane per genome (up to 12, opening on every reference at once), and allele
   frequency against depth (cut at 10 reads and half frequency, with smaller points because the calls overlap). Intra-host diversity (collapsed): the Shannon entropy of the alleles at every position with an alternative allele, one lane per genome, from every call before the frequency filter, with a card of the mixed positions (second allele at 5 % or more). The call table and iVar's own table (p-value, codon change; pruned with a bcftools run) are collapsed.
   A collapsed Genome browser section (`MAPPING_REFERENCES_FASTA` only) opens the picked genome on
   its reference and steps between its 5' and 3' ends (200 bp): mosdepth's per-base depth, iVar's
   plain-text VCF and the deduplicated BAM (soft clips shown). Without the variable it is removed.

## Notes

- Genome browser. Every genome is its own reference (a constraint reference, a pool pick, or the
  sample's own de novo consensus), and a `genomic_tracks` collection takes one assembly. The
  browser therefore reads one indexed multi-FASTA of every mapping reference of the run,
  `MAPPING_REFERENCES_FASTA`; the pipeline does not publish it, so the tab is opt-in (a
  conditional removes `tracks` and `genome_loci` without it). The pipeline publishes its filtered
  VCFs (`*.filtered.vcf.gz`) next to the tabix index of the sorted VCF (`*.sort.vcf.gz.tbi`), so
  no bgzipped VCF has its own index; the browser reads iVar's plain-text `*.vcf` whole instead,
  and a bcftools run has no variant track. BAMs are not in the megatest subset, so the read track
  is checked on fixtures only. The Variants tab keeps its table-backed genome view, which needs
  none of this: its axis comes from the rows, a lane per genome on its own reference.
- The depth along each genome is a line figure over the position, not a coverage track: the genomes
  of a run sit on different references, and lines overlay them from their first base. It is a code
  figure because the profile kind has no horizontal reference line, and the 10X line is what the
  tile is read against. The refinement figure is a code figure for the same reason.
- The scatters leave the corner of the good verdict without a quadrant label, because the points
  of a healthy run crowd that corner and a label would sit on them; the tile description names it.
- CheckV on the megatest ran on the minimal test database, which holds no complete genome: every
  consensus reads `Not-determined` and completeness is null. With a full database the tiers and
  the completeness fill in.
- The iVar tables keep the calls under the consensus threshold. Most minor calls are filtered
  noise at low depth; the Minor calls card splits them by iVar's verdict.
