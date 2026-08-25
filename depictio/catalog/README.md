# Depictio bioinformatics catalog

A community-extensible **linking table** that connects, for each bioinformatics
tool output:

```
raw nf-core file  ──find──▶  recipe (.py)  ──▶  bindable columns  ──renders_as──▶  dashboard component
   (on disk)                  (optional)         (recipe OR YAML)                 (viz / multiqc plot / table)
                                            anchored on bio.tools + nf-core + EDAM
```

It is **not** a runtime column→viz suggestion engine (`schemas.suggest_viz_kinds`
does that from a DC's inferred schema). It is the map used to **build / assist
dashboards when scanning a run**.

## Contribute a tool without writing YAML

**[Tool Studio](https://depictio.github.io/depictio-tool-studio/)** is a no-backend web app
(source: [`packages/tool-studio/`](../../packages/tool-studio/)) that walks you
through it: drop a CSV/TSV, bind columns to visualizations with live previews, then
download a zip or open a PR into this folder. The authoritative check remains
`depictio dev catalog validate` — the same one CI runs.

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
    - { component: card, column: AF, aggregation: average, secondary_layout: histogram }
    - { component: interactive, interactive_type: MultiSelect, column_name: GENE }
    - { component: table, columns: [sample, GENE, AF], page_size: 25 }
```

Each render is one dashboard component. `SCHEMA.md` lists every field and which
component it belongs to; `dev catalog validate` rejects a field used on the
wrong one.

The golden rule for schemas — **one home, no duplication**:

| Output | where its columns live |
|---|---|
| **has a recipe** | the recipe (`EXPECTED_SCHEMA`). The YAML does **not** repeat them; `roles` are grounded against the recipe at validation time. |
| **no recipe** (raw is bindable) | the YAML, via a `columns:` block; `roles` bind to those. |

Each advanced_viz render can carry an **`id`** — a tool-unique handle a
dashboard addresses directly:

```yaml
renders_as:
  - { id: manhattan, component: advanced_viz, kind: manhattan, roles: {chr: CHROM, pos: POS, score: AF} }
```
```yaml
use: ivar/manhattan        # render id → viz_kind + roles, no viz_kind to guess
```

`use: <tool>/<ref>` resolves `<ref>` as a render id first, then falls back to an
output id (`use: qiime2/ancombc` + `viz_kind:` to disambiguate). Ids stay in the
output (a render binds to *its* columns), never in `module.yaml`, and must be
unique within a tool — so when the same `kind` is rendered by several outputs
(e.g. `rarefaction` from both `alpha_rarefaction` and `rarefaction_canonical`)
each gets a distinct handle (`rarefaction_alpha` vs `rarefaction`).

Don't know a recipe's output column names while writing `roles`?
`depictio catalog columns <recipe>` prints them.

## Catalog vs `projects/` — where a reshape lives

A reshape is **tool-domain logic** the moment it depends only on a tool's
output vocabulary (not on one pipeline version's quirks). Those belong in the
catalog so the tool owns them once and every pipeline emitting that tool reuses
them. Use this rule when deciding where a reshape goes:

| The reshape… | Lives in | Why |
|---|---|---|
| reshapes a tool output and is **version-stable** (same logic across pipeline versions) | `catalog/<tool>/<name>.py` (+ an output YAML if it should be auto-discovered) | tool-owned, reusable, version-agnostic |
| has **version-specific behaviour** (a `{version}/recipes/` override exists) | `projects/<pipeline>/recipes/<name>.py` | the catalog is version-agnostic; a version override must win |
| is just a **column rename** with no real transform | **nothing** — no recipe, no DC | bind the tool output directly via `use: <tool>/<output>` + the catalog `roles` |

"Second-layer" is not the deciding factor: a recipe that reads another DC's
columns (e.g. `embedding_pcoa` consuming `taxonomy_heatmap`) is still
tool-domain logic and belongs in the catalog. What forces a recipe to stay
under `projects/` is a real **version override**, nothing else.

The resolver (`depictio.recipes.resolve_recipe_path`) encodes exactly this
order, so a `qiime2/foo.py` ref and a `nf-core/ampliseq/foo.py` ref both resolve
correctly:

```
1. projects/<pipeline>/<version>/recipes/<name>   # version override wins
2. catalog/<module>/<name>                         # tool-owned reshape
3. projects/<pipeline>/recipes/<name>              # pipeline-keyed shared fallback
```

Live exceptions that prove the rule:

- **`taxonomy_rel_abundance`** stays pipeline-keyed: ampliseq 2.14.0 ships a
  real override (hard-coded `habitat`, mandatory metadata) that differs from
  2.16.0's generic optional join. (`test_legacy_pipeline_keyed_recipe_still_resolves`)
- **volcano / qq / lollipop / manhattan / da_barplot** carry **no recipe**:
  they were pure renames, so the component binds the tool output directly via
  `use:` + roles instead of materialising a remapper DC.

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

## After adding an output: regenerate the conformance project

`validate` proves an entry is *wired* correctly. What proves it is *usable*
(offered by the picker, addable to a dashboard, rendering in the editor and the
viewer) is the e2e suite, and that needs a project whose collections the catalog
recognises.

`depictio/projects/init/catalog_conformance/` is that project, and it is
generated from this directory, so a new output joins the suite with one command:

```bash
uv run python -m depictio.projects.init.catalog_conformance.scripts.generate_project
```

It writes a collection per distinct recipe and per recipe-free output, stages the
fixtures, derives the ids, and refuses to produce an ambiguous staging. Commit
what it changes. `depictio/tests/catalog/test_conformance_project.py` fails if
you forget, so the coverage gap cannot go unnoticed.

Two cases need a little more than a rerun:

- **A new MultiQC section** needs a parser-valid stub in
  `scripts/multiqc_stubs.py`, keyed on the catalog's own `section` value, or
  the report will not carry it. The generator says which section is missing.
- **A recipe-free output whose `find` collides** with another output's pattern
  fails the generator on purpose: one staged file recognised as two outputs
  would offer a render bound to columns that frame does not have.

The project is opt-in: deployments only seed it when
`DEPICTIO_SEED_EXTRA_PROJECTS=catalog_conformance` is set, as CI's Playwright
leg does.

## The other half: a project the CLI actually ingests

The conformance project seeds each recipe's *result*, so it proves an output is
offerable and renderable but never runs the recipe that produces it. `validate`
has the same blind spot in the other direction: it grounds `renders_as` against
the fixture when there is one, and only falls back to the recipe's
`EXPECTED_SCHEMA` when there is not — so a fixture that has drifted ahead of its
recipe keeps CI green while a real ingest produces a frame the render cannot
bind.

`depictio/projects/test/catalog_cli_smoke/` closes that gap for a handful of
outputs: six collections staged as raw tool output and ingested with
`depictio-cli run`, covering every way a collection reaches the matcher (recipe
with a file source, with a glob source, with a `dc_ref` source, and no recipe at
all). `depictio/tests/catalog/test_cli_smoke_project.py` executes every recipe
against those staged files offline, so a recipe whose input moved or whose output
lost a bound column fails there rather than in someone's browser.

It is not seeded — running it is the point. See the project's README.
