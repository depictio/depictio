# nf-core/molkart 1.2.0: Depictio dashboards

This template turns the output of [nf-core/molkart](https://nf-co.re/molkart) 1.2.0 into a
four-tab Depictio dashboard. molkart fills the tile grid lines of Molecular Cartography
images (Mindagap), marks the spots duplicated along them, enhances contrast (CLAHE),
segments the nuclei (or nuclei and membrane) with one or several methods, drops labels
outside an area range, then assigns every spot to the cell it falls in (spot2cell) and
writes one QC sheet per sample and method (molkartqc).

> **No AWS megatest data.** The 1.2.0 megatest prefix holds `pipeline_info/` only. The
> reference run is `-profile test_full` on the EMBL cluster
> (`scripts/nfcore_validation_hpc.py`, key `molkart`), fetched with `rsync -L` because
> several processes publish symlinks whatever `--publish_dir_mode` says. See
> `megatest.yaml` and `VALIDATION_REPORT.md`.

---

## Data collections

| Tag | Source | One row per |
| --- | --- | --- |
| `samples` | `input/samplesheet*.csv` (+ `METADATA_FILE`) | sample |
| `metadata` | `METADATA_FILE`, optional | sample |
| `mk-qc` | `molkartqc/*.spot_QC.csv` | sample and method |
| `mk-spots` | `mindagap/*_markedDups.txt` | sample and gene (duplicates on their own row) |
| `mk-cells` | `spot2cell/cellxgene_*.csv`, every method | cell |
| `mk-cells-primary` / `mk-cells-compare` | the same, one method each | cell |
| `mk-cell-genes` | primary method, non-zero counts only | cell and gene |
| `mk-gene-summary` | primary method | sample and gene |
| `mk-gene-heatmap` | primary method, 40 most abundant genes | gene (one column per sample) |
| `mk-img` | `*_clahe.tiff` (pyramidal OME-TIFF), bioimage | image store per sample |
| `mk-lbl-primary` / `mk-lbl-compare` | `segmentation/filtered_masks/*_<method>_filtered.tif`, bioimage labels | label store per sample |

The label stores are the **filtered** masks: their label values are the `CellID` spot2cell
writes, so the cells drawn over the image line up with their labels and with the table rows.
Label ids restart at 1 for every method, which is why each viewer reads one method only.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_ROOT` | | the run's `--outdir`, with the `--input` sheet copied to `input/` |
| `METADATA_FILE` | none | design table, sample id in `sample` or the first column |
| `GROUP_COL` / `GROUP_COL_DISPLAY` | | design factor of the pinned filter and glance donut |
| `PRIMARY_SEGMENTATION` | `mesmer` | method of the Tissue and Cell x gene tabs |
| `COMPARE_SEGMENTATION` | `cellpose` | method of the second viewer |
| `SINGLE_SEGMENTATION` | unset | set when the run used one method: drops the comparison viewer |
| `MEMBRANE_STACK` | unset | set for membrane runs: the viewer reads `stack/*_stack.ome.tif` |
| `IMAGE_SAMPLE_PATTERN` | see template | regex giving the sample of an image store |

## Tabs

1. **QC.** The pinned glance strip (samples, spots kept, cells, panel genes), the sample
   sheet, spot assignment per sample and method, the most detected genes before
   segmentation and the molkartqc table.
2. **Tissue.** The CLAHE image of the first selected sample with the primary labels and one
   point per cell coloured by its dominant gene. A lasso narrows the cell table; a row
   opens the cell record.
3. **Cell x gene.** Top genes by share of assigned transcripts, a dot plot of breadth and
   level per sample, per-cell counts of the most expressed genes and a clustered gene by
   sample heatmap.
4. **Segmentation comparison.** Cells, areas and transcripts per method, labels removed by
   the area filter, and a second viewer with the comparison method's labels and cells.

Every tab carries the pinned Sample and `{GROUP_COL_DISPLAY}` filters and its own open
filter section (method, assignment rate, dominant gene, area, transcripts, gene).

## Reproducing

```bash
python scripts/nfcore_validation_hpc.py run --key molkart
# fetch with rsync -L, copy the samplesheet into <DATA_ROOT>/input/
python -m depictio.cli run --template nf-core/molkart/1.2.0 --data-root <DATA_ROOT> \
  --var METADATA_FILE=<DATA_ROOT>/input/sample_metadata.tsv
```
