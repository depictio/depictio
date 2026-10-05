# nf-core/proteinannotator 1.1.0: validation report

Offline validation against the AWS megatest run
`s3://nf-core-awsmegatests/proteinannotator/results-cbf78d471f62d91af666e8c77bcd580b4743c6be/`
(a dev run, v1.2.0dev-gb8fac19; the template directory stays at 1.1.0, the latest release).
No server, no ingestion, no screenshots yet.

## Data

- Fetched with `uv run python scripts/nfcore_megatest.py fetch --pipeline proteinannotator --version 1.1.0 --max-file-mb 50`:
  36 files, 84 KB.
- Three samples, one protein each (408, 172 and 350 residues), test-sized HMM libraries,
  InterProScan with HAMAP, TIGRFAM and SFLD only. Two InterProScan TSVs are empty (no match)
  and two hmmsearch tables (Pfam and FunFam of one sample) hold only their header.
- The MultiQC parquet holds six SeqFu custom-content sections anchored by sample name
  (`<sample>_before-section-plot`, ...), so it is not read.
- No samplesheet or design is published: `input/samplesheet.csv` is the test-datasets sheet,
  `input/sample_metadata.tsv` a two-level `protein_set` design written for the demo.

## Recipe runs on the megatest

Run through the same raw scans the CLI builds (polars `scan_csv` with the template's
`polars_kwargs`, then the CLI's schema alignment and concat).

| Collection | Shape |
| --- | --- |
| `seqfu_stats` | 6 x 12 |
| `seqkit_sequences` | 3 x 5 |
| `hmmer_hmmsearch_domtbl` | 94 x 25 |
| `interproscan_matches` | 1 x 13 |
| `s4pred_secondary_structure` | 930 x 10 |
| `proteinannotator_domains` | 80 x 16 (79 hmmsearch domains at i-Evalue 0.01 or less, 1 InterProScan) |
| `proteinannotator_proteins` | 3 x 20 |
| `proteinannotator_residues` | 930 x 10 |
| `proteinannotator_database_coverage` | 3 x 7 |
| `proteinannotator_database_sets` | 3 x 7 |
| `samples` | 3 x 13 |

Every recipe also returns its declared schema with the optional sources absent (no
InterProScan, no S4PRED, no domains) and on a raw scan with no data line.

## Checks

- `depictio-cli run --dry-run` passes with and without `METADATA_FILE`, and with
  `SKIP_S4PRED` and `SKIP_INTERPROSCAN`.
- `test_shipped_dashboard_yamls.py`, `test_template_conventions.py`, `test_nfcore_megatest.py`
  and `test_catalog.py` pass for this template and its catalog tools.

## Not verified

- Ingestion, rendering and the structure resolver (ESMFold) on a live stack.
- The protein kinds (`molecule_3d`, `sequence_track`) were placeholders when the dashboard was
  written.
