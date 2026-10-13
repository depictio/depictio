# nf-core/cutandrun 3.2.2: template validation report

**Date:** 2026-10-09
**Worktree / branch:** `depictio-worktrees/feat-nfcore-templates-2x`
**Validator:** local depictio-cli (`uv run --extra dev python -m depictio.cli`), dry runs,
offline model validation and recipe runs only. No ingestion was run from here.

## Goal

Rebuild the cutandrun 3.2.2 template on top of the v2 3.1 template. The release keeps the 3.1
output layout, so this is a version bump rather than a port: the collections, recipes, links and
dashboard are the v2 3.1 ones (Overview plus seven tabs in three groups, 22 collections) with the
3.2.2 changes below on top. Those changes were first worked out on the September bump of the
pre-v2 template (`chore-nfcore-hpc-repin-runs`, report dated 2026-09-14) and are carried over
here. The reasoning behind the template's design (the MultiQC overlap policy, the two callers,
the IgG controls kept as samples, the funnel layout) is in `../3.1/VALIDATION_REPORT.md` and
still applies.

## Data used

There is no usable AWS megatest for 3.2.2: the 3.2, 3.2.1 and 3.2.2 prefixes hold directory
markers only (`depictio/projects/nf-core/MEGATEST_STATUS.md`), so `megatest.yaml` keeps
`results_sha: null`. The template was validated on two EMBL HPC runs repatriated with
`scripts/nfcore_validation_hpc.py`:

| Key | Profile | Design | Local tree |
|---|---|---|---|
| `cutandrun322-full` | `test_full` | The megatest design, GSE145187: two histone marks in two replicates each, plus two IgG controls (6 samples) | `~/Data/depictio-nfcore/cutandrun/3.2.2/test_full` |
| `cutandrun322-small` | `test_full_small` | The same 6 samples on the 10,000-read subset against chr20, with linear duplicate removal and mitochondrial filtering on | `~/Data/depictio-nfcore/cutandrun/3.2.2/test_full_small` |

Both ran on Nextflow 24.04.2 and wrote MultiQC 1.19. Both local trees hold the report
re-generated with MultiQC 1.35 at `multiqc/multiqc_data/multiqc.parquet`. The pipeline's own
report, as a MultiQC 1.35 run publishes it, was available for test_full_small only, as a copy
outside the tree (`~/Data/depictio-nfcore/_mqc135/`).

## Upstream changes and what they touched

| 3.2.2 change | Effect on the template | Action |
|---|---|---|
| Consensus files are named `TARGET.seacr.consensus.peak_counts.bed` (3.1: `TARGET.consensus.peak_counts.bed`) | The manifest glob `*.consensus.peak_counts.bed` and the recipe still match (291,096 intervals on test_full) | Manifest comment only |
| New `02_alignment/bowtie2/target/linear_dedup/` samtools stats (test_full_small) | A second set of stats for every sample, under the same file names as `markdup/` | Left out of the manifest for the reason `dedup/` already was; the flagstat scan keeps its `markdup/` anchor, which excludes it |
| Controls named per replicate | `samplesheet.valid.csv` pairs each target replicate with its own control replicate, so `samples.control_target` carries one control name per replicate | Column descriptions updated; nothing joins on the column; the two names are `forbidden_terms` |
| MultiQC 1.19 (3.1 wrote 1.14) | Still below the parquet floor | `multiqc.version: "1.19"`; MultiQC binding reworked (CR-D25) |
| Nextflow floor 23.04.0 | | `engine.version: "23.04.0"` |
| `pipeline_info/params.json` | Not published by either HPC run: `pipeline_info/` holds `software_versions.yml`, `local_versions.yml`, `samplesheet.valid.csv`, the execution report, timeline, trace and DAG, and `pipeline_report.*` | Template text says so; provenance still reads the two version files |
| SEACR beds copied into `04_reporting/igv/` | A file-name scan binds every SEACR region twice on a full outdir | Scan pattern skips `igv/` (CR-D23) |

Bundled files refreshed from the test_full run: `pipeline_info/software_versions.yml`,
`pipeline_info/local_versions.yml` and `input/samplesheet.valid.csv`. The bump had left the 3.1
content in them with the version strings rewritten (`python: 3.2.21.0` among them). No code in
the repository reads these copies.

## What the v2 rebuild changed for 3.2.2

Only the MultiQC binding and the MultiQC tab differ from the v2 3.1 dashboard:

- `cr-mqc-bowtie2` keeps `bowtie2` / Paired-end alignments and is retitled "Target genome
  alignments"; on the pipeline's report that module holds the target genome only.
- New `cr-mqc-bowtie2-spikein` beside it: `use: multiqc/bowtie2`, `selected_module: bowtie2-1`,
  Paired-end alignments. The catalog already pairs `use: multiqc/fastqc` with `fastqc-1` in
  airrflow, so a numbered module under a catalog render has a precedent.
- `cr-mqc-samtools-mapped` moved from the open "Alignment and spike-in" section into the
  collapsed "QC details" section, so the tab opens at 18 rows (RULES.md allows 20). The
  section description names it.
- The intro text says which report the tab may be reading and what a re-generated one shows.

No Key figure, highlight or Findings card reads the MultiQC report, so a pruned MultiQC tile
never empties the Overview. The Overview Findings stay two rows of two w4 cards.

## Validation results

### Lint and dashboard validation

```bash
uv run --extra dev python -m depictio.cli dashboard validate --offline \
  depictio/projects/nf-core/cutandrun/3.2.2/dashboards/base.yaml
```

Passes. The pytest subset (`test_template_conventions.py`, `test_shipped_dashboard_yamls.py`,
`test_template_dc_order.py` and `test_nfcore_megatest.py`, filtered with `-k cutandrun`):
40 passed, 20 of them 3.2.2 cases, `test_every_shipped_manifest_is_consistent[cutandrun-3.2.2]`
included.

### Dry runs

```bash
uv run --extra dev python -m depictio.cli ingest ~/Data/depictio-nfcore/cutandrun/3.2.2/test_full \
  --template nf-core/cutandrun/3.2.2 --dry-run
uv run --extra dev python -m depictio.cli ingest ~/Data/depictio-nfcore/cutandrun/3.2.2/test_full \
  --template nf-core/cutandrun/3.2.2 --var MULTIQC_REPROCESSED=true --dry-run
# and the same two on test_full_small
```

All four exit 0 with 8/8 steps; the CLI detects `nf-core/cutandrun 3.2.2` (27 tools) and lists
22 collections. Files bound per scan collection, identical on both trees:

| Scan collection | Files |
|---|---|
| `samplesheet` | 1 |
| `bowtie2_logs_raw` | 12 (6 target, 6 spike-in) |
| `seacr_peaks_raw` | 4 (the igv copies skipped, CR-D23) |
| `seacr_fragment_lengths_raw` | 4 |
| `samtools_flagstat_raw` | 6 (the linear_dedup twins skipped) |
| `seacr_frags_raw` | 4 |
| `multiqc_data` | 1 with `MULTIQC_REPROCESSED`, 0 without (the trees hold the re-generated report only) |

A dry run skips the Project model validation a real run performs at step 3 (CR-D28), so that
step was reproduced offline: the template resolved as `run.py` resolves it in template mode, a
placeholder `permissions` block added the way `validate_template_project_config` adds one,
`_resolve_link_tags_to_ids`, then `validate_model_config(config, Project)`. It passes on both
trees, with and without the variable (1 workflow, 22 collections).

### MultiQC binding

On a scratch tree holding both reports (test_full_small plus the pipeline's own MultiQC 1.35
parquet at `04_reporting/multiqc/multiqc_data/`), each branch binds exactly one file: the
pipeline's report without the variable, the re-generated one with it. The new unit test
`depictio/tests/unit/test_cutandrun_3_2_2_template.py` pins this, the SEACR igv skip and the
flagstat `linear_dedup/` skip with the CLI's own file matcher (5 passed).

### Collections built on the real trees

Every collection was built the way an ingest builds it, without a server: scan collections
read with the CLI's matcher and `polars.scan_csv`, recipe collections run through
`execute_recipe` with their dc_ref inputs injected. The re-generated report was bound on both
trees; a run on the scratch tree with the pipeline's report gives the same frames.

| Collection | test_full | test_full_small |
|---|---|---|
| `samples` | 6 x 10 | 6 x 10 |
| `bowtie2_spikein_factors` | 6 x 9 | 6 x 9 |
| `deeptools_fingerprint_metrics` | 6 x 9 | 6 x 9 |
| `deeptools_sample_pca` | 6 x 6 | 6 x 6 |
| `deeptools_correlation_matrix` | 6 x 7 | 6 x 7 |
| `seacr_peaks` | 472,284 x 12 | 50 x 12 |
| `seacr_peak_summary` | 4 x 11 | 3 x 11 |
| `macs2_peaks` | 27,373 x 11 | 353 x 11 |
| `seacr_consensus_peaks` | 291,096 x 16 | 49 x 15 (no set column for the sample SEACR called nothing for) |
| `seacr_fragment_lengths` | 2,710 x 6 | 742 x 6 |
| `seacr_fragment_classes` | 16 x 9 | 16 x 9 |
| `frip` | 8 x 10 | 6 x 10 |
| `caller_agreement` | 8 x 13 | 8 x 13 |
| `samtools_flagstat` | 6 x 9 | 6 x 9 |
| `seacr_frags_raw` | 7,628,277 x 4 | 1,031 x 4 |
| `seacr_frags_profile` | 122,000 x 11 | 2,989 x 11 |

Every column the dashboard names (interactive columns, card values and weights, filter
expressions, figure and advanced-viz column settings) exists in its collection on both trees.
The test_full_small `seacr_peaks_raw` build skipped the zero-byte bed by hand (CR-D24, since
resolved in the loaders).

The cutandrun recipe tests (`test_bowtie2_spikein_factors.py`, `test_cutandrun_frip.py`,
`test_seacr_recipes.py`): 20 passed.

### MultiQC tiles against each report

Each tile's module and plot were looked up in the parquet metadata, the way the import prune
(`_component_has_data`) decides:

| Report | Tiles kept | Dropped |
|---|---|---|
| Pipeline's own, MultiQC 1.35 (test_full_small) | 11 / 11 | none |
| Re-generated, test_full | 10 / 11 | `cr-mqc-bowtie2-spikein` (no `bowtie2-1` module) |
| Re-generated, test_full_small | 10 / 11 | `cr-mqc-bowtie2-spikein` |

`REPROCESSED.json` on both trees records `source_version: 1.19` and `reprocessed_with: 1.35`.

## Discrepancies

### Carried over from 3.1

CR-D3 to CR-D9 and CR-D11 to CR-D22 of `../3.1/VALIDATION_REPORT.md` describe the template, not
the data, and are unchanged. CR-D1 is superseded by CR-D17 there, CR-D2 by CR-D25 here. CR-D10
(3.1 pinned behind 3.2.2) is answered by this template; its second half still holds: a
`--peakcaller macs2` run empties the SEACR collections and the tabs built on them.

CR-D6 on the 3.2.2 data: on test_full, 177,199 of the 291,096 consensus intervals (61 %) have
`support = 1`, and almost all intervals belong to one of the two marks. Intervals both
replicates called are wider than single-replicate ones, which is what the width histogram on
the Consensus tab says.

### CR-D23: the SEACR scan loaded every region twice from a full outdir

cutandrun copies every SEACR stringent bed, byte for byte, into `04_reporting/igv/` for its IGV
session. The 3.1 pattern (`.*\.seacr\.peaks\.\w+\.bed$`) matches on file name alone, so over a
full `--outdir` it binds 8 files instead of 4 on both trees, which doubles `seacr_peaks`,
`seacr_peak_summary` and the SEACR side of `caller_agreement`. The megatest manifest fetches
nothing under `igv/`, which is why the 3.1 validation did not see it. The 3.1 template has the
same pattern and the same exposure on a full outdir.

The 3.2.2 pattern is `(?!(?:.*/)?igv/).*/[^/]*\.seacr\.peaks\.\w+\.bed$`. The scanner tries
every pattern against the bare file name first, and against the DATA_ROOT-relative path only
when the pattern contains a `/`, so the pattern has to require one before it can exclude a
directory. Checked on both trees: 4 beds each. The MACS2, consensus and fragment-length inputs
have no IGV copies under the names their patterns use.

### CR-D24: a zero-byte SEACR bed fails `seacr_peaks_raw` on test_full_small

SEACR called nothing for one sample on the small profile and published a zero-byte bed. The
scan builds a `File` for it, which refuses a size of zero ("File size cannot be zero"), and
the whole scan step fails; past the scan, `polars.scan_csv` would raise `NoDataError: empty
CSV` (reproduced on polars 1.43.2). `seacr_peaks_raw` is not
optional, so an ingest of the untouched test_full_small tree is expected to fail on this
collection. `caller_agreement` still shows the null result as an `n_peaks = 0` row. test_full has no zero-byte peak file. A scan pattern cannot test a file
size, so the template cannot guard against this itself.

**Resolved** in the same change: the scan (`scan_single_file`) skips a zero-byte file with a
warning and the recipe glob reader skips it too, so the untouched tree ingests and the
deletion step is gone from `post_fetch_help` and the docs.

### CR-D25: two possible MultiQC locations, one binding

3.2.2 pins MultiQC 1.19, which writes no parquet. A run on MultiQC 1.31 or later (the Nextflow
trigger forces 1.35) publishes `04_reporting/multiqc/multiqc_data/multiqc.parquet` itself. A
run on the pinned 1.19 has to be re-generated, which writes `multiqc/multiqc_data/multiqc.parquet`
at the DATA_ROOT. Loading both would put two reports of the same samples into one collection,
and a scan pattern cannot say "this file unless that one exists". The template binds one per
run, chosen by a variable:

- without `MULTIQC_REPROCESSED` (the trigger passes no `--var`), an `if_var_absent`
  conditional repoints `multiqc_data` at `.+/multiqc/multiqc_data/multiqc\.parquet$`, a
  `multiqc/` directory at least one level below the root;
- with `--var MULTIQC_REPROCESSED=true`, the collection keeps its own pattern,
  `multiqc/multiqc_data/multiqc\.parquet$`, matched from the start of the relative path, so
  only the root one.

The September bump spelled the first pattern `04_reporting/multiqc/...`. The v2 manifest and
scans never name a numbered stage directory (3.1 CR-D17), so the pattern here only requires a
parent directory. The collection's own pattern is the re-generated location because
`megatest.yaml` names that file, and `test_every_shipped_manifest_is_consistent` requires the
template's MultiQC pattern to match it.

### CR-D26: the HPC ingest path does not pass the variable

`scripts/nfcore_validation_hpc.py ingest` builds its CLI command without `--var`, so ingesting a
re-generated local tree through it binds no MultiQC report. It needs
`--var MULTIQC_REPROCESSED=true` for runs that were reprocessed. The script in this worktree
also has no `cutandrun322-full` / `cutandrun322-small` run entries yet (they exist on the
`chore-nfcore-hpc-repin-runs` branch). Not changed here: the script is outside this template.

### CR-D27: the pipeline's own MultiQC report names modules differently from a re-generated one

The pipeline's multiqc_config gives its second FastQC and Bowtie 2 runs module entries of their
own, so MultiQC 1.35 writes `fastqc` (raw reads) and `fastqc-1` (trimmed reads), `bowtie2`
(target genome) and `bowtie2-1` (spike-in), and adds `picard`, `linear_duplication_levels`,
`fragment_lengths` and a custom `peak_qc` module. It has no `macs` or `preseq` module and no
deepTools "Fingerprint quality metrics" section. The re-generated report has none of the
numbered or pipeline-only modules, and draws the spike-in libraries in the `bowtie2` panel with
a `.spikein` suffix.

The `multiqc_data` `modules` and `plots` lists mirror the pipeline's report. The dashboard binds
`bowtie2-1` for the spike-in tile (dropped on a re-generated report) and nothing else that only
one report carries. Not ported from the September bump: its FRiP tile on `peak_qc` / Sample
FRiP score. It replaced a deepTools quality-metrics tile the v2 dashboard no longer has, and the
template computes its own FRiP (`frip`), shown on the Overview and the Peaks tab, so a MultiQC
copy would be a twin. Also dropped from the `plots` lists: samtools "XY counts" and the raw-read
FastQC "Sequence Length Distribution", which the pipeline's report does not draw. The
pipeline's own test_full report was not available, so those lists were checked on
test_full_small only.

### CR-D28: angle brackets in descriptions fail the real step-3 validation

`MongoModel.sanitize_description` html-escapes every `description` and rejects a value that
still holds an angle bracket. The September bump's first trigger import stopped at step 3/8 on
exactly that, and a dry run skips the check. The v2 column descriptions had placeholders in
angle brackets as well; they are spelled out now (SAMPLE, TARGET, GROUP_R1). No string value
in `template.yaml` holds an angle bracket; comments keep theirs. The offline Project validation
above passes.

### CR-D29: the Locus tab's default region is on chr9, and test_full_small covers chr20 only

The navigator and the region cards open on a chr9 window, kept from the v2 3.1 template, where
the megatest calls peaks. test_full_small is aligned against chr20 alone, so on that run the
Locus tab opens on an empty window until a region is picked. A whole-genome run such as
test_full is unaffected.

**Resolved** after the live check: the navigator opens on `default_region: first`, the first
contig the calls sit on, like the atacseq 2.1.2 and chipseq 2.1.0 Locus tabs.

## Live check (2026-10-09)

test_full_small, untouched (its zero-byte SEACR bed included), ingested 8/8 on a local stack
with `--var MULTIQC_REPROCESSED=true`; the scan skipped the empty bed with a warning. The
Overview and the seven child tabs render with values. On the re-generated report the import
dropped `cr-mqc-bowtie2-spikein` and widened `cr-mqc-bowtie2` to the full row (12 libraries,
targets and spike-ins). The Locus tab opens on chr20, the contig the run covers.

## Not verified here

- test_full on a live stack (its dry run and collection builds are above).
- The pipeline's own MultiQC report of test_full: only test_full_small's was checked (CR-D27).
- No `docs/screenshots/`: the 3.1 ones predate the v2 dashboard and were not copied.
- There is no `.db_seeds/` directory for 3.2.2, so no seed needs regenerating.
