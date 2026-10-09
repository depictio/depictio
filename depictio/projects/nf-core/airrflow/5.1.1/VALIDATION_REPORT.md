# nf-core/airrflow 5.1.1: template validation report

**Date:** 2026-09-14
**Worktree / branch:** `depictio-worktrees/chore-nfcore-hpc-repin-runs`
**Validator:** local depictio-cli (`python -m depictio.cli` with this worktree on `PYTHONPATH`),
dry run and recipe runs only. No ingestion was run from here: the run below is ingested next
through the Nextflow completion trigger on the EMBL cluster.

## Goal

Bump the airrflow template from 5.1.0 to 5.1.1. The release keeps the output layout, so the
collections, recipes, links and dashboard are the 5.1.0 ones. The design decisions (AF-D1 to
AF-D8), the MultiQC overlap policy and the discrepancies AF-X1 to AF-X3 are in
`../5.1.0/VALIDATION_REPORT.md` and still apply.

## Data used

The AWS megatest bucket has no prefix for the 5.1.1 release sha
(`depictio/projects/nf-core/MEGATEST_STATUS.md`), so `megatest.yaml` keeps `results_sha: null`
and its keys stay the subset of the 5.1.0 megatest the template was built on. The bump was
validated on an EMBL HPC run repatriated with `scripts/nfcore_validation_hpc.py`, key
`airrflow511`:

- profile `test`: six BCR samples from two subjects (Sample2, Sample3 and Sample4 from Patient1,
  Sample6, Sample7 and Sample8 from Patient2);
- pipeline `v5.1.1-g8bc3e56` on Nextflow 26.04.6;
- local tree `~/Data/depictio-nfcore/airrflow/5.1.1/test`.

Every key in `megatest.yaml` matches a file in that tree.

## Upstream changes and what they touched

| 5.1.1 change | Effect on the template |
|---|---|
| enchantr boolean params formatted differently | None found. The template reads enchantR's report tables, not its arguments, and all ten enchantr recipes produce frames on the 5.1.1 run. `params.json` feeds provenance only, and `_introspect_pipeline_params` maps no airrflow flag, so the route flags are still passed by hand (AF-X2). |
| Nextflow floor `!>=26.04.1`, nf-schema 2.7.2 | None: the template declares no engine version. |
| MultiQC | Unchanged: the run wrote a MultiQC 1.34 report (version banner under `multiqc/`) with `multiqc/multiqc_data/multiqc.parquet`, where the template's pattern binds it. No reprocess. |

Bundled files refreshed from the HPC run: `pipeline_info/params.json` (the run's
`params_2026-09-14_20-38-52.json`, keys sorted and indented as before) and
`pipeline_info/software_versions.yml` (the run's `nf_core_airrflow_software_mqc_versions.yml`).
They held the 5.1.0 megatest content with only the version string rewritten. No code in the
repository reads these copies.

## Validation results

### Dry run

```bash
python -m depictio.cli run --template nf-core/airrflow/5.1.1 \
  --data-root ~/Data/depictio-nfcore/airrflow/5.1.1/test --dry-run
```

Exit 0 with 8/8 steps; the template resolves and the CLI detects `nf-core/airrflow 5.1.1`
(24 tools). A dry run does not scan files.

### Recipe runs

`python -m depictio.cli dev recipe run enchantr/<recipe>.py --data-dir <tree> -v 5.1.1` for the
ten recipes the template uses. All exit 0.

| Recipe | Output |
|---|---|
| `sequence_counts` | 6 rows x 17 columns |
| `sequence_fates` | 45 x 11 |
| `repertoire_summary` | 6 x 20 |
| `clonal_diversity` | 123 x 10 |
| `clone_sizes` | 190 x 7 |
| `clone_sets` | 189 x 10 |
| `clonal_overlap` | 6 x 8 |
| `v_gene_usage` | 119 x 9 |
| `v_gene_matrix` | 6 x 37 |
| `threshold_summary` | 2 x 9 |

### MultiQC

The run's parquet carries the fastp panels and the `fastqc-1` panels the dashboard binds, except
the `fastqc-1` Adapter Content plot: MultiQC wrote none for this run. The 5.1.0 run of the same
`test` profile has none either, while the 5.1.0 megatest and the 5.1.0 `test_tcr` run do, so it
follows the data rather than the release. On an ingest of this run that tile is expected to
render empty.

### Unit tests

`depictio/tests/unit/test_nfcore_megatest.py` and
`depictio/tests/models/test_shipped_dashboard_yamls.py`, filtered to cutandrun and airrflow:
46 passed. `depictio/tests/unit/test_nfcore_monitor.py`: 15 passed.

## Discrepancies

### AF-X4: `Table_sequences_assembly.tsv` is not byte-identical to `Table_sequences_process.tsv` on the test profile

The 5.1.0 manifest skipped `repertoire_comparison/Sequence_numbers_summary/Table_sequences_assembly.tsv`
as a byte-identical copy of `parsed_logs/Table_sequences_process.tsv`. On the `test` profile the
two carry the same counts but differ in how empty metadata cells are written (`NA` in the
`repertoire_comparison/` copy, blank in `parsed_logs/`). The 5.1.0 `test` and `test_tcr` runs
show the same difference, so it is not a 5.1.1 change, and no recipe reads the skipped file. The manifest
comment now says so.

### AF-X5: the test profile exercises fewer dashboard values than the megatest

Six samples instead of ten, and the samplesheet metadata is thinner: `tissue` reads `blood` for
all six and `sex` and `age` read `NA` for all six in `pipeline_info/samplesheet.valid.tsv`. On
an ingest of this run the `Tissue` and `Sex` filters each have a single value to offer. That is
a property of the test samplesheet, not of the template (compare AF-D7 on the megatest).

## Live check (2026-10-09, templates v2 rebuild)

The `test` run (EMBL HPC, `airrflow511`) ingested 8/8 on a local stack with
`--var GROUP_COL=cell_subset`. The Overview (hero, run facts, steps, four Key figures, four
Findings rows, four figures) and the seven child tabs (MultiQC, Sequence Processing, V Gene
Usage, CDR3 & Pairing, Clonal Diversity, Clonal Expansion, Clone Sharing) render with values.

## Not verified here

- The megatest and the TCR run on this template: the showcase points them at the 5.1.0 data,
  which 5.1.1 publishes in the same layout.
- No `docs/screenshots/`: the 5.1.0 ones predate the v2 dashboard and were not copied.
- There is no `.db_seeds/` directory for 5.1.1, so no seed needs regenerating.
