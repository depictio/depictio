# Sharing a filtered listing

`/dashboards` and `/projects` keep their filters in the URL. Whatever the page
is showing, the address bar is a link that reproduces it, so a view narrowed to
one pipeline can be handed to someone else and land on their screen already
narrowed.

The link icon in either toolbar copies that URL and tells you what the
recipient will see. The parameters are stable and readable, so they can also be
written by hand.

## What a recipient sees

Opening a link that carries a filter puts a banner above the listing naming the
scope, how many rows survived it, and how many the link is hiding, with a
**Show everything** button that drops the filter. The scope is a starting
point, not a wall: nothing is hidden from someone who wants to widen it.

A link that names any filter replaces the recipient's own stored filters rather
than combining with them. Otherwise a leftover "owner: me" in their browser
would silently subtract from the set you sent, and they would see less than you
meant without knowing why. Layout preferences they did not ask you to override
(view mode, grouping, sort order) survive.

## Parameters

Every list accepts repeats (`?owner=a&owner=b`) or one comma-joined value
(`?owner=a,b`). Values are matched case-insensitively.

Because a comma separates values, a project whose *name* contains one has to be
addressed by its id. The link button always emits ids, so this only comes up in
a link written by hand.

### `/dashboards`

| Parameter | Value |
| --- | --- |
| `template` | Pipeline template, see below |
| `project` | Project id, or the project's exact name |
| `owner` | Owner email, or `__mine__` |
| `workflow` | Workflow system, as tagged on the dashboard |
| `visibility` | `public` or `private` |
| `q` | Free-text search over title, subtitle, project, owner, template |
| `pinned` | `1` for favorites only |
| `view` | `thumbnails`, `list` or `table` |
| `group` | `none`, `project`, `owner`, `visibility` or `workflow` |
| `sort` | `recent`, `name` or `owner` |

### `/projects`

| Parameter | Value |
| --- | --- |
| `template` | Pipeline template, see below |
| `type` | `basic` or `advanced` |
| `visibility` | `public` or `private` |
| `q` | Free-text search over name, owner and template |
| `pinned` | `1` for favorites only |

`view`, `group` and `sort` only change the layout, so a link carrying nothing
else shows the full listing and no banner.

## Template scoping

A project instantiated from a pipeline template carries an identifier like
`nf-core/rnaseq/3.26.0`. Dashboards inherit it from the project that owns them,
which is what lets one link cover both listings.

The filter is version-agnostic, on both sides. `nf-core/rnaseq` matches
3.26.0 and every version that follows it. Pinning the version into the link
would silently drop next quarter's project.

| Link | Scope |
| --- | --- |
| `?template=nf-core` | Every nf-core pipeline |
| `?template=nf-core/rnaseq` | rnaseq only, at any version |
| `?template=rnaseq` | Any source's rnaseq, for links written by hand |
| `?template=nf-core/rnaseq,nf-core/viralrecon` | Either pipeline |

When a template scope is active, the banner also links across to the same scope
on the other listing, so "show me this pipeline" reaches both the projects and
their dashboards in two clicks.

## Examples

Every dashboard built from rnaseq, as a table:

```
/dashboards?template=nf-core/rnaseq&view=table
```

Two pipelines up for review, grouped by project:

```
/dashboards?template=nf-core/rnaseq,nf-core/viralrecon&group=project
```

The projects behind them:

```
/projects?template=nf-core/rnaseq,nf-core/viralrecon
```

Everything public one person owns:

```
/dashboards?owner=reviewer@example.org&visibility=public
```

## Access is unchanged

A link narrows what is listed. It grants nothing: the recipient still sees only
the dashboards and projects their own account can reach, so a scoped link sent
to someone without access shows them an empty listing rather than your rows.
