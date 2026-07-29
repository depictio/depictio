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
- [ ] The LinkedIn posts state the link twice on purpose (near the top, where it
      is visible before "see more", and again at the end). Keep both.
- [ ] LinkedIn strips markdown. Bold is done with unicode math-bold chars
      (matching the previous Depictio post's style); keep or drop as you prefer.
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

## 1. LinkedIn, Depictio company page

Product voice, matches the previous company post. The post's job is to get the
click, not to be the article: the first two lines are all that show before "see
more", so the hook and the fact that there is something to read go up top. Three
numbers, not ten, and the link appears twice (top and bottom) because people
skim to the end.

---

𝗡𝗲𝘄 𝗮𝗿𝘁𝗶𝗰𝗹𝗲: 𝘄𝗵𝗮𝘁 𝘄𝗲𝗻𝘁 𝗶𝗻𝘁𝗼 𝗗𝗲𝗽𝗶𝗰𝘁𝗶𝗼 𝟭.𝟬 ⚡

A dashboard over 12 million rows, three linked collections, on a laptop with one API worker. Change a filter and every component catches up in under two seconds.

We have written up how, in full, with the benchmark methodology and the numbers that did not flatter us:

📖 {BLOG_URL}

Three things from it:

→ 𝗜𝘁 𝗯𝗮𝗿𝗲𝗹𝘆 𝗺𝗮𝘁𝘁𝗲𝗿𝘀 𝘄𝗵𝗲𝗿𝗲 𝗮 𝗳𝗶𝗹𝘁𝗲𝗿 𝘀𝘁𝗮𝗿𝘁𝘀. Filtering the 12M-row feature matrix costs about the same as filtering the 500-row sample sheet, because both resolve to a few hundred sample IDs in 25 ms before any data is touched.

→ 𝗕𝗼𝘅 𝗽𝗹𝗼𝘁𝘀, 𝗵𝗶𝘀𝘁𝗼𝗴𝗿𝗮𝗺𝘀 𝗮𝗻𝗱 𝗯𝗮𝗿 𝗰𝗵𝗮𝗿𝘁𝘀 𝗺𝗮𝘁𝗲𝗿𝗶𝗮𝗹𝗶𝘀𝗲 𝘇𝗲𝗿𝗼 𝗿𝗼𝘄𝘀. They are computed as aggregations directly over the stored files: exact, not sampled. Largest data frame held in memory across the whole run: 1.6 MB.

→ 𝗧𝗵𝗲 𝗳𝗿𝗼𝗻𝘁 𝗲𝗻𝗱 𝗶𝘀 𝗻𝗼𝘄 𝗥𝗲𝗮𝗰𝘁 𝗮𝗻𝗱 𝗧𝘆𝗽𝗲𝗦𝗰𝗿𝗶𝗽𝘁, and the old Dash codebase is gone. One FastAPI backend instead of two servers, and full control of the render path, which is what made the performance work possible at all.

Those timings are a floor, not a ceiling: one worker, dev mode, auto-reloader attached. A real deployment runs several workers on server hardware.

What none of it changes is the point of the tool. Link your data collections once, then filter from anywhere: a dropdown in the side panel, a lasso around points on a scatter plot, rows in a table, a region on a map. Every other component follows.

MIT-licensed and self-hosted. In production at EMBL, and free for life-science researchers at Swedish universities through SciLifeLab Serve.

📖 Read it → {BLOG_URL}
🚀 Live demo → https://demo.depictio.embl.org/dashboards
⭐ GitHub → https://github.com/depictio/depictio

#bioinformatics #opensource #nfcore #datavisualization #computationalbiology

---

## 2. LinkedIn, Thomas's personal profile

First person, reflective, shorter. Personal posts do better when they admit
something, so this leads with the flaw rather than the fix. It says plainly that
there is an article and what is in it, rather than trailing a bare URL at the
end: a link with no description reads like an afterthought and gets treated as
one.

---

A year ago I put Depictio online and called it a prototype, which was generous. It worked, people built real dashboards with it, and it fell over on anything past a few tens of thousands of rows.

I have just published the write-up of what went into fixing that. It is the long version, with the benchmark method and the results that did not flatter us, because a benchmark you only publish when it looks good is marketing.

📖 The full article is here → {BLOG_URL}

The number I am most pleased with: a dashboard over 12 million rows, three linked collections, running on my laptop with a single API worker in dev mode. Change a filter and the whole thing catches up in under two seconds. Not one chart. All of them, across all three collections.

The part I did not expect going in: it barely matters where the filter starts. Filtering the 12-million-row feature matrix costs about the same as filtering the 500-row sample sheet, because both resolve down to a few hundred sample IDs in 25 milliseconds before any actual data gets touched. Getting the linking right turned out to matter more than any single optimisation.

I also rewrote the entire front end in React and deleted the Dash codebase. Same interface, one server instead of two, and finally full control over how things render, which is what made the rest possible.

The article covers all of it, plus where Depictio runs today and what I am building next. It is MIT-licensed and self-hosted: in production at EMBL, and any life-science researcher at a Swedish university can spin up an instance for free on SciLifeLab Serve.

If you only read one section, read the performance one → {BLOG_URL}

---

## 3. X / Twitter

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
