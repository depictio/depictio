<!--
DRAFT NOTE (remove before publishing):
- Publishes to depictio-docs blog; move/PR across. `authors:` slug must exist in .authors.yml.
- READINESS GATE: DC-linking UI + cross-DC filtering are MERGED (v1.1.4). But cross-tab filtering
  (#756) and bidirectional/linked components for tiled maps (#726) are still OPEN PRs at time of
  writing. Either publish AFTER they merge, or soften the "cross-tab" and "bidirectional" sections
  to "landing soon". Re-check PR status before publishing.
-->
---
date: 2026-07-15
authors:
  - thomas-weber
categories:
  - Features
---

# 🔗 Connected dashboards: make your components talk to each other

A chart is useful. A chart wired to the rest of your dashboard is a different
thing entirely. This is the feature that turns a page of separate figures into a
single interactive workspace.

<!-- more -->

## The problem with disconnected panels

Most dashboards are a wall of independent charts. You filter one, the others sit
still. To ask "show me everything for *this* sample" you end up exporting,
re-filtering, and cross-referencing by eye. The insight is there; the tool just
won't connect the dots for you.

Depictio's answer is coordination: a click or a filter in one place propagates to
the others.

## 🎛️ Start with interactive filters

The simplest form of connection is an **interactive** component — a dropdown,
slider, or search bound to a column. Point it at your data and it drives every
component that reads from the same source. Change the filter once; the whole view
responds.

## 🔗 Link data collections

Real analyses span more than one table — counts here, sample metadata there,
differential results in a third. Depictio lets you **link data collections** so a
selection in one flows to the others through their shared keys. You define the
relationship once in the UI, and cross-collection filtering just works — pick a
condition in a metadata table and your expression chart narrows to it.

## 🗂️ Filter across tabs

Dashboards grow into multiple tabs — QC on one, differential analysis on another,
composition on a third. **Cross-tab filtering with global filters** keeps a
selection consistent everywhere: choose a cohort on the overview and every tab
reflects it, so the story stays coherent as you move through the dashboard.

You can also structure a dashboard as a **journey** or a **funnel** — guiding a
reader from an overview down into detail, with each step filtered by the last.

## ↔️ Linked, bidirectional components

The richest connection is two-way. Selecting a region on a map can filter the
charts beside it, and a selection in those charts can highlight back on the
map — components that both **read** and **publish** selections. Coordination like
this is what makes a spatial or multi-panel dashboard feel like one instrument
instead of several.

## 🧭 How to set it up

The pattern is always the same three ideas:

1. **Interactive filters** for the simple, single-source case.
2. **Data-collection links** when a selection needs to cross tables.
3. **Global / cross-tab filters** when it needs to hold across the whole
   dashboard.

You wire these in the editor — no code — and the viewer handles propagation.

## 🚀 Try it

Build two charts from linked collections, drop a filter between them, and click.
When the second chart reacts to the first, you'll feel why this is the feature
that makes a dashboard worth sharing.
