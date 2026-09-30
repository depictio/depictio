# nf-core/oncoanalyser 3.0.0: Depictio dashboards

This template turns the output of [nf-core/oncoanalyser](https://nf-co.re/oncoanalyser) 3.0.0
into an eight-tab Depictio dashboard. oncoanalyser runs the Hartwig Medical Foundation WiGiTS
toolkit on tumor/normal DNA and tumor RNA: SAGE and PAVE call and annotate small variants,
ESVEE calls structural variants, AMBER and COBALT feed PURPLE's purity, ploidy and copy-number
fit, LINX clusters the SVs and calls fusions, and CUPPA, SIGS, CHORD, LILAC, TEAL, Neo and QSEE
add tissue of origin, signatures, HRD, HLA typing, telomere length, neoepitopes and QC. The
template reads their tables; it reads no BAM and no MultiQC report (the pipeline writes none).

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.csv`) | sample |
| `purple_purity` | `purple/*.purple.purity.tsv` and `*.purple.qc` | tumor |
| `purple_cnv_segments` | `purple/*.purple.cnv.somatic.tsv` | copy-number segment |
| `purple_gene_copy_number` | `purple/*.purple.cnv.gene.tsv` (canonical transcripts) | tumor and gene |
| `purple_drivers` | `purple/*.driver.catalog.*.tsv` and the LINX driver catalogs | tumor, gene, driver type |
| `purple_somatic_variants` | `purple/*.purple.somatic.vcf.gz` (PASS only) | somatic call |
| `purple_protein_changes` | derived from `purple_somatic_variants` | protein change |
| `linx_svs` | `linx/somatic_annotations/*.linx.svs.tsv` and `*.linx.clusters.tsv` | SV |
| `linx_fusions`, `linx_fusion_structure` | `*.linx.fusion.tsv` and `*.linx.breakend.tsv` | fusion, fusion exon span |
| `cuppa_predictions`, `cuppa_classifier_matrix` | `cuppa/*.cuppa.vis_data.tsv` | classifier and cancer type |
| `sigs_allocation` | `sigs/*.sig.allocation.tsv` | tumor and signature |
| `chord_prediction` | `chord/*.chord.prediction.tsv` | tumor |
| `lilac_alleles` | `lilac/*.lilac.tsv` | tumor and HLA allele |
| `teal_telomere_length` | `teal/*.teal.tellength.tsv` | DNA sample |
| `neo_neoepitopes` | `neo/scorer/*.neo.neoepitope.tsv` | neoepitope |
| `hmf_bamtools_*` | `bamtools/*/*.bam_metric.{summary,coverage,frag_length}.tsv` | DNA sample |
| `qsee_status` | `qsee/*.qsee.status.tsv.gz` | sample and QC feature |

oncoanalyser publishes every output under `<group_id>/<tool>/`, so `DATA_ROOT` is the pipeline
outdir and every recipe globs its files recursively: a cohort run is several group directories
side by side. The pipeline does not publish its samplesheet, so the template ships the test_full
sheet under `input/` and reads it by default; point `METADATA_FILE` at the sheet of another run.
CUPPA, SIGS, CHORD, LILAC, TEAL, Neo and QSEE collections are optional: a run that excludes a
tool, or a targeted panel run, drops their tiles.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample_id` | samplesheet id column (fixed by the pipeline) |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `sample_class`, `Sample class` | grouping filter and glance card |
| `GENOME` | `hg38` | chord ring, copy-number locus view and genome view assembly |

`sample_class` is derived by the sample hub (`sample_type` and `sequence_type` joined, for
example `tumor_dna`), so the default works on any sheet; any sheet column can be named instead.

## Tabs

1. **Overview.** Tumor purity, ploidy, mutations per Mb and microsatellite indels; purity
   against ploidy per tumor; CUPPA's cancer-type probability per classifier (heatmap);
   HRD probability, SIGS signature shares, missense load and SV burden; the PURPLE fit table
   with a tumor record card. The persistent glance strip counts samples, analysis groups,
   subjects and driver catalog entries; the sample sheet section is pinned and collapsed.
2. **Sequencing QC.** BamTools mean coverage, reads, highest duplicate share and lowest 30x
   breadth; cumulative coverage and insert-size curves per sample; QSEE verdicts per tool (PASS,
   WARN and FAIL in green, orange and red); the
   BamTools summary with a library record card.
3. **Copy number.** Segments, segment copy number, genes with an event and LOH share; the PURPLE
   copy-number profile (log2 of copy number over 2 with BAF, plus a locus view); lowest against
   highest copy number per gene (minimum against maximum, with the identity diagonal); the gene table with a gene record card.
4. **Drivers.** Reported, biallelic and total drivers, driver genes and the reported drivers'
   likelihood; an oncoplot of driver genes by tumor and driver type; catalog entries per driver
   type; the driver table with a driver record card. The tab opens with the Report status filter
   on `REPORTED`, so the oncoplot stays readable on a whole-genome catalog; clearing it adds the
   unreported entries.
5. **Small variants.** PASS calls, coding calls, purity-adjusted allele frequency and variant
   copy number; their histograms (variant types keep the genome track's colours); every call along the genome (GenomeSpy, with a gene lane);
   the variant table with a variant record card.
6. **Protein changes.** Protein-changing calls in residue form: a lollipop along the protein and
   a 3D structure resolved from the gene symbol (AlphaFold DB, ESMFold fallback) in one
   section, both opening on the protein with the most changes, driven by the Protein filter and
   linked residue by residue; the protein change
   table with a record card.
7. **Structural variants.** SVs, clusters, junction copy number and candidate fusions; a chord
   diagram of breakend pairs and SVs per resolved event; kept and lost exons per fusion and
   fusions per phase; the fusion table with a fusion record card; the SV table (collapsed).
8. **Immune context.** HLA alleles, neoepitopes, neoepitope expression and telomere length; tumor
   copy number per HLA allele and telomere length per sample; neoepitope expression and source;
   the neoepitope table with a record card; the allele and telomere tables (collapsed).

Every tab carries the persistent Sample filters (sample, `GROUP_COL`, analysis group) and an
open tab-local filter section.

## Selection

- The sample sheet selects on `sample_id`; the links carry it to every collection's `sample`
  column (`sampleId` for TEAL).
- A driver selection narrows the protein changes to its genes (`gene` to `entity`); a gene
  selected in the gene copy-number table or scatter narrows the driver catalog.
- The lollipop and the 3D structure read the same collection, so a residue picked in one rings
  the same residue in the other.
- Each record card sits beside the table that drives it (`linked_component`) and opens on the
  selected row.

## Methods and assumptions

- **Tumor sample.** Tumor-level tables are named after the tumor's `sample_id`; the recipes take
  the sample from the file name, so sample ids with dots are kept whole.
- **Somatic calls.** Only PASS calls of the PURPLE VCF are kept. The gene, effect and HGVS change
  come from PAVE's canonical-transcript `IMPACT`; the tumor genotype is the last VCF column.
- **Protein changes.** The three-letter residues of each HGVS protein change are converted to
  a residue number and one-letter reference and alternate amino acids; synonymous changes keep
  the reference residue and frameshifts carry no alternate residue.
- **Copy-number events.** Gene events follow PURPLE's driver cut-offs: AMP when the lowest copy
  number is above three times the ploidy, DEL below 0.5 copies, LOH when the minor allele is
  below 0.5 copies, PARTIAL_* when only part of the gene qualifies.
- **Fusion structure.** Exon spans are drawn in exon units along the fused transcript (the
  pipeline writes no transcript model), from the fused and total exon counts of each partner.
- **Not shown.** LINX's protein-domain plot table is in genomic coordinates with no CDS offset,
  so it is not mapped onto residues; the virus table, Isofox, PEACH, CIDER and ORANGE are not
  read yet.
