# Autopilot: solve one small issue, end to end

One invocation = one tick = **one GitHub issue**: pick it, check it is small enough,
fix it test-first, verify, open a PR and drive it to green. A human always merges.

Run it once (`/autopilot`, `/autopilot #1280`), or repeatedly with `/loop /autopilot`.
Several sessions can run it in parallel: each claims its issue with a label first.

## Usage

```
/autopilot               # next ready issue
/autopilot #1280         # this issue (it does not need the label)
/autopilot --dry-run     # say which issue would be picked and why, change nothing
```

## Labels (the whole state lives on GitHub)

| Label | Meaning | Set by |
|---|---|---|
| `autopilot` | small and clear enough to hand to an agent | Thomas |
| `autopilot:wip` | claimed by a running session; see its issue comment for the branch | the tick |
| `needs-thomas` | blocked on a decision; the question is in the last issue comment | the tick |

Use `gh` when it is available, otherwise the GitHub MCP tools (`mcp__github__*`).

## 0. Pick

- With `#N`: take that issue.
- Otherwise: the **oldest** open issue labelled `autopilot`, without `autopilot:wip` or
  `needs-thomas`, and with no open PR that closes it.
- Nothing ready: print the report line (§6) with `status=nothing-ready` and stop. Under
  `/loop`, that also ends the loop.

Read the issue body **and its comments**: an answer to an earlier `needs-thomas`
question is in the comments.

## 1. Gate: is it really small?

Go to `needs-thomas` (§5) instead of coding when any of these hold:

- the expected behaviour cannot be stated in two sentences from the issue (empty
  template, "support X" with no scope);
- it needs a design choice with no obvious reversible default;
- it touches a reserved area:
  - dashboard versioning, snapshots, time travel (`dashboards_endpoints/versioning.py`,
    `TabSnapshot`, component ids). See the Dashboard Versioning section of `CLAUDE.md`;
  - auth, permissions, tokens, public/private visibility;
  - stored formats: Mongo documents, Delta layouts, `.db_seeds` structure (a migration);
  - releases, version bumps, Helm, `.github/workflows/`;
  - a breaking change to the REST API, the CLI flags or the dashboard YAML schema;
  - a new external dependency or service (a new storage backend, a new database…);
- the fix would plausibly change more than ~10 files.

A small, **reversible** ambiguity does not block: pick the obvious option, keep going,
and list it under **Assumed** in the PR body.

## 2. Claim and branch

1. Add `autopilot:wip` to the issue (create the label if it is missing).
2. Branch: the session's designated branch if it has one, otherwise
   `autopilot/<N>-<short-slug>` from a fresh `origin/main`.
3. Comment once on the issue: `Autopilot is on this, branch <branch>.`

## 3. Fix, test first

- Find the code path. `/arch` helps, `CLAUDE.md` is the map.
- Write the failing test first, under `depictio/tests/{unit,api,cli,models}`. Run it
  and see it fail for the right reason.
- Make the smallest change that passes it. Match the surrounding code. Do not refactor
  things you do not need to touch.
- Follow every rule in `CLAUDE.md`. Common traps: a dashboard YAML change needs its
  `.db_seeds/*.json` regenerated; a new dashboard field needs `TabSnapshot` coverage;
  frontend work uses Mantine theming, never hardcoded colours.
- User-visible behaviour (a CLI flag, a file format, a config key) gets a line in the
  relevant `docs/` page.

## 4. Verify, then open the PR

Run and keep the output for the PR body:

```bash
ruff format depictio && ruff check depictio
uv run --extra dev ty check depictio/models/        # when depictio/models/ changed
uv run --extra dev pytest -x -n auto <the test files you touched or that cover the change>
uv run --extra dev pytest -x -n auto                # the whole default suite, before the PR
pre-commit run --all-files                          # mandatory
```

Viewer changes: also `cd depictio/viewer && pnpm exec tsc --noEmit`, plus the
`pnpm run check:*` contracts of the area touched. Docker and the Playwright e2e suite
are not run locally (`CLAUDE.md`: no docker commands): CI runs them.

Push the branch and open a **ready** PR (not a draft) against `main`:

- title: conventional commit, e.g. `feat(cli): accept YAML and JSON samplesheets`;
- body: `Closes #N`, what changed and why, **Assumed** (if any), **Verification** (the
  commands above and their results), **Not verified locally** (e2e, anything else).

Then drive it to green: fix CI failures and answer review comments (Claude Code Review
included) until CI passes and no blocking finding is open.

**Never** merge, enable auto-merge, push to `main`, force-push a branch you did not
create, or skip, weaken or delete a test to get green.

## 5. needs-thomas

Whenever the tick stops on a decision (gate in §1, a design fork found while coding,
a CI failure that is not this PR's and has no fix):

1. Comment on the issue: what you found (with `file:line`), the question, 2–3 options,
   your recommendation, and what is already done (branch, PR) if anything.
2. Add `needs-thomas`, remove `autopilot:wip`.
3. Stop this tick. Under `/loop`, the next tick moves to the next issue.

When Thomas answers in a comment and removes `needs-thomas`, the issue is ready again.

## 6. Report (always, last)

Print exactly one line:

```
AUTOPILOT issue=#1280 status=pr-green|pr-open|needs-thomas|nothing-ready pr=<url or ->  next=<#N or ->
```
