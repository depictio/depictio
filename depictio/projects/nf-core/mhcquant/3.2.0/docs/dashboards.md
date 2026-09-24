# nf-core/mhcquant 3.2.0: Depictio dashboards

This template turns the output of [nf-core/mhcquant](https://nf-co.re/mhcquant) 3.2.0 into a
six-tab Depictio dashboard. mhcquant identifies MHC-presented peptides from immunopeptidomics
mass-spectrometry runs: Comet searches every raw file, MS2Rescore and Percolator rescore the
matches, OpenMS filters them at the requested FDR, links features across the replicates of a
sample and writes one peptide table per sample. The template reads that table, the Comet pin
files that precede rescoring, the fragment-ion annotations and the MultiQC report.

## Inputs

| Collection | Source | Grain |
| --- | --- | --- |
| `samples` | the samplesheet (`METADATA_FILE`, default `input/samplesheet.tsv`) | raw file |
| `multiqc_data` | `multiqc/multiqc_data/multiqc.parquet` | MultiQC sample |
| `mhcquant_peptides` | `<Sample>_<Condition>.tsv` at the output root | sample and precursor |
| `mhcquant_fragment_ions` | `intermediate_results/ion_annotations/*_matching_ions.tsv` | sample and peptidoform |
| `mhcquant_replicate_intensity` | the `intensity_<k>` columns of the peptide tables | sample, peptidoform, replicate |
| `openms_comet_psms`, `openms_comet_fdr_curve` | `intermediate_results/comet/*_pin.tsv` | raw file |

mhcquant does not publish the samplesheet it ran on, so the template ships the test_full sheet
under `input/` and reads it by default; point `METADATA_FILE` at the sheet of another run.
Derived collections (sample summary, length distribution, composition, motif matrix, replicate
pairs and detection, source proteins, condition sharing) are recipes over the peptide table.

## Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `METADATA_FILE` | `{DATA_ROOT}/input/samplesheet.tsv` | samplesheet read by `samples` |
| `METADATA_ID_COL` | `ID` | samplesheet id column |
| `GROUP_COL`, `GROUP_COL_DISPLAY` | `Condition` | grouping filter and glance card |
| `NO_QUANTIFICATION` | unset | set for runs without `--quantify`: drops the replicate collections |
| `NO_ION_ANNOTATION` | unset | set for runs without `--annotate_ions`: drops the fragment-ion collection |

The CLI's metadata auto-detection picks the first non-id sheet column as `GROUP_COL`, so pass
`--var GROUP_COL=Condition` (or keep `Condition` second in the sheet).

## Tabs

1. **MultiQC.** The pipeline's own report: identification counts, q-value and Xcorr
   distributions, precursor m/z, retention time and intensity, and (collapsed) chromatograms,
   fragment mass error and Percolator feature weights. The persistent glance strip counts
   samples, raw files, groups and identified peptides; the sample sheet and the per-sample
   summary are pinned.
2. **Identification.** PSMs, peptides and source proteins per sample, Comet PSMs at 1% FDR per
   raw file, the accepted-PSM curve against the q-value threshold and the score distribution.
3. **MHC signature.** Length profile with the class I (8 to 12) and class II (13 to 25) ranges
   shaded, 9-mer and class shares, composition by length, charge and modification, and a
   positional amino-acid heatmap per sample and length for reading anchor motifs.
4. **Reproducibility.** Replicate correlation and completeness, intensity scatter for every
   replicate pair and an UpSet of the replicate combinations each peptide was quantified in.
5. **Peptides and proteins.** Peptides shared between conditions (UpSet over one set per
   condition), peptides per source protein against intensity, and the peptide and protein
   tables, each with a record card beside it that opens on the selected row.
6. **Physico-chemical checks.** Observed against DeepLC-predicted retention time, retention time
   against Kyte-Doolittle hydropathy, precursor m/z over the gradient by charge, and precursor
   and fragment mass accuracy. A peptide picked on the retention-time plot opens its record
   beside it.

## Selection

Tables and scatters emit a selection on their entity column, and the selection narrows every
other tile that reads the same collection or a collection linked from it:

- The sample sheet selects on `sample_id`, which the links carry to every collection and to the
  MultiQC panels; the pinned per-sample summary selects on `sample`.
- The Comet table selects raw files (`run_id`), the replicate membership table peptides.
- The peptide table and the three scatters of the physico-chemical tab select on `sequence`,
  which also reaches the condition-sharing collection. The source-protein scatter and table
  select on `protein`; the fragment-ion table on `peptide`.
- A record card sits beside the table or scatter that drives it and stays a thin rail until a
  row or point is picked.

The length table and the replicate-pair scatter select nothing: no other tile reads their
collections or a collection linked from them.

## Methods and assumptions

- **Peptide rows.** The peptide table has one row per precursor (peptidoform and charge). Counts
  of peptides use distinct sequences or peptidoforms; replicate intensities are summed over the
  charge states of a peptidoform.
- **Replicate order.** The `intensity_<k>` columns carry no file name. The template assumes
  column `k` is the raw file ranked `k+1` by samplesheet `ID` within its sample, the order the
  files enter feature linking. Pair and replicate labels follow that assumption.
- **Comet FDR.** `openms_comet_*` apply target-decoy competition on Xcorr to the pin files,
  before MS2Rescore and Percolator, so they describe the raw search, not the final FDR.
- **Length windows.** Class I is 8 to 12 residues and class II 13 to 25. The pipeline's own
  length filter (`peptide_min_length`, `peptide_max_length`) bounds what can appear.
- **Motifs.** Frequencies are over distinct sequences of one length in one sample; lengths
  with fewer than 20 sequences are left out.
- **No binding predictions.** 3.2.0 no longer runs MHCflurry or other binders, so there is no
  binder-rank view.
