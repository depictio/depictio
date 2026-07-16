<!--
DRAFT NOTE (remove before publishing):
- Publishes to depictio-docs blog; move/PR across. `authors:` slug must exist in .authors.yml.
- VERIFY UI LABELS against the current build before publishing — the step names below are
  written from the model/CLI structure and may differ slightly from the live UI wording.
  Do a real run-through and adjust the click-by-click steps + screenshots.
- Distinct from the existing "Project Types" post: this is click-by-click, NOT a concept comparison.
-->
---
date: 2026-07-15
authors:
  - thomas-weber
categories:
  - Tutorials
---

# 🚀 Your first dashboard in 15 minutes

You have a table of results and fifteen minutes. By the end of this post you'll
have an interactive dashboard you can filter, explore, and share by link — with
no front-end code.

<!-- more -->

## ⚙️ Before you start

You need a running Depictio instance. The fastest options:

- **One-click in the browser:** open the repository in GitHub Codespaces (badge
  in the README) — nothing to install.
- **Local with Docker:** clone the repo and bring it up with the dev compose
  file. See the deployment docs for the exact command.

You'll also want a small tabular file to play with — any CSV works. If you don't
have one handy, the demo ships with example datasets you can use instead.

## 🚀 Step 1 — Open Depictio

Navigate to your instance and sign in. You'll land on the dashboards overview —
the home for every dashboard you create.

## 📁 Step 2 — Create a project

Everything in Depictio lives inside a **project**. Create a new one and give it a
name. For a single spreadsheet, a **basic project** is exactly right — it's built
for simple tabular data and the quickest path to a dashboard. (For
multi-sample pipeline outputs there are advanced projects; see the *Project
Types* post for that comparison — we'll stay basic here.)

## 📤 Step 3 — Upload your data

Inside the project, create a **data collection** and upload your CSV directly
from the UI. Depictio reads the file, infers the columns and their types, and
registers it — no config file required. Beyond CSVs, you can also bring Parquet,
MultiQC reports, GeoJSON, and images, but a CSV is perfect for a first run.

Take a moment to check the detected columns look right. This schema is what your
charts will bind to.

## 📈 Step 4 — Add your first chart

Open a dashboard in the project and add a **figure** component. Pick a chart type
(a bar or scatter is a friendly start), then map your columns to the chart's
axes. The preview updates as you go. Save it, and it drops onto the dashboard
grid, where you can drag and resize it.

That's already a live, rendered chart from your data. But a dashboard is more
than one chart.

## 🎛️ Step 5 — Add a filter

Add an **interactive** component — a dropdown, a slider, or a search box bound to
one of your columns. Now, changing the filter updates the chart. This is the
moment Depictio stops being a static report and becomes something you *explore*.

Add a second chart if you like; the same filter drives both.

## 🔗 Step 6 — Share it

Your dashboard has a URL. Share it with a collaborator or your PI, and they open
the same interactive view you're looking at — no notebook, no environment to set
up, no re-running anything. What they can see and do is governed by Depictio's
permissions, so you stay in control.

## ➡️ Where to go next

In fifteen minutes you went from a CSV to a shareable, interactive dashboard.
From here:

- **Connect multiple data collections** so components react to each other.
- **Explore the omics visualisation catalog** — volcano, heatmap, UMAP, Manhattan.
- **Read *Project Types*** to understand basic vs advanced projects for pipeline
  outputs.

Now that you've built your first dashboard, everything else is just more of the
same idea — bring data, bind a component, share the link. 🎉
