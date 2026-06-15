# Depictio launch & visibility kit

Copy-paste-ready content + the strategy behind it, for promoting Depictio around
the **v1.0.0** release and recruiting both **users** (run a pipeline → get a
dashboard) and **contributors** (extend the catalog / build templates). Tone is
deliberately broad and accessible — written to reach PIs, core-facility leads and
students, not only framework engineers.

---

## 1. Strategy in one screen

### Positioning (the one-liner)

> **Depictio turns your bioinformatics results into interactive dashboards —
> free, open-source, and self-hosted. No front-end code, no SaaS, no data leaving
> your servers.**

For the nf-core crowd, the sharper framing *"MultiQC, but for everything past
QC"* still works well — keep it for technical channels (Slack), soften it for the
broad LinkedIn feed.

### Two audiences, two messages

| | **Users** | **Contributors** |
|---|---|---|
| Who | Bioinformaticians, core-facility staff, PIs running pipelines | nf-core module authors, tool devs, viz-minded contributors |
| Pain | "Pipeline's done — now I hand-build a Shiny app or pay for SaaS" | "My tool's output deserves better than a static PNG" |
| Hook | v1.0.0 stable · templates · pre-built omics viz | Add a tool / template = one config file, CI-validated |
| CTA | Try in Codespaces / read docs | Contribute a template or catalog entry → PR |

Don't blur them. Each post should clearly serve one. Alternate across the series.

### Channels & cadence

- **LinkedIn** — the visibility engine. ~1 post / week in the arc below. Tue–Thu
  mornings (CET) land best. Lead with a hook line + one visual (GIF > screenshot
  > text).
- **nf-core Slack** — the *contributor* funnel. High-trust, low-tolerance for
  marketing. Post sparingly, humbly, with substance. The highest-leverage single
  move is proposing an nf-core **bytesize** talk.
- **Docs blog** — the canonical, linkable artefact every post points back to.
- **Secondary**: Bluesky/Mastodon (bioinformatics is active there), a Show-HN-style
  post for a traffic spike.

### Mechanics that compound

- **One link, always**: the docs. Everything funnels there.
- **Show, don't tell**: every feature post needs a real GIF. The before/after and
  the cross-component interactivity are the wow moments — static images undersell
  them.
- **End with a question**: each post below closes with a prompt ("which plot is
  *the* plot in your field?") to drive comments and reach.
- **Hashtags (3–5 max)**: #bioinformatics #nfcore #opensource #datavisualization
  #computationalbiology
- **Tag thoughtfully**: nf-core, relevant tool authors, your institute. Don't spray.

### Light metrics to watch

Docs uniques · GitHub stars/forks · Codespaces opens · template/catalog PRs from
non-core contributors · bytesize talk accepted (y/n).

---

## 2. LinkedIn series (v1.0.0 arc)

Five ready-to-post entries: the launch, then four feature/angle posts. `[VISUAL]`
notes what to attach. Keep the first line as a standalone hook — LinkedIn
truncates after ~2 lines.

### Post 1 — Depictio hits v1.0.0 🎉 (the launch)

> **Depictio is 1.0.0.** After years of building in the open, it's officially a
> stable major release. 🚀
>
> Depictio is a free, open-source platform that turns your bioinformatics results
> into **interactive dashboards** — no front-end code, no SaaS subscription, no
> data leaving your servers.
>
> You run your pipeline. Depictio gives your collaborators a dashboard they can
> actually click through: filter samples, zoom into a gene, explore the biology —
> instead of squinting at a folder full of CSVs and static PNGs.
>
> What "1.0.0" means:
> ✅ Stable, production-ready core — deploy it with Docker or Kubernetes
> ✅ Built on solid open foundations (FastAPI, Plotly/Dash, Polars, Delta Lake)
> ✅ Self-hostable — your data stays yours
> ✅ Ready for real labs, core facilities, and consortia
>
> This is a milestone I'm genuinely proud of — and it's just the foundation. Big
> things coming on top of it (interactive omics visualisations and one-click
> dashboard templates for nf-core pipelines — more soon 👀).
>
> ⭐ Star it, try it, break it, tell me what you think. Links in the comments.
>
> Huge thanks to everyone who tested, filed issues, and pushed me to ship. 🙏
>
> #bioinformatics #opensource #nfcore #datavisualization #computationalbiology
>
> *[VISUAL: a polished dashboard hero shot or a "1.0.0" badge over a short
> dashboard tour clip. This is your reach moment — make the visual count.]*

### Post 2 — The visualisation catalog 🌋 (feature)

> Every omics field has *that one plot*. 🌋
>
> RNA-seq has the volcano. Single-cell has the UMAP. GWAS has the Manhattan.
> Expression studies have the heatmap. You know them the instant you see them.
>
> Depictio ships them as a **catalog of ready-made, interactive visualisations** —
> not static images, but living panels:
>
> 🌋 **Volcano** — drag your fold-change and significance thresholds, search a
> gene, watch it light up
> 🔥 **Heatmap / clustergram** — cluster, rescale, zoom into a block of
> co-expressed genes
> 🔬 **UMAP / embeddings** — colour cells by cluster or by any gene, lasso a
> population
> 📊 **Manhattan** — slide your significance line, jump to a locus
>
> And they're **connected**: click a gene in the volcano and your embedding
> recolours by it. Pick the chart that fits your data; Depictio wires up the
> interactivity.
>
> Which plot is *the* plot in your field? 👇
>
> #bioinformatics #datavisualization #singlecell #genomics #opensource
>
> *[VISUAL: a 4-panel grid (volcano / heatmap / UMAP / Manhattan), ideally one
> short GIF showing the volcano-click → embedding-recolour link.]*

### Post 3 — The template system 📦 (feature)

> What if a standardised pipeline came with a standardised dashboard? 📦
>
> If you run nf-core pipelines, your outputs already follow a known structure. So
> why rebuild a dashboard from scratch every single time?
>
> Depictio's **template system** lets you:
> 1. Pick a pre-defined dashboard template for your pipeline
> 2. Point it at your run's results
> 3. Get a populated, interactive dashboard in minutes — no manual wiring
>
> Run the same pipeline next week on new samples? Same template, new data, instant
> dashboard. Reproducible by design, shareable with your PI or collaborators by
> link.
>
> Templates are reusable and extensible — build one for your lab's standard
> analysis once, and everyone benefits. We're growing a library of them for common
> nf-core pipelines, and you can contribute your own.
>
> Standardised pipeline in → standardised dashboard out. 📈
>
> Which nf-core pipeline should get a template first? Tell me 👇
>
> #nfcore #bioinformatics #reproducibility #opensource #datavisualization
>
> *[VISUAL: a 3-step GIF — choose template → point at results → dashboard
> populates. Show the "minutes" speed.]*

### Post 4 — Folder-of-CSVs → dashboard 📁 (angle)

> Be honest: how many analysis results are buried in a `results/` folder nobody's
> opened since the pipeline finished? 📁
>
> That's the quiet tragedy of bioinformatics. Weeks of compute, brilliant biology
> in there somewhere — delivered as a pile of CSVs and static PNGs that only the
> person who made them can read.
>
> Depictio turns that folder into something people actually use:
>
> 📁 Before → a directory of `deseq2_results.csv`, `counts.tsv`, twelve `.png` files
> 📊 After → one interactive dashboard: filter, search, zoom, explore the biology
>
> No front-end code. No copying numbers into a slide deck. No "can you re-run it
> but colour the other condition?" emails. Your collaborators just open a link and
> dig in themselves.
>
> The results were always there. Depictio makes them explorable.
>
> What's sitting in *your* unopened results folder? 👇
>
> #bioinformatics #datavisualization #opensource #computationalbiology #nfcore
>
> *[VISUAL: literal before/after — a file-browser screenshot of a messy results
> folder on the left, the live dashboard built from it on the right.]*

### Post 5 — Self-hosted / data sovereignty 🔒 (angle)

> The fastest way to turn your data into a dashboard is to upload it to someone
> else's cloud. It's also, for a lot of us, completely off the table. 🔒
>
> Patient genomes. Unpublished results. Consortium data under a DUA. You can't
> just paste that into a SaaS tool and click "share publicly."
>
> Depictio is **self-hosted by design**. You run it on your own infrastructure —
> your laptop, your institute's servers, your cluster, your private cloud. Your
> data never leaves your control. There's no vendor account, no usage tracking, no
> per-seat bill, no "we updated our terms" email.
>
> 🔒 Your data stays on your servers
> 🐳 Deploy with Docker or Kubernetes
> 🆓 Open-source — audit every line if you want to
> 🤝 Share dashboards internally without sharing data externally
>
> Interactive dashboards and data sovereignty shouldn't be a trade-off. With
> Depictio they aren't.
>
> #bioinformatics #datasovereignty #opensource #clinicalgenomics #privacy
>
> *[VISUAL: a simple diagram — data + Depictio inside your institute's walls,
> nothing flowing out to a cloud. Or a clean "your data never leaves your servers"
> text card.]*

### Bench of other angles (draft when you want variety)

- **Share with your PI, not a notebook** — send a link, not a Jupyter file. High
  relatability, reaches wet-lab collaborators and PIs.
- **Build-in-public / founder story** — the road to 1.0.0; builds personal brand
  and trust.
- **One-click try (Codespaces)** — "try it in your browser in 60 seconds, nothing
  to install." Great recurring CTA, lowers the barrier for everyone.
- **Performance on big data** — Polars + Delta Lake handling large cohorts
  smoothly. For power users.
- **Open-source & community** — free forever, extend it yourself. The contributor
  funnel.

---

## 3. nf-core Slack posts

nf-core Slack is high-trust and allergic to marketing. Rules of engagement: lead
with substance, be humble, make it about *their* workflow, never hard-sell, reply
to every question. Post in the right channel, once.

### Post A — Introduction (channel: `#general` or `#tools`)

> 👋 Hi all — I'm Thomas. I just released **Depictio v1.0.0**, an open-source,
> self-hostable platform that turns pipeline outputs into interactive dashboards.
> The short pitch: *MultiQC, but for everything past QC* — volcano plots, heatmaps,
> UMAP embeddings, taxonomy bars, etc., all interactive and cross-linked.
>
> It's built around the nf-core ecosystem: there's a **template system** so a
> standardised pipeline can get a standardised dashboard (pick a template → point
> at your run → populated dashboard), and it works for custom workflows too.
>
> Repo: https://github.com/depictio/depictio · Docs:
> https://depictio.github.io/depictio-docs/latest/ · one-click try via Codespaces
> in the README.
>
> I'd genuinely value feedback from people who live the "pipeline finished, now I
> hand-build a viz app" problem. Happy to answer anything here. 🙏

### Post B — Templates / contributor call (channel: a viz, modules, or tooling channel)

> Following up on Depictio with something concretely contributable. We're building
> a library of **dashboard templates** for nf-core pipelines: a template maps a
> pipeline's known outputs to a ready-made interactive dashboard, so users go from
> a run directory to a populated dashboard in minutes — no manual wiring.
>
> Under the hood it's a catalog mapping each tool's output → the right viz (e.g.
> DESeq2 → volcano), recognised by MultiQC-style search patterns and bound to a
> visualisation's roles. Contribution is a config file, not a Python PR.
>
> If you maintain a pipeline or a module and would like its outputs to render as
> proper interactive charts, I'd love to help you build the template — reply here
> or open an issue. Design write-up in the docs (blog → modules catalog).

### Post C — bytesize talk pitch (DM to nf-core outreach / `#bytesize`)

> Hi! Would a Depictio walkthrough fit a future **nf-core/bytesize**? It's an
> open-source tool (just hit v1.0.0) for turning pipeline outputs into interactive
> dashboards — "MultiQC for everything past QC" — with a template system for
> nf-core pipelines and a catalog of omics visualisations. I'd cover a live demo
> and how people can contribute a template. ~15–20 min + Q&A. Happy to fit your
> schedule.

---

## 4. Reusable snippets

**GitHub repo description (≤120 chars):**
> Interactive dashboards from bioinformatics workflow outputs. Free, open-source,
> self-hosted. No front-end code, no SaaS.

**One-liner for talks/bios:**
> Depictio — open-source, self-hosted interactive dashboards for nf-core and
> bioinformatics workflow outputs.

**Bluesky / Mastodon (short):**
> Pipeline's green, MultiQC's done… and the actual biology is still a static CSV.
> Depictio (now v1.0.0) turns bioinformatics results into interactive dashboards —
> open-source, self-hosted. Volcano, heatmap, UMAP, all cross-linked. 🧬 [link]
> #bioinformatics #nfcore

---

## 5. Suggested 6-week schedule

| Week | LinkedIn | nf-core Slack | Other |
|---|---|---|---|
| 1 | Post 1 (v1.0.0 launch) | Post A (intro) | Publish docs blog post |
| 2 | Post 2 (visualisation catalog) | — | Bluesky/Mastodon cross-post |
| 3 | Post 3 (template system) | Post B (templates) + pin "good first template" issues | — |
| 4 | Post 4 (folder → dashboard) | — | DM Post C (bytesize pitch) |
| 5 | Post 5 (self-hosted / sovereignty) | — | — |
| 6 | a bench angle (PI-share / build-in-public) | answer threads | Consider Show HN |

Adjust pace to your bandwidth — consistency beats volume. The two highest-leverage
moves are a strong **launch visual** (Post 1) and landing a **bytesize talk**
(Post C).
