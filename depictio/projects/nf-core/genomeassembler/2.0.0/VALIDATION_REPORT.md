# nf-core/genomeassembler 2.0.0: template ingestion validation report

Date: 2026-09-23. New template (wave 3).

## Data used

AWS megatest `s3://nf-core-awsmegatests/genomeassembler/results-a72d47d9cdb50f21b97882dfb2abf4af8f4c74ad/`
(`full_test_samplesheet_v2_no_medaka.csv`, 10 samples), fetched selectively
with `download_test_data.sh` (`--max-file-mb 50`): about 8.6 MB. The
samplesheet is vendored under `input/samplesheet.csv`.

## What the run published

The megatest run is **partial**. `execution_trace` shows LINKS failing on one
sample (exit 255) and 22 tasks ABORTED afterwards, among them the assembly
steps of five samples. What was published:

- QUAST: 3 transposed reports (reference-based, genome fraction present);
- BUSCO: 3 batch summaries;
- Merqury: 10 assemblies (QV, completeness, per-sequence QV, spectra-cn);
- samtools idxstats: 15 files; GenomeScope: 7 summaries; jellyfish: 7 histograms;
- no MultiQC, no `report/` directory; `software_versions.yml` holds only the
  Workflow block.

Five of the ten samples have no assembly QC at all. The template keeps them in
`sample_status` as `No assembly QC`; every tool data collection is optional and
every join is a left join, so a sample absent from a tool is a null, not an
error.

## Offline ingestion (all recipes, real files)

| Data collection | Shape |
| --- | --- |
| samplesheet | 10 x 17 |
| merqury_assembly_qv | 10 x 9 |
| merqury_sequence_qv | 5050 x 7 |
| merqury_copy_number | 60 x 7 |
| busco_batch_summary / busco_composition | 3 x 14 / 12 x 6 |
| quast_assembly_report / length_ladder / reference_report | 3 x 15 / 18 x 7 / 3 x 17 |
| genomescope_summary / jellyfish_histogram | 7 x 17 / 864 x 5 |
| assemblies / nx_curve / stage_steps / sample_status | 10 x 46 / 909 x 7 / 11 x 50 / 10 x 25 |

Nx at 50 from idxstats equals QUAST's N50 on the same assembly.

## Checks

- `test_shipped_dashboard_yamls.py` + `test_template_conventions.py`: all
  genomeassembler cases pass.
- `test_catalog.py` + `test_catalog_source_from_use.py`: pass.
- `test_genomeassembler_recipes.py`, `test_genomeassembler_catalog.py`: 13 pass.
- `depictio-cli run --dry-run`, with and without `--var METADATA_FILE`: 8/8 steps.

## Known caveats

- **Duplicate `Workflow` key.** The published `software_versions.yml` repeats
  its `Workflow` block (only that block is written by this run). The vendored
  copy is deduplicated; YAML loaders that reject duplicate keys would fail on
  the raw file.
- **Stage coverage.** The megatest only reached the raw assembly and LINKS /
  RagTag stages for the samples that finished; polishing tiles (medaka, dorado,
  pilon) and Hi-C scaffolding (YaHS) are wired by name but unverified on data.
- **GenomeScope and jellyfish** are per read set, not per assembly; they link to
  each other but not to the samplesheet.
- Not rendered in a live stack (offline validation only); no seeds generated.
