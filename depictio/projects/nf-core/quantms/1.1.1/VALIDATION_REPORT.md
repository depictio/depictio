# nf-core/quantms 1.1.1 template: validation report

Status: built and validated offline against the AWS megatest (no server ingest was run).

## Run

- Bucket prefix: `s3://nf-core-awsmegatests/quantms/results-600505011027ab196bb18b1320607468bdae951a/`
  (the 1.1.1 release tag sha, 2023-03-27), run root `mode_dia/`.
- Profile: DIA (label free, DIA-NN, MSstats): 4 runs, 2 conditions of 2 injections, 1 contrast.
  `mode_lfq` holds a one-protein DDA test with no result tables; `mode_tmt` is a single TMT run.
  Neither is templated (see caveats).
- Subset fetched by `megatest.yaml`: 26 files, about 85 MB (the DIA-NN report 21 MB, four
  mzML spectrum tables 14 MB each, the matrices, the MSstats table, `sdrfparsing/`).
- No `params*.json` in this release: Run parameters and `{{param:}}` values print dashes.
- No `multiqc.parquet` and no MultiQC module in the pmultiqc report: no MultiQC collection or tab.

## Checks

| Check | Result |
| --- | --- |
| `depictio dashboard validate base.yaml --offline` | passed |
| `pytest depictio/tests -k "shipped_dashboard or template or recipe or megatest"` | 3816 passed, 1 skipped |
| Every recipe run on the megatest (outputs match `OUTPUT_SCHEMA`) | passed |
| Every column named by a component, filter, card, record card, `filter_expr`, text value and `dict_kwargs` exists in its collection | 86 components, 0 missing |
| `ruff format` and `ruff check` on the recipes | clean |

Warn-only: three cards take the median of `cv_pct` (a per-protein coefficient of variation, so
a median of per-protein values, not a mean of percentages). The convention test flags the
column name.

## Collections (rows x columns, default `GROUP_COL=condition`)

| Collection | Rows | Columns |
| --- | --- | --- |
| `samples` | 4 | 25 |
| `quantms_precursors` | 26758 | 26 |
| `quantms_proteins` | 6006 | 10 |
| `quantms_acquisition` | 4 | 11 |
| `quantms_acquisition_profile` | 464 | 6 |
| `quantms_ms2_peak_bins` | 44 | 6 |
| `quantms_run_summary` | 4 | 12 |
| `quantms_protein_summary` | 1515 | 16 |
| `quantms_protein_conditions` | 3019 | 8 |
| `quantms_sample_embedding` | 4 | 7 |
| `quantms_sample_correlation` | 4 | 6 |
| `quantms_replicate_pairs` | 2987 | 9 |
| `quantms_comparisons` | 1103 | 20 |

## Findings on this run

- The four runs are acquired alike: same gradient length, same MS2 rate, near-identical
  precursor and protein-group counts.
- The MSstats contrast tests 1103 protein groups and makes no significant call (smallest
  adjusted p-value about 0.29), which is expected: the spiked proteins are not in the search
  database, and two replicates per condition leave the test little power. The Differential
  abundance tab therefore shows an empty significant-protein card and a flat p-value
  histogram; the volcano, MA and QQ views still render.
- The MSstats table has `issue` empty for every protein, so the issue filter is not offered.

## Caveats

- The vendored SDRF (`input/sdrf.tsv`) is the public SDRF of the same dataset, taken from an
  older (2022) run in the same bucket; the 1.1.1 run itself stores only a staging path. The
  design in `sdrfparsing/` is the authoritative one; the SDRF only adds characteristics.
- `samples.py` keeps one row per file (label free). A TMT or iTRAQ design would need one row
  per channel and a different set of result tables.
- DIA-NN 1.8.1 reports no mass error, so there is no mass-accuracy view.
- The `<run_id>` entries in `columns_description` stand for the one-column-per-run matrices
  (the UpSet matrix of the protein summary and the correlation matrix).
- Group-based links use `{GROUP_COL}` as source and target column. They resolve when
  `GROUP_COL` is a hub column that the recipes can pass through (default `condition`).
