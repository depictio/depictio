<!--
DRAFT NOTE (remove before publishing):
- Publishes to depictio-docs blog; move/PR across. `authors:` slug must exist in .authors.yml.
- Accuracy: `depictio catalog list | info | preview` commands + catalog entries (ivar, metaphlan,
  mosdepth, multiqc, nextclade, pangolin, qiime2) are SHIPPED on main. The model is
  module output -> find -> recipe -> renders_as.
- READINESS GATE: the one-click "catalog studio" authoring UI (#902) is an OPEN PR at time of
  writing. The final section is framed as "coming"; update once it merges.
- Confirm exact CLI flags (import-meta, validate) against `depictio catalog --help` before publishing.
-->
---
date: 2026-07-15
authors:
  - thomas-weber
categories:
  - Tutorials
  - Features
---

# 🧩 Contribute a tool to the catalog: from `meta.yml` to a live viz in one PR

Your tool's output deserves better than a static PNG. Depictio's catalog maps a
bioinformatics tool's output to the right interactive visualisation — and adding
a mapping is a config file, not a Python pull request. Here's how.

<!-- more -->

## The model: output → find → recipe → renders_as

Everything in the catalog composes from one building block:

```
tool/module output  →  find  →  (recipe?)  →  renders_as (viz)
```

- **find** — how Depictio *recognises* a file: a filename, a path glob, a content
  match, or a set of required columns. (Think MultiQC's search patterns.)
- **recipe** *(optional)* — when the raw file isn't already the shape a viz wants,
  a recipe reshapes it. When it's already bindable, you omit it.
- **renders_as** — the visualisation the output feeds, with its columns mapped to
  the viz's roles.

The catalog is keyed by **module**, not pipeline — a pipeline is just a list of
modules that pick from it. That's what makes it work for any nf-core pipeline and
for custom workflows that reuse nf-core modules.

## 🧩 The anatomy of a catalog entry

Depictio already ships entries you can read as templates — `pangolin`,
`nextclade`, `ivar`, `metaphlan`, `mosdepth`, `multiqc`, and a multi-output
`qiime2` module. A single-output tool is one flat file; a multi-output tool
(QIIME 2 is the stress test) is a folder with one file per output, each with its
own `find`, schema, optional `recipe`, and `renders_as`.

Browse what's there today:

```bash
depictio catalog list          # every tool/output and what it renders as
depictio catalog info <tool>   # the details of one entry
```

## 🏗️ Scaffold from an existing `meta.yml`

If you maintain (or use) an nf-core module, you don't start from a blank file.
The importer reads the module's `meta.yml` — which already publishes tool
identity, EDAM terms, and output channels — and scaffolds a draft entry for you
to fill in. It runs offline, so it works on locked-down networks.

From there you complete each output's `find`, its raw `file_schema`, a `recipe`
if the shape needs work, and the `renders_as` binding.

## 👀 Preview it through the real viewer

This is the part that makes contributing satisfying: you don't have to guess
whether your mapping works. The preview command renders every `renders_as` target
for an entry **through Depictio's actual React viewer**, grounding each role
against the recipe's real output columns:

```bash
depictio catalog preview <tool> <output>
```

If the chart looks right here, it will look right in a dashboard.

## ✅ Validate and open a PR

A validation command checks your entry against the catalog schema and fails fast
on anything malformed or viz-incompatible — the same check CI runs. Once it's
green, add a one-line assertion to the catalog tests and open a pull request.

The barrier is "write a YAML file and a one-line test," not "understand the
engine." If your tool emits a table that clearly wants to be a volcano, a
heatmap, or a taxonomy bar, that's a perfect first contribution.

## ✨ Coming: one-click authoring

Writing YAML by hand is fine, but we're making it easier still — a **catalog
studio** that lets you author an entry with builder-fidelity previews and open
the contribution as a pull request in one click. It's on the way; for now, the
CLI path above is the way in.

## 🚀 Get involved

- **See what's mapped:** `depictio catalog list`.
- **Add your tool:** scaffold from `meta.yml`, fill in `find` / `recipe` /
  `renders_as`, preview, validate, PR.
- **Not sure where to start?** Tell us which tool's output you'd love to see
  interactive, and we'll help you map it.

Help us map the long tail of bioinformatics tools to the visualisations they
deserve — one YAML file at a time.
