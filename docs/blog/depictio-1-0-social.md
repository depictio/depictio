<!--
SOCIAL COPY for the Depictio 1.0 blog post. Not published by mkdocs; delete or
move before the docs build if it ends up in the docs tree.

IMPORTANT FRAMING NOTE:
The Depictio company page ALREADY announced v1.0.0 (~1 month ago,
linkedin.com/posts/depictio_multiqc-bioinformatics-opensource-activity-7472199374719102977-IJh8).
So none of these should read as "1.0 is here" a second time. They announce the
WRITE-UP: the numbers, the React rewrite, and where it runs. Framing is
"here's what went into it", not "here's a new release".

BEFORE POSTING:
- [ ] Replace {BLOG_URL} with the published article URL.
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

Product voice, matches the previous company post. Lead with the engineering.

---

𝗪𝗵𝗮𝘁 𝗶𝘁 𝘁𝗼𝗼𝗸 𝘁𝗼 𝗺𝗮𝗸𝗲 𝗗𝗲𝗽𝗶𝗰𝘁𝗶𝗼 𝟭.𝟬 𝗳𝗮𝘀𝘁 ⚡

We wrote up the year of work behind the 1.0 release. The short version: a dashboard over 12 million rows, spread across three linked collections, on a laptop running a single API worker in dev mode.

→ First component on screen in 133-270 ms, whether the dashboard holds 4 components or 30.
→ Change a filter and everything catches up in 1.7 to 4.1 s, across all three collections.
→ A filter starting on the 12M-row feature matrix costs about the same as one starting on the 500-row sample sheet, because both resolve to a few hundred sample IDs in 25 ms before any data is touched.
→ Box plots, histograms and bar charts are computed as aggregations straight over the stored files. Zero rows materialised, exact rather than sampled. The largest data frame held in memory across the whole run was 1.6 MB.

Those are floor numbers, not ceiling ones: one worker, dev mode, auto-reloader attached. A real deployment runs several workers on server hardware.

The other half of the release is structural. The front end was rebuilt in React and TypeScript and the old Dash codebase is gone, which means one FastAPI backend instead of two servers side by side, and full control over the render path. That control is exactly what made the performance work possible.

The point of all of it stays the same: link your data collections once, then filter from anywhere. A dropdown in the side panel, a lasso around points on a scatter plot, rows in a table, a region on a map. Every other component follows.

Depictio is MIT-licensed and self-hosted, in production at EMBL and available free to Swedish life-science researchers through SciLifeLab Serve.

📖 Full write-up → {BLOG_URL}
🚀 Live demo → https://demo.depictio.embl.org/dashboards
⭐ GitHub → https://github.com/depictio/depictio

#bioinformatics #opensource #nfcore #datavisualization #computationalbiology

---

## 2. LinkedIn, Thomas's personal profile

First person, reflective, shorter. Personal posts do better when they admit
something. This one leads with the flaw rather than the fix.

---

A year ago I put Depictio online and called it a prototype, which was generous. It worked, people built real dashboards with it, and it fell over on anything past a few tens of thousands of rows.

I have just published the write-up of what went into fixing that, and I wanted to share the number I am most pleased with.

A dashboard over 12 million rows, three linked collections, running on my laptop with a single API worker in dev mode. Change a filter and the whole thing catches up in under two seconds. Not one chart. All of them, across all three collections.

The part I did not expect going in: it barely matters where the filter starts. Filtering the 12-million-row feature matrix costs about the same as filtering the 500-row sample sheet, because both resolve down to a few hundred sample IDs in 25 milliseconds before any actual data gets touched. Getting the linking right turned out to matter more than any single optimisation.

I also rewrote the entire front end in React and deleted the Dash codebase. Same interface, one server instead of two, and finally full control over how things render, which is what made the rest possible.

The write-up includes the numbers that did not flatter us, because a benchmark you only publish when it looks good is marketing.

Depictio is MIT-licensed and self-hosted. It runs in production at EMBL, and any life-science researcher at a Swedish university can spin up an instance for free on SciLifeLab Serve.

{BLOG_URL}

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
