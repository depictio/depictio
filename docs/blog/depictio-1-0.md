<!--
DRAFT NOTE (remove before publishing):
- Publishes to the depictio-docs blog. Move this file there, or PR it across.
- `authors:` slug must exist in depictio-docs `.authors.yml` (existing posts use Thomas Weber).
- Version framing per user decision: celebrate "1.0" as the milestone (repo tag is currently 1.1.4).
- ACTION REQUIRED: the "Where Depictio is today" section has PLACEHOLDER numbers in [square brackets].
  Fill in real figures (GitHub stars, Docker/GHCR pulls, deployment count, contributors) before publishing.
- Real-time dashboards intentionally NOT mentioned.
- Features referenced are all in the shipped changelog: React migration #770, performance work
  (Polars-native figures, Delta schema cache/column projection, render offload, MultiQC caching),
  advanced-viz catalog + live Celery clustering, nf-core templates, DC linking, Helm/Percona HA.
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

# Depictio 1.0: from prototype to production

When Depictio went live last year, I'll be honest, it was still a prototype. A
promising one, running real dashboards for real people, but a prototype all the
same. Releasing 1.0 is me saying something different this time: Depictio is now a
stable, production-ready product. This post is about what that actually means,
and about everything that went into getting here.

<!-- more -->

## What 1.0 really means

A version number is a kind of promise, and 1.0 is the one that matters most. It
says the core has settled: the data model, the API, and the viewer are stable
enough that you can deploy Depictio for a lab, a core facility, or a consortium
and build on top of it without expecting the ground to move under you.

That is the real change here. Everything before was "you can try this." 1.0 is
"you can rely on this." Depictio is no longer an experiment I'm asking people to
test, it's a product I'm asking people to depend on, and that shift shaped every
decision in this release.

## A serious step forward in performance

This is the part I'm most proud of, and it's the least visible in a screenshot.
A lot of the past year went into making Depictio fast on real, large data
instead of tidy little demo files.

Figures and cards now read straight from your Delta tables and pull only the
columns they actually need, backed by a schema cache, so a chart doesn't drag the
whole table across just to draw a few series. The figure engine is Polars-native
now, with downsampling and Arrow for moving data around efficiently. Heavy
rendering is pushed off to background workers with higher concurrency and gzip on
the wire, which keeps the interface responsive while the expensive work happens
somewhere else. MultiQC reports, which can get large, get filter-aware caching
and prewarming so they don't recompute from scratch every time you touch a
filter.

We even wrote up a gigabyte-scale dataframe performance audit to keep ourselves
honest about where the limits are. The upshot is simple: dashboards that hold up
when the data gets serious, not just when it's a few thousand rows.

## The front end is now React

The biggest structural change since launch is one you feel more than you see. The
entire front end was rebuilt in React and TypeScript, and the old Dash codebase
is gone.

Charts still render with Plotly, what changed is everything around them. React
gives Depictio a real component model and much tighter control over interactivity
and state, and that foundation is what made the advanced visualisations and the
data linking below possible in the first place. As a nice bonus, even the
automatic dashboard screenshots came out roughly twice as fast on the new stack.

## Visualisations built for biology

Depictio now ships a catalog of advanced visualisations aimed squarely at omics
work: volcano plots, clustered heatmaps, embeddings (PCA, UMAP, t-SNE, PCoA),
Manhattan plots, oncoplots, taxonomy bars, and more. Each one is a self-contained
panel that comes with its own controls, so a volcano arrives with movable
thresholds and a Manhattan knows how to order chromosomes.

The heavier steps, dimensionality reduction and clustering, run in the background
with caching, so you can compute an embedding and then explore it without the
page locking up. Underneath all of this there's a module-granular catalog that
maps a bioinformatics tool's output to the visualisation that suits it, anchored
on nf-core, bio.tools, and EDAM. That catalog is the seed of something I care a
lot about: a community-extensible library where adding a tool is a config file,
not a code change.

## Made for nf-core pipelines

If you run nf-core, a good part of this release is pointed at you. Depictio ships
templates for pipelines like viralrecon and ampliseq that adapt to how the
pipeline was actually run, including awkward things like option variability and
alternate routes, so the dashboard reflects your run rather than an idealised
one. MultiQC reports load straight into a dashboard, and you can create and link
data collections directly from the UI.

The goal behind all of it is unglamorous and, I think, exactly right: your
pipeline finishes, and you get a real dashboard, not a folder of files nobody
opens again.

## Ready to deploy for real

Production-readiness is also about the parts nobody tweets about. On Kubernetes,
the Helm chart moved MongoDB high-availability onto the Percona operator, there's
permission-based authentication, and there are dedicated ingress paths for the
backend and object storage. Dashboards now carry an ingestion report and a health
banner, so when something goes wrong during a scan you can actually see it instead
of guessing. These are the boring, essential things that separate a demo from
something a department can run without babysitting.

And it's still self-hosted and open-source, the way it started. Your data stays
on your infrastructure, there's no vendor account and no per-seat bill, and you
can read every line if you want to.

## Where Depictio is today

1.0 is also a good moment to look up from the code for a second. A few numbers,
please treat these as a snapshot to be filled in with the real figures at
publish time:

- deployed across **[N]** labs and core facilities, including several groups at
  EMBL,
- container images pulled more than **[N]** times,
- **[N]** stars and **[N]** contributors on GitHub.

None of that happened by accident, and all of it is why 1.0 felt worth doing
properly.

## What's next

A stable foundation is the point, not the finish line. Next up: deeper templates
for common nf-core pipelines, guided dashboard assembly straight from a run
directory, and opening up that tool-to-visualisation catalog so the community can
extend it.

## Try it

- **Live demo:** explore the pre-loaded datasets, or upload your own.
- **Docs:** start with "Your first dashboard in 15 minutes."
- **GitHub:** star the repo, open an issue, tell me what breaks.

A year ago Depictio went live as a prototype. Today it's 1.0, stable, faster, and
ready to be relied on. Thank you to everyone who tested it, filed issues, and
pushed me to get it here.
