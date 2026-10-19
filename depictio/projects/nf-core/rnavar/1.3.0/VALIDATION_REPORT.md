# nf-core/rnavar 1.3.0 template validation report

Validated offline against the AWS megatest `results-5e72bcb5520e00422750c978d4153b38f1fd7312`, a
complete `test_full` run of the 1.x line (software_versions.yml: `nf-core/rnavar: v1.3.0dev`,
Nextflow 26.04.3, written 2026-06-01): 8 samples of four cell lines in two replicates each, aligned
to GRCh38 (NCBI iGenomes, chr-prefixed), HaplotypeCaller with VariantFiltration, no annotation.
The run is 136 GB, almost all BAMs; the fetched subset is 145 files, 140 MB
(`bash download_test_data.sh`), plus the vendored design table.

**Megatest:** `s3://nf-core-awsmegatests/rnavar/results-5e72bcb5520e00422750c978d4153b38f1fd7312/`
(not a release tag sha: 1.3.0dev, two weeks before the release run; run_root `.`, manifest megatest.yaml)

**MultiQC:** run wrote 1.35 -> used as-is

## Why not the 1.3.0 release run (RV-D1)

`nfcore_megatest.py resolve --pipeline rnavar --version 1.3.0` maps to
`results-a0e4641409eb7aed4b325e543d20577f9c08e437`, which is a truncated sync: 148 objects, six of
the eight BAMs, the per-sample STAR / Picard / samtools / FastQC reports, three restarted
`pipeline_info` sets, and **no `variant_calling/` and no MultiQC report**. Of the eight rnavar
prefixes in the bucket, `5e72bcb5` is the only one holding the calls; the others stop before
variant calling or hold `pipeline_info/` only (survey in megatest.yaml). The pin follows the mag
5.5.0 precedent: `fetch` warns "not the 1.3.0 release sha (a0e4641409eb); keeping the pin" and
keeps it. The prefix holds 235 objects (not the 290 first reported), 136.0 GB.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k rnavar` | pass; six warn-only "median of a percentage" notices, see Open issues |
| `test_advanced_viz_config_alignment.py` | pass |
| `depictio/tests/recipes/test_rnavar_recipes.py` (catalog: star, samtools idxstats, picard stage, vcf summaries, density) and `test_rnavar_project_recipes.py` (calls, navigator, hub) | 22 passed |
| `depictio/tests/recipes/` and the three template suites over every template (shared `sample_ids` and Picard edits) | 2072 passed |
| `depictio dev catalog validate`, `depictio/tests/models/test_catalog.py` | pass (121 tools) |
| `depictio/tests/catalog/test_conformance_project.py` | 4 fail until the conformance project is regenerated (RV-D8) |
| Every recipe of the template over the mirrored megatest (`execute_recipe`, input and output schemas, in declaration order) | pass, row counts below |
| `depictio ingest --template nf-core/rnavar/1.3.0 --dry-run` on the megatest with `METADATA_FILE` | 19 collections ingest (`vcf_variant_density` included), the 3 snpEff scans empty, their 3 recipes missing (optional) |
| The same template on a root holding real snpEff output of the same subworkflow (RV-D3) | the 6 snpEff collections resolve `ok` |

The text tiles, KPI strips and open-row budgets are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`,
persistent filters reaching MultiQC). The row budgets below are counted from the stored heights.

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| metadata | 8 (4 cell lines x 2 replicates, vendored) |
| multiqc_data | 1 report (modules star, samtools, picard) |
| star_log_final | 8 |
| star_read_fate | 48 (8 samples x 6 fates) |
| star_junctions | 62 (2.43 million junctions summed into motif class x annotation) |
| picard_markduplicates_metrics_raw | 13,694 lines |
| picard_markduplicates_metrics | 8 |
| samtools_stats_raw | 79,557 lines (the 8 `.md.stats`) |
| samtools_stats_sections | 1,826 (SN 8, RL 8, COV 1,048, ID 322, IS 440) |
| samtools_idxstats | 1,560 (8 samples x 195 contigs, the `.md` stage) |
| vcf_calls_raw | 767,016 lines (16 VCFs, raw and filtered) |
| vcf_variants | 383,508 (the 8 filtered VCFs; 331,776 PASS) |
| vcf_callset_summary | 8 |
| vcf_substitution_spectrum | 48 |
| vcf_filter_breakdown | 62 |
| variant_windows | 2,543 (1 Mb windows over the primary contigs) |
| vcf_files | 8 VCFs + 8 .tbi (indexed_file) |
| snpeff_* (6 collections) | 0 (no `--tools`; on the proxy root: 89,653 annotated calls, 100 composition rows, 39,968 gene rows for 2 samples) |
| samples | 8 |
| vcf_variant_density (catalog `vcf/variant_density`) | 17,441 (8 samples x 1 Mb windows holding a PASS call, primary contigs) |

## Routes (RULES section 13)

Simulated from the collections each component binds and the importer's gates
(`_component_has_data`, `_prune_unresolved_text_values`, `_tab_meets_minimum`, orphaned
highlights); the live import is pending (section 15 below).

| Route | Result |
| --- | --- |
| Full run with `--tools snpeff` | nothing dropped |
| No `--tools` (the megatest) | every Annotation component reads a `snpeff_*` collection, so the tab keeps only its intro and is dropped; the Annotate step loses its line with `n_ann`; the tab tile draws nothing; the four highlights stay (none is on Annotation) |
| `--skip_tools variantfiltration` | no filtered VCF: `vcf_files` is empty and pruned with the Genome file track; `variants.py` reads the unfiltered VCFs, every call is PASS (FILTER `.`), the FILTER cards and filter collapse to one value |
| No design table | `metadata` is dropped; the hub carries `__no_group__` ("All samples"); group filters, splits and colours fall back to one group |
| Start from BAM / CRAM | STAR and MarkDuplicates are skipped: `star_*` and `picard_*` are optional and pruned, so the Alignment strip, read fate, junctions and duplication go; the hub keys on the callset's samples; samtools still runs |
| Start from VCF | every alignment report is absent: the Alignment and Coverage tabs are dropped, the MultiQC tab keeps whatever the report holds |

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 21 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 10, how to read 2 |
| MultiQC | 13 | 2 (the intro is 1 of them) |
| Alignment | 17 | strip + 3 (read fate 4, mapping and duplication 6, junctions 4; tables collapsed) |
| Coverage | 17 | strip + 3 (depth 6, contig classes 4, mitochondrial and ribosomal 4; table collapsed) |
| Callset | 19 | strip + 3 (quality 6, spectrum 4, depth and allele fraction 6; tables collapsed) |
| Annotation | 18 | strip + 3 (impact 4, consequences 5, coding calls 6; tables collapsed) |
| Genome | 20 | strip + 2 (karyotype 5, navigator 3 + calls 5 + files 4) |

## Findings on the megatest

- **Alignment.** 92 to 132 million input reads per sample, 82.0% to 88.1% uniquely mapped, a
  mismatch rate of 0.28% to 0.73%; 99.6% to 99.85% of the splices fall on annotated junctions and
  0.3% to 0.9% of the junctions are novel.
- **Duplication.** Picard flags 38% to 87% of the reads as duplicates; the two replicates of a cell
  line agree within 7 points, so the spread is the libraries' expression profile, not a failure.
  Hence a box, not a threshold, on the duplication card.
- **Coverage.** 16% to 46% of the covered bases reach 10x. 2.1% to 10.0% of the mapped reads go to
  the mitochondrion, and **5% to 23% land on two unplaced contigs, `chr22_KI270733v1_random` and
  `chrUn_GL000220v1`, which carry the 45S ribosomal DNA repeats on GRCh38** (RV-D5): hence the
  "unplaced and alt contigs" card and the mitochondrial-against-ribosomal scatter.
- **Calls.** 32,741 to 64,693 calls per sample, 82% to 91% PASS (29,829 to 53,163). SnpCluster is
  the commonest failed filter (6.6% of the calls of one sample), then QD, then FS.
- **Ts/Tv and editing.** Ts/Tv of the PASS SNVs is 2.45 to 2.72, above the genome-wide ~2.0 to 2.1
  of a DNA callset; in every sample the folded T to C class (A to G or T to C on the transcript,
  where A-to-I editing lands) holds 37.4% to 39.2% of the PASS SNVs against 33.0% to 34.6% for C to
  T, the reverse of a DNA spectrum (RV-D9).
- **Zygosity.** The het/hom-alt ratio is 1.61 for one cell line, 1.71 to 1.78 for another, and 1.04
  to 1.25 for the two cancer lines, whose loss of heterozygosity is visible without a matched normal.
- **Depth.** Median depth at the PASS calls is 14 to 29; the median heterozygous allele fraction is
  0.44 to 0.47.
- **Genome.** 2,543 windows of 1 Mb hold a PASS call; chr1, chr19 and chr2 carry the most variants;
  1,323 calls (0.3%) sit on alt or unplaced contigs and are left out of the navigator.

## Decisions and defects

- **RV-D1** release run truncated; non-tag pin (above).
- **RV-D2** rnavar runs no bcftools stats and no mosdepth on a FASTQ start (mosdepth only on a CRAM
  input), so the callset numbers come from the VCF rows (new catalog `vcf/callset_summary`,
  `vcf/substitution_spectrum`, `vcf/filter_breakdown`) and coverage from `samtools stats` (COV
  histogram) and `samtools idxstats` (new catalog `samtools/idxstats`).
- **RV-D3** the megatest ran without `--tools` (params.json has no `tools` key), so there is no
  annotation. rnavar annotates through the nf-core `vcf_annotate_snpeff` subworkflow, the same as
  sarek, and names its files the same way (`<sample>.haplotypecaller.filtered_snpEff.ann.vcf.gz`,
  `..._snpEff.csv`, `..._snpEff.genes.txt`). The Annotation route was therefore validated on
  sarek 3.10.0's HaplotypeCaller snpEff output (2 VCFs + .tbi, 2 CSV, 2 gene tables, 13.3 MB, under
  `~/Data/depictio-nfcore/rnavar/1.3.0/snpeff_route_proxy`): the template's three scan regexes
  match, the three catalog recipes produce 89,653 / 100 / 39,968 rows with sample and caller
  parsed. Not validated: VEP (`--tools vep`) has no CSQ parser in the catalog, so a VEP-only run
  has no Annotation tab (only MultiQC's `vep` module, which no tile binds).
- **RV-D4** the MultiQC report has no FastQC section although the FastQC zips are published; no
  FastQC panel is bound.
- **RV-D5** the rDNA on unplaced contigs (above); the sample hub carries it as
  `other_contig_reads_pct`.
- **RV-D6** rnavar publishes two samtools stats and idxstats per sample (`.aligned` and `.md`) and
  names the Picard report `<sample>.md.metrics.txt`. `md` and `aligned` were added to the shared
  stage tokens (`depictio/recipes/lib/sample_ids.py`) and `md` to Picard's report tokens; the
  template scans the `.md` reports only, and `samtools/idxstats` keeps one stage per sample.
- **RV-D7** both HaplotypeCaller VCFs of a sample hold the same records; `variants.py` reads the
  filtered one (or the only one), so no call is counted twice.
- **RV-D8** the catalog gained 8 outputs (`star/log_final`, `star/read_fate`, `star/junctions`,
  `samtools/idxstats`, `vcf/callset_summary`, `vcf/substitution_spectrum`, `vcf/filter_breakdown`,
  `vcf/variant_density`); `depictio/projects/init/catalog_conformance` (shared, not edited here)
  must be regenerated (`python -m depictio.projects.init.catalog_conformance.scripts.generate_project`)
  for `test_conformance_project.py` to pass again.
- **RV-D9** the T to C excess is the editing signal only in aggregate; the template does not flag
  individual editing sites (no REDIportal / RADAR lookup is published by the pipeline).
- **RV-D11** (wave 4c) the variant karyotype: `vcf_variant_density` (catalog
  `vcf/variant_density`, 1 Mb bins) is now declared after `vcf_variants`, linked from the sample
  hub, and drawn on the Genome tab as an `ideogram` in density mode on `{GENOME}` (`use:
  vcf/density_karyotype`, a render added to the catalog output). It takes the slot and the 5 rows
  of the cohort manhattan it replaces, so the tab keeps its 20-row budget; the Overview's Genome
  highlight now reads it.
- **RV-D10** `samtools/stats_sections` decimates the COV histogram to 200 geometric bins, so
  `bases_10x_pct` counts from the bin whose centre is at or above 10x, a few tenths of a point off
  the exact share.

## Section 15 live check (pending, no stack in this environment)

Every item below is **pending live check**; nothing here has been seen rendered.

| Item | Status |
| --- | --- |
| The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open | pending live check |
| Controls dock right on full-width viz and on top of narrower ones | pending live check |
| No tile shows an empty band or a cut body; no tick label cut, no legend scrolling over ticks | pending live check |
| The map draws its tiles and points | not applicable (no map) |
| Each dock shows a few controls and "More options"; every view switch draws | pending live check |
| The group has the same colour on figures, advanced viz and the filter chips | pending live check |
| Every child tab opens on its intro; every KPI card draws its secondary and caption, no bar reads about 1%, each icon in its own colour | pending live check |
| The Guide's demos are not empty | pending live check |
| Each conditional route renders without a broken highlight or a stray `{VAR}` | pending live check |
| A sample picked in the left panel moves every card of a child tab; the Genome tab opens on data (non-zero region cards) | pending live check |

## Open issues

- The Genome tab's navigator and density tiles read `variant_windows`, a cohort-level collection
  with no sample column: the persistent sample filters narrow the call track and the region cards
  but not the windows. A per-sample navigator would be about 17,000 rows, past the 10,000-row
  sample a `genome_view` navigator receives (TEMPLATE_BOTTLENECKS 20).
- The Genome file track reads one lane per sample; TEMPLATE_BOTTLENECKS 26 (one lane decoded at a
  time) applies to its 8 lanes as it did to sarek's.
- The navigator opens on `default_region: first`, the whole first contig, so the file track's
  `file_window_size` is raised to 250 Mb (RULES section 8): an RNA VCF is 1.3 to 2.9 MB whole,
  so a whole-contig range read is cheap here, but a DNA-scale VCF on the same template would
  fetch far more. Not measured live.
- Six cards take the median of a `*_pct` column (lint rule f, warn only): each row is one sample,
  so the median is the intended reading.
- The `allele fraction against depth` scatter binds the 383,508-row call table; it is sampled by
  the server like sarek's and was not seen live.
- The Genome karyotype shows one sample at a time (`facet_by_sample: false`): the eight samples
  of the megatest are past the six karyotypes a tile draws side by side. The sample is picked in
  the tile's controls (the first until then); not seen live.
- `indexed_file` + `genome_view` stands in for a JBrowse2 collection (`TODO(jbrowse)`).

## Validation scenarios

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| RV1 | **test_full megatest (validated offline)** | `test_full`, pinned `5e72bcb5` | none | 19 of 25 collections populate: 383,508 `vcf_variants`, 8 callsets, 2,543 navigator windows, 17,441 karyotype windows; the 6 snpEff collections are absent and the Annotation tab is pruned. |
| RV2 | **snpEff annotation** | `--tools snpeff` | `annotation/<s>/*_snpEff.ann.vcf.gz`, `reports/snpeff/<s>/` appear | The Annotation tab and the Annotate step appear; recipes validated on the same subworkflow's sarek output (RV-D3); the rnavar file layout itself is unseen. |
| RV3 | **VEP only / merge** | `--tools vep` or `merge` | `_VEP.ann.vcf.gz` / `_snpEff_VEP.ann.vcf.gz` | VEP's CSQ is not parsed by any catalog recipe: VEP-only has no Annotation tab; with `merge`, the `_snpEff_VEP` file does not match the snpEff regex (it ends in `_VEP.ann`), so only a `snpeff` entry in `--tools` feeds the tab. |
| RV4 | **no VariantFiltration** | `--skip_tools variantfiltration` | only `<s>.haplotypecaller.vcf.gz` | `variants.py` falls back to the unfiltered VCF; `vcf_files` pruned with the file track; FILTER tiles show one value. |
| RV5 | **BAM / CRAM / VCF start** | samplesheet with `bam`, `cram` or `vcf` columns | no STAR, no MarkDuplicates (VCF: no alignment reports at all); mosdepth runs on CRAM | `star_*` / `picard_*` (and from VCF `samtools_*`) are optional and pruned; the hub keys on the callset; mosdepth output is not read. |
| RV6 | **no design table** | any, without `METADATA_FILE` | no factors | `metadata` pruned, one constant group. |
| RV7 | **GRCh37 Ensembl** | `--genome GRCh37` | contigs `1`, `2`, ... | Pass `--var GENOME=none`: the Genome tab loses its assembly axis and gene lane; the contig classes and primary-contig filters already accept unprefixed names. |

**Ranking by template stress:** RV1 > RV2 > RV5 > RV4 > RV3 > RV7 > RV6
