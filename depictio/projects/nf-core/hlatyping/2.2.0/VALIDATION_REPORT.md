# nf-core/hlatyping 2.2.0 template validation report

Validated offline against the AWS megatest `results-3237d20e7e611d8bbf8c37e637202dfe8a23e996`
(the 2.2.0 release tag, `test_full` profile). Whole prefix: 176 objects, 153 MB; the fetched
subset is 9 files, 1.9 MB (`bash download_test_data.sh`).

No running stack was available for this build: the live check of RULES section 15 is listed
below as pending, item by item.

## Which run, and which samplesheet

**Three launches under one prefix.** `pipeline_info/` holds three sets of `params_*.json`,
`execution_trace_*.txt` and reports:

| Launch | Trace | Outcome |
| --- | --- | --- |
| 2026-02-02 07:08 | FastQC and CAT_FASTQ done, YARA_MAPPER failed (exit 134) on every sample, then aborted | no typing |
| 2026-02-16 10:30 | the same failure | no typing |
| 2026-02-16 10:48 | every process completed: CAT_FASTQ, CHECK_PAIRED, SAMTOOLS_COLLATEFASTQ, FastQC, YARA_INDEX, YARA_MAPPER, OptiType for five samples, MultiQC | the published outputs |

All three name the same input and parameters (`solver glpk`, `enumerations 1`, `beta 0.009`,
`tools optitype`), so the outputs (`optitype/`, `yara/`, the FastQC files at the root and
`multiqc/`) are one coherent set: the last launch's. The fetch keeps the latest
`params_*.json` as `pipeline_info/params.json`.

**Five samples, a three-row sheet.** `params.json` names
`test-datasets/hlatyping/samplesheets/samplesheet_full.csv` by URL, not by revision. That file
today (test-datasets `710446f`, 2026-07-10) has three rows (`NA12878_WES`, `GM12878_RNA`, a
peptide row with a `tsv` column that the 2.2.0 input schema does not accept): it was replaced
five months after the run. The sheet the run read is the previous revision (`2adcc84`,
2025-01-25): seven rows, five samples, a DNA exome as FASTQ, as the same FASTQ in two parts
(concatenated) and as a BAM, and an RNA sample as FASTQ and in two parts. That is exactly the
set in `optitype/`, `yara/`, the execution trace and the MultiQC report, so the template vendors
`2adcc84` unchanged under `input/samplesheet.csv`.

The five samples are therefore two individuals typed several ways, not a cohort: the three DNA
samples share one genotype (1129 to 1133 reads), the two RNA samples another (130 and 131
reads). The genotypes repeat by design, which is what a pipeline-function test checks.

## What was verified offline

| Check | Result |
| --- | --- |
| `depictio dashboard validate --offline dashboards/base.yaml` | pass |
| `test_template_conventions.py`, `test_shipped_dashboard_yamls.py`, `test_template_dc_order.py` with `-k hlatyping` | 22 passed |
| `test_advanced_viz_config_alignment.py`, `test_advanced_viz_allele_grid.py` | pass |
| `depictio/tests/recipes/test_hlatyping_recipes.py` (catalog `optitype`) and `test_hlatyping_project_recipes.py` (`samples`, `read_qc`) | 17 passed |
| `depictio dev catalog validate`, `depictio/tests/models/test_catalog.py` | pass, 106 passed |
| `depictio/tests/catalog/` | `test_conformance_project.py` fails 4 tests until the conformance project is regenerated for the new `optitype` outputs (shared files; the same 4 already fail for the other wave 4 modules) |
| Every recipe over the megatest (`execute_recipe`, input and output schemas) | pass, 5 collections |
| `depictio ingest --template nf-core/hlatyping/2.2.0 --dry-run` on the megatest | template resolved, 5 of 5 collections `ok`, 0 empty, 0 missing sources; stops at step 1 (no server configured) |
| The allele frequency code figure, run on the megatest genotypes | draws three traces (one per locus); HLA-A's commonest allele at 60% of the locus's 10 calls |
| MultiQC sample mapping (`SampleLookup` over the report's mappings) | each samplesheet sample reaches its FastQC rows (`<sample>_1`, `_2` and their adapter traces); OptiType's `<sample>_result` rows are not reached (open issues) |

The text tiles, KPI strips and section styling are held by the lint above (stored text heights,
at most three sentences per paragraph, no forbidden terms, no `GROUP_COL` in a `filter_expr`,
persistent filters reaching MultiQC, bundled section icons). The row budgets below are counted
by hand from the stored heights.

## Collection sizes on the megatest

| Collection | Rows |
| --- | --- |
| samples | 5 (3 DNA, 2 RNA; 4 FASTQ, 1 BAM; two samples of 2 runs) |
| multiqc_data | 1 report (MultiQC 1.32): FastQC (10 read files), OptiType, general statistics |
| optitype_genotypes | 30 (5 samples x 3 loci x 2 haplotypes; 3 homozygous loci, all HLA-A) |
| optitype_summary | 5 (11 distinct alleles over the run; 5 or 6 per sample) |
| read_qc | 10 (5 samples x 2 read files) |

## Routes (RULES section 13)

The template declares no conditional route: hlatyping 2.2.0 has no switch that removes FastQC,
OptiType or MultiQC, so every collection is written by every run that reaches MultiQC. The
Overview's Key figures and Findings rows read collections every run writes. A sample missing
from the samplesheet still enters the hub (`seq_type` `Not stated`), and a run without a sheet
lists the typed samples, so the hub never empties.

## Open rows per tab (stored heights)

| Tab | Open rows | Open sections |
| --- | --- | --- |
| Overview | 22 of 24 | hero 1, about 3, pipeline 3, key figures 2, findings 11 (text 2, grid and frequency 5, quality and reads 4), how to read 2 |
| MultiQC | 17 | 2 (read quality 12, HLA typing 4; more FastQC collapsed) |
| Reads | 12 | 3 (strip 2, read depth 4, read composition 4; table collapsed) |
| Genotypes | 10 | 2 (strip 2, genotype grid 6; two tables collapsed) |
| Alleles | 12 | 3 (strip 2, allele frequency 4, calls per allele 4) |
| Typing quality | 14 | 3 (strip 2, read support 6, per sample 4) |

## Findings

- **Genotypes.** The DNA individual is homozygous at HLA-A and heterozygous at HLA-B and -C
  (five distinct alleles); the RNA individual is heterozygous at all three loci (six). The
  FASTQ, concatenated-FASTQ and BAM routes of the DNA sample agree allele for allele, as do the
  two RNA routes.
- **Reads.** The concatenated samples explain 4 and 1 more reads than their single-file twins
  (1133 against 1129, 131 against 130): the concatenation step loses nothing. The DNA genotype
  explains 2.5% of its read pairs (4.5% for the BAM route, whose read files are smaller), the
  RNA genotype 8.3%: the test reads are pre-selected around HLA.
- **Objective.** The objective per read is 0.982 for the DNA samples and 0.973 for the RNA
  ones, exactly `1 - 0.009 x 2` and `1 - 0.009 x 3`: OptiType's objective subtracts `beta` per
  heterozygous locus (FRED-2/OptiType `model.py`, `read_cov`). The template says so on the
  Typing quality tab rather than presenting the ratio as a fit score.
- **FastQC.** Every read file fails or warns on per-sequence GC content (the HLA-enriched reads
  against FastQC's whole-genome model) and nothing else fails; duplicates stay between 9.6% and
  14.5%.

## Live check (RULES section 15): pending

None of these could be checked without a running stack; each is pending a live check.

| Item | Status |
| --- | --- |
| The Overview fits in about two screens, values fill in, highlights draw, `tab:` links open | pending live check |
| Controls dock right on full-width viz and on top of narrower ones | pending live check (allele grid w8, scatters w8 and w4) |
| No tile shows an empty band or a cut body; no tick label cut, no legend scrolling over tick labels | pending live check (the allele frequency x axis names every allele) |
| The map draws its tiles and points | not applicable (no map) |
| Each dock shows a few controls and "More options"; every view switch draws | pending live check (allele grid, scatters) |
| The group has the same colour on figures, advanced viz and filter chips | pending live check |
| Every child tab opens on its intro; every KPI card draws its secondary and caption, no bar reads about 1%, each icon in its own colour | pending live check |
| The Guide's demos are not empty | pending live check |
| Each conditional route renders without a broken highlight or a stray `{VAR}` | not applicable (no route); pending live check of the no-sheet hub |
| A sample picked in the left panel moves every card of a child tab | pending live check (the OptiType MultiQC rows are not narrowed, see open issues) |
| The allele grid draws both haplotypes, merges the homozygous HLA-A cells and an allele click narrows the per-sample tables | pending live check (the kind is INCUBATING; this is its first template binding) |
| The Locus tab opens on data | not applicable (no locus tab) |

## Scenarios

**Megatest:** `s3://nf-core-awsmegatests/hlatyping/results-3237d20e7e611d8bbf8c37e637202dfe8a23e996/`
(tag 2.2.0, run_root `.`, manifest megatest.yaml; the last of three launches, samplesheet
test-datasets `2adcc84`)

**MultiQC:** run wrote 1.32 -> used as-is (FastQC and OptiType sections, general statistics)

| # | Label | Profile / Flags | What differs | Template impact |
|---|-------|-----------------|--------------|-----------------|
| HT1 | **test_full megatest (validated offline)** | none | none | Every recipe runs on the real files, FASTQ, concatenated FASTQ and BAM routes, DNA and RNA; CLI dry run resolves 5 of 5 collections. |
| HT2 | **a real cohort** | a sheet of many individuals | many alleles per locus | The allele frequency axis and the allele filters grow with the alleles; the grid caps at 200 samples (`max_samples`). Highest-value check: no megatest has more than two individuals. |
| HT3 | **several solutions** | `--enumerations 3` | three rows per result table | The optimum is kept, `solutions` and `runner_up_gap` fill in; tested on synthetic tables only. |
| HT4 | **single-end reads** | a sheet with `fastq_1` only | FastQC names the file `<sample>` | `read_qc` reads it as `Single-end`; the typing share divides by the one file. Synthetic test only. |
| HT5 | **HLA-HD** | `--tools optitype,hlahd` (licensed, local install) | `hlahd/` class I and II tables | Not read: no class II tile, no HLA-HD collection. A catalog `hlahd` module would add DRB1, DQB1 and DPB1 to the grid. |
| HT6 | **no samplesheet given** | another run's DATA_ROOT without `input/` | `samples` from `optitype/` only | Every sample enters with `seq_type` `Not stated`; one group, every tile still draws. |
| HT7 | **with epitopeprediction** | the `alleles` column fed into an epitopeprediction sheet | two projects | Same allele strings; no live cross-project link (see docs/dashboards.md). |

**Ranking by template stress:** HT2 > HT5 > HT3 > HT4 > HT6 > HT1 > HT7

## Open issues

- **OptiType rows of MultiQC are not narrowed by the sample filters.** MultiQC names them
  `<sample>_result`, and the runtime sample mapping (`build_sample_mapping` without hub ids)
  keeps `<sample>_result` as its own canonical id, so a pick of `<sample>` reaches the FastQC
  rows only. The OptiType summary panel's own rows are the haplotype slots (A1 ... C2), so it
  cannot be narrowed by sample anyway; the general statistics keep the OptiType rows of every
  sample. `canonicalize_to_hub` (prefix match against the hub ids) would attach them, but it is
  not called at ingest.
- **`allele_grid` is INCUBATING** (`schemas.py`, pending the section 8 gate review against an
  oncoplot view). This template is its first binding outside the showcase; the INCUBATING entry
  is left to the lead (`test_advanced_viz_allele_grid.py` pins it).
- **No mapping statistics.** yara publishes BAMs only; the reads behind a genotype are
  OptiType's own count. A mapping rate would need `samtools flagstat` on the BAMs, which the
  pipeline does not run.
- **Samplesheet not published**: `pipeline_info/samplesheet.valid.csv` is documented but
  absent; the run's sheet is vendored from test-datasets history (`2adcc84`), since the URL in
  `params.json` now serves a different file.
- **FastQC files and the yara index land at the output root** in this release (the docs say
  `fastqc/`); the template reads FastQC through MultiQC's table, so either layout works.
- The conformance project and the Tool Studio catalog snapshot are not regenerated here
  (shared files): `test_conformance_project.py` fails until they are.
