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

**One folder per module** — a self-contained unit holding the tool identity,
one YAML per output, and each output's **co-located fixture**:

```
depictio/catalog/
  ivar/
    module.yaml          # lightweight tool identity: id, name, nf_core_url (pointer)
    variants_long.yaml   # one output per file — find + recipe + renders_as live HERE
    variants_long.tsv    # its fixture, right next to it
  qiime2/
    module.yaml
    alpha_diversity.yaml   alpha_diversity.tsv
    ancombc.yaml           ancombc.tsv
    taxa_barplot.yaml  rel_abundance.yaml  alpha_rarefaction.yaml  (+ .tsv)
  mosdepth/   multiqc/   pangolin/   nextclade/   metaphlan/
```

Adding a tool = a PR that adds **one folder** (`module.yaml` + output YAML(s) +
fixture). **No Python** unless an output needs a reshape (a recipe).

`module.yaml` is deliberately **lightweight**: it carries the folder anchor
(`id`), a display `name`, and the `nf_core_url` **pointer** — nothing else. The
rest of the identity (homepage, bio.tools id, EDAM topics) already lives in the
module's nf-core `meta.yml`, so we don't duplicate it. Declare an identity field
in `module.yaml` only to **override** a stale `meta.yml` (e.g. MultiQC's homepage
moved to Seqera) or when there is **no** nf-core module to derive from (QIIME 2,
whose `nf_core_url` is per-output and whose identity stays declared in full).
All depictio-specific glue — `find`, `recipe`, `fixture`, `renders_as` — lives in
the **output** YAMLs, never in `module.yaml`.

## What one output declares

```yaml
- id: ivar_variants_long
  find:   { filename: "variants_long_table.csv" }   # recognise the raw file
  recipe: ivar/variants_long.py                      # optional reshape (module-owned, co-located here)
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
