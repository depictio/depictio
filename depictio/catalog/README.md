# Depictio bioinformatics catalog

A community-extensible **linking table** that connects, for each bioinformatics
tool output:

```
raw nf-core file  ──find──▶  recipe (.py)  ──▶  bindable columns  ──renders_as──▶  dashboard component
   (on disk)                  (optional)         (recipe OR YAML)                 (viz / multiqc plot / table)
                                            anchored on bio.tools + nf-core + EDAM
```

It is **not** a second column→viz suggestion engine (`producers.py` already does
that). It is the map used to **build / assist dashboards when scanning a run**.

## Layout

A **tool** is a flat file (single output) or a folder (many outputs):

```
depictio/catalog/
  ivar.yaml              # single output  → one flat file (tool fields + outputs)
  pangolin.yaml  nextclade.yaml  metaphlan.yaml
  qiime2/                # many outputs   → a folder
    module.yaml          #   the tool's fields (id, name, URLs…)
    taxa_barplot.yaml    #   one output per file
    ancombc.yaml  rel_abundance.yaml  alpha_diversity.yaml  alpha_rarefaction.yaml
  mosdepth/   multiqc/
```

Adding a tool = a PR that adds one YAML file. **No Python** (unless the output
needs a reshape, which is a recipe).

## What one output declares

```yaml
- id: ivar_variants_long
  find:   { filename: "variants_long_table.csv" }   # recognise the raw file
  recipe: nf-core/viralrecon/variants_long.py        # optional reshape
  renders_as:
    - { component: advanced_viz, kind: manhattan, roles: {chr: CHROM, pos: POS, score: AF} }
```

The golden rule for schemas — **one home, no duplication**:

| Output | where its columns live |
|---|---|
| **has a recipe** | the recipe (`EXPECTED_SCHEMA`). The YAML does **not** repeat them; `roles` are grounded against the recipe at validation time. |
| **no recipe** (raw is bindable) | the YAML, via a `columns:` block; `roles` bind to those. |

Don't know a recipe's output column names while writing `roles`?
`depictio catalog columns <recipe>` prints them.

## Commands

```bash
depictio catalog list                 # every tool + output + render targets
depictio catalog info qiime2          # one tool: URLs + outputs in detail
depictio catalog columns <recipe.py>  # the recipe's output columns (to write roles)
depictio catalog preview <output>     # render the output's components on its fixture → HTML (opens in browser)
depictio catalog match path/to/run    # recognise tool outputs in a run dir
depictio catalog validate             # CI gate: schema + roles vs recipe + nf-core/EDAM existence
depictio catalog refresh-index        # (maintainer, needs network) refresh _index/ from nf-core + EDAM
depictio catalog schema -o catalog.schema.json   # regenerate the JSON Schema
```

Identity validation is two-tier: `mode`/`description` are free; `nf_core_url`
modules and `edam_*` terms are checked for **existence** against vendored
indices in `_index/` (offline CI), while `biotools_url` is format-only.

`validate` is the CI guarantee: it fails if any `renders_as` role doesn't exist
in the recipe's real output — so a green CI means the entry is wired correctly,
with no manual review.
