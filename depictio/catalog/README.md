# Depictio bioinformatics catalog

The **community-extensible catalog** that maps the outputs of bioinformatics
tools (nf-core modules / bio.tools entries) to depictio visualisations —
structured like **MultiQC modules**.

## Layout

A **module = a tool**. A single-output tool is one flat file; a multi-output
tool (QIIME 2) is a folder with one file per output / running mode:

```
depictio/catalog/
  pangolin.yaml          # single output  → one file
  nextclade.yaml
  ivar.yaml
  metaphlan.yaml
  multiqc.yaml
  fastqc.yaml
  qiime2/                # many outputs   → a folder
    module.yaml          #   the tool's identity (links to nf-core + bio.tools)
    taxa_barplot.yaml    #   one output / running mode = one file
    rel_abundance.yaml
    alpha_diversity.yaml
    alpha_rarefaction.yaml
    ancombc.yaml
    phylogeny.yaml
  mosdepth/
    module.yaml
    genome_coverage.yaml
    amplicon_coverage.yaml
    amplicon_heatmap.yaml
```

Adding support for a tool (or a new mode of an existing tool) is a PR that adds
one YAML file. **No Python required.**

## What one output declares

Each output is self-contained and answers four questions (full field reference
in **`SCHEMA.md`**; machine contract in **`catalog.schema.json`**):

1. **`find`** — how depictio-cli *recognises* the file (filename glob /
   path glob / content match / required columns), exactly like MultiQC's
   `search_patterns` (`fn` / `contents`).
2. **`file_schema`** — the columns + dtypes the tool actually writes (the raw
   file as-emitted), so you can see what the file looks like.
3. **`reshape`** — how to turn that raw file into a viz-ready shape (`melt` /
   `pivot` / `aggregate`, or a `recipe` for arbitrary logic).
4. **`feeds_viz` + `role_mapping`** — which depictio visualisation(s) it maps to.

Identity is **resolvable**: `biotools_id` → `https://bio.tools/<id>`,
`nf_core_module` → the nf-core/modules tree, `edam_*` → edamontology.org.

Example (`pangolin.yaml`):

```yaml
module:
  id: pangolin
  name: Pangolin
  nf_core_module: pangolin/run         # → github.com/nf-core/modules/.../pangolin/run
  biotools_id: pangolin_cov-lineages   # → bio.tools/pangolin_cov-lineages
outputs:
  - id: pangolin_report
    find: { filename: "*.pangolin.csv", required_columns: [taxon, lineage] }
    file_schema: { taxon: String, lineage: String, scorpio_call: String, qc_status: String }
    reshape: { kind: recipe, recipe: nf-core/viralrecon/pangolin_lineages.py }
    feeds_viz: []
```

## How depictio-cli recognises files

```bash
depictio catalog match <run_dir>   # walk a run dir, report recognised tool outputs
```
This is the catalog analogue of MultiQC's file search. Each hit reports
`module / output → feeds_viz`.

## Commands

```bash
depictio catalog list                 # every module + output, with its find rules
depictio catalog info qiime2          # one module: resolvable links + output detail
depictio catalog validate             # validate the bundle (CI-friendly)
depictio catalog match path/to/run    # recognise files in a run directory
depictio catalog import-meta meta.yml # scaffold a draft entry from an nf-core meta.yml
depictio catalog schema -o catalog.schema.json   # regenerate the JSON Schema
```
