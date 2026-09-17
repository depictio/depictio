# Weekly repo audit

Generates the milestone/epic/backlog hygiene report published as a Claude artifact
each week.

The design lives in `template.html`, committed once. `build.py` only fills slots in
it, so the page looks identical week to week and differences you see reflect the
repo rather than whoever generated the report.

## Running it

```bash
python3 dev/repo_audit/build.py            # -> dev/repo_audit/audit.html
python3 dev/repo_audit/build.py --raw /tmp/raw.json   # also dump the gh payload
```

Needs an authenticated `gh` CLI. No Python dependencies beyond the standard library.

## What is mechanical vs. written

`build.py` computes everything on the page except the Notes section. Its checks:

- closed milestones still holding open issues or PRs
- open milestones with no `epic`-labelled issue attached
- epics whose title claims a version number another milestone owns
- open issues with no assignee
- open issues with no milestone and no `backlog` label
- PR bodies carrying a `closes`/`fixes`/`resolves` keyword

Judgment calls go in `notes.md`, which is injected into its own slot. Keep it to
plain paragraphs separated by blank lines; `#123` is auto-linked. Rewrite it each
week, or empty it and the section renders "No commentary this week."

Anything you find yourself writing into `notes.md` every single week is a sign it
should become a check in `build.py` instead.

## Weekly routine

The scheduled agent should do roughly this:

1. `python3 dev/repo_audit/build.py`
2. Rewrite `notes.md` with anything the mechanical checks cannot see
3. Re-run the build so the notes land in the page
4. Publish `dev/repo_audit/audit.html` with the Artifact tool, passing the existing
   artifact URL as `url` so it updates in place instead of minting a new one

Step 4 matters: without `url`, each week creates an orphaned page and the version
history is lost.

`audit.html` is gitignored. It is regenerated on every run and committing it would
add churn to unrelated diffs.
