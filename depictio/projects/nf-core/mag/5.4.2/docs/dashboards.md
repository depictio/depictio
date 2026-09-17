# nf-core/mag 5.4.2: Depictio dashboards

This template turns the output of [nf-core/mag](https://nf-co.re/mag) 5.4.2 into a two-tab
Depictio dashboard. mag assembles short and (optionally) long reads per sample, then bins the
resulting contigs with up to five binners (MetaBAT2, MaxBin2, MetaBinner, SemiBin2, COMEBin).

Data comes from the AWS megatest run `results-5dabb0159ac0104885e09f301db22126e8fcb394` (the
5.4.2 release tag): three samples (CAPES_S7, CAPES_S11, CAPES_S21), each hybrid-assembled from
a short-read pair and a long-read (Nanopore) run, assembled with FLYE, MEGAHIT, METAMDBG and
SPAdes.

> **This template is thinner than most nf-core templates.**
> The megatest run's real layout does not match what the pipeline's docs suggest is published.
> There is no standalone taxonomy (GTDB-Tk/Kraken2/Centrifuge/CAT), read-QC
> (FastQC/fastp/Filtlong/NanoPlot), assembly-QC (QUAST) or bin-quality (CheckM2/BUSCO/GUNC)
> report file anywhere in the local `DATA_ROOT`. See `VALIDATION_REPORT.md` for the full
> discrepancy list against the original (guessed) `megatest.yaml`.
>
> What the run DOES publish: the cross-binner contig-to-bin membership map
> (`GenomeBinning/contig_to_bin/contig_to_bin_map.tsv`), COMEBin's raw per-contig 128-dim
> embeddings (not used by this template, see `VALIDATION_REPORT.md`), and a MultiQC 1.31
> report whose general-statistics table carries CheckM2 completeness/contamination, QUAST
> N50/contig counts and Prokka coding-density as extra columns, even without the standalone
> report files those numbers usually come from.

---

## How the dashboard is built

- **Two tabs, not a longer funnel.** MultiQC (the landing tab), then Binning. A
  taxonomy/assembly-comparison tab was not built because no local data supports one: see
  `VALIDATION_REPORT.md` for what a future fetch of `Annotation/` (Prokka, 917 files on S3,
  not in this local snapshot) or a re-run with GTDB-Tk/QUAST outputs published would unlock.
- **The sample hub is the anchor.** `samples` is one row per sample (mag's samplesheet is
  already sample-level, unlike cutandrun/hic's library-level sheets), with its co-assembly
  group and whether it has a long-read run. A persistent `Sample filters` section (sample) is
  pinned to the top of every tab, and the template's links fan a pick there out to the MultiQC
  panels and both binning tables.
- **Pinned sample sheet and reference table.** The sample hub sits in a collapsed
  `Sample sheet` section pinned to the top of every tab, and the binner-comparison summary in
  a collapsed `Reference tables` section pinned to the bottom.
- **MultiQC general statistics carries the QC story.** FastQC, fastp, Porechop_ABI, Bowtie2,
  QUAST, CheckM2 and Prokka all contribute general-stats columns in this run but publish no
  standalone report of their own, so the MultiQC tab's single general-statistics panel is
  where all of that surfaces (the table's column picker narrows to one module at a time).
- **Binning is a recovery yield, not a quality score.** `bin_summary` (one row per bin) and
  `binner_comparison` (one row per sample/assembler/binner) come from the cross-binner
  contig-to-bin map: they count contigs per bin, which is the closest thing to a "bin summary"
  the local data supports. They are NOT completeness/contamination, for that, read the
  CheckM2 columns on the MultiQC tab's general-statistics panel.

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline mag --version 5.4.2 \
  --dest ~/Data/depictio-nfcore/mag/5.4.2/megatest
# or, equivalently:
bash depictio/projects/nf-core/mag/5.4.2/download_test_data.sh

depictio-cli run --template nf-core/mag/5.4.2 \
  --data-root ~/Data/depictio-nfcore/mag/5.4.2/megatest --dry-run
```
