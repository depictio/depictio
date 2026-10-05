# nf-core/demultiplex 1.8.0: template validation report

**Date:** 2026-09-23
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-lot2`
**Scope:** offline validation only (recipes on the real megatest files, model and catalog
tests, template resolution, CLI dry run). No ingestion against a running stack yet.

## Data used

AWS megatest run
`s3://nf-core-awsmegatests/demultiplex/results-daade37c4a75a4c1709ccf12434deb3424141319/`,
fetched with `bash download_test_data.sh` (183 files, 34.6 MB; FASTQ excluded).

- One flowcell, one lane, paired-end dual-index, 18 libraries.
- Demultiplexer: **bcl2fastq 2.20** (`params.json`: `demultiplexer: bcl2fastq`), so the run
  writes `Stats/Stats.json` and no BCL Convert `Reports/`.
- CheckQC 4.1.0, fastp 1.1.0, Falco 1.2.5, MultiQC 1.35 (parquet present, no reprocess).
- The run is a useful stress case: six libraries got almost no reads and a third of the lane
  went to Undetermined, mostly swapped combinations of the indexes in use.

## Catalog tools added

| Tool | Outputs | Fixture |
| --- | --- | --- |
| `bcl2fastq` | `demux_stats`, `lane_summary`, `read_quality`, `unknown_barcodes` | cut from the megatest Stats.json outputs |
| `bclconvert` | same four, same schemas | MultiQC test-data BCL Convert 3.9.3 reports run through the recipes |
| `interop` | `summary` | MultiQC test-data `summary_paired-end_dual-index.csv` |
| `multiqc/bcl2fastq`, `multiqc/checkqc`, `multiqc/falco` | MultiQC panels | the demultiplex megatest parquet |

## Recipe runs on the real data

| Collection | Rows | Check |
| --- | --- | --- |
| `demux_stats` | 19 | 18 libraries plus one Undetermined row; shares sum to 100 per lane |
| `lane_summary` | 1 | 30.7 M clusters PF of 34.2 M (90.0 %), 9.28 Gb, 34.7 % Undetermined |
| `read_quality` | 2 | Read 1 and Read 2 |
| `unknown_barcodes` | 100 | 96 % of their reads classed "Both indexes in use" |
| `fastp_library_qc` | 18 | library and lane parsed from the FASTQ stem |
| `cycle_quality` | 302 | two series, at most 200 points each |
| `checkqc_verdicts` | 16 | the reads-per-sample and Undetermined errors CheckQC raised, plus pass rows |
| `libraries` | 18 | 23 columns with metadata, 21 without (`__no_group__`) |

`interop/summary.py` was run on its fixture only (16 lane rows over 4 reads, error rate null
on the index reads). `bclconvert/*.py` were run on the MultiQC test-data reports only.

## Tests and checks

| Command | Result |
| --- | --- |
| `uv run pytest depictio/tests/models/test_shipped_dashboard_yamls.py -k demultiplex` | 10 passed |
| `uv run pytest depictio/tests/models/test_template_conventions.py -k demultiplex` | 6 passed |
| `uv run pytest depictio/tests/recipes/test_demultiplex_recipes.py` | 10 passed |
| `uv run pytest depictio/tests/models/test_catalog.py test_catalog_source_from_use.py` | 106 passed, 1 failed on another tool's catalog (`bismark_window_pca`), not this template |
| isolated catalog check of `bcl2fastq`, `bclconvert`, `interop` (`_load_tool_dir`, fixture schema, render roles, dtype grounding, existence) | clean |
| `resolve_template` with metadata, without, and with `IS_BCLCONVERT` | expected collections kept and dropped, 11 links, scans match the megatest files |
| `depictio-cli run --template nf-core/demultiplex/1.8.0 --data-root <megatest> --var METADATA_FILE=... --dry-run` | 8/8 steps |
| dashboard columns against recipe schemas (every bound column, `{GROUP_COL}` resolved) | no missing column |
| `use:` coverage | 48 of 60 tiles |

The twelve tiles without `use:` read pipeline-local collections (`libraries`,
`fastp_library_qc`, `cycle_quality`, `checkqc_verdicts`) that have no catalog entry.

## Not yet validated

- End-to-end ingestion and dashboard import against a running stack.
- The BCL Convert route on a real nf-core/demultiplex BCL Convert run.
- The SAV section on a run that ships an `interop_summary --csv=1` table.
- Multi-lane runs: `fastq_id` on the hub is the first lane's FASTQ stem, so the MultiQC
  fastp and Falco rows of the other lanes are not narrowed by the library filter.
