/**
 * Template identifiers, parsed and matched.
 *
 * A project instantiated from a pipeline template carries a `template_origin`
 * stamped by the CLI (`depictio/cli/cli/utils/templates.py`) whose
 * `template_id` looks like `nf-core/rnaseq/3.26.0`. Both listings — projects
 * directly, dashboards through their owning project — filter on it, and the
 * rules are subtle enough (version-agnostic matching, ids that omit segments)
 * to be worth keeping in one tested place.
 */

export interface ParsedTemplate {
  /** Original full identifier, e.g. `nf-core/viralrecon/3.0.0` */
  full: string;
  /** First slash-separated segment, e.g. `nf-core` */
  source: string;
  /** Middle segment if present, e.g. `viralrecon` */
  repo: string;
  /** Trailing segment if it looks like a semver, otherwise empty */
  version: string;
}

/** Parse a raw `template_origin` into source/repo/version. Accepts the
 *  object the API serves (`{template_id, template_version, ...}`) and a plain
 *  string, and tolerates ids that omit the version segment. Returns null when
 *  the project wasn't created from a template. */
export function parseTemplateOrigin(origin: unknown): ParsedTemplate | null {
  let raw: string | null = null;
  if (typeof origin === 'string') {
    raw = origin.trim();
  } else if (
    origin &&
    typeof origin === 'object' &&
    typeof (origin as { template_id?: unknown }).template_id === 'string'
  ) {
    raw = ((origin as { template_id: string }).template_id || '').trim();
  }
  if (!raw) return null;
  const parts = raw.split('/').map((s) => s.trim()).filter(Boolean);
  const looksVersion = (s: string) => /^v?\d/.test(s);
  let version = '';
  if (parts.length >= 2 && looksVersion(parts[parts.length - 1])) {
    version = parts.pop() || '';
  }
  const source = parts[0] || raw;
  const repo = parts[1] || '';
  return { full: raw, source, repo, version };
}

/** The canonical filter values a template offers: its source (`nf-core`)
 *  and, when the id names one, its pipeline (`nf-core/rnaseq`). These are the
 *  values a listing puts in its Template dropdown and writes into the URL.
 *
 *  The version is deliberately absent. Someone sharing "every rnaseq
 *  dashboard" means every version of rnaseq — pinning 3.26.0 into the link
 *  would silently drop the 3.27.0 project the day it lands. */
export function templateFilterValues(parsed: ParsedTemplate): string[] {
  const values = [parsed.source];
  if (parsed.repo) values.push(`${parsed.source}/${parsed.repo}`);
  return values;
}

/** Every spelling a template answers to when a filter value is matched
 *  against it: the canonical values above plus the bare pipeline name, so a
 *  hand-written `?template=rnaseq` works as well as the full id the Share
 *  button emits. */
function templateMatchKeys(parsed: ParsedTemplate): string[] {
  const keys = templateFilterValues(parsed);
  if (parsed.repo) keys.push(parsed.repo);
  return keys.map((k) => k.toLowerCase());
}

/** The one key a selected filter value stands for — its most specific
 *  segment. `nf-core` scopes to the whole source; `nf-core/rnaseq` (and
 *  `nf-core/rnaseq/3.26.0`, whose version is dropped on the way in) scopes to
 *  that pipeline alone. */
function selectionKey(selected: string): string | null {
  const parsed = parseTemplateOrigin(selected);
  if (!parsed) return null;
  const values = templateFilterValues(parsed);
  return values[values.length - 1].toLowerCase();
}

/** Does this template origin match any of the selected filter values?
 *
 *  Matching is case-insensitive and version-agnostic. An empty selection
 *  matches everything — "no filter", not "nothing" — while an origin that
 *  isn't from a template matches nothing once a selection exists. */
export function matchesTemplateFilter(origin: unknown, selected: string[]): boolean {
  if (selected.length === 0) return true;
  const parsed = parseTemplateOrigin(origin);
  if (!parsed) return false;
  const keys = new Set(templateMatchKeys(parsed));
  return selected.some((raw) => {
    const key = selectionKey(raw);
    return key != null && keys.has(key);
  });
}

// ---------------------------------------------------------------------------
// Template revision
//
// `template_id` ends in the version of the pipeline the template targets
// (`nf-core/nascent/2.3.0`). The template has a version of its own besides:
// `template.version` in its `template.yaml`, bumped whenever its data
// collections, dashboards or recipes change (see depictio/projects/nf-core/
// RULES.md, "Template versioning"). A project records the revision it was
// ingested with (`template_origin.template_version`), and every dashboard the
// template import writes records the revision it came from (its own
// `template_origin`, with `imported_at`). Both serve the same three keys, so one
// reader serves both.
// ---------------------------------------------------------------------------

export interface TemplateRevision {
  templateId: string;
  /** The template's own revision (semver), without a leading `v`. */
  version: string;
  /** Server timestamp of the import (a dashboard) or the ingest (a project). */
  at: string | null;
}

/** Read the revision out of a `template_origin` object, a project's or a
 *  dashboard's. Null when it names no revision: not from a template, or from
 *  one stamped before the revision was recorded. */
export function readTemplateRevision(origin: unknown): TemplateRevision | null {
  if (!origin || typeof origin !== 'object') return null;
  const o = origin as {
    template_id?: unknown;
    template_version?: unknown;
    imported_at?: unknown;
    applied_at?: unknown;
  };
  if (typeof o.template_id !== 'string' || typeof o.template_version !== 'string') return null;
  const templateId = o.template_id.trim();
  const version = o.template_version.trim().replace(/^v/i, '');
  if (!templateId || !version) return null;
  const at = [o.imported_at, o.applied_at].find((v) => typeof v === 'string' && v) as
    | string
    | undefined;
  return { templateId, version, at: at ?? null };
}

export interface TemplateRevisionMismatch {
  dashboard: TemplateRevision;
  project: TemplateRevision;
}

/** The dashboard was imported from another template revision than the one the
 *  project was ingested with: the dashboard may show tiles the project's
 *  collections no longer have, or lack ones they gained. Null when both agree,
 *  and when either side records no revision (nothing to compare). */
export function templateRevisionMismatch(
  dashboardOrigin: unknown,
  projectOrigin: unknown,
): TemplateRevisionMismatch | null {
  const dashboard = readTemplateRevision(dashboardOrigin);
  const project = readTemplateRevision(projectOrigin);
  if (!dashboard || !project) return null;
  if (dashboard.templateId === project.templateId && dashboard.version === project.version) {
    return null;
  }
  return { dashboard, project };
}

/** The warning for a mismatch, in a sentence. The template id is named only
 *  when the two sides differ in it, where a bare version would not say enough. */
export function describeRevisionMismatch(m: TemplateRevisionMismatch): string {
  const sameTemplate = m.dashboard.templateId === m.project.templateId;
  const side = (r: TemplateRevision) => (sameTemplate ? `v${r.version}` : `${r.templateId} v${r.version}`);
  return `Dashboard imported from ${side(m.dashboard)}, project ingested with ${side(m.project)}.`;
}
