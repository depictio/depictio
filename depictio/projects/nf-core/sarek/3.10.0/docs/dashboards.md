# nf-core/sarek 3.10.0: Depictio dashboards

This template turns the output of [nf-core/sarek](https://nf-co.re/sarek) 3.10.0 into a
six-tab Depictio dashboard. sarek trims and aligns reads, marks duplicates, recalibrates base
quality with GATK4 BQSR, calls variants with any mix of germline and somatic callers, and
annotates the calls with SnpEff and VEP. The dashboard follows that chain and keeps going past
the summary counts: it reads the VCFs themselves, so callers are compared call by call and gene
by gene, not only by how many calls each one made.

The template was validated on the AWS megatest run `results-8ccac7ad37b05dd792447763bf9671b719824587`
(the 3.10.0 release tag), `test_full_germline_ncbench_agilent/` profile. The dashboard texts
quote nothing from that run: its sample names, depths and loci are listed as `forbidden_terms`
in `megatest.yaml`, and `test_template_conventions.py` keeps them out.

## Inputs the template relies on

- **The sample hub comes from sarek's own CSV manifests.** sarek writes its resume points under
  `csv/` (`recalibrated.csv`, `markduplicates*.csv`, `variantcalled.csv`). The `samples`
  collection reads the first design manifest present for patient, sex and status (0 normal,
  1 tumour, shown as `status_label`) and counts the callers per sample from `variantcalled.csv`.
  Nothing is parsed out of sample names, and the samplesheet the run was launched with is not
  needed.
- **`GENOME`** (default `hg38`) names the assembly of the genome tracks and of the annotated VCF
  collection. The bundled gene lane of the calls track stays `hg38`, because the viz model only
  accepts a fixed list there.
- **Optional collections.** The VCFtools and SnpEff collections, the X/Y sex check and the
  somatic outputs (ASCAT, CNVkit, MSIsensor-pro, NGSCheckMate) are `optional: true`: a run that
  skipped a step loads without them. Somatic outputs carry no tiles yet.
- **The MultiQC tab links through `sample_mapping`** with no hand-written name table: each
  MultiQC sample name is resolved to the hub sample it starts with.
- **One mosdepth pass per sample.** sarek runs mosdepth on the duplicate-marked and on the
  recalibrated CRAM; the coverage recipes keep the recalibrated pass when present (then the
  duplicate-marked, then the sorted one), so no tile double-counts a sample.

## Conventions

- **Tab 1 is MultiQC.** The five tabs after it are a funnel: coverage, caller yield, caller
  agreement, consequences, genes.
- **Pinned on every tab:** the `Run at a glance` strip (SNPs called, indels per callset as a box
  plot, samples by status, median Ts/Tv), the collapsed `Sample sheet`, the `Sample filters`
  (sample, status) and the collapsed `QC thresholds` (a Ts/Tv floor).
- **Structural-variant callers call few SNPs**, so every Ts/Tv card and filter carries
  `filter_expr: col('ts_tv') > 0`.
- **Every tab has its own open filters**, and within a tab the order is cards, distributions,
  detail, then collapsed tables. Advanced visualisation controls sit in the tile header.

---

## MultiQC

The run's native MultiQC report: general statistics, read quality (FastQC, fastp), alignment and
recalibration (samtools, MarkDuplicates, BQSR, mosdepth coverage and insert size), the
variant-call QC MultiQC pools across callers, and the SnpEff and VEP summaries. A tab-local
`Glance scope` picker narrows the pinned strip to one caller.

## Cohort QC

Coverage bounds every call, so it comes first. Cards: target depth per contig (box plot over the
capture-target scope), targets under 20x (top samples), and the X/Y depth ratio.

`One locus, three tracks` is a locus section. The navigator is a `genome_view` on
`mosdepth_windows` (the per-target bed binned to 1 Mb windows) that keeps the whole genome and
only zooms to its region; it opens on `chr1:1,000,000-2,000,000`, a generic window that is
already small enough for the file track to fetch. Its locus field (a region or a gene symbol)
and its brush drive three followers through the region links in `template.yaml`: per-target
depth (`coverage_track` on `mosdepth_targets`), the calls over the gene lane (`genome_view` on
`vcf_variants`), and the snpEff-annotated VCFs range-read by the browser from the
`snpeff_vcf_files` indexed_file collection. Cards are not region-scoped.

`Whole contig against capture targets` compares mosdepth's two scopes per contig, one facet row
per scope; the scope picker opens on the targets. `X against Y coverage` is a heuristic sex
check from the same summaries.

## Variant yield

Each caller's own bcftools stats and VCFtools reports, caller against caller. Cards: MNPs,
multiallelic sites, calls by FILTER value, and the het to hom ratio per callset. Then SNP and
indel counts per sample, the mutation spectra (strand-folded substitutions and indel lengths,
each normalised to its callset), the `parallel_coordinates` callset profile, calls per FILTER
partition, Ts/Tv above a rising quality floor, and the remaining bcftools blocks (indel length,
substitution, depth, allele frequency, singletons) behind a block picker that opens on depth.
The bcftools QUAL histogram is not ingested: it outweighed every other block and repeated the
quality-floor panel.

## Caller concordance

Agreement between callers and samples, never a truth comparison (that is
nf-core/variantbenchmarking). Two UpSets (exact PASS calls, then genes carrying a coding
variant; both fixed, the pickers do not narrow them), allele fraction against depth as a
density and as a histogram, a rainfall plot of inter-call distances, and the call table.

## Consequences

SnpEff's published composition next to the same composition recomputed from the annotated calls.
Cards count impact classes, consequence terms, HIGH-impact calls (top callers) and genes with a
HIGH or MODERATE call. A click on the allele fraction against depth scatter fills the variant
record card beside it, which stays a thin rail until a call is picked, with the gene linked to
Ensembl.

## Genes

The per-gene burden SnpEff writes: a clustered gene by callset heatmap of coding-variant counts,
a protein lollipop, and the per-gene table, whose row selection drives the lollipop. A high
burden on long, repetitive genes is a mappability signal before it is a biological one.

## Selection

Tables and point views select on their entity column, and the selection narrows every tile on the
tab that reads the same collection or one linked from it:

- The sample sheet selects on `sample_id`, which the links carry to every collection and the
  MultiQC panels. The contig-depth, sex-check, FILTER and distribution tables, and the sex-check
  scatter, select on `sample`.
- The bcftools summary and Ts/Tv tables and the SnpEff composition table select on `caller`,
  which the links carry to the other callset-level collections on the Variant yield tab and to
  the annotated calls.
- The rainfall plot and the call tables select single calls on `variant_key`; the per-gene table
  selects on `gene_name`, which reaches the protein lollipop.

The genome view tracks move the locus through their region links rather than a selection, the
Ts/Tv quality sweep and the callset QC profile have no sibling tile on their collection, and the
allele fraction against depth view on the Caller concordance tab draws density bins rather than
points, so none of them selects.

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
