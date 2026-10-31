# nf-core/raredisease 3.1.2 template validation report

Validated offline against a real `test_full` run of nf-core/raredisease 3.1.2 (Nextflow 25.10.7)
executed on the EMBL cluster, not against an AWS megatest: the bucket has no raredisease results
that hold the callset, the ranked VCFs and the MultiQC report together. The run is the pipeline's
own full test profile, a trio on a reduced GRCh37 reference restricted to one autosome and the
mitochondrion, aligned with bwa-mem2, called with DeepVariant and GLnexus, annotated with VEP 107,
ranked with GENMOD, with the mitochondrial, repeat expansion, mobile element and SMN branches on.
`skip_tools` was `gens,germlinecnvcaller,peddy` and `skip_subworkflows` was `sv_calling`.
`megatest.yaml` has `results_sha: null` and says why.

**Data root:** `~/Data/depictio-nfcore/raredisease/3.1.2/test_full`

**MultiQC:** run wrote 1.35 -> used as-is (FastQC, fastp, Picard, mosdepth)

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `pytest depictio/tests -k "shipped_dashboard or template or recipe or megatest"` (every template, once) | 3839 passed, 1 skipped; two warn-only "median of a percentage" notices on Alignment cards, see Open issues |
| `ty check depictio/models/` | pass (models untouched) |
| `ruff format` and `ruff check` on `recipes/` | pass |
| Every recipe over the run (`execute_recipe`, input and output schemas, in declaration order) | pass, row counts below |
| `depictio ingest --template nf-core/raredisease/3.1.2 --dry-run` on the run | 19 collections ingest, 0 empty, 0 missing sources; nothing was ingested into a server |
| Every column a component, record card, value, filter, `locus_from` or code figure names, against the output of its collection | no missing column (119 components) |
| Every highlight source and every record card's linked component exists | pass |
| Each of the 11 code figures run in the code-figure sandbox (`SimpleCodeExecutor`, RestrictedPython) on the real frames | all draw (the pedigree builds three traces: the links and one per affected status) |

The text tiles, KPI strips and open-row budgets are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, persistent filters reaching every tab,
no table drawn twice on a genomic axis, one browser per family).

## Collection sizes on the run

| Collection | Rows |
| --- | --- |
| multiqc_data | 1 report (modules fastqc, fastp, picard, mosdepth) |
| alignment_qc | 3 (one per sample, 24 columns) |
| contig_depth | 6 (two contigs per sample) |
| vcf_variants | 23,449 calls carried (joint file unpivoted, carriers only) |
| vcf_callset_summary, vcf_filter_breakdown, vcf_substitution_spectrum, vcf_variant_density | 3, 6, 18, 42 |
| ranked_variants | 11,253 (10 clinical, the rest research only) |
| ranked_genotypes | 21,347 |
| family_checks | 6 (three pairs, both directions) |
| mt_variants | 92 |
| repeat_expansions | 6 (two loci, three samples) |
| mobile_elements | 33 |
| smn | 3 |
| tracks | 13 (four family VCFs, then an alignment and two signal tracks per sample) |
| samples | 3 (29 columns) |

## Routes (RULES section 13)

| Route | Pruned at import |
| --- | --- |
| mitochondrial branch skipped | `mt_variants`; the Mitochondria tab, the step citing it (`n_mt`), its filters and cards |
| repeat expansion calling skipped | `repeat_expansions`; its card, figure, table, filter, the Repeats step (`n_rep`) and its source in the browser (readable sources only) |
| mobile element calling skipped | `mobile_elements`; its card, figure, table, filter and browser source |
| SMN calling skipped | `smn`; its card and table |
| all three repeat routes skipped | the Repeats tab (every section loses its data-bound members) |
| no pedigree | the hub keys on the QC and callset samples; role reads Other; the pedigree figure draws a single row |
| target capture | whole-genome coverage columns stay empty, tiles draw a dash, the hybrid-selection columns fill |
| no `TRACKS_URI` and files in `DATA_ROOT` | `tracks` uploads whichever files it finds; with `TRACKS_URI` it reads them in place |
| peddy, GENS, gCNV, structural variants | not read; nothing to prune |

These routes were not exercised end to end on a stack (see Section 15). They are prunable by the
rules of the import (`_filter_unresolved_components`, per-line value pruning), and the highlights
and text of the Overview cite only collections every route writes, except the two steps above.

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections | Collapsed |
| --- | --- | --- | --- |
| Overview | 23 of 24 (hero 1, About and The run 4, steps 2, Key figures 2, Findings 10, How to read 4) | | Sample sheet (persistent, pinned) |
| MultiQC | 17 | Library QC, Alignment and coverage | Read quality, Depth per contig |
| Alignment | 17 | at a glance, Depth distribution, Depth per contig, Duplication and depth | Alignment tables |
| Family | 13 | at a glance, Pedigree, Pair checks | Family tables |
| Callset | 13 | at a glance, Callset quality, Substitution spectrum | Depth and allele fraction, Karyotype, Callset tables |
| Ranked | 19 | at a glance, Rank by model, Top-ranked variants, Rank along the genome | Carriers, Ranked tables |
| Mitochondria | 14 | at a glance, Heteroplasmy, Population frequency | Mitochondrial tables |
| Repeats | 12 | at a glance, Repeat counts, Mobile elements | Repeat tables |
| Locus | 19 | at a glance, Variants on one axis (linked), Ranked variants in the region | none |

## Findings on the run

- The ranked clinical VCF (10 variants) is a subset of the research VCF (11,257 records, 11,253
  distinct keys): `ranked_variants` merges them on `variant_key` and keeps one row, `variant_set`
  says which set it belongs to.
- `RankScore` is present for most records, CADD is null everywhere, gnomAD frequencies are null for
  about half of the variants. The GENMOD models seen are AD, AD_dn, AR_hom, AR_hom_dn, AR_comp and
  AR_comp_dn; `model_class` folds them onto Compound heterozygous, Recessive, Dominant, X-linked and
  No model fits. `de_novo` is GENMOD's `_dn` allowance, which is loose at this depth.
- The joint callset holds 0/0 cells with depth 0; they are treated as missing and never counted as
  a call. No multi-allelic site occurs, so the `multiallelic` column reads 0.
- Depth is about 1.4x on the autosome and thousands of times that on the mitochondrion, so the
  contig chart is on a log axis and the Alignment cards read the nuclear depth.
- The relatedness estimate is unreliable at this depth (an unrelated pair reads high), so the
  family verdict is judged on IBS0 of parent and child pairs only; `relatedness` is shown, not
  judged.
- There is no X or Y contig: the sex check reads Not tested for every sample, and the SMN table is
  all No call. Both tiles draw correctly but say little here.
- The mitochondrial VCF is Mutect2: the allele fraction is the heteroplasmy. MitoTip scores exist
  for a handful of calls only, so they stay in the table and not on a card.
- Repeat calls of the two loci are one pathogenic-range call per sample at a count of 2 and one
  locus with no call: the repeat figure drops the no-call rows.
- The mosdepth distribution carries two decimals only, so the depth curves are stepped at low
  coverage.

## Decisions and defects

| Id | Decision |
| --- | --- |
| RD-D1 | No AWS megatest: a local `test_full` run on the cluster is the reference (see `megatest.yaml`). |
| RD-D2 | The group column is the literal `role`, read from the pedigree. No `{GROUP_COL}` is used, so no filter expression needs the sentinel guard. |
| RD-D3 | The sample hub joins the QC, the callset, the ranked genotypes and the family checks; the ranked variants have no sample column, so a sample pick reaches `ranked_variants` through `ranked_genotypes` on `variant_key`. |
| RD-D4 | `variants.py` unpivots the joint VCF into one-sample lines and reuses the catalog `vcf_to_long`, so every catalog `vcf/*` recipe reads the frame unchanged. |
| RD-D5 | The navigator excludes the mitochondrion (the hg19 axis does not know it), so the Mitochondria tab has no genome view and no browser. |
| RD-D6 | The one browser sits in the Locus tab, with three sources (ranked variants, repeats, mobile elements). Family-level tracks (VCFs) are linked on `family_id`, so a sample filter narrows the per-sample alignment and signal tracks only. |
| RD-D7 | The pedigree is the `pedigree` advanced viz on the hub (squares male, circles female, filled affected), which draws and colours itself. The genotype grid uses one literal neutral for the cells a sample does not carry, the only literal colour outside `category_colors`, since Plotly has no theme-aware neutral. |

## Section 15 live check (pending, no stack in this environment)

Not done: importing the template on a running stack and looking at every tab. To check there: the
Overview fits in about two screens and its values fill in; the pedigree and the relatedness points draw at
their width; the rank-order bars, the ranked table with its record card, the score-component bars
and the genotype grid read; the navigator
and the browser follow each other and the three `locus_from` sources step; a sample picked in the
left panel moves every card of every tab; each conditional route (no mitochondrial branch, no
repeat calling, no pedigree) still renders without a stray `{VAR}` or a broken highlight.

## Open issues

1. Two warn-only "median of a percentage" notices (Aligned reads, Duplication on the Alignment
   tab): the columns are bounded per sample percentages, not averaged ones; same notice as other
   templates.
2. Scale: `ranked_variants`, `mt_variants`, `repeat_expansions` and `mobile_elements` parse VCF
   records in Python loops, and `family_checks` and `variants.py` read the whole joint VCF. A
   whole-genome run (millions of ranked records) will be slow and heavy; the helper parsing is
   duplicated across the recipes and could move to a shared `depictio/recipes/lib` module (a shared
   file, so not changed here).
3. A sample id containing a dot breaks the fake file name `variants.py` builds for `vcf_to_long`.
4. The sample filter reaches `ranked_variants` as an `IN` list of variant keys (thousands on a real
   run); a role or sample pick on the Ranked tab is therefore heavy on a whole genome.
5. Peddy, GENS, germline CNV and structural variant outputs are not built; a run that publishes them
   gets no tab for them.
6. The Overview's How to read tiles for the Mitochondria and Repeats tabs print a bare label when a
   run prunes those tabs (a `tab:` link alone stays); the steps cite a value and so are pruned.
7. The Repeats tab's KPI strip reads three optional collections: a run with a subset of the
   branches shows fewer than four cards in the strip.
8. Alignments precede the signal tracks in the manifest order, so the default track set opens on
   the VCFs and alignments and leaves the signal tracks to the picker.
