<!--
DRAFT NOTE (remove before publishing):
- Publishes to depictio-docs blog; move/PR across. `authors:` slug must exist in .authors.yml.
- Accuracy: React renderers confirmed on main for volcano, embedding, complex-heatmap, manhattan,
  oncoplot, lollipop, stacked-taxonomy, rarefaction, sunburst, MA, QQ, dotplot, sankey, upset, etc.
  Volcano + Embedding are the MOST MATURE (fully typed configs + "live" suggestion logic);
  the others have renderers but newer configs. VERIFY which are exposed in the builder UI before
  publishing so we don't over-promise "point-and-click" for renderer-only ones.
-->
---
date: 2026-07-15
authors:
  - thomas-weber
categories:
  - Features
---

# 🧬 The omics visualization catalog: volcano, heatmap, UMAP, Manhattan

Every omics field has *that one plot* — the chart you'd recognise across a room.
Depictio ships them as interactive, self-contained panels, not static images.
Here's the catalog and when to reach for each.

<!-- more -->

## Why a catalog

A generic "make a scatter plot" tool can technically draw a volcano. But the
plots that matter in biology come with expectations: a volcano needs
significance thresholds you can move; a Manhattan needs chromosomes in the right
order; a heatmap needs clustering. Depictio's advanced visualisations bake those
expectations in. Each one is a **chart plus its own controls**, and you bind your
data collection's columns to the roles the plot needs.

## 🌋 Volcano

The signature of differential analysis — RNA-seq, proteomics,
differential abundance. You map three roles: a **feature id**, an **effect size**
(log fold-change), and a **significance** value (p or adjusted p). Then you drag
the fold-change and significance thresholds and watch points light up, search for
a gene by name, and label the top hits. The `-log10` transform is handled for
you.

Volcano is one of the two most mature panels in the catalog, with a fully typed
configuration and column suggestions that recognise when your data is a good fit.

## 🔥 Heatmap / clustergram

Expression matrices, sample-by-feature comparisons, pseudo-bulk summaries. The
complex-heatmap panel clusters rows and columns, rescales (z-score / log), and
lets you zoom into a block of co-regulated features. Annotation tracks put sample
metadata alongside the matrix so patterns line up with conditions.

## 🔬 Embedding (PCA / UMAP / t-SNE / PCoA)

The map of single-cell and community-level data. Bind a **sample id** and the
**dimensions**, then colour points by cluster or by any variable, adjust point
size, and lasso a population. Embedding is the second fully-mature panel — and
it pairs naturally with a compute step that can produce the embedding from a raw
matrix.

## 📊 Manhattan / GWAS

Genome-wide association and anything with significance along the genome. Map
**chromosome**, **position**, and **p-value**; slide the significance line and
jump to a locus. Chromosome ordering (1…22, X, Y, MT) is enforced so the plot
reads correctly.

## 🧩 …and the rest of the family

The four above are the headliners, but the catalog is broader — panels for
**oncoplot** (cohort mutation matrices), **lollipop / needle** (mutations along a
protein), **stacked taxonomy** (metagenomic composition), **rarefaction**,
**sunburst**, **MA**, **QQ**, **dot plot**, **Sankey**, and **UpSet**, among
others. The family spans bulk omics, single-cell, metagenomics, and
variants/clinical.

## 🔌 How binding works

Every panel declares the **roles** it needs and the column types they accept. In
the editor you pick, per role, which column of your data collection fills it —
and Depictio validates the match, so a mismatch is caught with a clear message
rather than a broken chart. Extra columns are always welcome; they show up in
tooltips and hover.

## 🔗 They're connected

The real payoff isn't any single plot — it's that they talk to each other. Click
a gene in the volcano and an embedding can recolour by it; lasso samples in the
embedding and promote that selection to a dashboard-wide filter. That's a whole
post of its own — *Connected dashboards* — and it's where these visualisations
stop being charts and become a workspace.

## 🚀 Try it

Open the demo, bind one of these panels to a dataset, and drag a threshold. The
plot you reach for every day is now something you can *explore*.

Which plot is *the* plot in your field? We're growing the catalog — tell us.
