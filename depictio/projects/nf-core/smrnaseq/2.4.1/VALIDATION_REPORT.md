# nf-core/smrnaseq 2.4.1: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/smrnaseq/results-cb0af579b24cb8d5a3accd87b2f14ea93fe04832/`
(the 2.4.1 release tag). No server, no ingestion, no screenshots yet.

## Data

- Fetched with `uv run python scripts/nfcore_megatest.py fetch --pipeline smrnaseq --version 2.4.1 --max-file-mb 200`:
  60 files, 58.9 MB.
- 28 libraries, full test profile, 2x2 design (condition x stage). The design is not in any
  pipeline output: it is vendored as `input/sample_metadata.tsv` (built once from the
  test-datasets samplesheet, which is vendored as `input/samplesheet.csv`).
- Published layout quirks: miRDeep2 `result_*.csv` / `.bed` sit at the run root; no mature or
  hairpin count matrices, no edgeR tables (`mirna_quant/edger_qc/` is empty); miRTrace only
  published collapsed FASTAs; 20 of 28 mirtop GFFs were published (not used).
- MultiQC 1.33 parquet with fastp, fastqc, fastqc-1, mirtrace, mirtop, samtools sections.

## Recipe runs on the megatest

| Collection | Shape |
| --- | --- |
| `mirtop_mirna_counts` | 66612 x 12 with design (x 7 without) |
| `samples` | 28 x 19 with design (x 14 without) |
| `mirtop_mirna_summary` | 2379 x 12 |
| `mirtop_sample_matrix` | 28 x 1006 |
| `mirtop_sample_pca` | 28 x 11 |
| `mirtop_top_variable_heatmap` | 100 x 30 |
| `mirtop_isomir_composition` | 476 x 5 |
| `mirtop_isomir_landscape` | 280 x 6 |
| `mirtrace_composition` | 325 x 5 |
| `mirtrace_length` | 1428 x 5 |
| `mirtrace_complexity` | 5600 x 3 |
| `mirdeep2_predictions` | 20942 x 24 (18279 known, 2663 novel) |
| `mirdeep2_novel_precursors` | 648 x 25 |
| `mirdeep2_score_summary` | per sample x 21 cutoffs |

Sample hub medians: 5.87 M miRNA reads, 1394 miRNAs detected, 447 at 10 CPM or more, 46 %
of reads on the reference sequence, 89 novel and 646 known miRDeep2 calls per sample.

## Checks

| Check | Result |
| --- | --- |
| `test_shipped_dashboard_yamls.py`, `test_template_conventions.py` (`-k smrnaseq`) | 16 passed; 6 warn-only median-of-percent cards |
| `forbidden_terms` lint | passes (a "PC1" filter title collided with a sample id and was renamed) |
| `depictio/tests/recipes/test_smrnaseq_recipes.py` | 7 passed |
| `test_catalog.py`, `test_catalog_source_from_use.py`, `test_catalog_compose_matching.py` | 138 passed; 2 failures in other agents' dirs |
| `depictio-cli run --template nf-core/smrnaseq/2.4.1 --dry-run` | 8/8 steps, with and without `METADATA_FILE` |
| `ruff format` / `ruff check` on the new Python | clean |

## Not verified

- Live ingestion, dashboard rendering and screenshots (offline only).
- Catalog conformance project: the mirtrace and mirtop MultiQC sections need stubs and a
  regeneration (main-owned).
- Precursor links use `chrN:start-end`; assemblies without a `chr` prefix in UCSC are not
  handled.
