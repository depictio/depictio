<!--
DRAFT NOTE (remove before publishing):
- Publishes to the depictio-docs blog. Move this file there, or PR it across.
- `authors:` slug must exist in depictio-docs `.authors.yml` (existing posts use Thomas Weber).
- Version framing per user decision: celebrate "1.0" as the milestone (repo tag is currently 1.1.4).
- IMAGES: screenshots sourced from the live depictio-docs site, referenced here as ABSOLUTE
  URLs so the draft previews on GitHub. NOTE the deployed site serves images from a shared,
  UNVERSIONED root (/depictio-docs/images/...); version-prefixed paths like /v1.2.0/images/ all 404.
  When integrating into depictio-docs, switch to repo-relative paths
  (e.g. ../../images/guides/advanced-visualizations/volcano_light.webp), which the build resolves.
  LOGO: uses this repo's docs/images/logo_hd.png (../images/logo_hd.png) so it renders on GitHub;
  in depictio-docs repoint to that repo's images/logo/logo_hd.svg (or logo_hd.png).
  VIDEO: the two performance screencasts are Vimeo embeds (the docs repo commits no video files and
  caps added files at 2 MB). It will not render in GitHub's markdown preview, only in mkdocs.
  The advanced-viz images come as light/dark pairs (volcano_light.webp / volcano_dark.webp). Draft
  uses the light one only (GitHub renders both variants, looking like a duplicate). In mkdocs you can
  use the theme-aware pattern: img#only-light + img#only-dark to switch with the site theme.
- NUMBERS: GitHub stars (47) and forks (4) are REAL as of 2026-07 (GitHub API). Deployment count and
  container-image pulls are PLACEHOLDERS [N] - GHCR pull counts are not exposed by any API, fill by hand.
  Performance numbers come from benchmark/PERF_REPORT_v2.md (single run, 12,019,500 rows, M1 Max /
  Colima, 1 dev API worker). v1's numbers described a different dataset AND a different dashboard -
  do not mix the two. Full report to be published alongside the follow-up post.
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

![A Depictio dashboard in the viewer, with interactive filters](https://depictio.github.io/depictio-docs/images/v0.12/react-beta/page_dashboard_viewer.png)

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
instead of tidy little demo files. So here it is in motion instead.

<div style="max-width: 1200px; margin: 1.5rem auto 2rem auto;">
<div style="padding: 62.19% 0 0 0; position: relative">
  <iframe
    src="https://player.vimeo.com/video/1213726629?badge=0&amp;autopause=0&amp;player_id=0&amp;app_id=58479&amp;autoplay=1&amp;loop=1&amp;muted=1"
    frameborder="0"
    allow="autoplay; fullscreen; picture-in-picture; clipboard-write; encrypted-media; web-share"
    referrerpolicy="strict-origin-when-cross-origin"
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%"
    title="Opening a Depictio dashboard with the full range of components"
  ></iframe>
  </div>
  <p style="text-align: center; margin-top: 0.5rem; font-style: italic; color: #666;">🎬 A dashboard using the full range of components, over three linked collections, captured in the browser.</p>
</div>

Figures and cards now read straight from your Delta tables and pull only the
columns they actually need, backed by a schema cache, so a chart doesn't drag the
whole table across just to draw a few series. The figure engine is Polars-native
now, with downsampling and Arrow for moving data around efficiently. Heavy
rendering is pushed off to background workers with higher concurrency and gzip on
the wire, which keeps the interface responsive while the expensive work happens
somewhere else. MultiQC reports, which can get large, get filter-aware caching
and prewarming so they don't recompute from scratch every time you touch a
filter.

Some numbers, so those aren't just adjectives. On a dataset of **12 million rows**
across three linked collections (1 GB raw, 1.4 GB as Delta), running on a laptop
with a **single API worker in dev mode**, a dashboard puts its first component on
screen in **133 to 270 ms** whether it holds 4 components or 30. A sixteen-component
dashboard (thirty fetches, counting the filter panel) has its first chart up at
**190 ms** and everything drawn in **3.3 s** cold, 3.1 s warm.

Change a filter, and the dashboard starts responding in **around 100 to 200 ms**
and is fully caught up in **1.7 s** at four components, 2.0 s at eight and 4.1 s
at sixteen, across all three collections. Where the filter starts barely matters:
one on the 12-million-row feature matrix costs about the same as one on the
500-row sample sheet (2.0 s against 2.4 s median), because both resolve to a few
hundred sample ids in **25 ms** before any data is touched. Per component, the
median render is **11 ms** for a filter widget, **222 ms** for a table and
**822 ms** for a volcano plot reading several million rows off the feature matrix.

<div style="max-width: 1200px; margin: 1.5rem auto 2rem auto;">
<div style="padding: 62.19% 0 0 0; position: relative">
  <iframe
    src="https://player.vimeo.com/video/1213726492?badge=0&amp;autopause=0&amp;player_id=0&amp;app_id=58479&amp;autoplay=1&amp;loop=1&amp;muted=1"
    frameborder="0"
    allow="autoplay; fullscreen; picture-in-picture; clipboard-write; encrypted-media; web-share"
    referrerpolicy="strict-origin-when-cross-origin"
    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%"
    title="Filtering a MultiQC report embedded in a Depictio dashboard"
  ></iframe>
  </div>
  <p style="text-align: center; margin-top: 0.5rem; font-style: italic; color: #666;">🎬 A MultiQC report inside a dashboard, re-rendering as filters change, with caching and prewarming behind it.</p>
</div>
<script src="https://player.vimeo.com/api/player.js"></script>

The part I like best: box plots, histograms and bar charts are computed as an
aggregation directly over the stored files, so they materialise **zero rows** —
exact, not sampled. That's half the figure renders in the run (114 of 225).
Across the whole run, the largest data frame ever held in memory was **1.6 MB**,
with a median of 439 KB.

Honest caveats: this is a single run on one machine, and a production deployment
runs several API workers rather than the one measured here, so these are on the
pessimistic side. Density still costs, and past a point it stops being a matter of
seconds: on the densest dashboards the four background workers stop clearing the
queue of figure builds, and 44 renders over the run hit the configured 30 s
ceiling and were cut off rather than finishing late, 28 of them in the
thirty-component filter rounds alone. That's where the next round of work goes.
No table, card, advanced visualisation or filter render failed. The full
report, with methodology and the numbers that didn't flatter us, comes with the
follow-up post.

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

![The Depictio dashboards landing page on the new React frontend](https://depictio.github.io/depictio-docs/images/v0.12/react-beta/page_dashboards.png)

## 🧬 Visualisations built for biology

Depictio now ships a catalog of advanced visualisations aimed squarely at omics
work: volcano plots, clustered heatmaps, embeddings (PCA, UMAP, t-SNE, PCoA),
Manhattan plots, oncoplots, taxonomy bars, and more. Each one is a self-contained
panel that comes with its own controls, so a volcano arrives with movable
thresholds and a Manhattan knows how to order chromosomes.

<div style="max-width: 1200px; margin: 1.5rem auto 2rem auto; display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem;">
  <figure style="margin: 0;">
    <img src="https://depictio.github.io/depictio-docs/images/guides/advanced-visualizations/volcano_light.webp" alt="Volcano plot showing effect size against significance, with labelled genes" style="width: 100%; border-radius: 4px;" />
    <figcaption style="text-align: center; font-style: italic; font-size: 0.8em; color: #666; margin-top: 0.4rem;"><strong>Volcano.</strong> Effect size against significance, movable thresholds, top-N gene labels.</figcaption>
  </figure>
  <figure style="margin: 0;">
    <img src="https://depictio.github.io/depictio-docs/images/guides/advanced-visualizations/complex_heatmap_light.webp" alt="Clustered heatmap with row and column dendrograms and a cluster annotation strip" style="width: 100%; border-radius: 4px;" />
    <figcaption style="text-align: center; font-style: italic; font-size: 0.8em; color: #666; margin-top: 0.4rem;"><strong>Clustered heatmap.</strong> Rows and columns clustered server-side, with annotation tracks.</figcaption>
  </figure>
  <figure style="margin: 0;">
    <img src="https://depictio.github.io/depictio-docs/images/guides/advanced-visualizations/oncoplot_light.webp" alt="Oncoplot showing a sample by gene mutation matrix coloured by mutation type" style="width: 100%; border-radius: 4px;" />
    <figcaption style="text-align: center; font-style: italic; font-size: 0.8em; color: #666; margin-top: 0.4rem;"><strong>Oncoplot.</strong> Sample by gene mutation matrix, coloured by mutation type.</figcaption>
  </figure>
  <figure style="margin: 0;">
    <img src="https://depictio.github.io/depictio-docs/images/guides/advanced-visualizations/phylogenetic_light.webp" alt="Phylogenetic tree of bacterial species, tips coloured by phylum" style="width: 100%; border-radius: 4px;" />
    <figcaption style="text-align: center; font-style: italic; font-size: 0.8em; color: #666; margin-top: 0.4rem;"><strong>Phylogenetic tree.</strong> Newick input, five layouts, tip search, clade highlighting and export.</figcaption>
  </figure>
</div>

*Four of the eighteen advanced visualisations in the catalog, each shown with its own controls panel open. [Browse the full gallery in the docs.](https://depictio.github.io/depictio-docs/latest/features/components/#advanced-visualizations)*

Those controls are additional, not a replacement. The interactive filters in the
left panel still apply, narrowing the underlying data across every component on
the dashboard at once. On top of that, each advanced visualisation exposes its
own parameters for how that data gets drawn: normalisation and clustering method
on the heatmap, significance and effect-size cutoffs on the volcano, mutation
sorting on the oncoplot, layout and colouring on the tree. You filter down to the
samples you care about, then tune the plot itself without leaving the dashboard.

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

<p align="center"><img src="https://depictio.github.io/depictio-docs/images/logo/templates_catalog_logo.png" alt="Depictio Templates" width="220"></p>

A **template** is a ready-made dashboard for a known pipeline. Instead of
rebuilding a dashboard from scratch every time, you pick the template that
matches your pipeline, point Depictio at your results, and it assembles the
dashboard for you. Run the same pipeline next week on new samples, and it's the
same template with new data: a populated, interactive dashboard in minutes.

<p align="center"><img src="https://depictio.github.io/depictio-docs/images/logo/tools_catalog_logo.png" alt="Depictio Tools Catalog" width="220"></p>

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
with the full performance report behind the numbers above. More soon.

## 🚀 Try it

- **Live demo:** explore the pre-loaded datasets, or upload your own.
- **Docs:** start with "Your first dashboard in 15 minutes."
- **GitHub:** star the repo, open an issue, tell me what breaks.

A year ago Depictio went live as a prototype. Today it's 1.0, stable, faster, and
ready to be relied on. Thank you to everyone who tested it, filed issues, and
pushed me to get it here.
