# Depictio bioinformatics catalog

This directory is the **community-extensible catalog** that maps the outputs of
bioinformatics tools (nf-core modules / bio.tools entries) to depictio
visualisations. It is the evolutive, grow-with-the-community layer that sits on
top of the hand-curated fingerprint registry in
`depictio/models/components/advanced_viz/producers.py`.

Each `*.yaml` file describes **one tool** and **all of the outputs** it can
produce. Adding support for a new tool — or a new running mode of an existing
tool — is a pull request that adds or edits one YAML file. No Python required.

## Why a catalog (and not just more `producers.py`)

`producers.py` is a vetted core kept in a single Python file. The catalog
extends it for three things a bare fingerprint can't express:

1. **Upstream identity** — every tool carries its `biotools_id`, EDAM ontology
   terms, and per-output `nf_core_module`. This is the same metadata nf-core
   modules already publish in `meta.yml`, so entries can be *scaffolded
   automatically* (see below).
2. **Many running modes per tool** — heavyweight tools like QIIME 2 emit dozens
   of differently-shaped artefacts depending on the subcommand. One `tool`
   owns many `outputs`, each tagged with its `mode` (mirroring how nf-core
   models a module's output channels and how bio.tools models a tool's EDAM
   operations). See `qiime2.yaml`.
3. **The reshape a raw file needs** — a tool's on-disk output is rarely in the
   exact long/wide shape a viz wants. Each output declares the reshape
   (`melt` / `pivot` / `aggregate`) declaratively, or defers to a Python
   `recipe` for arbitrary logic.

At runtime the catalog is compiled to the same `Producer` primitives the
suggestion engine already uses, and merged via `producers.all_producers()`
(hand-curated entries win on any name collision).

## Anatomy of an entry

```yaml
schema_version: 1
tool:
  id: metaphlan
  name: MetaPhlAn
  biotools_id: metaphlan          # links to bio.tools
  edam_topics: [topic_3174]       # Metagenomics
outputs:
  - id: metaphlan_merged_abundance  # stable, globally-unique producer id
    mode: merge_metaphlan_tables    # the running mode that emits this artefact
    nf_core_module: metaphlan/mergemetaphlantables
    edam_formats: [format_3475]     # TSV
    file_patterns: ["merged_abundance_table.txt"]
    read_options: {format: tsv}
    reshape:                        # raw file -> bindable shape
      kind: melt
      id_vars: [clade_name, NCBI_tax_id]
      variable_name: sample_id
      value_name: abundance
    fingerprint:                    # column-name signature (post any read parse)
      required_columns: [clade_name, NCBI_tax_id]
    feeds_viz: [stacked_taxonomy, sunburst]
    role_mapping:                   # pre-fill viz role -> column
      stacked_taxonomy: {sample_id: sample_id, taxon: clade_name, abundance: abundance}
```

`reshape.kind` is one of: `identity` (default), `melt`, `pivot`, `aggregate`,
`recipe`. When the reshape is too complex to express declaratively, set
`kind: recipe` and point at an existing
`depictio/projects/<pipeline>/recipes/<name>.py`.

An output with no `fingerprint` is still useful (it carries provenance + the
recipe link), it just won't be matched from column names by the suggestion
engine — its viz comes via its `recipe` producing an already-known canonical
shape.

## Scaffold from an nf-core module

```bash
# fetch a module meta.yml, then:
depictio catalog import-meta path/to/meta.yml -o depictio/catalog/<tool>.yaml
# then fill in each output's fingerprint.required_columns + feeds_viz
```

## Validate before committing

```bash
depictio catalog list           # show every tool + mode
depictio catalog validate       # validate the whole bundle (CI-friendly)
depictio catalog validate -p depictio/catalog/<tool>.yaml
```
