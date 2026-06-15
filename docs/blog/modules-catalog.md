# From nf-core outputs to interactive dashboards: introducing the Depictio modules catalog

*A community-driven catalog that binds the outputs of bioinformatics modules to
the right interactive visualisation — volcano, heatmap, UMAP, taxonomy bar, and
more.*

---

## The gap between "pipeline finished" and "I can explore my results"

If you run [nf-core](https://nf-co.re) pipelines, you know the moment well. The
workflow turns green, the `results/` directory fills up, and
[MultiQC](https://multiqc.info) gives you a beautiful QC report. Then you hit the
wall: **everything past QC**. The DESeq2 table, the ANCOM-BC differentials, the
MetaPhlAn profile, the QIIME 2 artefacts — the *biology* — lands as static CSVs
and PNGs. To explore it interactively you either pay for a SaaS platform or
spend a week hand-building a Shiny/Dash app that you'll maintain forever.

Depictio exists to close that gap. It's an open-source platform that turns
bioinformatics workflow outputs into **interactive dashboards** — a
React/TypeScript front end (Plotly.js for the charts) backed by FastAPI, Polars
and Delta Lake, deployable with Docker Compose or Helm/Kubernetes. You point it
at your pipeline outputs; it serves dashboards.

The piece we're writing about today is what connects the two ends: the
**modules catalog**.

## The idea: MultiQC, but for *exploration*, and community-extensible

MultiQC's genius is a simple, extensible recipe: each tool publishes a *search
pattern* for its output, and a module that knows how to render it. Hundreds of
tools are supported because adding one is a contained, well-documented
contribution.

The Depictio modules catalog applies the same philosophy one step downstream —
not to QC metrics, but to **analysis results and the advanced visualisations
that make them explorable**. It is:

- **Not limited to QC** — volcano plots, clustergrams/heatmaps, UMAP/PCoA
  embeddings, stacked taxonomy bars, OncoPrint, Manhattan plots, lollipop/needle
  plots, genome browser tracks.
- **Driven by a catalog the community can extend** — adding a tool is a YAML
  file, not a Python PR into the internals.
- **Built for tools with many modes and many outputs** — QIIME 2 is the stress
  test: dozens of differently-shaped artefacts depending on the subcommand.

## The atom: `module output → find → recipe → renders_as`

Everything in the catalog composes from one building block:

```
nf-core module output  →  find  →  (recipe?)  →  renders_as (viz)
```

- **`find`** — how the CLI *recognises* a file in a run directory: a filename, a
  path glob, content match, or a set of required columns. This is the catalog
  analogue of MultiQC's `search_patterns`.
- **`recipe`** *(optional)* — when the raw file isn't already in the shape a viz
  wants, a recipe reshapes it (a join, a melt, a derived column). When the file
  is already bindable, you omit it. This is honest about where column-name
  matching stops and real code must take over.
- **`renders_as`** — the advanced visualisation the output feeds, plus a
  pre-filled mapping of columns to the viz's *roles* (e.g. for a volcano:
  `feature_id`, `effect_size`, `significance`).

Crucially, the catalog is **keyed by module, not by pipeline**. A pipeline is
just a *list of modules* that picks from the catalog. That single decision is
what makes the system pipeline-agnostic: it works for a brand-new nf-core
pipeline (its dashboard is the assembly of its modules' visualisations) *and* for
a custom workflow that reuses nf-core modules (we recognise the module outputs
regardless of the wrapper).

Identity is anchored on the ecosystems that already publish it — every entry
carries directly-clickable `nf_core_url`, `biotools_url` and EDAM ontology terms,
which nf-core `meta.yml` already exposes per output channel.

## Two ways to use it

**Free mode** — you browse the catalog's modules and map columns to viz roles by
hand, assisted by dtype-aware suggestions (`suggest_viz_kinds` matches your
columns to a viz's required roles). Full control, no magic.

**Guided mode** — `depictio-cli` recognises module outputs in a run directory
(via `find`, optionally scoped by the run's `software_versions.yml`) and composes
a **starter dashboard** for you. Because recognition is per-module, it works the
same whether the run came from an official nf-core pipeline or your own Nextflow
glue around nf-core modules.

## The advanced visualisations it maps into

The catalog binds outputs into a family of self-contained, interactive panels —
each one bundles a non-trivial chart with its own controls (sliders, search,
threshold lines) and participates in cross-component coordination (click a gene
in the volcano, recolour the embedding by it). The initial family spans four
domains:

| Domain | Visualisations |
|---|---|
| Bulk omics | Volcano (+ threshold + search), Clustergram / heatmap, PCA |
| Single-cell | UMAP / t-SNE embedding, Clustergram |
| Metagenomics | Stacked taxonomy bar, PCoA, rarefaction |
| Variants / clinical | OncoPrint, Manhattan / GWAS, Lollipop / needle, genome browser |

Dimensionality reduction and clustering (PCA / UMAP / t-SNE / PCoA / hclust) are
modelled as a first-class `compute` step that runs on Celery and materialises a
derived Data Collection — so a heatmap or embedding binds to its output exactly
like any other data.

## Adding a tool is a YAML file (and you should)

This is the part we most want help with. Extending the catalog does **not**
require understanding Depictio's internals. The workflow is:

```bash
# 1. Scaffold from an existing nf-core module's meta.yml (offline, no network needed)
depictio catalog import-meta path/to/meta.yml -o depictio/catalog/<tool>.yaml

# 2. Fill in each output's: find, file_schema, recipe (if needed),
#    feeds_viz, role_mapping

# 3. Validate (CI-friendly, non-zero on schema violation)
depictio catalog validate

# 4. Add a one-line assertion to the test suite and open a PR
```

Single-output tools are one flat YAML file; multi-output tools (QIIME 2,
mosdepth, MultiQC sections) are a folder with one file per output. CI runs
`catalog validate` plus the suggestion test, so a malformed or viz-incompatible
entry fails fast. **The barrier is "write a YAML file and a one-line test", not
"learn the producer registry."**

If you maintain an nf-core module, or you just have a tool whose output you'd love
to see rendered as a proper interactive chart instead of a static PNG — that's a
perfect first contribution.

## Where this is going

- **Wire `match` + `recipe` into ingest** so module outputs are auto-recognised
  and reshaped at ingest time, then validated against the target viz schema.
- **EDAM-semantic suggestions** — use ontology terms as a secondary match signal
  when column fingerprints are ambiguous, and to group suggestions by tool.
- **Bulk import across the nf-core modules registry** to scaffold the long tail,
  tracking catalog coverage per pipeline (viralrecon and ampliseq are seeded
  first).

## Try it / get involved

- **Docs**: <https://depictio.github.io/depictio-docs/latest/>
- **Try in the browser**: open the repo in GitHub Codespaces (badge in the README)
- **Code & issues**: <https://github.com/depictio/depictio>
- **Contribute a module**: see the catalog `README.md` and `SCHEMA.md`, run
  `depictio catalog import-meta`, open a PR.

Whether you want dashboards for your nf-core runs the easy way, or you want to
help map the long tail of bioinformatics tools to the visualisations they
deserve — there's a door in for you.
