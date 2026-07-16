<!--
DRAFT NOTE (remove before publishing):
- Publishes to the depictio-docs blog. Move this file there, or PR it across.
- `authors:` slug must exist in depictio-docs `.authors.yml` (existing posts use Thomas Weber).
- Version framing per user decision: celebrate "1.0" as the milestone (repo tag is currently 1.1.4).
- All features referenced are shipped on main (v1.1.4): React migration #770, realtime #899/#900,
  advanced-viz renderers, catalog CLI, Gateway API #882.
-->
---
date: 2026-07-15
authors:
  - thomas-weber
categories:
  - Announcements
  - Launch
  - Features
---

# 🎉 Depictio 1.0 — what's changed since we went live

A year ago, Depictio went live with a public demo and a simple promise: turn
bioinformatics results into interactive dashboards, without writing a
front-end. Today, Depictio reaches its first **stable major release**.

This post is the tour of everything that landed on the way to 1.0 — and there's
a lot.

<!-- more -->

## ✅ What "1.0" means

1.0 is a commitment, not just a number. It means the core is stable and
production-ready: the data model, the API, and the viewer have settled enough
that you can build on them and deploy them for real users — in a lab, a core
facility, or a consortium — without expecting the ground to shift under you.

Concretely, 1.0 ships with:

- a rewritten, modern front end,
- real-time dashboards,
- a catalog of omics-specific visualisations,
- pipeline templates,
- and the same self-hosted, open-source foundation Depictio started with.

Let's go through them.

## 🔁 The big one: Dash → React

The single largest change since launch is invisible in a screenshot but felt
everywhere: **the entire front end was rewritten in React/TypeScript**, and the
old Dash codebase was removed.

Why do it? The dashboard viewer is the heart of Depictio, and a React foundation
gives us what a dashboarding tool needs most — a real component model, precise
control over interactivity and state, and a clean path to advanced,
cross-linked visualisations. Charts still render with Plotly.js; what changed is
everything around them.

For you, the payoff is a faster, smoother viewer and a component architecture
that made the rest of this release possible.

## ⚡ Real-time dashboards

Dashboards used to describe data that already existed. Now they can describe
data as it *arrives*.

Depictio 1.0 introduces **real-time dashboards over WebSockets**. A running
process — say a microscopy acquisition — can stream events into Depictio, and a
live timeline and gallery update in the browser as new items land, with recent
arrivals highlighted. No refresh, no re-run.

It's a small feature to describe and a striking one to watch: a dashboard that
moves while you look at it.

## 📊 An omics visualization catalog

Every field has *that one plot*. RNA-seq has the volcano. Single-cell has the
UMAP. GWAS has the Manhattan. Expression studies have the heatmap.

Depictio now ships a growing family of **advanced, interactive
visualisations** built for exactly these: volcano plots with draggable
significance thresholds, clustered heatmaps, PCA/UMAP/PCoA embeddings, Manhattan
plots — and more (oncoplot, lollipop, stacked taxonomy, rarefaction, sunburst…).
Each is a self-contained panel: a chart plus its own controls.

We'll dedicate a whole post to the catalog. For now: the plots you reach for are
becoming first-class, interactive citizens in Depictio.

## 📥 Bring any data

Depictio 1.0 is deliberately unfussy about inputs. You can bring:

- **dataframes** (CSV, Parquet, …),
- **MultiQC reports**,
- **GeoJSON**,
- **images**,

and create data collections straight from the UI. Then you can **connect
multiple sources together** so components react to one another — click in one
panel and the rest update. One linked, interactive view instead of a folder of
disconnected files.

## 🔒 Still self-hosted — your data stays yours

None of this changes the founding principle: **Depictio is self-hosted and
open-source**. You run it on your own infrastructure — laptop, institute
servers, cluster, private cloud — and your data never leaves your control.

1.0 makes the deployment story sturdier, including a **Gateway API** option for
cleaner ingress in front of the backend, alongside the existing Docker Compose
and Helm/Kubernetes paths. No vendor account, no per-seat bill, no data leaving
the building.

## 🗺️ What's next

1.0 is a foundation, not a finish line. On the roadmap: deeper pipeline
templates for common nf-core workflows, guided dashboard assembly straight from
a run directory, and a community-extensible catalog so any tool's output can be
mapped to the right visualisation.

## 🚀 Try it

- **Live demo:** explore pre-loaded datasets or upload your own.
- **Docs:** start with *Your first dashboard in 15 minutes*.
- **GitHub:** ⭐ the repo, file issues, join the discussion.

A year ago Depictio went live. Today it's 1.0 — stable, faster, real-time, and
ready for your data. Huge thanks to everyone who tested, filed issues, and
pushed us to ship. 🙏
