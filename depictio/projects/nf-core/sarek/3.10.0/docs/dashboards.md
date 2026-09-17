# nf-core/sarek 3.10.0: Depictio dashboards

This template turns the output of [nf-core/sarek](https://nf-co.re/sarek) 3.10.0 into a
two-tab Depictio dashboard. sarek trims and aligns reads, marks duplicates, recalibrates base
quality with GATK4 BQSR, and calls germline variants with five callers side by side
(DeepVariant, FreeBayes, HaplotypeCaller, Manta, Strelka), annotating each with SnpEff and VEP.
The dashboard follows that chain: read/alignment/recalibration QC first, then what each caller
actually called, compared caller against caller.

Data comes from the AWS megatest run `results-8ccac7ad37b05dd792447763bf9671b719824587` (the
3.10.0 release tag), `test_full_germline_ncbench_agilent/` profile: one exome (Agilent, WES),
sequenced at two depths (75M and 200M reads), run through the germline-only route (no
tumor/normal pair, so ASCAT / ControlFREEC / MSIsensor never run).

> **No per-variant table exists in this template.** The megatest manifest does not fetch the
> VCFs themselves (225 MB, deliberately excluded, see `megatest.yaml`), only bcftools stats,
> VCFtools stats and the SnpEff/VEP summaries per caller. There is therefore no manhattan,
> lollipop or oncoplot panel here: the caller comparison stops at the bcftools-stats level
> (record counts, Ts/Tv), not individual variant positions. See `VALIDATION_REPORT.md`.

---

## How the dashboard is built

- **Two tabs.** MultiQC, then Variant calling. The first answers "is the data clean enough to
  trust", the second "what did each of the five callers call, and how do they compare".
- **The sample hub is the anchor.** `samples` is one row per sample (`NA12878_75M`,
  `NA12878_200M`), each read as its own `patient` in the samplesheet, see the discrepancy note
  below. A persistent `Sample filters` section (sample) is pinned to the top of every tab.
- **Pinned sample sheet and reference table.** The sample hub sits in a collapsed `Sample sheet`
  section pinned to the top of every tab, and the per-caller variant-count summary in a
  collapsed `Reference tables` section pinned to the bottom, next to a collapsed
  `QC thresholds` section holding the Ts/Tv floor.
- **Manta reads near-zero, on purpose.** Manta is a structural-variant caller running alongside
  four SNP/indel callers; its bcftools stats report `ts=0 tv=0` and almost no SNPs/indels. Every
  panel that shows it says so, rather than treating it as missing data.
- **Catalog provenance.** Every dashboard tile computed from bcftools stats carries
  `use: bcftools/stats_summary` or `use: bcftools/stats_tstv`, the two catalog outputs this
  template owns; the MultiQC panels carry `use: multiqc/<module>`, three of which
  (`multiqc/gatk`, `multiqc/vcftools`, `multiqc/vep`) are new in this lot.

---

## MultiQC

The main tab, reading the run's native MultiQC 1.35 report (no reprocessing needed).

`Sample sheet`, collapsed at the top of every tab, holds the sample hub with a donut of the
sample count by read-depth condition beside its intro.

`Run at a glance` opens with the general statistics table: one row per sample and tool run,
pooling FastQC, fastp, samtools, mosdepth, bcftools, SnpEff and VEP headline numbers.

`Read quality` carries FastQC sequence counts, quality histograms and GC content, then fastp's
kept-reads count.

`Alignment and recalibration` is sarek-specific: samtools percent mapped, GATK4 MarkDuplicates'
duplication rate, GATK4 BQSR's reported-vs-empirical quality fit, and mosdepth's coverage
distribution over the Agilent exome target, cumulative and per-contig.

`Variant-call QC` pools every caller's VCF into one bcftools/VCFtools panel per plot:
substitution types, indel lengths, variant depths, Ts/Tv by allele count. The per-caller
breakdown these panels cannot show is the Variant calling tab.

`Annotation` carries SnpEff's impact and genomic-region breakdowns next to VEP's general
statistics and SIFT summary, two vocabularies for the same set of consequences.

---

## Variant calling

Everything the five callers' bcftools stats reports carry, compared caller against caller.

`Caller yield` counts SNPs, indels and multiallelic sites pooled across samples (top 3 callers
by contribution on each card), plus the mean Ts/Tv ratio on a threshold card.

`SNPs and indels by caller` opens with a dot plot putting all five callers and both samples on
one plane (`use: bcftools/stats_summary`, `viz_kind: dot_plot`): colour is
`log10(records)`, size is the fraction of each caller's records that are SNPs (0 for Manta),
next to two grouped bar charts of SNP and indel counts.

`Ts/Tv by caller` is one grouped bar chart: the four SNP/indel callers cluster near the
germline WES expectation (roughly 1.8-2.6 on this exome), Manta reads zero.

`Variant tables`, collapsed, holds both bcftools-stats tables (record counts, Ts/Tv), filtered
by the sample and caller pickers in the left panel and the Ts/Tv floor pinned at the bottom of
every tab.

---

## A discrepancy worth reading before you trust the "one patient" framing

The megatest samplesheet's `patient` column is **not** a shared `NA12878` value across both
rows: it repeats the `sample` column exactly (`NA12878_200M`/`NA12878_200M`,
`NA12878_75M`/`NA12878_75M`). Both sequencing depths are, biologically, the same individual, but
structurally the samplesheet treats them as two distinct patients. `status` is `0` (normal) for
both either way, and the `samples` hub reflects the samplesheet as published rather than the
biological framing. See `VALIDATION_REPORT.md`, SK-D2.

---

## Reproducing

```bash
# 1. Fetch the megatest subset
bash depictio/projects/nf-core/sarek/3.10.0/download_test_data.sh \
  ~/Data/depictio-nfcore/sarek/3.10.0/megatest

# 2. Dry run, then ingest
depictio-cli run --template nf-core/sarek/3.10.0 \
  --data-root ~/Data/depictio-nfcore/sarek/3.10.0/megatest --dry-run
depictio-cli run --template nf-core/sarek/3.10.0 \
  --data-root ~/Data/depictio-nfcore/sarek/3.10.0/megatest
```
