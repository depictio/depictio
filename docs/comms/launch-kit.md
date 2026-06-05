# Depictio launch & visibility kit

Copy-paste-ready content + the strategy behind it, for promoting Depictio and
recruiting both **users** (run nf-core → get dashboards) and **contributors**
(extend the modules catalog). Built around the modules-catalog announcement.

---

## 1. Strategy in one screen

### Positioning (the one-liner)

> **Depictio turns bioinformatics workflow outputs into interactive dashboards —
> open-source, self-hostable, and community-extensible. Think MultiQC, but for
> everything *past* QC.**

That MultiQC analogy is your most powerful asset with the nf-core crowd: it
instantly conveys *what* and *why*, and it's accurate (search-pattern recognition
+ extensible per-tool modules, applied to analysis viz instead of QC metrics).

### Two audiences, two messages

| | **Users** | **Contributors** |
|---|---|---|
| Who | Bioinformaticians, core-facility staff, PIs running nf-core | nf-core module authors, tool devs, viz-minded contributors |
| Pain | "Pipeline's done — now I hand-build a Shiny app or pay for SaaS" | "My tool's output deserves better than a static PNG" |
| Hook | Guided mode: point CLI at a run → starter dashboard | Add a tool = one YAML file, no Python, CI-validated |
| CTA | Try in Codespaces / read docs | `depictio catalog import-meta` → PR |

Don't blur them. Each post should clearly serve one. Alternate across the series.

### Channels & cadence

- **LinkedIn** — the visibility engine. Aim for **1 post / week** in a coherent
  arc (the 6-post series below). Tue–Thu mornings (CET) land best for science/eng
  audiences. Always lead with a hook line + one visual (GIF > screenshot > text).
- **nf-core Slack** — the *contributor* funnel. High-trust, low-tolerance for
  marketing. Post sparingly, humbly, with substance. Pick the right channel
  (`#general` for the intro, a viz/tooling channel for the catalog deep-dive).
  Consider proposing an nf-core **bytesize** talk — that's the highest-leverage
  single move you can make in this community.
- **Docs blog** (`docs/blog/modules-catalog.md`) — the canonical, linkable
  artefact every post points back to. Owned media, no algorithm.
- **Secondary**: Bluesky/Mastodon (bioinformatics has migrated heavily there),
  the nf-core Slack `#announcements` only if invited, and a short Show-HN-style
  post if you want a traffic spike.

### Mechanics that compound

- **One link, always**: the docs. Everything funnels there.
- **Build in public**: post the catalog coverage count as it grows ("we now map
  N tools across M pipelines"). A visible, climbing number recruits contributors.
- **Make contribution legible**: pin a "good first module" issue list. People
  contribute when the next step is obvious.
- **Show, don't tell**: every viz post needs a real GIF of the interaction
  (volcano threshold drag, click-gene-recolour-embedding). The cross-component
  coordination is the wow moment — static images undersell it.
- **Hashtags (LinkedIn, 3–5 max)**: #bioinformatics #nfcore #opensource
  #datavisualization #computationalbiology
- **Tag thoughtfully**: nf-core, relevant tool authors, your institute. Don't
  spray.

### Light metrics to watch

Docs uniques · GitHub stars/forks · Codespaces opens · catalog PRs from
non-core contributors · bytesize talk accepted (y/n). The last two are the real
signal that the contributor flywheel is turning.

---

## 2. LinkedIn series (6-post arc)

Each is ready to post. `[VISUAL]` notes what to attach. Keep the first line as a
standalone hook — LinkedIn truncates after ~2 lines.

### Post 1 — The problem & the vision (audience: users)

> Your nf-core pipeline turns green. MultiQC gives you a gorgeous QC report.
> And then… everything *past* QC lands as static CSVs and PNGs. 📉
>
> The DESeq2 table. The taxonomy profile. The differential-abundance results —
> the actual biology — sits there, un-explorable, until someone spends a week
> hand-building a Shiny app (and maintaining it forever).
>
> That's the gap I've been building Depictio to close.
>
> Depictio is an open-source platform that turns bioinformatics workflow outputs
> into **interactive dashboards**. Point it at your pipeline results; it serves
> dashboards you can filter, brush, and drill into. Self-hostable (Docker /
> Kubernetes), built on FastAPI + Dash + Polars + Delta Lake. No SaaS lock-in.
>
> Think MultiQC — but for everything that comes *after* QC.
>
> Over the next few weeks I'll share how it works, starting with the piece I'm
> most excited about: a community-extensible catalog that maps each tool's output
> to the right interactive visualisation.
>
> ⭐ Repo & docs in comments. Curious what *your* "post-QC wall" looks like —
> tell me below.
>
> #bioinformatics #nfcore #opensource #datavisualization #computationalbiology
>
> *[VISUAL: split-screen GIF — static PNG/CSV on the left, the same data live and
> interactive in Depictio on the right.]*

### Post 2 — The modules catalog reveal (audience: both)

> How do you get from "an nf-core module produced a file" to "here's the right
> interactive chart for it"? 🧩
>
> In Depictio, it's one composable building block:
>
> **module output → find → (recipe?) → renders_as (viz)**
>
> • **find** — recognise the file in a run (like MultiQC's search patterns)
> • **recipe** — *optionally* reshape it when the raw output isn't chart-ready
> • **renders_as** — bind it to a visualisation, columns pre-mapped to roles
>
> The key design call: the catalog is keyed by **module, not pipeline**. A
> pipeline is just a list of modules that picks from the catalog. So it works for
> a brand-new nf-core pipeline *and* for your custom Nextflow that reuses nf-core
> modules — same recognition either way.
>
> Volcano, heatmap, UMAP, stacked taxonomy, OncoPrint, Manhattan… each tool
> output finds its home.
>
> Full write-up in comments 👇
>
> #bioinformatics #nfcore #opensource #datavisualization
>
> *[VISUAL: a clean diagram of the module output → find → recipe → renders_as
> pipeline, with a real example (e.g. DESeq2 results → volcano).]*

### Post 3 — Viz spotlight: cross-component coordination (audience: users)

> A volcano plot is nice. A volcano plot wired to the rest of your dashboard is a
> different thing entirely. 🌋
>
> In Depictio, advanced visualisations aren't static images — they're panels that
> talk to each other:
>
> • Drag a fold-change / FDR threshold → labels and selection update live
> • Click a gene in the volcano → the UMAP embedding recolours by that gene
> • Lasso cells in the embedding → publish the selection back as a dashboard
>   filter → every panel re-fetches on that subset
>
> This cross-component coordination is the part that's almost impossible to
> convey in a screenshot — so here's it in motion 👇
>
> Built on Plotly, with heavy compute (UMAP/PCA/clustering) offloaded to a worker
> so the browser stays snappy.
>
> #bioinformatics #datavisualization #singlecell #opensource
>
> *[VISUAL: the money GIF — click gene in volcano → embedding recolours → lasso →
> filter propagates. This is your single best recruiting asset.]*

### Post 4 — Contributor call: add a tool in one YAML (audience: contributors)

> Maintain an nf-core module? Have a tool whose output deserves better than a
> static PNG? This one's for you. 🛠️
>
> Extending Depictio's visualisation catalog does **not** mean learning the
> codebase internals. It's a YAML file:
>
> ```
> depictio catalog import-meta path/to/meta.yml -o catalog/<tool>.yaml
> # fill in: find, file_schema, recipe (if needed), feeds_viz, role_mapping
> depictio catalog validate     # CI-friendly, fails fast
> # add a one-line test → open a PR
> ```
>
> It scaffolds straight from your module's existing `meta.yml` (offline — works on
> locked-down networks). Identity is anchored on nf-core, bio.tools and EDAM, all
> of which `meta.yml` already publishes.
>
> The barrier is "write a YAML and a one-line test", not "understand the engine."
>
> I'm collecting "good first module" candidates — if there's a tool you'd love to
> see rendered interactively, drop it in the comments and I'll help you map it.
>
> #nfcore #bioinformatics #opensource #contributing
>
> *[VISUAL: a short carousel — slide 1 the 4-step workflow, slide 2 a real filled
> YAML, slide 3 the resulting chart.]*

### Post 5 — The hard case: many-mode tools (audience: contributors / credibility)

> Most "tool → chart" mappings are easy. Then there's QIIME 2. 🧬
>
> One tool, dozens of differently-shaped outputs depending on the subcommand —
> taxonomy bars, diversity, rarefaction, ANCOM-BC differentials, phylogeny. A flat
> "columns → viz" table would drown in near-duplicate fingerprints.
>
> Depictio's catalog models heavyweight tools the way the ecosystem already does:
> **one module, many outputs, each tagged with its mode** — exactly how nf-core
> models output channels and bio.tools models EDAM operations.
>
> Adding QIIME 2's next mode is adding one file to a folder, not touching code.
> The same shape scales to bcftools, samtools, seqkit — any multi-subcommand tool.
>
> Designing for the hard case from day one is how you avoid a catalog that rots.
>
> #bioinformatics #nfcore #metagenomics #opensource
>
> *[VISUAL: the qiime2/ folder layout (one file per output) next to the dashboard
> assembled from those outputs.]*

### Post 6 — Ecosystem & invitation (audience: both)

> A quick recap of what Depictio is, now that the picture's complete. 🧭
>
> Open-source, self-hostable dashboards for bioinformatics workflow outputs —
> everything past QC, made interactive:
>
> ✅ Guided mode: point the CLI at an nf-core run → a starter dashboard
> ✅ Free mode: map columns to viz roles by hand, with dtype-aware suggestions
> ✅ A community catalog mapping tool outputs → volcano / heatmap / UMAP / taxonomy
> ✅ Pipeline-agnostic: official nf-core pipelines *and* your custom workflows
> ✅ FastAPI + Dash + Polars + Delta Lake; Docker or Kubernetes; no lock-in
>
> Two ways to get involved:
> → **Use it**: try it in GitHub Codespaces in one click (link in comments)
> → **Extend it**: contribute a tool mapping in a single YAML file
>
> I'd love feedback from anyone living the "pipeline's done, now what?" problem.
> Stars, issues, and especially first-time catalog PRs all very welcome. 🙏
>
> #bioinformatics #nfcore #opensource #datavisualization #computationalbiology
>
> *[VISUAL: a polished dashboard hero shot, or a 20s tour video.]*

---

## 3. nf-core Slack posts

nf-core Slack is high-trust and allergic to marketing. Rules of engagement:
lead with substance, be humble, make it about *their* workflow, never hard-sell,
and reply to every question. Post in the right channel, once — don't cross-post.

### Post A — Introduction (channel: `#general` or `#tools`)

> 👋 Hi all — I'm Thomas, building **Depictio**, an open-source, self-hostable
> platform that turns pipeline outputs into interactive dashboards. The short
> pitch: *MultiQC, but for everything past QC* — volcano plots, heatmaps,
> UMAP/PCoA embeddings, taxonomy bars, OncoPrint, etc., all interactive and
> cross-linked.
>
> It's deliberately built around the nf-core ecosystem: recognition is keyed by
> **module** (not pipeline), so it works for any nf-core pipeline *and* for custom
> workflows that reuse nf-core modules. A `depictio-cli` guided mode can point at
> a run directory and assemble a starter dashboard.
>
> Repo: https://github.com/depictio/depictio · Docs:
> https://depictio.github.io/depictio-docs/latest/ · one-click try via Codespaces
> in the README.
>
> Very much in active development and I'd genuinely value feedback from people who
> live the "pipeline finished, now I hand-build a viz app" problem. Happy to
> answer anything here. 🙏

### Post B — Catalog / contributor call (channel: a viz, modules, or tooling channel)

> Following up on Depictio with something concretely contributable. We're building
> a **modules catalog** that maps a tool's output → the right interactive viz, on
> this atom:
>
> `module output → find → (recipe?) → renders_as (viz)`
>
> `find` is essentially MultiQC-style search patterns; `renders_as` binds the
> output's columns to a viz's roles (e.g. DESeq2 → volcano). It's keyed by module
> and indexed the way you already model things — identity stored as nf-core /
> bio.tools / EDAM, all of which your `meta.yml` already publishes per channel.
>
> The contribution path is intentionally a *YAML file, not a Python PR*:
>
> ```
> depictio catalog import-meta path/to/meta.yml -o catalog/<tool>.yaml
> depictio catalog validate
> ```
>
> `import-meta` scaffolds straight from an existing module `meta.yml` (offline).
> Multi-mode tools (QIIME 2 is the stress test) are modelled as one module with
> many outputs, each tagged by mode — so heavyweight tools don't explode the
> registry.
>
> If you maintain a module and would like its output to render as a proper
> interactive chart, I'd love to help you map it — reply here or open an issue.
> Design write-up: https://depictio.github.io/depictio-docs/latest/ (blog →
> modules catalog).

### Post C — bytesize talk pitch (DM to nf-core outreach / `#bytesize`)

> Hi! Would a Depictio walkthrough fit a future **nf-core/bytesize**? It's an
> open-source tool for turning pipeline outputs into interactive dashboards
> ("MultiQC for everything past QC"), built around nf-core modules — guided
> dashboard assembly from a run, plus a community catalog that maps module outputs
> to advanced visualisations via a YAML contribution path. I'd cover the design,
> a live demo, and how people can contribute a tool mapping. ~15–20 min + Q&A.
> Happy to fit your schedule.

---

## 4. Reusable snippets

**GitHub repo description (≤120 chars):**
> Interactive dashboards from bioinformatics workflow outputs. MultiQC, but for
> everything past QC. Self-hostable, extensible.

**One-liner for talks/bios:**
> Depictio — open-source, self-hostable interactive dashboards for nf-core and
> bioinformatics workflow outputs.

**Bluesky / Mastodon (short):**
> Pipeline's green, MultiQC's done… and the actual biology is still a static CSV.
> Depictio turns bioinformatics workflow outputs into interactive dashboards —
> open-source, self-hostable, MultiQC-but-past-QC. Volcano, heatmap, UMAP,
> taxonomy, all cross-linked. 🧬 [link] #bioinformatics #nfcore

---

## 5. Suggested 6-week schedule

| Week | LinkedIn | nf-core Slack | Other |
|---|---|---|---|
| 1 | Post 1 (problem/vision) | — | Publish docs blog post |
| 2 | Post 2 (catalog reveal) | Post A (intro) | — |
| 3 | Post 3 (viz coordination GIF) | — | Bluesky/Mastodon cross-post |
| 4 | Post 4 (contributor call) | Post B (catalog) + pin "good first module" issues | — |
| 5 | Post 5 (many-mode tools) | — | DM Post C (bytesize pitch) |
| 6 | Post 6 (recap/invite) | answer threads, share coverage count | Consider Show HN |

Adjust pace to your bandwidth — consistency beats volume. The two highest-leverage
moves are the **cross-component-coordination GIF** (Post 3) and landing a
**bytesize talk** (Post C).
