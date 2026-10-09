# nf-core/chipseq 2.1.0: template validation report

**Date:** 2026-09-14, rebuilt 2026-10-09 (templates v2, `depictio-worktrees/feat-nfcore-templates-2x`)
**Worktree / branch:** `depictio-worktrees/chore-nfcore-hpc-repin-runs`
**Validator:** local depictio-cli (`python -m depictio.cli`), config
`~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml`.

## Goal

Port the chipseq template from pipeline release 1.2.0 (DSL1, `bwa/mergedLibrary/`, MACS2,
DESeq2 differential binding) to 2.1.0 (DSL2, `<aligner>/merged_library/`, MACS3, DESeq2 QC
only), aligner-agnostic and for both peak types. The 1.2.0 validation history (megatest
ingest, CS-D1 to CS-D13) stays in `../1.2.0/VALIDATION_REPORT.md`.

**Scope of this pass.** Dry-runs, recipe runs and glob checks against real 2.1.0 output. No
real ingest was run and no dashboard was rendered: see "Not validated" below.

**v2 rebuild.** The sections from "Data used" to "Not validated" record the September port.
The 2026-10-09 rebuild (section "v2 rebuild, 2026-10-09", decisions CS2-D12 to CS2-D20)
replaced its hub and DESeq2 recipes and its dashboard. A decision that a later one
supersedes says so under its heading.

## Data used

EMBL HPC runs of the 2.1.0 release, repatriated by `scripts/nfcore_validation_hpc.py`
(Nextflow 24.04.2, `nf-core/chipseq: v2.1.0-g76e2382`):

| Key | Local tree | Aligner | Peak type |
|---|---|---|---|
| `chipseq2-test` | `~/Data/depictio-nfcore/chipseq/2.1.0/test` | bwa | narrowPeak (`--narrow_peak`) |
| `chipseq2-bowtie2` | `.../test_bowtie2` | bowtie2 | narrowPeak |
| `chipseq2-chromap` | `.../test_chromap` | chromap | narrowPeak |
| `chipseq2-star` | `.../test_star` | star | narrowPeak |

All four use the `test` profile: six libraries, SPT5 ChIP at T0 and T15 with two replicates
each (`SPT5_T0_REP1` ...), against two inputs (`SPT5_INPUT_REP1`, `SPT5_INPUT_REP2`), one
antibody. `chipseq2-full` (profile `test_full`, bwa, 16 libraries on hg19, broadPeak, the
megatest design) is not available locally and was not checked. `megatest.yaml` pins no AWS
run (`results_sha: null`).

## 1.x to 2.x path mapping

| 1.2.0 | 2.1.0 |
|---|---|
| `bwa/mergedLibrary/` | `<aligner>/merged_library/` (bwa, bowtie2, chromap, star) |
| `bwa/mergedLibrary/macs/narrowPeak/*_peaks.narrowPeak` | `<aligner>/merged_library/macs3/narrow_peak/*_peaks.narrowPeak` |
| `bwa/mergedLibrary/macs/broadPeak/*_peaks.broadPeak` | `<aligner>/merged_library/macs3/broad_peak/*_peaks.broadPeak` (pipeline default) |
| `.../macs/<type>/*_peaks.annotatePeaks.txt` | `.../macs3/<type>/*_peaks.annotatePeaks.txt` |
| `.../macs/<type>/qc/<sample>_peaks.FRiP_mqc.tsv` | `.../macs3/<type>/qc/<sample>.FRiP_mqc.tsv` |
| `.../macs/<type>/qc/*peak.summary.txt` | `.../macs3/<type>/qc/macs3_peak.summary.txt` |
| `.../macs/<type>/consensus/<ab>/<ab>.consensus_peaks.boolean.txt` | `.../macs3/<type>/consensus/<ab>/<ab>.consensus_peaks.boolean.txt` |
| `.../consensus/<ab>/deseq2/<contrast>/*.deseq2.results.txt` | removed (no differential binding since 2.0.0) |
| (MultiQC custom content only) | `.../consensus/<ab>/deseq2/<ab>.consensus_peaks.pca.vals.txt`, `.sample.dists.txt` |
| `.../deepTools/plotFingerprint/`, `.../deepTools/plotProfile/` | same names under `<aligner>/merged_library/deepTools/` |
| `.../preseq/*.ccurve.txt` | not written by default (`skip_preseq: true`) |
| `trim_galore/` | `trimgalore/` |
| `pipeline_info/design_reads.csv`, `design_controls.csv` | `pipeline_info/samplesheet.valid.csv` (one row per library, different schema) |
| `pipeline_info/software_versions.csv` (TSV) | `pipeline_info/nf_core_chipseq_software_mqc_versions.yml` + `pipeline_info/params_<timestamp>.json` |
| `multiqc/narrowPeak/multiqc_data/` (MultiQC 1.9) | `multiqc/<narrow_peak\|broad_peak>/multiqc_data/` (MultiQC 1.23, or 1.35 when forced) |
| samples `<group>_R<n>`, libraries `_T<n>` | samples `<sample>_REP<n>`, libraries `<sample>_REP<n>_T<n>` |

## MultiQC

The release pins MultiQC 1.23, which writes no parquet. Two layouts exist and the template
reads both:

- **Local trees.** Each holds the pipeline's 1.23 report under `multiqc/narrow_peak/` (no
  parquet) and a report regenerated with MultiQC 1.35 by `depictio.dev_scripts.multiqc_reprocess`
  at `multiqc/multiqc_data/multiqc.parquet` (+ `REPROCESSED.json`).
- **Cluster, Nextflow completion trigger.** MultiQC is forced to 1.35 and the pipeline itself
  writes `multiqc/narrow_peak/multiqc_data/multiqc.parquet` (measured by the coordinator on the
  resumed `chipseq2-test` run: exit 0, 350 KB); a broadPeak run writes it under
  `multiqc/broad_peak/`. The 1.23 report is overwritten and `multiqc/multiqc_data/` does not
  exist.

The `multiqc_data` scan pattern is
`multiqc/(?:(?:narrow|broad)_peak/)?multiqc_data/multiqc\.parquet$`, matched (like the scan
does) against the basename and against the path relative to DATA_ROOT. Checked:

| Path | Matches |
|---|---|
| `multiqc/narrow_peak/multiqc_data/multiqc.parquet` | yes |
| `multiqc/broad_peak/multiqc_data/multiqc.parquet` | yes |
| `multiqc/multiqc_data/multiqc.parquet` | yes |
| `other/multiqc/multiqc_data/multiqc.parquet` | no |
| every file of each of the four local trees | exactly one hit: `multiqc/multiqc_data/multiqc.parquet` |

### Bindings checked against the pipeline-written report

The trigger ingests the report the pipeline writes itself. A copy of it from the resumed
`chipseq2-test` run (MultiQC 1.35 with the pipeline's own `multiqc_config`) was read with
`extract_multiqc_metadata` from `depictio/cli/cli/utils/multiqc_processor.py`, the extraction
the ingest uses, and compared with the local reprocess of the same run:

| Module id | Pipeline-written report | Local reprocess |
|---|---|---|
| `fastqc` | LIB: FastQC (raw) | raw and trimmed reads in one module |
| `fastqc-1` | LIB: FastQC (trimmed) | absent |
| `samtools` | LIB: SAMTools, per library (`SPT5_T0_REP1_T1` ...) | filtered merged libraries |
| `samtools-1` / `samtools-2` | MERGED LIB: SAMTools (unfiltered) / (filtered) | absent |
| `picard` | MERGED LIB: Picard (unfiltered), Mark Duplicates only | every Picard plot |
| `picard-1` | MERGED LIB: Picard (filtered), CollectMultipleMetrics | absent |
| deepTools | `mlib_deeptools` (Fingerprint plot, Read Distribution Profile) | `deepTools` (also Fingerprint quality metrics) |
| `macs` | absent | present, no plot |
| `nf-core-chipseq-summary` | present, no plot | absent |
| `preseq` | absent | absent |

Rebound to the pipeline-written ids (CS2-D10): `cs-qc-samtools` from `samtools` to
`samtools-1`, `cs-qc-fingerprint` from `deepTools` to `mlib_deeptools`, and the collection's
`modules` / `plots` lists. After the change, checked both ways against the pipeline-written
report: no declared module, plot or dataset is missing, no section of the report is left
undeclared, and all 12 tiles bind. Against the local reprocess, 10 of 12 tiles bind; the
two rebound tiles have no section there. The other ten (`general_stats`, `fastqc` twice,
`cutadapt`, `picard` Mark Duplicates, `featurecounts`, `frip_score`,
`strand_shift_correlation`, `nsc_coefficient`, `rsc_coefficient`) bind in both reports. The
four design ids map to themselves through `build_sample_mapping` in both reports; the
library-level modules (`fastqc`, `fastqc-1`, `samtools`) carry `_T1` names the design
filter does not reach.

Local reprocess parquets (all four trees): 39 plot anchors on bwa, bowtie2 and chromap;
star adds `star_alignment_plot` and `star_summary_table` (41). No pipeline-written report was
available for the bowtie2, chromap and star routes, so their module ids are unchecked. The
rendering of the tiles was not checked in this pass.

## Dry-run: 4 / 4 trees, 8 / 8 steps

```bash
python -m depictio.cli run --template nf-core/chipseq/2.1.0 --data-root <tree> --dry-run \
  --CLI-config-path ~/.depictio/CLI.feat-nfcore-templates-lot1-101.yaml
```

`test`, `test_bowtie2`, `test_chromap`, `test_star`: "Depictio-CLI run completed successfully!
(8/8 steps)". The CLI detected `nf-core/chipseq 2.1.0 (nextflow, 20 tool(s))`. A dry-run does
not resolve recipe sources or scan matches (the unported 1.x copy of this template passed it
too), so the evidence that the template reads 2.x is the next two sections.

## Real import validation, offline

The dry-run skips `validate_template_project_config`, the step-3 check a real import runs
(Project model validation, including `MongoModel.sanitize_description`, which rejects any
`<` or `>` in a description). The coordinator's offline reproduction of that step
(template resolution as in `run.py`, a dummy `permissions` block, `_resolve_link_tags_to_ids`,
then `validate_model_config(resolved_config, Project)`) passed on all four trees, after the
description edits of CS2-D11: "OK nf-core/chipseq/2.1.0 on <tree>: 1 workflow(s), 15 data
collections, 1 dashboard(s)".

## Recipes

### `dev recipe run` (no overrides, dc_ref sources skipped)

`python -m depictio.cli dev recipe run <recipe> --data-dir <tree> -v 2.1.0`, rows produced:

| Recipe | test | test_bowtie2 | test_chromap | test_star |
|---|---|---|---|---|
| `nf-core/chipseq/sample_design.py` (local) | 4 | 4 | 4 | 4 |
| `nf-core/chipseq/peaks.py` (local) | 2832 | 1994 | 3608 | 2785 |
| `nf-core/chipseq/deseq2_pca.py` (local) | 4 | 4 | 4 | 4 |
| `nf-core/chipseq/deseq2_sample_distance.py` (local) | 16 | 16 | 16 | 16 |
| `deeptools/fingerprint_metrics.py` | 6 | 6 | 6 | 6 |
| `deeptools/plot_profile.py` | 4200 | 4200 | 4200 | 4200 |
| `macs2/peak_summary.py` | FAILED | FAILED | FAILED | FAILED |
| `homer/annotate_peaks.py` | passes, but reads 5 files | same | 5194 | 4033 |
| `macs2/consensus_boolean.py` | 1275 | 870 | 1586 | 1248 |
| `macs2/consensus_fc.py` | 250 | 250 | 250 | 250 |
| `preseq/complexity_curve.py` | dc_ref skipped | dc_ref skipped | dc_ref skipped | dc_ref skipped |
| `homer/tss_distance_profile.py` | dc_ref skipped | dc_ref skipped | dc_ref skipped | dc_ref skipped |

Both anomalies are what the template's `source_overrides` are for, and `dev recipe run`
applies none: `macs2/peak_summary.py` fails with "Source 'frip': no files matched glob
`**/*_peaks.FRiP_mqc.tsv`", and `homer/annotate_peaks.py`'s own glob also takes the consensus
annotation (5 files instead of the 4 per-sample tables).

### With the template's overrides and dc_ref inputs

The same recipes through `depictio.recipes.execute_recipe`, passing the `source_overrides`
declared in `template.yaml` and feeding dc_ref sources from the upstream recipe:

| Recipe | test | test_bowtie2 | test_chromap | test_star |
|---|---|---|---|---|
| `macs2/peak_summary.py` (frip `**/*.FRiP_mqc.tsv`) | 4 | 4 | 4 | 4 |
| `homer/annotate_peaks.py` (annotation `*/merged_library/macs3/*/*_peaks.annotatePeaks.txt`) | 2832 | 1994 | 3608 | 2785 |
| `homer/tss_distance_profile.py` (dc_ref from the row above) | 72 | 61 | 95 | 68 |

Every other recipe gave the row counts of the first table. Glob counts behind the overrides,
identical on all four trees:

| Source | Catalog glob | Template glob |
|---|---|---|
| `macs2/peak_summary.py` `frip` | 0 files | 4 files |
| `macs2/peak_summary.py` `summary` (`**/*peak.summary.txt`, not overridden) | 1 file (`macs3_peak.summary.txt`) | n/a |
| `homer/annotate_peaks.py` `annotation` | 5 files (4 per-sample + consensus) | 4 files |

FRiP per sample, bwa: 0.344, 0.346, 0.303, 0.299; bowtie2 0.45 to 0.60; chromap 0.30 to 0.31;
star 0.27 to 0.29.

### Link keys

Replayed as set intersections on the recipe outputs, identical on all four trees:
`design.sample_id` hits 4 / 4 in `macs2_peaks.sample`, `macs2_peak_summary.sample`,
`homer_annotated_peaks.sample`, `deeptools_fingerprint_metrics.sample`,
`deeptools_plot_profile.sample`, `deseq2_pca.sample_id` and `deseq2_sample_distance.sample`.
`macs2_peaks.peak_id` and `homer_annotated_peaks.peak_id` match 100% both ways. The
`design` -> `multiqc_data` sample_mapping link was not replayed.

### Synthetic broadPeak check

No local tree is a broadPeak run, so `recipes/peaks.py` was also run on a scratch tree built
from the bwa narrowPeak calls. The tree held `bwa/merged_library/macs3/broad_peak/`, with
each file cut to its first 9 columns as `*_peaks.broadPeak` and rewritten as a 15-column
`*_peaks.gappedPeak`. Result: 2832 of 2832 rows, `peak_type` `broadPeak` only (every
gappedPeak row dropped), no null `summit`, and every `summit` inside `[start, end]`. Adding
one `macs3/narrow_peak/*_peaks.narrowPeak` to the same tree makes the recipe refuse with
"DATA_ROOT holds both narrowPeak and broadPeak calls". This checks the code path, not
MACS3's real broad output.

## Unit tests

```bash
python -m pytest depictio/tests/models/test_shipped_dashboard_yamls.py \
  depictio/tests/unit/test_nfcore_monitor.py -q
```

First run: 766 passed, 2 failed, both on this dashboard (`test_every_tab_validates`,
`test_advanced_viz_survives_the_component_union`): `cs-cons-fig-distance` used
`visu_type: density_heatmap`, which a `mode: ui` figure does not accept. After switching that
figure to code mode (CS2-D3): 768 passed. Run once more on the final state, after the
MultiQC rebinding (CS2-D10) and the description edits (CS2-D11): 768 passed.

## Not validated

- **A real ingest and the dashboard render.** Out of scope for this pass: no data was
  written to a server, so card values, table and advanced_viz payloads, MultiQC tile renders
  and the code-mode sample-distance figure are unchecked against real frames.
- **The broadPeak route on real data** (the megatest `chipseq2-full`); only the synthetic
  check above covers `recipes/peaks.py`'s broad branch.
- **More than one antibody.** Every local tree has one (SPT5), so the per-file splitting of
  `deseq2_pca.py` / `deseq2_sample_distance.py` over several antibodies, the second
  `deseq2_*_2` MultiQC sections and the multi-set consensus panels are unexercised.
- **The preseq collections**: no tree has `*.ccurve.txt`.

## v2 rebuild, 2026-10-09

The template was rebuilt on the templates v2 rules: `dashboards/base.yaml` from the 1.2.0 v2
dashboard, `template.yaml` and the recipes brought level with every 1.x change made since the
September port (CS2-D20). Offline checks only: no ingest, no server, no render.

### What changed

- `template.yaml`: the `design` hub has the shared `design_factors.py` schema, built by a
  2.1.0 override (CS2-D12). New collections: `metadata` (optional design table),
  `picard_markduplicates_metrics_raw` / `picard_markduplicates_metrics`,
  `macs2_summit_profile`. DESeq2 QC is read by the 1.x recipes (CS2-D13). New variables:
  `METADATA_FILE`, `METADATA_ID_COL`, `GROUP_COL`, `GROUP_COL_DISPLAY`, `ANNOTATION_COLS`,
  `GENOME`, `PRESEQ_RAN`. 22 links.
- `recipes/`: `design_factors.py` and `deseq2_qc_pca.py` added; `sample_design.py`,
  `deseq2_pca.py` and `deseq2_sample_distance.py` removed; `peaks.py` declares
  `OUTPUT_SCHEMA`.
- `dashboards/base.yaml`: rebuilt from the 1.2.0 v2 dashboard without the Differential
  binding tab (CS2-D14), with the fingerprint, preseq and MultiQC bindings of CS2-D15 to
  CS2-D17.
- `docs/dashboards.md`: rewritten in the 1.2.0 structure, with what 2.x lost.
- `megatest.yaml`: `forbidden_terms` for the test and megatest designs; the help text calls
  `depictio-cli ingest`.

### Checks

| Check | Result |
|---|---|
| `pytest -n auto tests/models/test_template_conventions.py tests/models/test_shipped_dashboard_yamls.py tests/models/test_template_dc_order.py tests/unit/test_nfcore_megatest.py -k chipseq` | 40 passed |
| `pytest tests/recipes/test_chipseq_2_1_0_*.py tests/recipes/test_chipseq_design_factors.py` | 15 passed |
| `python -m depictio.cli dashboard validate dashboards/base.yaml --offline` | passed |
| `ruff format --check`, `ruff check` on the recipes and the new tests | clean |
| `<` or `>` in a `template.yaml` description; em dash in any file of this version | none |

### Replay on the four trees

Every collection replayed in template order: scans read as the template declares them,
recipes run through `execute_recipe` with the template's overrides, params and dc_ref inputs,
conditionals applied. `GROUP_COL=condition`, no `METADATA_FILE`. Rows:

| Collection | test | test_bowtie2 | test_chromap | test_star |
|---|---|---|---|---|
| `metadata` | removed | removed | removed | removed |
| `design` | 6 | 6 | 6 | 6 |
| `samplesheet` | 6 | 6 | 6 | 6 |
| `multiqc_data` (files matched) | 1 | 1 | 1 | 1 |
| `preseq_ccurve_raw`, `preseq_complexity_curve` | no file, optional | same | same | same |
| `deeptools_fingerprint_metrics` | 6 | 6 | 6 | 6 |
| `deeptools_plot_profile` | 4200 | 4200 | 4200 | 4200 |
| `picard_markduplicates_metrics_raw` (lines) | 672 | 672 | 672 | 672 |
| `picard_markduplicates_metrics` | 6 | 6 | 6 | 6 |
| `macs2_peaks` | 2832 | 1994 | 3608 | 2785 |
| `macs2_peak_summary` | 4 | 4 | 4 | 4 |
| `homer_annotated_peaks` | 2832 | 1994 | 3608 | 2785 |
| `homer_tss_distance_profile` | 72 | 61 | 95 | 68 |
| `macs2_summit_profile` | 324 | 324 | 324 | 324 |
| `macs2_consensus_boolean` | 1275 | 870 | 1586 | 1248 |
| `macs2_consensus_fc` | 250 | 250 | 250 | 250 |
| `deseq2_qc_pca` (with `condition`) | 4 | 4 | 4 | 4 |
| `deseq2_qc_sample_dists` | 4 | 4 | 4 | 4 |

The hub holds the four ChIPs and the two inputs; each ChIP takes its sample group as
condition, and the inputs keep their own group because the ChIPs they serve disagree. With
a two-row design table (`METADATA_FILE`, `METADATA_ID_COL`, `GROUP_COL` set to one of its
columns) and `PRESEQ_RAN=true` on `test`: `metadata` has 2 rows, the hub keeps 6, the ChIPs
take their condition from the table and its other column joins, and both Picard collections
are removed.

### Link keys

Key intersections on the frames above, identical on the four trees:

- `design.sample_id` reaches every value of `macs2_peaks`, `macs2_peak_summary`,
  `homer_annotated_peaks`, `homer_tss_distance_profile`, `macs2_summit_profile`,
  `deseq2_qc_pca` and `deseq2_qc_sample_dists` (4 / 4), and of
  `deeptools_fingerprint_metrics` and `deeptools_plot_profile` (6 / 6).
- `design.sample_id` reaches 0 / 6 of `picard_markduplicates_metrics.sample`: the catalog
  recipe leaves the `.mLb.mkD.sorted` stage tokens on the name (CS2-D16). Resolved in the
  template, not the catalog (which other templates' Picard names rely on): the link is now
  `resolver: pattern`, `pattern: "{sample}.mLb.mkD.sorted"`, as in atacseq 2.1.2.
- `macs2_peaks.peak_id` and `homer_annotated_peaks.peak_id` match 100% both ways; every
  `macs2_consensus_fc.peak_id` is in `macs2_consensus_boolean`.
- The three `design.antibody` wildcard links (`macs2_consensus_boolean`,
  `macs2_consensus_fc`, `deseq2_qc_pca`) reach the one consensus set, through its prefix
  label (CS2-D7).
- Not replayed (server-side resolution): the two region links from `macs2_peaks.chr` and the
  two `multiqc_data` links. The reprocessed parquet names the merged libraries as the hub does,
  plus `.mLb` / `.mLb.clN` stage names and the library-level `_T1_1` read names that
  `samplesheet.sample` maps.

### Not validated in the rebuild

- **A real ingest and the render**: Overview values and highlights, the route alternates
  after `_recompact_main_grid`, the PCA coloured by `condition`, the `{{param:...}}` values.
- **The preseq route**: no tree ran preseq, so the same-slot preseq and Picard alternates of
  CS2-D16 are checked by the offline validation only.
- **The fingerprint alternates on a pipeline-written report**: the local trees hold the
  reprocess (`deepTools`), not the trigger's report (`mlib_deeptools`).
- **broadPeak on real data and more than one antibody**, as in September.

## Live check (2026-10-09)

`test` ingested 8/8 on a local stack. The Overview (run facts with the aligner and read
length, steps, Key figures, Findings rows and the four highlights, the consensus PCA coloured
by condition) and the six child tabs (MultiQC, Signal, Peaks, Annotation, Locus, Consensus)
render with values. After the pattern link, picking one library in the left panel moves the
Signal tab's Duplicate reads card from the 3.4% median to that library's 4.8%.

## Discrepancies and decisions

### CS2-D1: every 1.x path moved; two catalog recipes need overrides

`<aligner>/merged_library/macs3/<type>/` replaces `bwa/mergedLibrary/macs/<type>/`. Recipes
and scans match on file name, so most of them read 2.x unchanged. Two do not. The FRiP file lost
its `_peaks` infix, and the HOMER glob now also sees the consensus annotation (a second
aggregation level under the same `sample` column). Both are fixed with `source_overrides`
in `template.yaml`; no catalog file changed.

### CS2-D2: the design hub is built from `samplesheet.valid.csv`

*Superseded by CS2-D12.*

2.x publishes no `design_controls.csv` / `design_reads.csv`. The template-local
`recipes/sample_design.py` collapses the library-level validated samplesheet into one row
per ChIP sample (`sample_id`, `control_id`, `antibody`, `group`, `replicate`, `single_end`,
`n_libraries`, `libraries`, `replicatesExist`, `multipleGroups`), so the `design` tag and the
dashboard bindings on it survive. The library-level sheet is also scanned as-is into a
`samplesheet` collection (replacing `design_reads`). The bundled 1.x copies
(`input/design_controls.csv`, `input/design_reads.csv`, `pipeline_info/software_versions.csv`)
were referenced by nothing in 2.1.0 and were removed.

### CS2-D3: differential binding is gone; DESeq2 QC is bound instead

*Superseded by CS2-D13 (recipes, figure) and CS2-D14 (tab).*

2.0.0 removed the DESeq2 differential binding test, so `deseq2_results_raw`, `deseq2_results`
and the whole `Differential binding` tab (volcano, MA, QQ, DA barplot, cards, table, contrast
filter) were removed. What `consensus/<ab>/deseq2/` still holds is read by two template-local
recipes (the catalog `deseq2/vst_pca.py` and `vst_sample_distance.py` need
differentialabundance's `all.vst.tsv`): `deseq2_pca` (the pipeline's own PCA coordinates and
explained variance, antibody joined from the samplesheet) and `deseq2_sample_distance` (the
distance matrix melted into sample pairs). Both are `optional: true`
(`--skip_deseq2_qc`), bound in a new `Sample similarity` section of the Consensus tab as
`use: deseq2/pca` and a code-mode figure that pivots the pairs back into a matrix and draws it
with `px.imshow`. The UI `heatmap` visu_type expects a wide matrix, and `density_heatmap` is
not a UI visu_type (`test_shipped_dashboard_yamls.py` rejected a first attempt with it). Each file carries a header row with
per-file content, so both recipes read the files headerless and split them on that row: the
glob loader does not expose file names (`pl.read_csv` in polars 1.43.2 has no
`include_file_paths`).

### CS2-D4: narrowPeak and broadPeak through one template-local recipe

`recipes/peaks.py` reads `**/*_peaks.*Peak` headerless and classifies each row by its filled
column count: 10 is narrowPeak, 9 is broadPeak, 15 is a gappedPeak row (also matched by the
glob), which is dropped. The rows go to the matching catalog transform (`macs2/peaks.py` or
`macs2/broad_peaks.py`). For broadPeak, `midpoint` is renamed to `summit`, so the Manhattan
panel keeps its column. A tree with both peak types is refused rather than double-counted.
Output adds `peak_type`.

### CS2-D5: preseq is skipped by default

*Superseded by CS2-D16.*

`skip_preseq: true` in 2.x on every aligner route, so no tree has complexity curves and no
parquet has a `preseq` module. `preseq_ccurve_raw` and `preseq_complexity_curve` are
`optional: true` (skipped with a warning when absent), and the MultiQC `cs-qc-preseq` tile
was removed (the featureCounts tile moved up to `y: 6`). The Signal tab's ribbon stays bound
and is empty on a default run.

### CS2-D6: no aligner-dependent collection

All ten non-dc_ref recipes and the scans produce the same collections on all four aligner
trees; the only route difference seen is the `star` MultiQC module on `--aligner star`. No
collection had to become optional for chromap or star.

### CS2-D7: `consensus_set` is labelled `SPT5_T`

`macs2/consensus_boolean.py` labels a consensus table by the longest common prefix of its
sample columns. With SPT5 at T0 and T15 that prefix is `SPT5_T`, not the antibody. It is a
label artifact of the catalog recipe (not changed here); the `peak_id` built from it stays
unique.

### CS2-D8: fingerprint metrics include the inputs

*Superseded by CS2-D15.*

2.x runs plotFingerprint once per IP with its control, and `deeptools/fingerprint_metrics.py`
returns a row for the input too (6 rows for 4 IPs). The input rows have no JSD columns, so
the `percent_genome_enriched` / `js_distance` scatter plots the IPs only, as its intro says.

### CS2-D9: provenance and engine

Provenance now reads `pipeline_info/params*.json` (with `hook_url` and `email*` excluded) and
`pipeline_info/*software*versions.yml`. The engine version is 24.04.2, read from the versions
YAML of the `test` run.

### CS2-D10: the pipeline-written MultiQC report uses its own module ids

*Superseded by CS2-D17 (in part: `deepTools` is declared again, the scan pattern changed).*

The first bindings were authored against the local reprocess. It regenerates the report
without the pipeline's `multiqc_config`, so every tool sits under a single module id. The
report the pipeline writes itself, the one the trigger ingests, splits them by stage (see
the MultiQC section). Two tiles did not bind there:
- `cs-qc-fingerprint` named `deepTools`, which is `mlib_deeptools` in that report.
- `cs-qc-samtools` named `samtools`, which there is the per-library instance; its `_T1` sample names escape the design filter.

Both now use the pipeline-written ids (`mlib_deeptools`, `samtools-1`). For samtools, the
unfiltered merged instance was chosen because the filtered one (`samtools-2`) is 100% mapped
by construction.

The collection's `modules` / `plots` lists now mirror that report exactly:
- Added: `fastqc-1`, `samtools-1`, `samtools-2`, `picard-1`, `mlib_deeptools`, `nf-core-chipseq-summary`, and the `featurecounts` plot list, which was missing.
- Dropped: `deepTools`, `macs`, `star`, `preseq`, `deseq2_pca_2`, `deseq2_clustering_2`. None of them is in a default single-antibody report.

Neither report has a `preseq` section.

### CS2-D11: no angle brackets in YAML descriptions

A real import rejects any description containing `<` or `>` (`MongoModel.sanitize_description`),
and `--dry-run` never runs that check. Six values in `template.yaml` used `<sample>`-style
placeholders: the `DATA_ROOT` variable description and five `columns_description` entries.
They now read `SAMPLE_REPn`, `CONTROL_REPn`, "one directory per aligner" and similar. Comments
keep their placeholders. The only `<` in `dashboards/base.yaml` is a `<=` inside a code-mode
figure's `code_content`, not a description.

### CS2-D12: the hub is the shared `design_factors.py` schema, built from the samplesheet

The v2 dashboard reads the 1.x hub columns (`sample_id`, `role`, `is_control`, `antibody`,
`condition`, `replicate`, `control_id`). A 2.1.0 override of
`nf-core/chipseq/design_factors.py` builds them from `pipeline_info/samplesheet.valid.csv`:
libraries collapse to their merged id (`_T<n>` dropped), ChIPs are the rows with an antibody,
controls are the rows without one plus every control a ChIP names, and a control carries the
antibodies of the ChIPs it serves. The design-table join (`METADATA_FILE`, keyed on the merged
id or on the sample group) and the condition inheritance are those of the shared recipe, and
`OUTPUT_SCHEMA` is identical (tested). `samplesheet` stays a scan of the library-level sheet;
it replaces 1.x `design_reads` for the MultiQC library link.

### CS2-D13: DESeq2 QC is read by the 1.x recipes

2.x publishes the same `*.pca.vals_mqc.tsv` and `*.sample.dists_mqc.tsv` files as 1.x, and
also the plain `.txt` copies. `deseq2_qc_sample_dists` uses the catalog recipe unchanged
(its default glob reads the `.txt` copy, so the 1.x `_mqc` override is not needed).
`deseq2_qc_pca` uses a 2.1.0 override that delegates to the shared
`nf-core/chipseq/deseq2_qc_pca.py` and left-joins `condition` from the hub (an optional
output column, null when the hub does not list a library). The template-local `deseq2_pca.py`
and `deseq2_sample_distance.py` and the code-mode distance figure are gone: the Consensus
tab's new "Sample space" section draws the PCA (`deseq2/qc_pca_embedding`, one cluster per
consensus set, coloured by condition) and the distance heatmap (`qc_distance_heatmap`).

### CS2-D14: no Differential binding tab; the Overview is rebuilt without it

The tab, its filters and every Overview element on `deseq2_results` were removed. The
Overview keeps the v2 shape (21 open rows):
- **Key figures**: Libraries, Peaks called, Consensus intervals (new: `ov-kf-consensus`,
  composition by libraries per interval, links to the Consensus tab), FRiP. Every route
  writes all four.
- **Findings**: Peaks, Annotation, Consensus, and a Signal row (new) that replaces the
  differential row with the largest distance from uniform coverage.
- **Figures**: the Manhattan and TSS highlights stay; the PCA (`cons-pca`) and the
  fingerprint (`sig-fingerprint`) replace the consensus support figure and the volcano.
- **The run**: libraries, antibodies, aligner and read length from `{{param:aligner}}` and
  `{{param:read_length}}`, and peaks with their type. No genome line, since `genome` is null
  on the test runs.

### CS2-D15: the fingerprint panels bind the columns 2.x writes

2.x runs plotFingerprint without the control comparison, so `js_distance`, `chance_divergence`
and `percent_genome_enriched` are never written. The Signal tab binds what is:
`synthetic_js_distance` (distance from a uniform coverage, card and scatter y),
`elbow_point` (share of the genome at background, card, filter and scatter x) and
`x_intercept` (scatter size). The inputs are ordinary rows with these columns, so the panels
show all six libraries and the Role filter separates them. This replaces CS2-D8.

### CS2-D16: preseq or Picard in the same Signal slot

2.x skips preseq by default. The Signal tab's preseq filter and card keep their slots, and a
Picard MarkDuplicates duplication filter and card take the same slots, since every run writes
the MarkDuplicates metrics. On a default run the optional preseq collections are skipped and
the Picard pair shows. A run with `--skip_preseq false` sets `--var PRESEQ_RAN=true`, whose
conditional removes the two Picard collections, so the alternates never both survive (they
would collide in the slot and one would wrap). The CLI does not set `PRESEQ_RAN` from the
run's params yet (proposed patch in the hand-off). The catalog
`picard/markduplicates_metrics.py` names the samples `SAMPLE_REPn.mLb.mkD.sorted` on this
layout, so the hub link reaches no row until the catalog patch: the card shows the run's
median but the hub filters do not narrow it.

### CS2-D17: MultiQC tiles for both report flavours

The tiles keep the pipeline-written ids of CS2-D10 (`samtools-1`, `mlib_deeptools`). The
fingerprint tile gets a same-slot alternate on `deepTools`, the reprocess id, and `deepTools`
is declared again in the collection's `modules`. Import drops the tile whose module is
absent, so one of the two shows. The scan pattern is the 1.x layout-agnostic one,
`(?:.*/)?multiqc(?:/[^/]+)?/multiqc_data/multiqc\.parquet$`: one hit on each local tree.

### CS2-D18: no genome by default

`GENOME` defaults to empty: the test runs use a non-UCSC reference, and an empty assembly
lays the Locus axis out from the contigs of the calls. A UCSC run sets `--var GENOME=hg38`.
The genome views open on `default_region: first`, the first contig.

### CS2-D19: consensus panels read the replicate columns

The UpSet and the heatmap select their set columns with `'_REP\d+$'`, the 2.x replicate
suffix. The first Consensus card ranks the intervals by chromosome.

### CS2-D20: 1.x changes since September

`diff -u` of the September 1.2.0 template (`chore-nfcore-hpc-repin-runs`) against the
current one. Carried over: `METADATA_FILE` and the design-table conditionals, the
`design_factors` hub (CS2-D12), `GENOME`, the layout-agnostic MultiQC pattern, the recursive
HOMER glob, `macs2_summit_profile` and its link, the region links, the library-level MultiQC
link (from `samplesheet`), the antibody wildcard links to the consensus and DESeq2 QC
collections, `deseq2_qc_pca` / `deseq2_qc_sample_dists` and their hub links, `depictio-cli
ingest` in the help text. Skipped: `deseq2_results_raw` / `deseq2_results` and their links
(no differential test in 2.x), `design_reads` / `design_controls` (2.x writes neither file;
`samplesheet` and the hub replace them), the vendored design table and
`reference.vars.GENOME` (no 2.x reference design table; the test data is not on a UCSC
assembly). Catalog changes since September only renamed the schema constants, which
`recipes/peaks.py` follows.
