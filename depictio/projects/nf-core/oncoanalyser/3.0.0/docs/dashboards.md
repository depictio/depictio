# nf-core/oncoanalyser 3.0.0: Depictio dashboards

This template turns the output of [nf-core/oncoanalyser](https://nf-co.re/oncoanalyser) 3.0.0
into an Overview and eight tabs in three groups. oncoanalyser runs the Hartwig Medical Foundation
WiGiTS toolkit on tumor and normal DNA and on tumor RNA: SAGE and PAVE call and annotate small
variants, ESVEE calls structural variants, AMBER and COBALT feed PURPLE's purity, ploidy and
copy-number fit, LINX clusters the SVs and calls fusions, and CUPPA, SIGS, CHORD, LILAC, TEAL, Neo
and QSEE add tissue of origin, signatures, HRD, HLA typing, telomere length, neoepitopes and QC.
The template reads their tables and lists PURPLE's VCFs and the BAMs as genome-browser tracks;
it reads no MultiQC report (the pipeline writes none). The family rules it follows are in `depictio/projects/nf-core/RULES.md`.

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
| `purple_protein_genes` | derived from `purple_protein_changes` and `purple_drivers` | tumor and gene |
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
| `tracks` | built by `recipes/tracks.py` from the samplesheet: PURPLE's VCFs and the REDUX BAMs (no colour column: tracks are coloured by `kind`) | track file |

oncoanalyser publishes every output under `<group_id>/<tool>/`, so `DATA_ROOT` is the pipeline
outdir and every recipe globs its files recursively: a cohort run is several group directories
side by side. The pipeline does not publish its samplesheet, so the template ships the test_full
sheet under `input/` and reads it by default; point `METADATA_FILE` at the sheet of another run.

CUPPA, SIGS, CHORD, LILAC, TEAL, Neo and QSEE can be excluded with `--processes_exclude`, and a
targeted (panel) run skips several of them, so their collections are optional. A run without
them skips those collections at ingest and the import drops the tiles that bind them: the
Findings row and the Pipeline step that cite them, a section whose tiles all go, and the Immune
context tab when LILAC, Neo and TEAL are all missing.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.csv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `sample_id` | samplesheet id column (fixed by the pipeline) |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `sample_class`, `Sample class` | grouping filter, Key figures breakdown and group colours |
| `GENOME` | `hg38` | assembly of the chord diagram and the genome tracks |
| `TRACKS_URI` | unset | `s3://` or `https://` outdir to read the genome tracks in place; unset uploads the VCFs and BAMs DATA_ROOT holds |

`sample_class` is derived by the sample hub (`sample_type` and `sequence_type` joined, for
example `tumor_dna`), so the default works on any sheet; any sheet column can be named instead.

## Methods

- **Tumor sample.** Tumor-level tables are named after the tumor's `sample_id`; the recipes take
  the sample from the file name, so sample ids with dots are kept whole.
- **Somatic calls.** Only PASS calls of the PURPLE VCF are kept. The gene, effect and HGVS change
  come from PAVE's canonical-transcript `IMPACT`; the tumor genotype is the last VCF column.
- **Protein changes.** The three-letter residues of each HGVS protein change are converted to
  a residue number and one-letter reference and alternate amino acids; synonymous changes keep
  the reference residue and frameshifts carry no alternate residue.
- **Genes with a protein change.** One row per tumor and gene: the change count, hotspot count,
  highest purity-adjusted allele frequency and worst coding effect of its changes, with the
  likelihood of the gene's `MUTATION` row in the somatic driver catalog. Genes without such a
  row (outside the driver panel, or with changes that do not qualify) get a likelihood of 0 so
  every gene keeps its point. The recipe is `recipes/protein_genes.py` of this pipeline; it
  imports no shared helper.
- **Copy-number events.** Gene events follow PURPLE's driver cut-offs: AMP when the lowest copy
  number is above three times the ploidy, DEL below 0.5 copies, LOH when the minor allele is
  below 0.5 copies, PARTIAL_* when only part of the gene qualifies.
- **Drivers.** PURPLE's rows are kept as they are; a LINX row is kept only when PURPLE has no row
  for the same tumor, gene and driver type, so LINX's disruptions are added without doubling the
  reported drivers.
- **Fusion structure.** Exon spans are drawn in exon units along the fused transcript (the
  pipeline writes no transcript model), from the fused and total exon counts of each partner.
- **Not shown.** LINX's protein-domain plot table is in genomic coordinates with no CDS offset,
  so it is not mapped onto residues; the virus table, Isofox, PEACH, CIDER and ORANGE are not
  read yet.

## Tabs

The Overview follows the family layout (`RULES.md` section 3): hero, About and run cards, a six
step pipeline flow, four key figures with a group and sample filter bar, four findings with a
highlight each, and a link list of the tabs. The persistent sample filters (sample class,
sample, analysis group) sit in the left panel and the collapsed sample sheet at the bottom of
every other tab.

**Data & QC**

1. **Sequencing QC.** *Is the sequencing deep and clean enough for the calls?* Mean coverage,
   reads per sample, the highest duplicate share (against QSEE's 30% fail line) and the lowest
   share at 10x or more (against QSEE's 90% fail line); fractions read as percentages. Cumulative
   coverage and insert-size curves per sample, and QSEE's PASS, WARN and FAIL verdicts per tool.
   The BamTools summary with a library record card and the QSEE checks are collapsed.

**Genome**

2. **Tumor profile.** *How pure is the tumor, and what kind of tumor is it?* Purity (against
   QSEE's 20% fail line), ploidy (split by PURPLE fit status), mutations per Mb (against PURPLE's
   high-burden line at 10) and microsatellite indels (against its instability line at 4), each
   description saying what a normal value is. CUPPA's cancer-type probability per classifier
   (heatmap); the share of SNVs per COSMIC signature, sorted and coloured by the signature's
   proposed cause (hover names it), beside the HRD probability (against CHORD's 50% line) and
   the SNVs allocated. The PURPLE fit table with a tumor record card and
   the CUPPA and CHORD tables are collapsed.
3. **Copy number.** *Which regions are gained or lost, and in which genes?* Segments, segment
   copy number, genes in view and the LOH share. The PURPLE copy-number profile (log2 of copy
   number over 2 with BAF, Plotly view only) and the number of genes under each copy-number call
   (log axis: loss of heterozygosity holds most genes and would flatten every gain and loss; its
   genome share is the LOH card).
   The profile's Open in genome browser action opens the reads and the SV breakpoints at the
   region clicked, selected or in view, in a genome browser tab.
   The tab opens with the event filter on amplifications and deletions, so the gene counts
   stay readable; clearing it adds the genes with loss of heterozygosity or no change. The gene
   table with a gene record card is collapsed.
4. **Structural variants.** *Which rearrangements shaped the genome, and which fusions follow?*
   SVs, clusters, junction copy number and candidate fusions. A chord diagram of breakend pairs
   beside the SVs per resolved event (both coloured by the resolved event), then kept and lost
   exons per fusion beside the fusions per reading frame. The fusions card ranks the 5' partners. The fusion table with a fusion record card and the SV table are collapsed,
   as is a genome browser (Reads at the breakends) that jumps to the first breakend of the SV
   picked in the chord diagram or the table. It opens on the first tumor's four VCFs and its
   tumor and normal reads (six tracks), on the SV with the highest junction copy number; the
   stepper lists 20 SVs, each with its type, length and genes.

**Variants**

5. **Drivers.** *Which genes drive this tumor, and how?* Driver entries, oncogenes and
   suppressors, biallelic entries and the driver likelihood. An oncoplot of driver genes by
   tumor and driver type beside the entries per gene role, and the likelihood per driver type.
   The tab opens with Report status on `REPORTED`, so the oncoplot stays readable on a
   whole-genome catalog; clearing it adds the unreported entries. The driver table with a
   record card is collapsed.
6. **Small variants.** *How many somatic variants are there, and how clonal?* PASS calls, coding
   calls, purity-adjusted allele frequency and variant copy number; their histograms (variant
   types keep one colour on every tile); then one linked section: every call along the genome
   (GenomeSpy, with a gene lane, coloured by coding effect as the browser's calls) and the
   genome browser under it, which follows its brush (its window shows as a band on the calls)
   and jumps to the call picked in the table. It opens on the tumor's VCFs, its tumor and normal
   reads and the dbSNP and ClinVar tracks, on a reported driver call when there is one.
   The variant table with a variant record card is collapsed.
7. **Protein changes.** *Which proteins change, and where on the protein?*
   Protein changes, proteins hit, hotspots and allele frequency. A scatter of the genes with a
   change (highest purity-adjusted allele frequency against PURPLE's driver likelihood, coloured by
   worst effect, the eight most likely drivers named) sits beside the needle plot, which narrows to the
   gene picked on the scatter. Without a pick, the needles open on the protein with the most
   changes; the Protein filter drives them too. Collapsed: the protein change table with a
   record card. The Gene role filter opens on the driver-panel genes (the genes outside it all sit at a
   likelihood of 0 and bury the scatter); clearing it adds them. The tab draws no 3D structure: that tile needs the server's structure resolver,
   which is off by default, and it would have read as a message above the figures that matter.
8. **Immune context.** *Which HLA alleles does the tumor keep, and what could they present?*
   HLA alleles, neoepitopes, neoepitope expression and telomere length; tumor copy number per
   HLA allele and telomere length per sample (with the tumor to normal ratio); neoepitope
   expression against variant copy number and the neoepitopes per source event, one colour per
   event. The neoepitope table with a record card and the allele
   and telomere tables are collapsed.

Every child tab carries the persistent Sample filters and an open tab-local filter section:
depth band and verdicts (Sequencing QC); PURPLE fit status and QC (Tumor profile); copy-number
event and chromosome (Copy number); resolved event, SV type and fusion phase (Structural
variants); driver type, gene role, origin and report status (Drivers); coding effect, variant
type and allele frequency (Small variants); protein and coding effect (Protein changes); HLA gene
and neoepitope source (Immune context).

## Genome tracks

The `tracks` collection lists PURPLE's somatic and germline VCFs of every analysis group and
the tumor and normal REDUX BAMs, one row per file, built from the samplesheet by
`recipes/tracks.py`. Every row is keyed on the group's tumor sample, so a sample pick (or a call,
copy-number segment or SV of that tumor) opens the tumor's VCFs and both alignments. The VCFs
come first and the BAMs, 80 to 170 GB each on a WGS run, last, except that the first group
leads with everything: its four VCFs, then its tumor and normal BAMs, so a browser opens on a
call with the reads under it. With `--var TRACKS_URI=<outdir>`
the files are read in place by range; without it the VCFs and BAMs that DATA_ROOT holds, with
their index, are uploaded. The browsers colour a track by its `kind` (somatic, SV, germline, tumor reads, normal reads)
through `category_colors`; the manifest has no colour column. The tumor RNA alignment is not
listed. The use cases are in
`docs/design/jbrowse/oncoanalyser.md`.

## Selection

- The sample sheet selects on `sample_id`; the links carry it to every collection's `sample`
  column (`sampleId` for TEAL).
- A driver selection narrows the protein changes to its genes (`gene` to `entity`); a gene
  selected in the gene copy-number table narrows the driver catalog.
- The gene scatter selects on `entity`, the column the protein changes and the needles read, so
  a click moves the needles to that gene.
- Each record card sits beside the table that drives it (`linked_component`) and opens on the
  selected row.

## Colours

`category_colors` is declared once on the Overview: the group column (`auto`), the QC verdicts
(`qc_status`), the variant types, the coding effects (`coding_effect`, `worst_effect` and
`category`, which also holds the gene roles), the copy-number events, the driver types, the
fusion reading frames, the event an SV cluster resolves to (`resolved_type`, shared by the
chords and the bar beside them), the track kinds and the proposed cause of a mutational
signature (`signature_cause`). Figures, advanced viz and filter chips all read it.

## Height budget

Open rows per tab (the collapsed sections excluded, stored `h`): Overview 23, Sequencing QC 13,
Tumor profile 19, Copy number 16, Structural variants 15, Drivers 13, Small variants 13, Protein
changes 14, Immune context 15.
