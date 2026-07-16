<!--
DRAFT NOTE (remove before publishing):
- Publishes to the depictio-docs blog. Move this file there, or PR it across.
- `authors:` slug must exist in depictio-docs `.authors.yml` (existing posts use Thomas Weber).
- Version framing per user decision: celebrate "1.0" as the milestone (repo tag is currently 1.1.4).
- IMAGES: screenshots sourced from the live depictio-docs site (v1.2.0), referenced here as ABSOLUTE
  URLs so the draft previews on GitHub. When integrating into depictio-docs, switch to repo-relative
  paths (e.g. ../../images/guides/advanced-visualizations/volcano_light.webp) so they track the version.
  LOGO: uses this repo's docs/images/logo_hd.png (../images/logo_hd.png) so it renders on GitHub;
  in depictio-docs repoint to that repo's images/logo/logo_hd.svg (or logo_hd.png).
  No videos exist on the docs (screenshots/webp only); if you have screencasts, add them.
  The advanced-viz images come as light/dark pairs (volcano_light.webp / volcano_dark.webp). Draft
  uses the light one only (GitHub renders both variants, looking like a duplicate). In mkdocs you can
  use the theme-aware pattern: img#only-light + img#only-dark to switch with the site theme.
- NUMBERS: GitHub stars (47) and forks (4) are REAL as of 2026-07 (GitHub API). Deployment count and
  container-image pulls are PLACEHOLDERS [N] - GHCR pull counts are not exposed by any API, fill by hand.
  Performance benchmark numbers are pending (author running them); the post promises rather than states.
- Real-time dashboards intentionally NOT mentioned.
- nf-core pipelines / workflow templates / tools catalog intentionally NOT covered (separate article).
- Features referenced are all shipped: React migration #770, performance work (Polars-native figures,
  Delta schema cache/column projection, render offload, MultiQC caching), advanced-viz catalog + live
  Celery clustering, Helm/Percona HA.
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

# 🎉 Depictio 1.0: from prototype to production

<p align="center"><img src="../images/logo_hd.png" alt="Depictio" width="280"></p>

When Depictio went live last year, I'll be honest, it was still a prototype. A
promising one, running real dashboards for real people, but a prototype all the
same, with the rough edges in performance and stability that come with that.
Releasing 1.0 is me saying something different this time: Depictio is now a
stable, production-ready product. This post is about what that actually means,
and about everything that went into getting here.

![A Depictio dashboard in the viewer, with interactive filters](https://depictio.github.io/depictio-docs/v1.2.0/images/v0.12/react-beta/page_dashboard_viewer.png)

<!-- more -->

## ✅ What 1.0 really means

A version number is a kind of promise. With 1.0, the promise is that the core has
stopped moving: the data model, the API, and the viewer are stable enough that
you can deploy Depictio for a lab, a core facility, or a consortium and build on
top of it without the ground shifting under you.

That is the real change here. Everything before was "you can try this." 1.0 is
"you can rely on this." Depictio is no longer an experiment I'm asking people to
test, it's a product I'm asking people to depend on, and that shift shaped every
decision in this release.

## ⚡ A serious step forward in performance

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

I'm currently running proper performance benchmarks so I can put concrete numbers
next to those claims instead of adjectives. Those are coming shortly, and I'll
share them in a follow-up. The short version for now: dashboards that hold up
when the data gets serious, not just when it's a few thousand rows.

## ⚛️ The front end is now React, same look, cleaner architecture

The biggest structural change since launch is one you feel more than you see. The
entire front end was rebuilt in React and TypeScript, and the old Dash codebase
is gone. Importantly, the interface looks the same: Dash is itself built on top
of React, and Depictio's UI was made of Dash Mantine Components, so moving to
React with Mantine directly let us keep the exact same visual identity while
gaining full control over it.

The bigger win is under the hood. Depictio used to run two servers side by side,
FastAPI for the API and a Flask server under Dash for the interface. Now there's
a single FastAPI backend with a cleanly decoupled React frontend talking to it.
One server instead of two, a real separation between front and back, and as a
nice bonus the automatic dashboard screenshots came out roughly twice as fast on
the new stack.

![The Depictio dashboards landing page on the new React frontend](https://depictio.github.io/depictio-docs/v1.2.0/images/v0.12/react-beta/page_dashboards.png)

## 🧬 Visualisations built for biology

Depictio now ships a catalog of advanced visualisations aimed squarely at omics
work: volcano plots, clustered heatmaps, embeddings (PCA, UMAP, t-SNE, PCoA),
Manhattan plots, oncoplots, taxonomy bars, and more. Each one is a self-contained
panel that comes with its own controls, so a volcano arrives with movable
thresholds and a Manhattan knows how to order chromosomes.

![Volcano plot in Depictio](https://depictio.github.io/depictio-docs/v1.2.0/images/guides/advanced-visualizations/volcano_light.webp)

*The volcano panel is one of eighteen advanced visualisations in the catalog. [Browse the full gallery in the docs.](https://depictio.github.io/depictio-docs/v1.2.0/images/guides/advanced-visualizations/)*

The heavier steps, dimensionality reduction and clustering, run in the background
with caching, so you can compute an embedding and then explore it without the
page locking up. There's a lot more to say about how these plots connect to
pipelines and to a community-extensible tool catalog, but that deserves its own
post, so I'll come back to it.

## 🚀 Ready to deploy for real

Production-readiness is also about the parts nobody tweets about. Depictio's
services are built to scale independently: an API replica runs with four FastAPI
workers to handle concurrent requests, a separate pool of Celery workers absorbs
the heavy jobs (ingestion, clustering, rendering) so they never block the
interface, and the stateless viewer and API can be scaled out to several replicas
under load. On Kubernetes, MongoDB can run as a three-node replica set for high
availability via the Percona operator. Splitting the work this way is exactly
what keeps the UI responsive while big data is being crunched behind it.

There's permission-based authentication and dedicated ingress paths for the
backend and object storage, and dashboards now carry an ingestion report and a
health banner, so when something goes wrong during a scan you can actually see it
instead of guessing. These are the boring, essential things that separate a demo
from something a department can run without babysitting.

And it's still self-hosted and open-source, the way it started. Your data stays
on your infrastructure, there's no vendor account and no per-seat bill, and you
can read every line if you want to.

## 📊 Where Depictio is today

1.0 is also a good moment to look up from the code for a second. Depictio has been
in the making for about three years, it's MIT-licensed, and as of this release it
has 47 stars and 4 forks on GitHub. Small numbers, honest ones, and growing.

Beyond GitHub, please fill in the real figures before publishing:

- deployed across **[N]** labs and core facilities, including several groups at
  EMBL,
- container images pulled more than **[N]** times.

None of that happened by accident, and all of it is why 1.0 felt worth doing
properly.

## 🗺️ What's next

A stable foundation is the point, not the finish line, and the next post is
already taking shape. It's about the two pieces I deliberately kept out of this
one: Depictio's dashboard **templates** and its bioinformatics **tools catalog**.

A **template** is a ready-made dashboard for a known pipeline. Instead of
rebuilding a dashboard from scratch every time, you pick the template that
matches your pipeline, point Depictio at your results, and it assembles the
dashboard for you. Run the same pipeline next week on new samples, and it's the
same template with new data: a populated, interactive dashboard in minutes.

The **tools catalog** is the library that makes templates possible. For each
bioinformatics tool, it records what the tool's output looks like and which
visualisation renders it best, so a differential-expression table knows it should
become a volcano plot, and a taxonomy table knows it should become a stacked bar.
A template is really just an assembly of catalog entries. And the catalog is
built to be community-extensible: adding a new tool is a small config
contribution, not a code change, which is how the coverage grows beyond what I
could ever map on my own.

Put together, that's how Depictio goes from "a dashboard builder" to "the
dashboard your pipeline should have shipped with." That's the next story, along
with the performance benchmarks I promised above. More soon.

## 🚀 Try it

- **Live demo:** explore the pre-loaded datasets, or upload your own.
- **Docs:** start with "Your first dashboard in 15 minutes."
- **GitHub:** star the repo, open an issue, tell me what breaks.

A year ago Depictio went live as a prototype. Today it's 1.0, stable, faster, and
ready to be relied on. Thank you to everyone who tested it, filed issues, and
pushed me to get it here.
