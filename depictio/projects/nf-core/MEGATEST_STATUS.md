# nf-core megatest status

Survey of the public AWS megatest bucket (`s3://nf-core-awsmegatests/`) for the
pipelines depictio templates or considered templating, taken on 2026-09-05 with
`scripts/nfcore_megatest.py`. Every release of a pipeline is expected at
`<pipeline>/results-<tag_sha>/`, where `tag_sha` is the release's sha in
<https://nf-co.re/pipelines.json>. In practice many release prefixes are empty
(only `pipeline_info/` plus zero-byte directory markers), truncated syncs (a few
multi-GB BAM/FASTQ intermediates, no reports) or simply absent, so the resolver
verifies each run before anything is downloaded.

**Status column.** `ok` = the release's own prefix is a real run (at least 5 data
objects outside `pipeline_info/`, at least 5 of them under 50 MB); `empty` = the
prefix exists but fails that check (failed run or truncated sync); `missing` = no
prefix for the release sha; `partial` = passes the check but publishes only part
of the expected outputs. Object counts come from listings capped at 2000-3000 keys
and are lower bounds for the big runs.

## Latest release per pipeline

| pipeline | latest release | tag_sha | megatest | run_root | MultiQC parquet | notes |
|---|---|---|---|---|---|---|
| ampliseq | 2.18.0 | `2723d4c2` | ok | `.` | yes (`multiqc/multiqc_data/`) | Shipped template (2.16.0, 2.18.0). Run wrote MultiQC 1.34. 2.14.0 to 2.17.0 prefixes are complete too. |
| viralrecon | 3.0.0 | `395079f1` | partial | `.` | no | Shipped template. Prefix holds 277 files / 7.9 GB (nanopore + artic layout: `artic_minion/`, `assembly/`, `fastp/`, `kraken2/`, `nanoplot/`) but no `multiqc.parquet`; the bundled `run_1/` comes from an EMBL cluster run (MultiQC 1.31). 2.x prefixes predate the parquet era. |
| variantbenchmarking | 1.5.0 | `8b21c017` | ok | `.` | no (no `multiqc/`) | Shipped template is 1.4.0 and pins this 1.5.0 run on purpose: it is the only run with both `small/` (germline) and `indel/` (somatic). The 1.4.0 release's own run (`68a32098`) is a truncated sync (7 files: rtg-tools reference SDF, two VCFs, one parquet under `small/multiqc/`, no summary tables) and resolves as `empty`. |
| differentialabundance | 2.0.0 | `30ed7741` | ok | `.` (outputs under `tables/<paramset>/`, paramset dirs contain commas) | none (no MultiQC by design) | **Selected.** 33 files / 134 MB. Every older release prefix (1.2.0 to 1.5.0) is empty. |
| funcscan | 4.0.0 | `aee3dc96` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Selected.** 3769 files / 2.9 GB. Run wrote MultiQC 1.34 with an empty general-stats table. 3.0.0 and 2.x prefixes are empty. |
| airrflow | 5.1.1 | `8bc3e567` | missing | | | **Selected run is 5.1.0** (`e69d49e3`, 739 files / 12.2 GB, parquet at `multiqc/multiqc_data/`, MultiQC 1.34 with fastp + FastQC). 5.0.0 is complete too; 4.3.x runs predate the parquet; 4.2.0 and 4.1.0 prefixes are empty. |
| rnafusion | 4.1.3 | `76ad76e7` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Selected.** 383 files / 624 MB, MultiQC 1.33 with full module exports. 4.1.1 is empty; 4.1.0 (10 files) and 4.0.0 (20 files) are partial syncs. |
| rnaseq | 3.26.0 | `e7ca4627` | ok | `aligner_star_salmon/` | yes (`multiqc/star_salmon/multiqc_report_data/`) | **Selected.** 1568 files / 114 GB across `aligner_star_salmon/` and `aligner_star_rsem/`. MultiQC 1.33 writes `multiqc_report_data/` (not `multiqc_data/`): no shipped scan regex or catalog glob matches it today. 3.24.0 and 3.25.0 are complete; 3.23.0 and older predate the parquet or are truncated. |
| taxprofiler | 2.0.1 | `70ecc15e` | ok | `.` | yes (`multiqc/multiqc_data/`) | **Selected.** 680 files / 3.1 GB, MultiQC 1.34 with 16 modules plus raw profiler txt outputs. 2.0.0 is complete too; 1.2.x predate the parquet. |
| chipseq | 2.1.0 | `76e2382b` | empty | | no | 2.1.0 (29 files / 199 GB, 1 small) and 2.0.0 (9 files / 51 GB) are truncated syncs of BAMs. **Selected run is 1.2.0** (`048fd685`, 871 files / 79.7 GB, run root `bwa/mergedLibrary/...`), which wrote **MultiQC 1.9** (`multiqc/{broadPeak,narrowPeak}/multiqc_data/multiqc_data.json`, no parquet) and must be reprocessed with 1.35. 1.2.1 (`0f487ed7`) exists and is a complete structural twin of 1.2.0 (same 871 files, same sizes, same layout); the selection stays on 1.2.0. |
| sarek | 3.10.0 | `8ccac7ad` | ok | `test_full_germline_ncbench_agilent/` (also `test_full_germline_aws/`) | yes (`test_full_germline_ncbench_agilent/multiqc/multiqc_data/`) | Not in this lot. 563 files / 104 GB; somatic profiles absent from the megatest. 3.9.0 complete; 3.8.x and older predate the parquet. |
| crisprseq | 2.3.0 | `0e9f915c` | ok | `.` | not seen | Not in this lot. Flat layout with thousands of per-sample files at the prefix root (listing capped at 3000 keys, no parquet among them); screening workflow never published. Every 2.0.0 to 2.2.1 prefix is empty. |
| scrnaseq | 4.2.0 | `3fc17b4f` | ok | `aligner_*/` (`cellranger`, `kallisto`, `simpleaf`, `star`) | yes (per aligner `multiqc/multiqc_data/`) | Not in this lot. 421 files / 137 GB; three of the four aligner roots carry a parquet. 2.x prefixes are empty or a single BAM. |
| smrnaseq | 2.4.1 | `cb0af579` | ok | `.` | yes (`multiqc/multiqc_data/`) | Not in this lot. 163 files / 1.6 GB. Every older prefix (2.2.3 to 2.4.0) is empty. |
| oncoanalyser | 3.0.0 | `7c74c87a` | ok | `HCC1395/` (sample-named) | none (no MultiQC) | Not in this lot. 604 files / 272 GB; 2.3.0 and 2.2.0 complete, 2.1.0 and older empty. |
| methylseq | 4.2.0 | `5aa56467` | empty | | no | 5 intermediates (3 BAM, 2 `txt.gz`, 37.6 GB) and nine restart `params_*.json`; 4.0.0 empty, 3.0.0 truncated (9 BAMs / 92 GB). Last complete run is 2.3.0 (2022, 1283 files, pre-parquet MultiQC). |
| atacseq | 2.1.2 | `1a1dbe52` | empty | | no | 2.1.2 and 2.1.1 hold a single 12 GB object each. Last complete run is 1.2.2 (2022, 488 files, pre-parquet). |
| cutandrun | 3.2.2 | `6e1125d4` | empty | | no | 3.2.2, 3.2.1 and 3.2 hold directory markers only. Last complete run is 3.1 (2023, 415 files, pre-parquet). |
| quantms | 1.2.0 | `fa34d79f` | empty | | no | Markers for `mode_dia/`, `mode_lfq/`, `mode_tmt/` and nothing else. Last complete run is 1.1.1 (2023, 224 files). |
| bacass | 2.6.1 | `5ed7c2dd` | missing | | | No prefix for 2.6.1 and every older prefix (2.1.0 to 2.5.0) is empty: no usable megatest at all. |
| raredisease | 3.1.2 | `83f2699d` | empty | | no | Every release prefix (2.2.0 to 3.1.2) holds `pipeline_info/` only. |
| mag | 5.5.0 | `56abab5b` | partial | `.` | no | 43 small files / 11.8 MB under `GenomeBinning/`, `QC_longreads/`, `QC_shortreads/`: passes the heuristic but publishes no MultiQC, bin QC or GTDB-Tk tables. 5.4.0 to 5.4.2 are complete (650 files / 11.9 GB, no parquet seen in the first 1500 keys); 5.2.0 and 5.3.0 empty. |
| phyloplace | 2.1.0 | `441e351e` | missing | | | 2.0.1 (`3e37f9d7`) is complete and small (25 files / 14.8 MB, parquet present but the MultiQC report carries no module data). 2.0.0 empty. |
| nanoseq | 3.1.0 | `6e563e54` | empty | | no | Two zero-sized data objects. Last complete run is 3.0.0 (2022, 205 files, pre-parquet). |

## Selected runs for this lot

The nine pipelines added in this lot, with the run each template is validated
against. `resolve` verifies the prefix; `fetch` mirrors the manifest subset
below the run root into `~/Data/depictio-nfcore/<pipeline>/<version>/megatest/`.

Two of them are pinned to an **older release than the latest**, because every
recent release of theirs published an empty or truncated prefix. `resolve` reports
that and prints the fallback table the pin was chosen from, so the mismatch is
deliberate and visible rather than silent.

| pipeline | version | results_sha | run_root | MultiQC |
|---|---|---|---|---|
| differentialabundance | 2.0.0 | `30ed7741fc392127156c2fb10cfa3d69d216b54b` | `.` (outputs under `tables/<paramset>/`) | none by design |
| funcscan | 4.0.0 | `aee3dc965eb0c77267435544dda30da858763913` | `.` | 1.34, general stats empty |
| airrflow | 5.1.0 | `e69d49e3f23f11a3391755b5fb7aa4283c0a2471` | `.` | 1.34 |
| rnafusion | 4.1.3 | `76ad76e7c39b2ba9edc35aa3602e3dc454d842ec` | `.` | 1.33 |
| rnaseq | 3.26.0 | `e7ca46272c8f9d5ceee3f71759f4ba551d3217a4` | `aligner_star_salmon/` | 1.33 at `multiqc/star_salmon/multiqc_report_data/` |
| taxprofiler | 2.0.1 | `70ecc15e49b4f1fcf79d876643b5d14b65c66178` | `.` | 1.34 |
| chipseq | 1.2.0 | `048fd6854fcc85b355c61dfc2e21da0bcc6399ea` | `.` (`bwa/mergedLibrary/...`) | 1.9, reprocessed with 1.35 |
| atacseq | 1.2.2 | `f327c86324427c64716be09c98634ae0bc8165f6` | `.` (`bwa/mergedLibrary/...`) | none, reprocessed with 1.35; raw inputs under `multiqc/broadPeak/multiqc_data/` |
| cutandrun | 3.1 | `42502fb44975e930eec865353c5481f472bcf766` | `.` (numbered stage dirs) | none, reprocessed with 1.35 |

## How to use

```bash
# Which run backs a release? Prints prefix, tag, sha, object counts, parquet path.
python scripts/nfcore_megatest.py resolve --pipeline ampliseq --version 2.18.0
python scripts/nfcore_megatest.py resolve --pipeline rnaseq --version latest --run-root aligner_star_salmon
# Exit code 3 plus a table of the newest real runs when the release's run is empty or missing:
python scripts/nfcore_megatest.py resolve --pipeline methylseq --version 4.2.0

# Explore a run before writing its manifest.
python scripts/nfcore_megatest.py ls --pipeline taxprofiler --version 2.0.1 --top-dirs
python scripts/nfcore_megatest.py ls --pipeline rnaseq --version 3.26.0 --ext tsv parquet --grep 'salmon' --sizes
python scripts/nfcore_megatest.py ls --pipeline chipseq --results-hash 048fd6854fcc85b355c61dfc2e21da0bcc6399ea --prefix multiqc

# Fetch the manifest subset (megatest.yaml next to the template); --dry-run plans only.
python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dry-run
python scripts/nfcore_megatest.py fetch --pipeline ampliseq --version 2.18.0 --dest ~/Data/depictio-nfcore/ampliseq/2.18.0/megatest
python scripts/nfcore_megatest.py fetch --pipeline rnaseq --version 3.26.0 --key 'star_salmon/salmon.merged.*.tsv'
```

`fetch` renames timestamped provenance files (`pipeline_info/params_*.json` to
`params.json`, `*software*versions*.yml` to `software_versions.yml`, newest
wins), keeps files whose size already matches, refuses objects above
`--max-file-mb` (500) and mirrors `prefix_keys` (files outside a nested run
root) into the same destination. The release index is cached for 6 hours under
`~/.cache/depictio-nfcore/`; `--index FILE` or `$NFCORE_PIPELINES_JSON` point
at a local copy.

## Known gaps

These are gaps in what the **bucket publishes**. The gaps in **Depictio itself** that
this lot exposed (recipe provenance, `dc_ref` ordering, catalog loading, the MultiQC
version gate, seeding, missing visualisation kinds) are in
[`TEMPLATE_BOTTLENECKS.md`](TEMPLATE_BOTTLENECKS.md).

- **Empty release prefixes** (failed runs or truncated syncs, to report to
  nf-core): methylseq 4.2.0 / 4.0.0 / 3.0.0, chipseq 2.1.0 / 2.0.0, atacseq
  2.1.1 / 2.1.2, cutandrun 3.2 / 3.2.1 / 3.2.2, quantms 1.2.0, bacass 2.1.0 to
  2.5.0, raredisease (every release), nanoseq 3.1.0, rnafusion 4.1.1,
  variantbenchmarking 1.3.0 and 1.4.0, differentialabundance 1.2.0 to 1.5.0,
  funcscan 2.x / 3.0.0, smrnaseq 2.2.3 to 2.4.0, scrnaseq 2.x, crisprseq 2.0.0 to
  2.2.1, taxprofiler 1.2.2 / 1.2.4, airrflow 4.1.0 / 4.2.0, oncoanalyser 1.0.0 to
  2.1.0, mag 5.2.0 / 5.3.0.
- **Missing runs** (no prefix for the release sha): airrflow 5.1.1, phyloplace
  2.1.0, bacass 2.6.1. viralrecon 3.0.0 has a prefix but no MultiQC parquet.
- **Partial runs**: mag 5.5.0 (no MultiQC, no bin-QC or GTDB-Tk tables),
  viralrecon 3.0.0 (nanopore layout only), phyloplace 2.0.1 (parquet without
  module data), sarek (germline only, somatic profiles never run).
- **Nested run roots**: rnaseq `aligner_star_salmon/` (and `aligner_star_rsem/`),
  scrnaseq `aligner_{cellranger,kallisto,simpleaf,star}/`, sarek
  `test_full_germline_ncbench_agilent/` and `test_full_germline_aws/`,
  oncoanalyser `HCC1395/`, differentialabundance `tables/<paramset>/` with commas
  in directory names (URLs must be quoted; `fetch` does). The manifest `run_root`
  plus `prefix_keys` (for `pipeline_info/` outside the root) cover these.
- **MultiQC layout and version variance**: rnaseq writes
  `multiqc/star_salmon/multiqc_report_data/multiqc.parquet`, which no shipped
  scan regex or catalog `**/multiqc/multiqc_data/multiqc.parquet` glob matches;
  chipseq 1.2.x wrote MultiQC 1.9 (JSON only) and needs a 1.35 reprocess; funcscan
  1.34 and phyloplace ship parquets with empty general-stats or module tables;
  runs span MultiQC 1.31 to 1.35 and are read by a 1.35 reader with no version
  gate in code (the scan regex is the only gate, see the Conventions block in
  `VALIDATION_SCENARIOS.md`).
- **Bucket behaviour**: intermittent 503 SlowDown answers (every request here is
  retried with backoff), listings of the big runs run to tens of thousands of keys
  (rnaseq, crisprseq, funcscan), and the same release can be re-synced with a
  different `LastModified`, so pins are by `results_sha`, never by recency.
- **variantbenchmarking**: the shipped 1.4.0 template pins the 1.5.0 run because
  the 1.4.0 release's own run is a truncated sync; `fetch` warns about the
  release mismatch and keeps the pin.
- **An empty latest release does not mean the pipeline is untemplatable.** atacseq
  and cutandrun both publish nothing usable on every recent release, but atacseq
  1.2.2 (488 objects) and cutandrun 3.1 (415 objects) are complete runs, so both
  are templated against those. `resolve` exits 3 and prints the fallback table
  precisely so an older usable run can be found instead of the pipeline being
  written off. Worth re-checking the other `empty` rows above the same way.
