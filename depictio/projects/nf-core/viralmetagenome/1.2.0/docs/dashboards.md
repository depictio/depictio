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
| `genomes` | recipe over the two overviews, `checkv_quality` and `samples` | consensus genome |
| `ivar_variants` | `variants/ivar/<sample>/*.tsv` (raw iVar tables) | variant call |
| `coverage_bins` | `variants/mapping-info/metrics/mosdepth/<sample>/*.per-base.bed.gz` | mapping and depth bin |
| `coverage_cumulative` | `variants/mapping-info/metrics/mosdepth/<sample>/*.mosdepth.global.dist.txt` | mapping and depth |

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

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | unset | optional metadata table, the one given to `--metadata`: sample id first (or a `sample` column), one column per factor |
| `METADATA_ID_COL` | first column | metadata id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | first factor column | group filter, Samples card breakdown and colours |

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
   each stage, and a sample plane (raw read pairs against the share retained, coloured by the
   group). The per-stage table is collapsed.

**Assembly**

3. **Contigs.** *Which contigs did the assembly build, and what are they?* Four cards: contigs by
   taxonomic call, assembled bases by length band, reads on contigs by cluster role and clusters
   refined or filtered out. Every contig by length and the reads that map back to it (log axes,
   coloured by its call), and the read depth share of the clusters per sample. Contig and cluster
   tables are collapsed. The tab exists only on the de novo route.
4. **Consensus.** *How close to a reference and how complete is each genome?* Four cards:
   genomes by route, ambiguous bases (5 % N passes, 20 % warns), identity to the closest
   reference and the CheckV tier. Every genome by its ambiguous bases and identity, coloured by
   route, with the record of the picked one; the ambiguous bases of each de novo consensus along
   its refinement (scaffold, mapping iterations, variant-calling round). The genome and CheckV
   tables are collapsed.
5. **Mapping.** *How deep and how evenly do the reads cover each genome?* Four cards: reads
   mapped, mean depth, breadth at 10X (90 % passes, 50 % warns) and duplicate pairs. The depth
   along each genome in bins (log), then depth against breadth per genome beside the cumulative
   coverage curves. The mapping table is collapsed.

**Variants**

6. **Variants.** *Which variants does each genome carry, and how fixed are they?* Four cards:
   passing calls by allele frequency band (fixed at 0.9 or more, major from 0.5, minor below),
   minor calls kept or filtered, call depth and the genomes carrying a passing call. Every call on
   a genome view, one lane per genome (opening on the first reference), and allele frequency
   against depth. The call table is collapsed.

## Notes

- Genome browser. The pipeline publishes its filtered VCFs (`*.filtered.vcf.gz`) next to the
  tabix index of the sorted VCF it filtered (`*.sort.vcf.gz.tbi`), so no published VCF has its
  own index and an `indexed_file` collection cannot range-read them. Its references are viral
  genomes no bundled assembly covers, so the genome view derives its axis from the rows; with
  several references in one run the axis lists each of them, and a lane shows its calls on its
  own reference. The base.yaml carries a `TODO(jbrowse)` for the JBrowse2 swap.
- The depth along each genome is a profile over the position, not a coverage track: the genomes
  of a run sit on different references, and a profile overlays them from their first base.
- CheckV on the megatest ran on the minimal test database, which holds no complete genome: every
  consensus reads `Not-determined` and completeness is null. With a full database the tiers and
  the completeness fill in.
- The iVar tables keep the calls under the consensus threshold. Most minor calls are filtered
  noise at low depth; the Minor calls card splits them by iVar's verdict.
