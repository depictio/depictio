# nf-core/hlatyping 2.2.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in two groups, read as a funnel from the reads
to the genotypes and the support behind them. The template follows the family rules in
`depictio/projects/nf-core/RULES.md` (ampliseq 2.18.0 is the reference implementation).

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Are the reads clean enough to type? |
| Data & QC | Reads | How many reads did each sample give, and how many typed it? |
| HLA | Genotypes | Which HLA class I alleles does each sample carry? |
| HLA | Alleles | How often does each allele occur across the samples? |
| HLA | Typing quality | How many reads does each genotype rest on? |

hlatyping types the HLA class I loci (HLA-A, -B and -C) of each sample. FASTQ runs of one
sample are concatenated, a BAM input is turned back into reads (`samtools collate`), FastQC
checks every read file, yara maps the reads to the DNA or RNA HLA reference (`seq_type`), and
OptiType picks, by integer linear programming, the pair of two-field alleles at each locus
that explains the most reads. It writes one table per sample,
`optitype/<sample>/<sample>_result.tsv`, with the alleles, the reads the genotype explains
and the objective value.

The design comes from the samplesheet (`samples`): one row per sample with its sequencing
type, its input format, its read layout and its runs. `seq_type` (DNA or RNA) is the default
`GROUP_COL`. Every filter starts there: the links carry a pick to every collection by sample,
and to the MultiQC panels by sample mapping (FastQC names its rows `<sample>_1` and
`<sample>_2`).

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`), plus every sample of `optitype/` | sample |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC sample (read file, typed sample) |
| `optitype_genotypes` | `optitype/<sample>/<sample>_result.tsv` (catalog `optitype/genotypes`) | sample, locus and haplotype |
| `optitype_summary` | the same (catalog `optitype/summary`) | sample |
| `read_qc` | `multiqc/multiqc_data/multiqc_fastqc.txt`, with `samples` and `optitype_summary` | read file |

hlatyping does not publish the samplesheet it ran on in this release, so the template ships the
sheet of the megatest run under `input/` and reads it by default; point `METADATA_FILE` at the
sheet of another run. Without a sheet the hub still lists every sample OptiType typed, with the
sequencing type `Not stated`. Not read: the OptiType coverage plots (PDF), the yara BAMs (the
mapping publishes no statistics), and the reads, FastQC reports and yara index this release
writes to the output root.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `seq_type`, `Sequencing type` | group filters, the Samples card, the read files' colour and the group colours |

No variable prunes a route: every hlatyping 2.2.0 run that reaches MultiQC writes all five
collections.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples (from the
  samplesheet), the distinct alleles (from the genotypes), the typing tool, the solver and the
  solutions asked per sample (from the run parameters).
- **Pipeline**: five steps (reads, QC, map, type, score). Each step opens the parameters that
  drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples (split
  by sequencing type), distinct alleles (ranked by locus), homozygous loci (split by locus) and
  the median reads behind a genotype (with its spread). A sequencing-type and a sample filter
  above them narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  commonest allele and its share of the calls, the homozygous loci, the reads behind the median
  genotype and the share of a sample's read pairs its genotype explains. Below them, four
  figures in two rows: the genotype grid beside the allele frequency by locus, then the reads
  against the objective beside the reads per sample. The bar of this section filters by
  sequencing type and allele.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (sequencing type, sample, input format) sit in the collapsed
left panel and narrow every tab. The `Sample sheet` section is pinned to the bottom of every
child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of four key numbers, each card with its own colour and a secondary that
reads it, then at most three open sections; tables follow, collapsed.

**MultiQC.** MultiQC panels only. Open: the general statistics, FastQC's sequence counts, mean
quality, GC content and duplication levels, and OptiType's allele calls by locus. Collapsed:
the FastQC status checks, adapter content, overrepresented sequences and N content. FastQC
judges GC content against a whole-genome model, so exome, RNA or HLA-enriched reads often fail
that module without harm. The pinned sample filters narrow the FastQC panels.

**Reads.** Strip: the read files (a ring by their worst FastQC module), the median reads per
file, the share of a sample's read pairs its genotype explains (OptiType's reads over the
larger read file of the pair) and the highest duplicate share against FastQC's 20% and 50%
lines. Then the reads per sample and read, the reads of each file against the reads its
sample's genotype explains (log axes, coloured by the group), the GC content by group and the
duplicate share per sample. Collapsed: the read file table. Filters: read of the pair and
FastQC status.

**Genotypes.** Strip: the samples typed (against all three loci), the distinct alleles per
sample (of six), the homozygous loci (by locus) and the allele groups (ranked by locus). Then
the allele grid: one row per sample, one column per locus, each cell split into its two
haplotypes and coloured by allele group, a homozygous locus merged into one cell, with the
objective and the reads as side bars. A click on an allele narrows the dashboard to the samples
that carry it. Collapsed: the genotype per sample (the allele pairs, and the alleles as an
epitopeprediction samplesheet lists them) and every allele call. Filters: locus, allele and
zygosity.

**Alleles.** Strip: the distinct alleles (ranked by locus), the commonest allele (with the
share of distinct alleles against repeats), the allele calls (a ring by zygosity) and the share
of the calls the three largest allele groups take. Then the allele frequency by locus (an
allele's calls over its locus's calls, two per sample, commonest first) and the calls per
allele group stacked by zygosity. Filters: locus and allele group.

**Typing quality.** Strip: the median reads behind a genotype, the fewest reads of any sample,
the median heterozygous loci (of three) and the median objective per read. Then the reads
against the objective, one point per sample coloured by its homozygous loci, and the reads per
sample. Filters: a reads range and a heterozygous-loci range.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the group column is
coloured `auto`; zygosity, the FastQC status and the HLA class are written out; loci, reads of
the pair, input formats and the homozygous-loci label are coloured `auto`. Alleles take no
pinned colour: the allele grid colours them by allele group (one hue family per first field,
one shade per allele), the same in every tile that draws it.

## Cross-selection

- The sample sheet selects on `sample`, which the links carry to every collection and to the
  MultiQC panels.
- An allele, locus or zygosity pick on the genotypes (the grid, the filters) reaches the
  per-sample typing and the read files through `sample_id`: a pick on an allele shows the
  samples that carry it.
- **With nf-core/epitopeprediction.** Both templates spell an allele the same way: two-field,
  `HLA-<gene>*<field1>:<field2>` (`HLA-A*02:01`), through the same function
  (`depictio.recipes.lib.epitope_predictions.normalize_allele`). OptiType writes `A*02:01`;
  the predictors write `HLA-A*02:01` or `HLA-A02:01`; all three become `HLA-A*02:01`. `locus`
  here and `hla_locus` there take the same values (`HLA-A`, `HLA-B`, `HLA-C`), and `hla_class`
  here and `mhc_class` there the same `Class I`. The two runs are imported as two projects,
  and a Depictio link joins collections of one project only, so an allele picked here does not
  filter the other dashboard live. What carries over is the value: an allele copied from this
  dashboard selects the same rows in the epitopeprediction allele filters, and the `alleles`
  column of the genotype table is exactly what an epitopeprediction samplesheet takes in its
  `alleles` column (`;`-separated), so a typed sample can be predicted against its own
  genotype.

## Methods and assumptions

- **Optimum only.** With `--enumerations` above 1 OptiType writes its optimal and next best
  solutions; the genotypes keep the optimum, and the per-sample table counts the solutions and
  the objective gap to the runner-up.
- **Objective.** OptiType maximises the reads its alleles explain, less `beta` (`--beta`, 0.009
  by default) times the reads for each heterozygous locus, so the objective per read is about
  `1 - beta x heterozygous loci`: it reads the zygosity, not the quality of the fit. The
  support of a genotype is its reads, and with enumerations its gap to the runner-up.
- **Zygosity.** A locus is homozygous when OptiType writes one allele on both haplotypes,
  heterozygous when they differ, and `One allele typed` when it leaves one of them empty.
- **Typing share.** The reads OptiType explains over the reads of the sample's larger read
  file, so a paired-end sample is not counted twice. Reads that map to the HLA reference but fit
  no picked allele, and reads outside HLA class I, make up the rest.
- **Allele frequency.** Each sample contributes two calls per locus, so a homozygous locus
  counts its allele twice, as population allele frequencies do.
- **HLA-HD.** `--tools hlahd` (class I and II, licensed, installed outside the containers)
  writes `hlahd/` tables this template does not read.
