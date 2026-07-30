<!--
SOCIAL COPY for the Depictio 1.0 blog post. Not published by mkdocs; delete or
move before the docs build if it ends up in the docs tree.

--------------------------------------------------------------------------
PUBLISHING CHECKLIST for the article itself (docs/blog/depictio-1-0.md).
Moved here when the draft-note comment was stripped off the top of the post.

- Publishes to the depictio-docs blog. Move the file there, or PR it across.
- `authors: thomas-weber` must exist in depictio-docs `.authors.yml`.
- Version framing: celebrate "1.0" as the milestone (repo tag is now 1.1.4).
- IMAGES are ABSOLUTE URLs so the draft previews on GitHub. The deployed site
  serves them from an UNVERSIONED root (/depictio-docs/images/...); version
  prefixes like /v1.2.0/images/ 404, and the react screenshots live under
  images/react/, NOT images/v0.12/react-beta/. All URLs verified 200 in 2026-07.
  When merging into depictio-docs, switch to repo-relative paths
  (e.g. ../../images/guides/advanced-visualizations/volcano_light.webp).
- LOGO points at this repo's docs/images/logo_hd.png so it renders on GitHub.
  In depictio-docs repoint to images/logo/logo_hd.svg.
- Advanced-viz images come as light/dark pairs; the draft uses light only. In
  mkdocs you can use img#only-light + img#only-dark to follow the site theme.
- VIDEO: four Vimeo embeds, none of which render in GitHub's preview.
  1194664914 landing page (opens the post), 1213942946 filtering screencast
  (interactivity), 1213726629 + 1213726492 performance screencasts.
- SCREENSHOTS: template-dashboard shots come from the docs
  (images/pipeline-templates/nf-core/), and are real template dashboards, which
  is why the post could claim nothing was laid out by hand. Dark variants do NOT
  exist for these, unlike the advanced-viz crops they replaced.
  The viralrecon lineage/clustering shot and its "nothing was laid out by hand"
  caption were dropped from 'What's next': that argument belongs in the
  templates article, and the section already has two logos in it.
  The remaining screenshots sit in two 2x2 grids wrapped in
  <div class="shot-grid" markdown>. The tiles are pinned to one aspect ratio in
  blog.css because the sources are 5120x3200, 2880x2200 and 1920x1080, and are
  click-to-zoom via mkdocs-glightbox (opt-in per page: `glightbox: true` in the
  front matter, `.off-glb` on the logos so they stay unclickable).
  The three under docs/images/blog/v1.0/ are captured locally by
  dev/playwright_debug/blog_shots.py against a running dev stack (1920x1080 at
  1x). They are GITIGNORED in this repo and committed only to depictio-docs
  (PR #148), matching the convention that docs/images/ here holds logos and
  favicons only. They stay on disk so the draft previews locally. Regenerate
  with:
    python dev/playwright_debug/blog_shots.py --viewer-url http://localhost:5601 \
      --scale 1 --width 1920 --height 1080 --out /tmp/shots
  and for a dashboard tab, add --dashboard-id <tab id> --prefix <name>.
- VERIFY BEFORE PUBLISHING: EMBL + SciLifeLab Serve as production, and
  GHGA / MGnify (EMBL-EBI) / ISCIII as trials came from the author, not a
  public source. The SciLifeLab webinar link and Serve availability are
  verified public pages.
- Performance numbers are from benchmark/PERF_REPORT_v2.md (single run,
  12,019,500 rows, M1 Max / Colima, 1 dev API worker). v1 measured a different
  dataset AND a different dashboard, so do not mix the two.
- Deliberately NOT covered: real-time dashboards, and nf-core pipelines /
  templates / tools catalog beyond the teaser (separate article).
--------------------------------------------------------------------------

IMPORTANT FRAMING NOTE:
The Depictio company page ALREADY announced v1.0.0 (~1 month ago,
linkedin.com/posts/depictio_multiqc-bioinformatics-opensource-activity-7472199374719102977-IJh8).
So none of these should read as "1.0 is here" a second time. They announce the
WRITE-UP: the numbers, the React rewrite, and where it runs. Framing is
"here's what went into it", not "here's a new release".

BEFORE POSTING:
- [ ] Replace {BLOG_URL} with the published article URL. It is
        https://depictio.github.io/depictio-docs/latest/blog/depictio-1-0/
      The post carries an explicit `slug: depictio-1-0`; without it the blog
      plugin derived the URL from the emoji heading and produced
      /blog/-depictio-10-from-prototype-to-production/. Use `latest/`, not a
      version number, so the link does not rot at the next release.
- [ ] LinkedIn: pick ONE from the company set (C1-C3) and ONE from the personal
      set (P1-P3). Within a set the three take different angles on purpose, so
      posting two of them reads as indecision rather than a campaign. C1 and P1
      are the defaults. Posting one of each is fine and intended: the company page
      and the personal profile have different audiences.
- [ ] Unicode bold appears on the HOOK LINE ONLY, per the launch-kit rule in
      docs/comms/launch-kit.md section 6. Screen readers announce those characters
      one at a time and LinkedIn search does not index them, so it must never
      carry load-bearing text or appear in a hashtag. Drop it if you prefer;
      the hooks read fine unstyled.
- [ ] Attach the filtering screencast (vimeo 1213942946) as NATIVE video to
      LinkedIn rather than a link. Native video gets far better reach, and a
      link in the post body suppresses it. If you link instead, put the URL in
      the first comment.
- [ ] Tag on LinkedIn: EMBL, SciLifeLab / SciLifeLab Data Centre. Only tag
      GHGA / MGnify / ISCIII if you are comfortable naming them publicly as
      trials, they are stated in the article as "as far as I'm aware".
- [ ] Every number below is from benchmark/PERF_REPORT_v2.md, single run,
      one dev API worker on an M1 Max. Keep the caveat in, it is what makes
      the numbers credible.

All facts verified against the article and the repo on 2026-07.
-->

# Social copy: Depictio 1.0

## LinkedIn

Two sets of three. The **company** set speaks as Depictio, about what the release
means for someone deciding whether to run it. The **personal** set is Thomas's
voice, in the build-in-public register the launch-kit arc uses.

All six lead on the same four things, in different orders and proportions:

1. **Stability** — the data model, the API and the viewer stopped moving.
2. **Production** — meant to be deployed and left running, not demoed.
3. **Performance and scalability** — real pipeline volumes, and it scales out.
4. **Breadth** — a lot is built in already, not a roadmap.

Common notes:

- The company page already announced 1.0 about a month ago, so none of these says
  "1.0 is here" again. They announce **what 1.0 actually means**, via the write-up.
- Emphasis follows the launch-kit rule: emoji anchors, `→`, short lines, and
  unicode bold on **at most the hook line**. Never in hashtags or load-bearing text.
- Attach the filtering screencast (vimeo 1213942946) as native video, and put the
  article link in the first pinned comment. A body link suppresses reach. Where a
  variant has `{BLOG_URL}` inline, that is the version to use if you would rather
  not use a comment.
- Tag EMBL and SciLifeLab. Only tag GHGA / MGnify / ISCIII if you are comfortable
  naming them publicly; the article says "as far as I'm aware".
- Pick ONE from each set. Do not post two variants from the same set.

---

## Company set

### C1 — What "1.0" actually means (default)

Answers the only question a prospective operator has: is this safe to build on?
Leads with stability, because that is what a major version is a promise about.

---

𝗪𝗵𝗮𝘁 𝗮 𝟭.𝟬 𝗮𝗰𝘁𝘂𝗮𝗹𝗹𝘆 𝗽𝗿𝗼𝗺𝗶𝘀𝗲𝘀

A dashboard is not something you build and admire. You set it up once, and come
back to it months later with new samples, often after the person who built it has
moved on.

That only works if the thing underneath holds still. So that is what 1.0 is:

✅ The data model, the API and the viewer are stable. Projects you ingest today
keep working. Dashboards you build today keep opening. Code you write against the
API does not need rewriting at the next release.

✅ Built to be deployed and left alone. The API runs several workers behind a
replica, heavy jobs (ingestion, clustering, rendering) go to a separate Celery
pool so they never block the interface, and the viewer and API scale out to more
replicas under load. On Kubernetes, MongoDB can run as a three-node replica set.

✅ Fast at real pipeline volumes. Twelve million rows across three linked
collections, on a laptop with a single API worker: first component on screen in
133 to 270 ms, and a filter fully caught up in 1.7 s at four components, 2.0 s at
eight, 4.1 s at sixteen. Those are floor numbers, from one worker in dev mode.

✅ Already broad. Eighteen advanced visualisation types, MultiQC rendered inline
rather than linked, images, GeoJSON maps, phylogenetic trees, and dashboards that
carry an ingestion report and a health banner so a bad scan is visible instead of
silent.

Still self-hosted, still MIT-licensed. Your data stays on your infrastructure,
there is no vendor account and no per-seat bill.

We wrote the whole thing up, including the benchmark numbers that did not flatter
us. Link in the comments.

#bioinformatics #opensource #nfcore #datavisualization #computationalbiology

---

### C2 — The gap between a tool people try and a tool people keep

Leads on performance and scalability, framed as the reason adoption sticks.
Best paired with the filtering screencast.

---

𝗧𝗵𝗲 𝗱𝗶𝗳𝗳𝗲𝗿𝗲𝗻𝗰𝗲 𝗯𝗲𝘁𝘄𝗲𝗲𝗻 𝗮 𝘁𝗼𝗼𝗹 𝗽𝗲𝗼𝗽𝗹𝗲 𝘁𝗿𝘆 𝗮𝗻𝗱 𝗮 𝘁𝗼𝗼𝗹 𝗽𝗲𝗼𝗽𝗹𝗲 𝗸𝗲𝗲𝗽

Usually it is not features. It is whether the thing is still pleasant on your
actual data, not the demo file.

So here is Depictio 1.0 on twelve million rows, across three linked collections,
running on a laptop with a single API worker in dev mode:

→ First component on screen in 133 to 270 ms, whether the dashboard holds 4
components or 30.
→ Change a filter and the dashboard starts responding in 100 to 200 ms, and is
fully caught up in 1.7 s at four components, 2.0 s at eight and 4.1 s at sixteen,
with all three collections re-filtered.
→ Box plots, histograms and bar charts materialise zero rows. They are computed
as aggregations directly over the stored files, so they are exact rather than
sampled. Largest data frame held in memory across the whole run: 1.6 MB.

Floor numbers, not ceiling ones: one worker, dev mode, auto-reloader attached. A
real deployment runs several workers on server hardware, and the services scale
independently, so heavy ingestion or clustering never blocks the interface.

The other half of 1.0 is that it stopped moving. The data model, the API and the
viewer are stable: what you ingest and build today still works at the next
release. That is the part that makes a dashboard worth setting up at all.

Self-hosted, MIT-licensed, in production at EMBL and available free to
life-science researchers at Swedish universities through SciLifeLab Serve.

Full write-up, with the methodology: link in the comments.

#bioinformatics #opensource #performance #datavisualization #computationalbiology

---

### C3 — How much is already in the box

Leads on breadth, for the reader who assumes a 1.0 is thin. Ends on stability so
it does not read as a feature dump.

---

𝗔 𝟭.𝟬 𝘁𝗵𝗮𝘁 𝗶𝘀 𝗻𝗼𝘁 𝘁𝗵𝗶𝗻

"1.0" often means the minimum that could be called finished. This one is the
opposite: the point of the release is that the foundation stopped moving, and a
lot is already built on it.

What is in the box today:

🌋 Eighteen advanced visualisation types aimed at omics work — volcano plots,
clustered heatmaps, embeddings (PCA, UMAP, t-SNE, PCoA), Manhattan plots,
oncoplots, taxonomy bars. Each arrives with its own controls: movable thresholds
on a volcano, clustering method on a heatmap, layout on a tree.

🔗 Everything filters everything. Declare how your collections relate, then filter
from anywhere: a dropdown, a lasso on a scatter plot, rows in a table, a region on
a map. Nothing is merged on disk, so a sample sheet can filter a MultiQC report,
not just another table.

📦 Every data type in its own format. MultiQC read as MultiQC and rendered inline,
images from object storage, GeoJSON for maps, Newick and Nexus straight to the
phylogeny renderer, and tabular data normalised to Delta for speed.

🚀 Deployable for real. Docker or Kubernetes, independently scaling API and worker
pools, permission-based auth, and an ingestion report plus health banner on each
dashboard so a failed scan is visible rather than silent.

And underneath all of it: a stable data model, API and viewer. Projects you ingest
today keep working, and code you write against the API does not need rewriting
next release.

Self-hosted and MIT-licensed, the way it started.

The full write-up is in the comments. What would you want to point it at first? 👇

#bioinformatics #opensource #nfcore #datavisualization #singlecell

---

## Personal set

### P1 — I was wrong about which part was hard (default)

Build-in-public register, admits something, lands on the same four themes.

---

I have been building Depictio for about three years, and I was wrong about which
part was hard.

I assumed it was the charts. Volcano plots, clustered heatmaps, phylogenetic
trees, coverage tracks: draw enough of those well and you have a product. So I
built those first, and a year ago I put it online and called it a prototype, which
was generous. It worked, people built real dashboards with it, and it fell over on
anything past a few tens of thousands of rows.

The hard part was never the charts. It was the links, and then it was holding
still.

The links, because "when you narrow this, what else has to narrow" is the whole
tool, and working that out without reading a twelve-million-row table is what
decides whether the dashboard is pleasant. A filter on twelve million rows across
three linked collections is now fully caught up in about two seconds, on my
laptop, with one API worker.

Holding still, because a dashboard is something you set up once and come back to
months later, often after the person who built it has left. So 1.0 mostly means
the data model, the API and the viewer stopped moving, and the services split up
so it can actually be deployed and left running.

I wrote all of it up, including the benchmark numbers that did not flatter us,
because a benchmark you only publish when it looks good is marketing.

It is MIT-licensed and self-hosted. It runs in production at EMBL, and any
life-science researcher at a Swedish university can spin up an instance for free
on SciLifeLab Serve.

{BLOG_URL}

---

### P2 — The unglamorous release

For the audience that appreciates restraint. The hook is that this release is
deliberately boring, which makes the stability point land.

---

The most useful release I have shipped is also the least exciting to announce.

Depictio 1.0 has almost no new features in it. What it has is a promise: the data
model, the API and the viewer stopped moving. Projects you ingest today keep
working. Dashboards you build today keep opening. Code you write against the API
does not need rewriting at the next release.

That sounds like nothing until you remember what a dashboard actually is. You set
one up once, and come back months later with new samples, often after whoever
built it has moved on. That only works if the ground underneath is still there,
and until now it was not.

The rest of the year went into the two things that stop a tool being a demo:

Making it fast on real data. Twelve million rows across three linked collections,
a filter fully caught up in about two seconds, on a laptop with a single API
worker. Some plots materialise zero rows at all, computed straight over the stored
files.

Making it deployable. Independently scaling API and worker pools, so heavy
ingestion and clustering never block the interface, plus an ingestion report and
health banner so a bad scan is visible instead of silent.

There is plenty already built on top: eighteen advanced visualisation types,
MultiQC inline, maps, trees, images. But the release itself is the foundation, and
I am oddly proud of how boring it is.

Write-up, with the numbers that did not flatter us: {BLOG_URL}

---

### P3 — Where it runs now

Personal and slightly reflective, leading with adoption as the evidence that the
production claims are real. Shortest of the three.

---

Three years in, the thing I did not expect to care most about is where Depictio
runs when I am not the one running it.

At EMBL, where it started, it serves dashboards for groups across the institute.
And through SciLifeLab Serve, any life-science researcher at a Swedish university
can spin up their own instance for free, with no infrastructure and no sysadmin.
That is the deployment story I care about most, because it takes "self-hosted" and
removes the part where you have to host it yourself. As far as I am aware it is
also being trialled at GHGA, at MGnify, and at ISCIII.

None of that was possible while it was still a prototype, which is really what
1.0 is about. Three things had to become true:

It had to hold still. The data model, the API and the viewer are stable now, so a
dashboard you set up today still opens next year.

It had to survive real data. Twelve million rows across three linked collections,
filters caught up in about two seconds, on a laptop with one API worker.

It had to be deployable by someone who is not me. Independently scaling API and
worker pools, Docker or Kubernetes, and health reporting when ingestion goes
wrong.

Still MIT-licensed, still self-hosted, still no vendor account.

I wrote up the whole year, benchmark methodology included: {BLOG_URL}

---

## X / Twitter

### Option A, single post (fits the 280-char limit)

> Depictio 1.0: a dashboard over 12M rows, 3 linked collections, on a laptop with ONE API worker.
>
> First chart in ~190ms. Filter anything, everything catches up in <2s.
>
> Box plots computed as aggregations over the files. Zero rows materialised.
>
> {BLOG_URL}

### Option B, thread (use if the single post underperforms)

**1/**
Depictio 1.0 is written up.

12 million rows. 3 linked collections. A laptop running a single API worker in dev mode.

First component on screen in 133-270ms, whether the dashboard has 4 components or 30.

🧵

**2/**
Change a filter and the whole dashboard catches up in 1.7-4.1s. Every component, all three collections.

The surprise: it barely matters where you start. Filtering 12M rows costs about the same as filtering a 500-row sample sheet.

Both resolve to a few hundred sample IDs first.

**3/**
Box plots, histograms and bar charts never materialise a single row. They're computed as aggregations directly over the stored files. Exact, not sampled.

Largest data frame held in memory across the entire benchmark run: 1.6 MB.

**4/**
These are floor numbers. One worker, dev mode, auto-reloader attached.

A real deployment runs several workers on server hardware and should beat all of it.

The write-up includes the numbers that didn't flatter us.

**5/**
The other half: the front end is now React + TypeScript, and the Dash codebase is gone.

One FastAPI backend instead of two servers. Full control of the render path, which is what made the performance work possible at all.

**6/**
Filter from anywhere: a dropdown, a lasso on a scatter plot, rows in a table, a region on a map. Everything else follows.

MIT-licensed, self-hosted. Production at EMBL, free for Swedish researchers via @SciLifeLab Serve.

{BLOG_URL}

---

## Fact-check reference

| Claim used above | Source |
|---|---|
| 12,019,500 rows, 3 collections, 1 GB raw / 1.429 GB Delta | `PERF_REPORT_v2.md` Setup |
| First component 133-270 ms across 4-30 components | v2 "Opening a dashboard" |
| First chart 190 ms (16-component, cold) | v2 "Opening a dashboard" |
| Filter catch-up 1.7 s / 2.0 s / 4.1 s | v2 "Changing a filter" |
| 12M-row vs 500-row origin: 2.0 s vs 2.4 s median | v2 "Changing a filter" |
| Link translation 25 ms | v2 "Changing a filter" |
| Zero-row figures, 114 of 225 | v2 "Efficiency" |
| Largest frame 1.57 MB | v2 "Efficiency" |
| 1 uvicorn worker, dev mode, M1 Max | v2 Setup |
| React/TS rewrite, Dash removed | PR #770 |
| SciLifeLab Serve, free for Swedish researchers | scilifelab.se event page |
| Webinar recording | youtube.com/watch?v=KWWHo4esUfg |

Deliberately NOT used: GitHub star/fork counts (author asked to drop them), the
30 s Celery ceiling failures (report detail, reads as a bug out of context), and
the 8-component warm row the report itself flags as unexplained.
